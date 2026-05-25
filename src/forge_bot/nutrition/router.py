from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .plan import NutritionPlan

ResolutionStatus = Literal[
    "resolved",
    "resolved_day",
    "missing_situation",
    "missing_moment",
    "ambiguous_situation",
    "ambiguous_moment",
    "invalid_mapping",
]

DEFAULT_MOMENT_ALIASES: Mapping[str, tuple[str, ...]] = {
    "desayuno": ("desayuno", "desayunar"),
    "almuerzo": ("almuerzo", "comida", "comer", "mediodia", "medio dia"),
    "merienda": ("merienda", "merendar", "media tarde", "pre entreno"),
    "cena": ("cena", "cenar", "ceno", "noche"),
}

DAY_OVERVIEW_ALIASES: tuple[str, ...] = (
    "todo lo que puedo comer",
    "todo lo que comer",
    "todo el dia",
    "dia completo",
    "plan del dia",
    "comidas del dia",
    "plan de comidas del dia",
    "que puedo comer hoy",
    "que comer hoy",
)


@dataclass(frozen=True)
class SituationMatch:
    """Situation detected from configured plan aliases."""

    key: str
    label: str
    matched_aliases: tuple[str, ...]


@dataclass(frozen=True)
class MomentMatch:
    """Meal moment detected from natural language aliases."""

    key: str
    matched_aliases: tuple[str, ...]


@dataclass(frozen=True)
class DayMealBlock:
    """One resolved meal block inside a whole-day nutrition answer."""

    moment_key: str
    moment_label: str
    meal_block_key: str
    meal_block: Mapping[str, Any]


@dataclass(frozen=True)
class MealResolution:
    """Result of routing one user message to a meal block."""

    status: ResolutionStatus
    situation_key: str | None = None
    moment_key: str | None = None
    meal_block_key: str | None = None
    meal_block: Mapping[str, Any] | None = None
    day_meal_blocks: tuple[DayMealBlock, ...] = ()
    supplementation: tuple[str, ...] = ()
    situation_matches: tuple[SituationMatch, ...] = ()
    moment_matches: tuple[MomentMatch, ...] = ()
    available_situations: tuple[str, ...] = ()
    available_moments: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.status in {"resolved", "resolved_day"}


def normalize_text(text: str) -> str:
    """Normalize user text for cheap alias matching."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    without_accents = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    cleaned = re.sub(r"[^a-z0-9_]+", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def detect_situations(plan: NutritionPlan, message: str) -> tuple[SituationMatch, ...]:
    """Return situation candidates detected from configured aliases."""
    normalized_message = normalize_text(message)
    matches: list[SituationMatch] = []
    for situation_key, situation in plan.situations.items():
        aliases = _situation_aliases(situation_key, situation)
        matched = tuple(
            alias for alias in aliases if _contains_alias(normalized_message, alias)
        )
        if matched:
            matches.append(
                SituationMatch(
                    key=situation_key,
                    label=_situation_label(situation_key, situation),
                    matched_aliases=matched,
                )
            )
    return tuple(matches)


def detect_moments(plan: NutritionPlan, message: str) -> tuple[MomentMatch, ...]:
    """Return meal moment candidates detected from plan-defined aliases."""
    normalized_message = normalize_text(message)
    matches: list[MomentMatch] = []
    for moment_key, aliases in _moment_aliases(plan).items():
        matched = tuple(
            alias for alias in aliases if _contains_alias(normalized_message, alias)
        )
        if matched:
            matches.append(MomentMatch(key=moment_key, matched_aliases=matched))
    return tuple(matches)


def resolve_meal_context(plan: NutritionPlan, message: str) -> MealResolution:
    """Resolve one natural language message to the smallest useful meal chunk."""
    wants_day_overview = _is_day_overview_request(message)
    situation_matches = detect_situations(plan, message)
    moment_matches = detect_moments(plan, message)
    available_situations = _available_situations(plan)
    available_moments = _available_moments(plan, situation_matches)

    if not situation_matches:
        return MealResolution(
            status="missing_situation",
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )
    if len(situation_matches) > 1:
        return MealResolution(
            status="ambiguous_situation",
            situation_matches=situation_matches,
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )
    if wants_day_overview:
        return _resolve_day_context(
            plan=plan,
            situation_match=situation_matches[0],
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )
    if not moment_matches:
        return MealResolution(
            status="missing_moment",
            situation_key=situation_matches[0].key,
            situation_matches=situation_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )
    if len(moment_matches) > 1:
        return MealResolution(
            status="ambiguous_moment",
            situation_key=situation_matches[0].key,
            situation_matches=situation_matches,
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )

    situation_key = situation_matches[0].key
    moment_key = moment_matches[0].key
    situation = plan.situations[situation_key]
    moments = situation.get("momentos", {})
    meal_block_key = moments.get(moment_key) if isinstance(moments, dict) else None
    if not isinstance(meal_block_key, str):
        return MealResolution(
            status="invalid_mapping",
            situation_key=situation_key,
            moment_key=moment_key,
            situation_matches=situation_matches,
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )
    meal_block = plan.meals.get(meal_block_key)
    if not isinstance(meal_block, dict):
        return MealResolution(
            status="invalid_mapping",
            situation_key=situation_key,
            moment_key=moment_key,
            meal_block_key=meal_block_key,
            situation_matches=situation_matches,
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )

    return MealResolution(
        status="resolved",
        situation_key=situation_key,
        moment_key=moment_key,
        meal_block_key=meal_block_key,
        meal_block=meal_block,
        supplementation=_supplementation(situation),
        situation_matches=situation_matches,
        moment_matches=moment_matches,
        available_situations=available_situations,
        available_moments=available_moments,
    )


def _resolve_day_context(
    *,
    plan: NutritionPlan,
    situation_match: SituationMatch,
    moment_matches: tuple[MomentMatch, ...],
    available_situations: tuple[str, ...],
    available_moments: tuple[str, ...],
) -> MealResolution:
    situation = plan.situations[situation_match.key]
    moments = situation.get("momentos", {})
    if not isinstance(moments, dict):
        return MealResolution(
            status="invalid_mapping",
            situation_key=situation_match.key,
            situation_matches=(situation_match,),
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )

    day_meal_blocks: list[DayMealBlock] = []
    for moment_key, meal_block_key in moments.items():
        if plan.moments and moment_key not in plan.moments:
            continue
        if not isinstance(moment_key, str) or not isinstance(meal_block_key, str):
            return MealResolution(
                status="invalid_mapping",
                situation_key=situation_match.key,
                situation_matches=(situation_match,),
                moment_matches=moment_matches,
                available_situations=available_situations,
                available_moments=available_moments,
            )
        meal_block = plan.meals.get(meal_block_key)
        if not isinstance(meal_block, dict):
            return MealResolution(
                status="invalid_mapping",
                situation_key=situation_match.key,
                moment_key=moment_key,
                meal_block_key=meal_block_key,
                situation_matches=(situation_match,),
                moment_matches=moment_matches,
                available_situations=available_situations,
                available_moments=available_moments,
            )
        day_meal_blocks.append(
            DayMealBlock(
                moment_key=moment_key,
                moment_label=_moment_label(plan, moment_key),
                meal_block_key=meal_block_key,
                meal_block=meal_block,
            )
        )

    if not day_meal_blocks:
        return MealResolution(
            status="invalid_mapping",
            situation_key=situation_match.key,
            situation_matches=(situation_match,),
            moment_matches=moment_matches,
            available_situations=available_situations,
            available_moments=available_moments,
        )

    return MealResolution(
        status="resolved_day",
        situation_key=situation_match.key,
        day_meal_blocks=tuple(day_meal_blocks),
        supplementation=_supplementation(situation),
        situation_matches=(situation_match,),
        moment_matches=moment_matches,
        available_situations=available_situations,
        available_moments=available_moments,
    )


def _situation_aliases(
    situation_key: str,
    situation: Mapping[str, Any],
) -> tuple[str, ...]:
    aliases = situation.get("aliases", [])
    values = [situation_key]
    if isinstance(aliases, list):
        values.extend(alias for alias in aliases if isinstance(alias, str))
    return _dedupe_normalized(values)


def _moment_aliases(plan: NutritionPlan) -> Mapping[str, tuple[str, ...]]:
    if not plan.moments:
        return DEFAULT_MOMENT_ALIASES

    aliases_by_moment: dict[str, tuple[str, ...]] = {}
    for moment_key, moment in plan.moments.items():
        values = [moment_key]
        aliases = moment.get("aliases", [])
        if isinstance(aliases, list):
            values.extend(alias for alias in aliases if isinstance(alias, str))
        aliases_by_moment[moment_key] = _dedupe_normalized(values)
    return aliases_by_moment


def _dedupe_normalized(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        alias = normalize_text(value)
        if alias and alias not in seen:
            seen.add(alias)
            normalized.append(alias)
    return tuple(normalized)


def _contains_alias(normalized_message: str, normalized_alias: str) -> bool:
    if not normalized_alias:
        return False
    alias_pattern = r"\s+".join(re.escape(part) for part in normalized_alias.split())
    return re.search(rf"(?<!\w){alias_pattern}(?!\w)", normalized_message) is not None


def _is_day_overview_request(message: str) -> bool:
    normalized_message = normalize_text(message)
    return any(
        _contains_alias(normalized_message, alias)
        for alias in _dedupe_normalized(DAY_OVERVIEW_ALIASES)
    )


def _situation_label(situation_key: str, situation: Mapping[str, Any]) -> str:
    label = situation.get("label")
    return label.strip() if isinstance(label, str) and label.strip() else situation_key


def _available_situations(plan: NutritionPlan) -> tuple[str, ...]:
    return tuple(
        _situation_label(situation_key, situation)
        for situation_key, situation in plan.situations.items()
    )


def _available_moments(
    plan: NutritionPlan,
    situation_matches: tuple[SituationMatch, ...],
) -> tuple[str, ...]:
    if len(situation_matches) != 1:
        return _all_available_moment_labels(plan)
    situation = plan.situations[situation_matches[0].key]
    moments = situation.get("momentos", {})
    if not isinstance(moments, dict):
        return ()
    return _dedupe_labels(
        tuple(
            _moment_label(plan, str(moment))
            for moment in moments.keys()
            if not plan.moments or moment in plan.moments
        )
    )


def _all_available_moment_labels(plan: NutritionPlan) -> tuple[str, ...]:
    if plan.moments:
        return tuple(_moment_label(plan, moment_key) for moment_key in plan.moments)
    return tuple(DEFAULT_MOMENT_ALIASES.keys())


def _dedupe_labels(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    labels: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            labels.append(value)
    return tuple(labels)


def _moment_label(plan: NutritionPlan, moment_key: str) -> str:
    moment = plan.moments.get(moment_key, {})
    label = moment.get("label") if isinstance(moment, dict) else None
    return label.strip() if isinstance(label, str) and label.strip() else moment_key


def _supplementation(situation: Mapping[str, Any]) -> tuple[str, ...]:
    value = situation.get("suplementacion", [])
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())
