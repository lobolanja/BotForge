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

NUTRITION_PLAN_FIXTURE_PATH = Path("tests/fixtures/nutrition_plan.json")
NUTRITION_FIXTURE_ROOT = Path("tests/fixtures")


@pytest.fixture
def sample_plan() -> NutritionPlan:
    return load_nutrition_plan_file(NUTRITION_FIXTURE_ROOT / "nutrition_plan.json")


def test_load_configured_nutrition_plan_file(sample_plan) -> None:
    assert sample_plan.plan_id == "sample_nutrition_plan_v1"
    assert "media_manana" in sample_plan.moments
    assert "pre_entreno" in sample_plan.moments
    assert "post_entreno" in sample_plan.moments
    assert "crossfit" in sample_plan.situations
    assert "comida_2" in sample_plan.meals


def test_configured_plan_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(NutritionPlanError, match="could not be read"):
        load_nutrition_plan_file(tmp_path / "missing.json")


def test_nutrition_plan_fixture_exists() -> None:
    assert NUTRITION_PLAN_FIXTURE_PATH.is_file()


def test_plan_validation_rejects_missing_meal_reference() -> None:
    with pytest.raises(NutritionPlanError, match="references missing meal"):
        parse_nutrition_plan(
            {
                "momentos": {
                    "almuerzo": {"aliases": ["almuerzo"]},
                },
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


def test_plan_validation_rejects_invalid_moment_aliases() -> None:
    with pytest.raises(NutritionPlanError, match="aliases"):
        parse_nutrition_plan(
            {
                "momentos": {
                    "almuerzo": {"aliases": ["almuerzo", ""]},
                },
                "situaciones": {
                    "crossfit": {
                        "aliases": ["crossfit"],
                        "momentos": {"almuerzo": "comida_1"},
                    }
                },
                "comidas": {
                    "comida_1": {"descripcion": "ok", "and": ["25g whey"]}
                },
            }
        )


def minimal_plan_with_meal(meal: dict[str, object]) -> dict[str, object]:
    return {
        "momentos": {
            "almuerzo": {"aliases": ["almuerzo"]},
        },
        "situaciones": {
            "no_entreno": {
                "aliases": ["no entreno"],
                "momentos": {"almuerzo": "comida_1"},
            }
        },
        "comidas": {"comida_1": meal},
    }


def test_plan_validation_accepts_nested_and_or_meal_tree() -> None:
    plan = parse_nutrition_plan(
        minimal_plan_with_meal(
            {
                "descripcion": "Almuerzo",
                "and": [
                    {
                        "nombre": "proteina",
                        "or": ["200g pollo", "220g merluza"],
                    },
                    {
                        "nombre": "hidrato_y_grasa",
                        "and": ["80g arroz", "10g aceite"],
                    },
                ],
                "warnings": ["Ajustar si hay hambre real."],
            }
        )
    )

    assert plan.meals["comida_1"]["descripcion"] == "Almuerzo"


def test_plan_validation_rejects_meal_without_and_or_tree() -> None:
    with pytest.raises(NutritionPlanError, match="exactly one logical operator"):
        parse_nutrition_plan(minimal_plan_with_meal({"descripcion": "Almuerzo"}))


def test_plan_validation_rejects_meal_with_both_and_or() -> None:
    with pytest.raises(NutritionPlanError, match="exactly one logical operator"):
        parse_nutrition_plan(
            minimal_plan_with_meal(
                {
                    "descripcion": "Almuerzo",
                    "and": ["200g pollo"],
                    "or": ["220g merluza"],
                }
            )
        )


def test_plan_validation_rejects_empty_logical_group() -> None:
    with pytest.raises(NutritionPlanError, match="non-empty list"):
        parse_nutrition_plan(
            minimal_plan_with_meal({"descripcion": "Almuerzo", "or": []})
        )


def test_plan_validation_rejects_invalid_logical_metadata() -> None:
    with pytest.raises(NutritionPlanError, match="warnings"):
        parse_nutrition_plan(
            minimal_plan_with_meal(
                {
                    "descripcion": "Almuerzo",
                    "and": ["200g pollo"],
                    "warnings": ["ok", ""],
                }
            )
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
def test_detect_situations_from_aliases(
    sample_plan,
    message: str,
    expected: str,
) -> None:
    matches = detect_situations(sample_plan, message)

    assert tuple(match.key for match in matches) == (expected,)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("que desayuno hoy", "desayuno"),
        ("que como al mediodia", "almuerzo"),
        ("que comida toca", "almuerzo"),
        ("que merienda hago", "merienda"),
        ("pre entreno rapido", "pre_entreno"),
        ("que ceno por la noche", "cena"),
    ],
)
def test_detect_moments(sample_plan, message: str, expected: str) -> None:
    matches = detect_moments(sample_plan, message)

    assert tuple(match.key for match in matches) == (expected,)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("que tomo a media mañana", "media_manana"),
        ("despues del entreno que hago", "post_entreno"),
    ],
)
def test_detect_plan_defined_moments(
    sample_plan,
    message: str,
    expected: str,
) -> None:
    matches = detect_moments(sample_plan, message)

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
def test_resolve_meal_context(sample_plan, message: str, meal_key: str) -> None:
    resolution = resolve_meal_context(sample_plan, message)

    assert resolution.status == "resolved"
    assert resolution.is_resolved
    assert resolution.meal_block_key == meal_key
    assert resolution.meal_block is sample_plan.meals[meal_key]
    assert resolution.supplementation == ("10g de creatina monohidrato creapure",)


def test_resolve_full_day_context_uses_only_canonical_plan_moments(sample_plan) -> None:
    resolution = resolve_meal_context(
        sample_plan,
        "Dame todo lo que puedo comer hoy dia de ciclismo",
    )

    assert resolution.status == "resolved_day"
    assert resolution.is_resolved
    assert resolution.situation_key == "ciclismo"
    assert tuple(
        (day_meal.moment_key, day_meal.meal_block_key)
        for day_meal in resolution.day_meal_blocks
    ) == (
        ("desayuno", "comida_1"),
        ("almuerzo", "comida_2"),
        ("merienda", "comida_0"),
        ("cena", "comida_3"),
    )


def test_resolve_missing_situation(sample_plan) -> None:
    resolution = resolve_meal_context(sample_plan, "que como al mediodia?")

    assert resolution.status == "missing_situation"
    assert "CrossFit o entrenamiento de fuerza alta intensidad" in (
        resolution.available_situations
    )


def test_resolve_missing_moment(sample_plan) -> None:
    resolution = resolve_meal_context(sample_plan, "hoy tengo crossfit")

    assert resolution.status == "missing_moment"
    assert resolution.situation_key == "crossfit"
    assert resolution.available_moments == (
        "Desayuno",
        "Almuerzo",
        "Merienda",
        "Cena",
    )


def test_resolve_unmapped_plan_defined_moment(sample_plan) -> None:
    resolution = resolve_meal_context(
        sample_plan,
        "hoy tengo crossfit, que tomo a media mañana?",
    )

    assert resolution.status == "invalid_mapping"
    assert resolution.situation_key == "crossfit"
    assert resolution.moment_key == "media_manana"


def test_resolve_ambiguous_situation(sample_plan) -> None:
    resolution = resolve_meal_context(
        sample_plan,
        "hoy descanso pero hago bici suave, que como al mediodia?",
    )

    assert resolution.status == "ambiguous_situation"
    assert tuple(match.key for match in resolution.situation_matches) == (
        "ciclismo",
        "no_entreno",
    )


def test_resolve_ambiguous_moment(sample_plan) -> None:
    resolution = resolve_meal_context(
        sample_plan,
        "hoy tengo crossfit, comida y cena?",
    )

    assert resolution.status == "ambiguous_moment"
    assert tuple(match.key for match in resolution.moment_matches) == (
        "almuerzo",
        "cena",
    )
