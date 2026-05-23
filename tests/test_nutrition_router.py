from pathlib import Path

import pytest

from forge_bot.nutrition.plan import (
    NutritionPlan,
    NutritionPlanError,
    load_nutrition_plan_file,
    parse_nutrition_plan,
)
from forge_bot.nutrition.router import (
    detect_moments,
    detect_situations,
    normalize_text,
    resolve_meal_context,
)

DEMO_PLAN_PATH = Path("bot_profiles/nutrition/demo_plan.json")
NUTRITION_PROFILE_ROOT = Path("bot_profiles/nutrition")


@pytest.fixture
def demo_plan() -> NutritionPlan:
    return load_nutrition_plan_file(NUTRITION_PROFILE_ROOT, "demo_plan.json")


def test_load_configured_nutrition_plan_file(demo_plan) -> None:
    assert demo_plan.plan_id == "demo_nutrition_plan_v1"
    assert "crossfit" in demo_plan.situations
    assert "comida_2" in demo_plan.meals


def test_configured_plan_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(NutritionPlanError, match="could not be read"):
        load_nutrition_plan_file(tmp_path, "missing.json")


def test_configured_plan_loader_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(NutritionPlanError, match="inside the profile folder"):
        load_nutrition_plan_file(tmp_path, "../outside.json")


def test_demo_plan_file_exists() -> None:
    assert DEMO_PLAN_PATH.is_file()


def test_plan_validation_rejects_missing_meal_reference() -> None:
    with pytest.raises(NutritionPlanError, match="references missing meal"):
        parse_nutrition_plan(
            {
                "situaciones": {
                    "crossfit": {
                        "aliases": ["crossfit"],
                        "momentos": {"almuerzo": "comida_missing"},
                    }
                },
                "comidas": {
                    "comida_1": {"descripcion": "ok", "and": ["25g whey"]}
                },
            }
        )


def test_normalize_text_removes_accents_and_punctuation() -> None:
    assert normalize_text("¿Qué como al mediodía?") == "que como al mediodia"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("hoy tengo crossfit", "crossfit"),
        ("vengo del gym", "crossfit"),
        ("partido de futbol al mediodia", "futbol"),
        ("salida en bici por la manana", "ciclismo"),
        ("hoy toca rodillo", "ciclismo"),
        ("voy a correr series", "atletismo"),
        ("dia de descanso", "no_entreno"),
        ("hoy no entreno", "no_entreno"),
    ],
)
def test_detect_situations_from_aliases(demo_plan, message: str, expected: str) -> None:
    matches = detect_situations(demo_plan, message)

    assert tuple(match.key for match in matches) == (expected,)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("que desayuno hoy", "desayuno"),
        ("que como al mediodia", "almuerzo"),
        ("que comida toca", "almuerzo"),
        ("que merienda hago", "merienda"),
        ("pre entreno rapido", "merienda"),
        ("que ceno por la noche", "cena"),
    ],
)
def test_detect_moments(message: str, expected: str) -> None:
    matches = detect_moments(message)

    assert tuple(match.key for match in matches) == (expected,)


@pytest.mark.parametrize(
    ("message", "meal_key"),
    [
        ("Hoy tengo crossfit, que como al mediodia?", "comida_2"),
        ("Tengo futbol, que ceno?", "comida_3"),
        ("Hoy no entreno, que almuerzo?", "comida_5"),
        ("Voy en bici, que merienda hago?", "comida_0"),
        ("Tengo atletismo, que desayuno?", "comida_1"),
    ],
)
def test_resolve_meal_context(demo_plan, message: str, meal_key: str) -> None:
    resolution = resolve_meal_context(demo_plan, message)

    assert resolution.status == "resolved"
    assert resolution.is_resolved
    assert resolution.meal_block_key == meal_key
    assert resolution.meal_block is demo_plan.meals[meal_key]
    assert resolution.supplementation == ("10g de creatina monohidrato creapure",)


def test_resolve_missing_situation(demo_plan) -> None:
    resolution = resolve_meal_context(demo_plan, "que como al mediodia?")

    assert resolution.status == "missing_situation"
    assert "CrossFit o entrenamiento de fuerza alta intensidad" in (
        resolution.available_situations
    )


def test_resolve_missing_moment(demo_plan) -> None:
    resolution = resolve_meal_context(demo_plan, "hoy tengo crossfit")

    assert resolution.status == "missing_moment"
    assert resolution.situation_key == "crossfit"
    assert "almuerzo" in resolution.available_moments


def test_resolve_ambiguous_situation(demo_plan) -> None:
    resolution = resolve_meal_context(
        demo_plan,
        "hoy descanso pero hago bici suave, que como al mediodia?",
    )

    assert resolution.status == "ambiguous_situation"
    assert tuple(match.key for match in resolution.situation_matches) == (
        "ciclismo",
        "no_entreno",
    )


def test_resolve_ambiguous_moment(demo_plan) -> None:
    resolution = resolve_meal_context(
        demo_plan,
        "hoy tengo crossfit, comida y cena?",
    )

    assert resolution.status == "ambiguous_moment"
    assert tuple(match.key for match in resolution.moment_matches) == (
        "almuerzo",
        "cena",
    )
