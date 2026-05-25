from datetime import date, datetime, timezone
from pathlib import Path

from forge_bot.nutrition.daily_state import (
    NutritionDailyLog,
    build_daily_update,
    message_cancels_training,
    message_changes_day_type,
    preview_daily_update,
    to_prompt_payload,
)
from forge_bot.nutrition.intent import classify_nutrition_message
from forge_bot.nutrition.plan import load_nutrition_plan_file


def _sample_plan():
    return load_nutrition_plan_file(Path("tests/fixtures/nutrition_plan.json"))


def test_daily_update_detects_training_cancellation_as_actual_rest_day() -> None:
    plan = _sample_plan()
    message = "Al final no he ido al crossfit, que ceno?"

    update = build_daily_update(
        plan=plan,
        message=message,
        understanding=classify_nutrition_message(message),
        normalized_message=None,
    )

    assert update.situation_key == "no_entreno"
    assert update.note is not None
    assert "Tipo de dia actualizado a no_entreno" in update.note
    assert message_cancels_training(message) is True
    assert message_changes_day_type(message) is True


def test_daily_update_detects_activity_replacement_as_day_type() -> None:
    plan = _sample_plan()
    message = "Al final cambio crossfit por natacion, que ceno?"

    update = build_daily_update(
        plan=plan,
        message=message,
        understanding=classify_nutrition_message(message),
        normalized_message=None,
    )

    assert update.situation_key == "natacion"
    assert update.note is not None
    assert "Tipo de dia actualizado a natacion" in update.note
    assert message_changes_day_type(message) is True


def test_daily_update_detects_current_activity_without_previous_activity() -> None:
    plan = _sample_plan()
    message = "Al final voy a natacion, que ceno?"

    update = build_daily_update(
        plan=plan,
        message=message,
        understanding=classify_nutrition_message(message),
        normalized_message=None,
    )

    assert update.situation_key == "natacion"


def test_daily_update_does_not_store_hypothetical_situation() -> None:
    plan = _sample_plan()
    message = "Futbol, que ceno?"

    update = build_daily_update(
        plan=plan,
        message=message,
        understanding=classify_nutrition_message(message),
        normalized_message=None,
    )

    assert update.situation_key is None


def test_daily_update_detects_skipped_meal_moment() -> None:
    plan = _sample_plan()
    message = "Que ceno hoy dia de no entreno? Me he saltado la merienda."

    update = build_daily_update(
        plan=plan,
        message=message,
        understanding=classify_nutrition_message(message),
        normalized_message=None,
    )

    assert update.situation_key == "no_entreno"
    assert update.skipped_moments == ("merienda",)


def test_preview_daily_update_does_not_persist_but_projects_prompt_state() -> None:
    plan = _sample_plan()
    update = build_daily_update(
        plan=plan,
        message="Hoy no entreno, que ceno?",
        understanding=classify_nutrition_message("Hoy no entreno, que ceno?"),
        normalized_message=None,
    )

    preview = preview_daily_update(
        log=None,
        user_id=7,
        bot_profile_id="nutrition",
        log_date=date(2026, 5, 24),
        plan=plan,
        update=update,
    )

    assert preview is not None
    assert preview.id == 0
    assert preview.situation_key == "no_entreno"


def test_daily_log_prompt_payload_is_compact_and_uses_day_type() -> None:
    log = NutritionDailyLog(
        id=1,
        user_id=7,
        bot_profile_id="nutrition",
        log_date=date(2026, 5, 24),
        plan_id="demo",
        situation_key="no_entreno",
        situation_updated_at=datetime(2026, 5, 24, 20, 0, tzinfo=timezone.utc),
        meals={
            "desayuno": {
                "status": "completed",
                "completed": True,
                "text": "tostada",
            }
        },
        notes=({"text": "cambio de dia"},),
    )

    payload = to_prompt_payload(log)

    assert payload is not None
    assert payload["tipo_dia"] == "no_entreno"
    assert payload["situation_key"] == "no_entreno"
    assert payload["meals"] == {
        "desayuno": {
            "status": "completed",
            "completed": True,
            "text": "tostada",
        }
    }
