import pytest

from forge_bot.nutrition.intent import classify_nutrition_message


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        (
            "Hazme la planificacion de la semana: lunes CrossFit, miercoles futbol "
            "y viernes no entreno.",
            "weekly_planning",
        ),
        ("Dame la lista de la compra.", "shopping_list"),
        ("Que ceno hoy dia de no entreno?", "recommend_meal"),
        (
            "Voy a cenar salmon con ensalada, le meto aguacate?",
            "adjust_existing_meal",
        ),
        (
            "He comido secreto y chuletas, como compenso la cena?",
            "recover_from_high_fat_meal",
        ),
        (
            "Me acabo de dar un atracon de dulces y un gofre.",
            "recover_from_high_carb_meal",
        ),
        ("Anoche me tome dos cervezas.", "alcohol_recovery_or_guidance"),
        ("Con respecto al plan, como vamos hoy?", "evaluate_day"),
        ("Cuanta proteina llevo?", "calculate_macros"),
        ("Estoy reventado del CrossFit, dime algo facil.", "recovery_guidance"),
        ("Puedo tomar creatina?", "supplement_guidance"),
        (
            "Quiero dejar pollo congelado para varios dias.",
            "batch_cooking_or_recipe_preparation",
        ),
        ("Te paso una receta de arroz con atun y huevo.", "recipe_submission"),
        ("/set_plan", "plan_generation"),
        ("Tengo hambre pero no quiero liarla.", "hunger_management"),
    ],
)
def test_classify_nutrition_messages(message: str, expected_intent: str) -> None:
    understanding = classify_nutrition_message(message)

    assert understanding.intent == expected_intent


def test_classify_weekly_planning_extracts_days_foods_and_people() -> None:
    understanding = classify_nutrition_message(
        "Hazme la planificacion de la semana. Yo lunes CrossFit, miercoles futbol, "
        "viernes no entreno. Mi pareja hace CrossFit jueves. Mete salmon el lunes."
    )

    assert understanding.intent == "multi_person_meal_planning"
    assert understanding.mentioned_days == ("lunes", "miercoles", "jueves", "viernes")
    assert "salmon" in understanding.foods
    assert understanding.people == ("pareja",)


def test_classify_deviations_are_preserved_for_follow_up_adjustments() -> None:
    understanding = classify_nutrition_message(
        "Que ceno hoy dia de no entreno? Me he saltado la media manana."
    )

    assert understanding.intent == "log_meal"
    assert understanding.deviations == ("skipped_meal",)


def test_classify_macro_day_request_as_full_day_context() -> None:
    understanding = classify_nutrition_message(
        "Cuantos macros tengo que tomar un dia de futbol?"
    )

    assert understanding.intent == "calculate_macros"
    assert understanding.asks_for_full_day is True
