from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .plan import NutritionPlan

ResolutionStatus = Literal[
    "resolved",
    "missing_situation",
    "missing_moment",
    "ambiguous_situation",
    "ambiguous_moment",
    "invalid_mapping",
]

MOMENT_ALIASES: Mapping[str, tuple[str, ...]] = {
    "desayuno": ("desayuno", "desayunar"),
    "almuerzo": ("almuerzo", "comida", "comer", "mediodia", "medio dia"),
    "merienda": ("merienda", "merendar", "media tarde", "pre entreno"),
    "cena": ("cena", "cenar", "ceno", "noche"),
}


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
class MealResolution:
    """Result of routing one user message to a meal block."""

    status: ResolutionStatus
    situation_key: str | None = None
    moment_key: str | None = None
    meal_block_key: str | None = None
    meal_block: Mapping[str, Any] | None = None
    supplementation: tuple[str, ...] = ()
    situation_matches: tuple[SituationMatch, ...] = ()
    moment_matches: tuple[MomentMatch, ...] = ()
    available_situations: tuple[str, ...] = ()
    available_moments: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"


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


def detect_moments(message: str) -> tuple[MomentMatch, ...]:
    """Return meal moment candidates detected from built-in Spanish aliases."""
    normalized_message = normalize_text(message)
    matches: list[MomentMatch] = []
    for moment_key, aliases in MOMENT_ALIASES.items():
        normalized_aliases = tuple(normalize_text(alias) for alias in aliases)
        matched = tuple(
            alias
            for alias in normalized_aliases
            if _contains_alias(normalized_message, alias)
        )
        if matched:
            matches.append(MomentMatch(key=moment_key, matched_aliases=matched))
    return tuple(matches)


def resolve_meal_context(plan: NutritionPlan, message: str) -> MealResolution:
    """Resolve one natural language message to the smallest useful meal chunk."""
    situation_matches = detect_situations(plan, message)
    moment_matches = detect_moments(message)
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


def _situation_aliases(
    situation_key: str,
    situation: Mapping[str, Any],
) -> tuple[str, ...]:
    aliases = situation.get("aliases", [])
    values = [situation_key]
    if isinstance(aliases, list):
        values.extend(alias for alias in aliases if isinstance(alias, str))
    return _dedupe_normalized(values)


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
        return tuple(MOMENT_ALIASES.keys())
    situation = plan.situations[situation_matches[0].key]
    moments = situation.get("momentos", {})
    if not isinstance(moments, dict):
        return ()
    return tuple(str(moment) for moment in moments.keys())


def _supplementation(situation: Mapping[str, Any]) -> tuple[str, ...]:
    value = situation.get("suplementacion", [])
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())
