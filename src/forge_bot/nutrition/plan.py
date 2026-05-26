from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MEAL_OPERATOR_KEYS = ("and", "or")


class NutritionPlanError(RuntimeError):
    """Raised when a nutrition plan document is invalid."""


@dataclass(frozen=True)
class NutritionPlan:
    """Validated nutrition plan shape used by the local router."""

    plan_id: str
    moments: Mapping[str, Mapping[str, Any]]
    situations: Mapping[str, Mapping[str, Any]]
    meals: Mapping[str, Mapping[str, Any]]

    @property
    def situation_keys(self) -> tuple[str, ...]:
        return tuple(self.situations.keys())


def parse_nutrition_plan(data: Mapping[str, Any]) -> NutritionPlan:
    """Validate a loaded nutrition plan document for situation routing."""
    plan_id = data.get("plan_id", "nutrition_plan")
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise NutritionPlanError("Nutrition plan field 'plan_id' must be a string.")

    situations = data.get("situaciones")
    meals = data.get("comidas")
    moments = data.get("momentos", {})
    if moments is not None and not isinstance(moments, dict):
        raise NutritionPlanError("Nutrition plan field 'momentos' must be an object.")
    if not isinstance(situations, dict) or not situations:
        raise NutritionPlanError("Nutrition plan requires non-empty 'situaciones'.")
    if not isinstance(meals, dict) or not meals:
        raise NutritionPlanError("Nutrition plan requires non-empty 'comidas'.")

    _validate_meals(meals)
    validated_moments = _validate_moments(moments or {})
    validated_situations = _validate_situations(situations, meals)
    return NutritionPlan(
        plan_id=plan_id.strip(),
        moments=validated_moments,
        situations=validated_situations,
        meals=meals,
    )


def _validate_meals(meals: Mapping[str, Any]) -> None:
    for meal_key, meal in meals.items():
        if not isinstance(meal_key, str) or not meal_key.strip():
            raise NutritionPlanError("Meal keys must be non-empty strings.")
        if not isinstance(meal, dict):
            raise NutritionPlanError(f"Meal '{meal_key}' must be an object.")
        description = meal.get("descripcion")
        if not isinstance(description, str) or not description.strip():
            raise NutritionPlanError(
                f"Meal '{meal_key}' must include non-empty 'descripcion'."
            )
        _validate_meal_node(meal, path=f"Meal '{meal_key}'")


def _validate_meal_node(node: Any, *, path: str) -> None:
    if isinstance(node, str):
        if not node.strip():
            raise NutritionPlanError(f"{path} cannot contain empty text options.")
        return

    if not isinstance(node, dict):
        raise NutritionPlanError(f"{path} must be a text option or object.")

    operator_keys = [key for key in MEAL_OPERATOR_KEYS if key in node]
    if len(operator_keys) != 1:
        raise NutritionPlanError(
            f"{path} must include exactly one logical operator: 'and' or 'or'."
        )
    operator_key = operator_keys[0]
    group = node[operator_key]
    if not isinstance(group, list) or not group:
        raise NutritionPlanError(
            f"{path}.{operator_key} must be a non-empty list of options."
        )

    for metadata_key in ("condiciones", "notas", "warnings"):
        metadata_value = node.get(metadata_key)
        if metadata_value is not None and not _is_string_list(metadata_value):
            raise NutritionPlanError(
                f"{path} field '{metadata_key}' must be a string list."
            )

    for index, child in enumerate(group):
        _validate_meal_node(child, path=f"{path}.{operator_key}[{index}]")


def _validate_situations(
    situations: Mapping[str, Any],
    meals: Mapping[str, Any],
) -> Mapping[str, Mapping[str, Any]]:
    validated: dict[str, Mapping[str, Any]] = {}
    for situation_key, situation in situations.items():
        if not isinstance(situation_key, str) or not situation_key.strip():
            raise NutritionPlanError("Situation keys must be non-empty strings.")
        if not isinstance(situation, dict):
            raise NutritionPlanError(f"Situation '{situation_key}' must be an object.")

        aliases = situation.get("aliases", [])
        if aliases is not None and not _is_string_list(aliases):
            raise NutritionPlanError(
                f"Situation '{situation_key}' field 'aliases' must be a string list."
            )

        supplementation = situation.get("suplementacion", [])
        if supplementation is not None and not _is_string_list(supplementation):
            raise NutritionPlanError(
                f"Situation '{situation_key}' field 'suplementacion' must be a "
                "string list."
            )

        moments = situation.get("momentos")
        if not isinstance(moments, dict) or not moments:
            raise NutritionPlanError(
                f"Situation '{situation_key}' requires non-empty 'momentos'."
            )
        for moment_key, meal_key in moments.items():
            if not isinstance(moment_key, str) or not moment_key.strip():
                raise NutritionPlanError(
                    f"Situation '{situation_key}' moment keys must be strings."
                )
            if not isinstance(meal_key, str) or not meal_key.strip():
                raise NutritionPlanError(
                    f"Situation '{situation_key}' moment '{moment_key}' must point "
                    "to a meal key string."
                )
            if meal_key not in meals:
                raise NutritionPlanError(
                    f"Situation '{situation_key}' moment '{moment_key}' references "
                    f"missing meal '{meal_key}'."
                )
        validated[situation_key] = situation
    return validated


def _validate_moments(moments: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    validated: dict[str, Mapping[str, Any]] = {}
    for moment_key, moment in moments.items():
        if not isinstance(moment_key, str) or not moment_key.strip():
            raise NutritionPlanError("Moment keys must be non-empty strings.")
        if not isinstance(moment, dict):
            raise NutritionPlanError(f"Moment '{moment_key}' must be an object.")
        aliases = moment.get("aliases", [])
        if aliases is not None and not _is_string_list(aliases):
            raise NutritionPlanError(
                f"Moment '{moment_key}' field 'aliases' must be a string list."
            )
        label = moment.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise NutritionPlanError(
                f"Moment '{moment_key}' field 'label' must be a non-empty string."
            )
        validated[moment_key] = moment
    return validated


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def load_nutrition_plan_file(plan_path: Path) -> NutritionPlan:
    """Load a configured nutrition plan file and validate its JSON content."""
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NutritionPlanError(
            f"Nutrition plan file is not valid JSON: {plan_path}"
        ) from exc
    except OSError as exc:
        raise NutritionPlanError(
            f"Nutrition plan file could not be read: {plan_path}"
        ) from exc

    if not isinstance(data, dict):
        raise NutritionPlanError("Nutrition plan file must contain a JSON object.")
    return parse_nutrition_plan(data)
