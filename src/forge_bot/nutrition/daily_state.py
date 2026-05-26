from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from ..database import conect_db
from .intent import NutritionMessageUnderstanding
from .normalizer import NormalizedNutritionMessage
from .plan import NutritionPlan
from .router import detect_moments, detect_situations, normalize_text

logger = logging.getLogger(__name__)

NO_TRAINING_SITUATION_CANDIDATES = ("no_entreno", "descanso", "rest_day")
ACTIVITY_CHANGE_PHRASES = (
    "en lugar de",
    "en vez de",
    "cambio",
    "cambiar",
    "cambiamos",
    "cambiado",
    "he cambiado",
    "hemos cambiado",
    "al final hago",
    "al final hacemos",
    "al final voy a",
    "al final toca",
    "sustituyo",
    "sustituimos",
)


@dataclass(frozen=True)
class LoggedMealUpdate:
    moment_key: str
    text: str


@dataclass(frozen=True)
class DailyNutritionUpdate:
    situation_key: str | None = None
    logged_meals: tuple[LoggedMealUpdate, ...] = ()
    skipped_moments: tuple[str, ...] = ()
    note: str | None = None

    @property
    def has_changes(self) -> bool:
        return bool(
            self.situation_key or self.logged_meals or self.skipped_moments or self.note
        )


@dataclass(frozen=True)
class NutritionDailyLog:
    id: int
    user_id: int
    bot_profile_id: str
    log_date: date
    plan_id: str | None
    situation_key: str | None
    meals: Mapping[str, Any]
    notes: tuple[Mapping[str, Any], ...]
    situation_updated_at: datetime | None = None


def today_local(timezone_name: str | None = None) -> date:
    """Return today's date in the configured application timezone."""
    if timezone_name:
        return datetime.now(ZoneInfo(timezone_name)).date()
    return datetime.now().astimezone().date()


def load_daily_log(
    *,
    user_id: int,
    bot_profile_id: str,
    log_date: date,
) -> NutritionDailyLog | None:
    """Load the nutrition day state for one user/profile/date."""
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, bot_profile_id, log_date, plan_id,
                       situation_key, situation_updated_at, meals, notes
                FROM nutrition_daily_logs
                WHERE user_id = %s
                  AND bot_profile_id = %s
                  AND log_date = %s
                """,
                (user_id, bot_profile_id, log_date),
            )
            row = cursor.fetchone()
            return _row_to_daily_log(row) if row else None
    finally:
        connection.close()


def apply_daily_update(
    *,
    user_id: int,
    bot_profile_id: str,
    log_date: date,
    plan: NutritionPlan,
    update: DailyNutritionUpdate,
    now: datetime | None = None,
) -> NutritionDailyLog | None:
    """Apply an idempotent-ish update to today's nutrition state."""
    if not update.has_changes:
        return load_daily_log(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            log_date=log_date,
        )

    timestamp = now or datetime.now().astimezone()
    connection = conect_db()
    if connection is None:
        return None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO nutrition_daily_logs (
                    user_id, bot_profile_id, log_date, plan_id,
                    situation_key, situation_updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, bot_profile_id, log_date) DO NOTHING
                """,
                (
                    user_id,
                    bot_profile_id,
                    log_date,
                    plan.plan_id,
                    update.situation_key,
                    timestamp if update.situation_key else None,
                ),
            )
            cursor.execute(
                """
                SELECT id, user_id, bot_profile_id, log_date, plan_id,
                       situation_key, situation_updated_at, meals, notes
                FROM nutrition_daily_logs
                WHERE user_id = %s
                  AND bot_profile_id = %s
                  AND log_date = %s
                FOR UPDATE
                """,
                (user_id, bot_profile_id, log_date),
            )
            row = cursor.fetchone()
            if row is None:
                connection.rollback()
                return None

            merged = _merge_daily_update(
                _row_to_daily_log(row),
                plan=plan,
                update=update,
                timestamp=timestamp,
            )
            cursor.execute(
                """
                UPDATE nutrition_daily_logs
                SET plan_id = %s,
                    situation_key = %s,
                    situation_updated_at = %s,
                    meals = %s,
                    notes = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    merged.plan_id,
                    merged.situation_key,
                    merged.situation_updated_at,
                    Jsonb(dict(merged.meals)),
                    Jsonb(list(merged.notes)),
                    merged.id,
                ),
            )
        connection.commit()
        return merged
    except Exception:
        connection.rollback()
        logger.warning(
            "nutrition_daily_log_update_failed user_id=%s bot_profile_id=%s",
            user_id,
            bot_profile_id,
            exc_info=True,
        )
        return None
    finally:
        connection.close()


def preview_daily_update(
    *,
    log: NutritionDailyLog | None,
    user_id: int,
    bot_profile_id: str,
    log_date: date,
    plan: NutritionPlan,
    update: DailyNutritionUpdate,
    now: datetime | None = None,
) -> NutritionDailyLog | None:
    """Return the daily log as it would look after applying an update."""
    if not update.has_changes:
        return log

    timestamp = now or datetime.now().astimezone()
    base_log = log or NutritionDailyLog(
        id=0,
        user_id=user_id,
        bot_profile_id=bot_profile_id,
        log_date=log_date,
        plan_id=plan.plan_id,
        situation_key=None,
        meals={},
        notes=(),
    )
    return _merge_daily_update(
        base_log,
        plan=plan,
        update=update,
        timestamp=timestamp,
    )


def build_daily_update(
    *,
    plan: NutritionPlan,
    message: str,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
) -> DailyNutritionUpdate:
    """Derive the daily-state mutation from the current user message."""
    detected_situation_key = _selected_situation_key(
        plan=plan,
        message=message,
        normalized_message=normalized_message,
    )
    replacement = _situation_replacement(plan, message)
    no_training_key = _no_training_situation_key(plan)
    day_situation_key = (
        replacement if replacement is not None else detected_situation_key
    )
    if no_training_key and _message_cancels_training(message):
        day_situation_key = no_training_key
    if (
        day_situation_key == detected_situation_key
        and _message_mentions_activity_change(message)
        and not _message_declares_current_activity(message)
    ):
        day_situation_key = None
    logged_meals = _logged_meals_from_normalized(normalized_message)
    skipped_moments = _skipped_moments_from_message(plan, message, understanding)
    if day_situation_key and not _should_store_situation_for_today(
        message=message,
        logged_meals=logged_meals,
        skipped_moments=skipped_moments,
    ):
        day_situation_key = None
    note = (
        f"Tipo de dia actualizado a {day_situation_key}."
        if day_situation_key and _message_changes_day_type(message)
        else None
    )

    return DailyNutritionUpdate(
        situation_key=day_situation_key,
        logged_meals=logged_meals,
        skipped_moments=skipped_moments,
        note=note,
    )


def to_prompt_payload(log: NutritionDailyLog | None) -> dict[str, Any] | None:
    """Return a compact JSON payload for runtime LLM context."""
    if log is None:
        return None
    return {
        "log_date": log.log_date.isoformat(),
        "plan_id": log.plan_id,
        "situation_key": log.situation_key,
        "tipo_dia": log.situation_key,
        "meals": dict(log.meals),
        "notes": list(log.notes)[-8:],
    }


def _merge_daily_update(
    log: NutritionDailyLog,
    *,
    plan: NutritionPlan,
    update: DailyNutritionUpdate,
    timestamp: datetime,
) -> NutritionDailyLog:
    meals = dict(log.meals or {})
    notes = list(log.notes or ())
    situation_key = update.situation_key or log.situation_key
    situation_updated_at = log.situation_updated_at
    if update.situation_key:
        situation_updated_at = timestamp

    for meal in update.logged_meals:
        meals[meal.moment_key] = {
            **_existing_meal_entry(meals.get(meal.moment_key)),
            "status": "completed",
            "completed": True,
            "text": meal.text,
            "situation_key": situation_key,
            "meal_block_key": _meal_block_key(
                plan,
                situation_key,
                meal.moment_key,
            ),
            "updated_at": timestamp.isoformat(),
        }
    for moment_key in update.skipped_moments:
        meals[moment_key] = {
            **_existing_meal_entry(meals.get(moment_key)),
            "status": "skipped",
            "completed": True,
            "text": "El usuario indica que se ha saltado esta comida.",
            "situation_key": situation_key,
            "meal_block_key": _meal_block_key(plan, situation_key, moment_key),
            "updated_at": timestamp.isoformat(),
        }
    if update.note:
        notes.append({"text": update.note, "created_at": timestamp.isoformat()})

    return NutritionDailyLog(
        id=log.id,
        user_id=log.user_id,
        bot_profile_id=log.bot_profile_id,
        log_date=log.log_date,
        plan_id=plan.plan_id,
        situation_key=situation_key,
        situation_updated_at=situation_updated_at,
        meals=meals,
        notes=tuple(notes),
    )


def _row_to_daily_log(row: Mapping[str, Any]) -> NutritionDailyLog:
    raw_meals = row.get("meals")
    raw_notes = row.get("notes")
    meals: Mapping[str, Any] = raw_meals if isinstance(raw_meals, dict) else {}
    notes: tuple[Mapping[str, Any], ...] = (
        tuple(item for item in raw_notes if isinstance(item, dict))
        if isinstance(raw_notes, list)
        else ()
    )
    return NutritionDailyLog(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        bot_profile_id=str(row["bot_profile_id"]),
        log_date=row["log_date"],
        plan_id=row.get("plan_id"),
        situation_key=row.get("situation_key"),
        situation_updated_at=row.get("situation_updated_at"),
        meals=meals,
        notes=notes,
    )


def _selected_situation_key(
    *,
    plan: NutritionPlan,
    message: str,
    normalized_message: NormalizedNutritionMessage | None,
) -> str | None:
    if normalized_message is not None and normalized_message.situation_key:
        return normalized_message.situation_key
    matches = detect_situations(plan, message)
    return matches[0].key if len(matches) == 1 else None


def _logged_meals_from_normalized(
    normalized_message: NormalizedNutritionMessage | None,
) -> tuple[LoggedMealUpdate, ...]:
    if normalized_message is None:
        return ()
    meals: list[LoggedMealUpdate] = []
    for item in normalized_message.logged_meals:
        moment_key = item.get("moment_key")
        text = item.get("text")
        if moment_key and text:
            meals.append(LoggedMealUpdate(moment_key=moment_key, text=text))
    return tuple(meals)


def _skipped_moments_from_message(
    plan: NutritionPlan,
    message: str,
    understanding: NutritionMessageUnderstanding,
) -> tuple[str, ...]:
    if "skipped_meal" not in understanding.deviations:
        return ()
    normalized = normalize_text(message)
    skipped_fragment = re.search(
        r"\b(?:me he saltado|saltado|no he hecho)\s+(?P<fragment>.+?)(?:$|\bque\b)",
        normalized,
    )
    if skipped_fragment is None:
        return ()
    matches = detect_moments(plan, skipped_fragment.group("fragment"))
    return tuple(match.key for match in matches)


def _message_cancels_training(message: str) -> bool:
    normalized = normalize_text(message)
    return any(
        phrase in normalized
        for phrase in (
            "al final no he ido",
            "al final no fui",
            "no he ido",
            "no fui",
            "no voy a ir",
            "no he entrenado",
            "al final no entreno",
        )
    )


def message_cancels_training(message: str) -> bool:
    """Return true when the user corrects a planned training into no training."""
    return _message_cancels_training(message)


def message_changes_day_type(message: str) -> bool:
    """Return true when the user explicitly changes today's day type."""
    return _message_changes_day_type(message)


def _message_changes_day_type(message: str) -> bool:
    return _message_cancels_training(message) or _message_mentions_activity_change(
        message
    )


def _should_store_situation_for_today(
    *,
    message: str,
    logged_meals: tuple[LoggedMealUpdate, ...],
    skipped_moments: tuple[str, ...],
) -> bool:
    normalized = normalize_text(message)
    today_terms = (
        "hoy",
        "esta manana",
        "esta tarde",
        "esta noche",
        "ahora",
    )
    return bool(
        logged_meals
        or skipped_moments
        or _message_changes_day_type(message)
        or any(term in normalized for term in today_terms)
    )


def _message_mentions_activity_change(message: str) -> bool:
    normalized = normalize_text(message)
    return any(phrase in normalized for phrase in ACTIVITY_CHANGE_PHRASES)


def _message_declares_current_activity(message: str) -> bool:
    normalized = normalize_text(message)
    return any(
        phrase in normalized
        for phrase in (
            "al final hago",
            "al final hacemos",
            "al final voy a",
            "al final toca",
        )
    )


def _situation_replacement(
    plan: NutritionPlan,
    message: str,
) -> str | None:
    if not _message_mentions_activity_change(message):
        return None
    positions = _situation_positions(plan, message)
    if len(positions) < 2:
        return None

    previous_situation_key = positions[0][1]
    replacement_situation_key = positions[-1][1]
    if previous_situation_key == replacement_situation_key:
        return None
    return replacement_situation_key


def _situation_positions(
    plan: NutritionPlan,
    message: str,
) -> tuple[tuple[int, str], ...]:
    normalized_message = normalize_text(message)
    positions: list[tuple[int, str]] = []
    for situation_key, situation in plan.situations.items():
        for alias in _situation_aliases(situation_key, situation):
            alias_pattern = r"\s+".join(re.escape(part) for part in alias.split())
            for match in re.finditer(
                rf"(?<!\w){alias_pattern}(?!\w)",
                normalized_message,
            ):
                positions.append((match.start(), situation_key))
    unique: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for item in sorted(positions):
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return tuple(unique)


def _situation_aliases(
    situation_key: str,
    situation: Mapping[str, Any],
) -> tuple[str, ...]:
    aliases = situation.get("aliases", [])
    values = [situation_key]
    if isinstance(aliases, list):
        values.extend(alias for alias in aliases if isinstance(alias, str))
    return tuple(
        alias for alias in (normalize_text(value) for value in values) if alias
    )


def _no_training_situation_key(plan: NutritionPlan) -> str | None:
    for key in NO_TRAINING_SITUATION_CANDIDATES:
        if key in plan.situations:
            return key
    for key, situation in plan.situations.items():
        aliases = situation.get("aliases", [])
        alias_values: Sequence[object] = aliases if isinstance(aliases, list) else ()
        normalized_values = {
            normalize_text(key),
            *(normalize_text(str(item)) for item in alias_values),
        }
        if {"no entreno", "descanso"} & normalized_values:
            return key
    return None


def _meal_block_key(
    plan: NutritionPlan,
    situation_key: str | None,
    moment_key: str,
) -> str | None:
    if not situation_key:
        return None
    situation = plan.situations.get(situation_key, {})
    moments = situation.get("momentos", {})
    if not isinstance(moments, dict):
        return None
    meal_block_key = moments.get(moment_key)
    return meal_block_key if isinstance(meal_block_key, str) else None


def _existing_meal_entry(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
