import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from forge_bot.bot_profile import load_active_bot_profile
from forge_bot.nutrition import orchestrator as nutrition_orchestrator
from forge_bot.nutrition.daily_state import NutritionDailyLog
from forge_bot.nutrition.orchestrator import (
    prepare_nutrition_prompt,
    prepare_nutrition_prompt_async,
)


def _nutrition_profile():
    return replace(
        load_active_bot_profile("nutrition", "bot_profiles"),
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
    )


def _payload(runtime_instruction: str) -> dict[str, object]:
    start = runtime_instruction.index('{"message_understanding"')
    return json.loads(runtime_instruction[start:])


class FakeNormalizerClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.models: list[str] = []
        self.messages: list[list[dict[str, str]]] = []

    async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
        self.models.append(model)
        self.messages.append(messages)
        return json.dumps(self.response)


def _write_custom_plan(path: Path) -> Path:
    plan_path = path / "custom_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "plan_id": "custom_user_plan",
                "momentos": {
                    "media_manana": {
                        "label": "Media manana",
                        "aliases": ["media manana", "snack manana"],
                    },
                    "cena": {"label": "Cena", "aliases": ["cena", "cenar"]},
                },
                "situaciones": {
                    "pilates": {
                        "label": "Pilates",
                        "aliases": ["pilates"],
                        "momentos": {
                            "media_manana": "snack_pilates",
                            "cena": "cena_pilates",
                        },
                    }
                },
                "comidas": {
                    "snack_pilates": {
                        "descripcion": "Snack de media manana",
                        "and": ["1 yogur proteico"],
                    },
                    "cena_pilates": {
                        "descripcion": "Cena ligera",
                        "and": ["240g pollo", "verdura"],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return plan_path


def test_prepare_nutrition_prompt_resolves_single_meal_chunk() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Hoy no entreno, que ceno?",
    )

    assert setup.direct_answer is None
    assert setup.include_memory is True
    assert setup.prompt_profile.context_documents == ()
    assert setup.runtime_instructions

    payload = _payload(setup.runtime_instructions[0])
    assert payload["message_understanding"]["intent"] == "recommend_meal"
    assert payload["nutrition_context"]["mode"] == "single_meal"
    assert payload["nutrition_context"]["situation_key"] == "no_entreno"
    assert payload["nutrition_context"]["moment_key"] == "cena"
    assert payload["nutrition_context"]["meal_block_key"] == "comida_3"


def test_prepare_nutrition_prompt_uses_recent_context_for_follow_up() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "cena",
        recent_conversation_messages=[
            {"role": "user", "content": "Que como hoy dia de no entreno?"},
            {"role": "assistant", "content": "Dime el momento."},
        ],
    )

    assert setup.direct_answer is None
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["situation_key"] == "no_entreno"
    assert payload["nutrition_context"]["moment_key"] == "cena"


def test_prepare_nutrition_prompt_preserves_deviation_context() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Que ceno hoy dia de no entreno? Me he saltado la media manana.",
    )

    assert setup.direct_answer is None
    payload = _payload(setup.runtime_instructions[0])
    assert payload["message_understanding"]["intent"] == "log_meal"
    assert payload["message_understanding"]["deviations"] == ["skipped_meal"]
    assert payload["nutrition_context"]["situation_key"] == "no_entreno"
    assert payload["nutrition_context"]["moment_key"] == "cena"


def test_prepare_nutrition_prompt_prioritizes_target_meal_over_daily_log() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        (
            "Hola, hoy es dia de futbol y en el desayuno tome una tostada con "
            "jamon y en la comida lentejas, que puedo tomar para la cena para "
            "compensar las proteinas que me faltaron en la comida?"
        ),
    )

    assert setup.direct_answer is None
    payload = _payload(setup.runtime_instructions[0])
    assert payload["message_understanding"]["intent"] == "recommend_meal"
    assert payload["nutrition_context"]["situation_key"] == "futbol"
    assert payload["nutrition_context"]["moment_key"] == "cena"
    assert payload["nutrition_context"]["meal_block_key"] == "comida_3"


def test_prepare_nutrition_prompt_asks_for_missing_context_without_llm() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Hoy tengo CrossFit",
    )

    assert setup.runtime_instructions == ()
    assert setup.direct_answer is not None
    assert "dime el momento" in setup.direct_answer


def test_prepare_nutrition_prompt_builds_weekly_planning_context() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        (
            "Hazme un plan de comidas para la semana: lunes CrossFit, miercoles "
            "futbol, viernes no entreno y el resto no entreno."
        ),
    )

    assert setup.direct_answer is None
    assert setup.include_memory is True
    payload = _payload(setup.runtime_instructions[0])
    context = payload["nutrition_context"]
    assert context["mode"] == "weekly_planning"
    assert set(context["situations"]) == {"crossfit", "futbol", "no_entreno"}
    assert {"comida_1", "comida_2", "comida_3", "comida_4", "comida_5"}.issubset(
        set(context["meal_blocks"])
    )


def test_prepare_nutrition_prompt_resolves_day_macros_without_meal_loop() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        (
            "Quiero saber los macros exactos que tengo un dia de futbol entre "
            "todas las comidas que tengo que hacer segun mi plan nutricional"
        ),
    )

    assert setup.direct_answer is None
    assert setup.include_memory is True
    payload = _payload(setup.runtime_instructions[0])
    assert payload["message_understanding"]["intent"] == "calculate_macros"
    assert payload["message_understanding"]["asks_for_full_day"] is True
    assert payload["nutrition_context"]["mode"] == "full_day"
    assert payload["nutrition_context"]["situation_key"] == "futbol"
    assert {
        item["moment_key"] for item in payload["nutrition_context"]["meal_blocks"]
    } == {"desayuno", "almuerzo", "merienda", "cena"}


def test_prepare_nutrition_prompt_uses_assistant_context_for_short_follow_up() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Futbol",
        recent_conversation_messages=[
            {"role": "user", "content": "Y si meriendo un batido de proteinas?"},
            {
                "role": "assistant",
                "content": "Para la merienda, dime primero el tipo de dia.",
            },
        ],
    )

    assert setup.direct_answer is None
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["situation_key"] == "futbol"
    assert payload["nutrition_context"]["moment_key"] == "merienda"


def test_prepare_nutrition_prompt_keeps_memory_for_non_plan_messages() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Te acuerdas de lo ultimo que te pregunte?",
    )

    assert setup.direct_answer is None
    assert setup.runtime_instructions == ()
    assert setup.include_memory is True
    assert setup.prompt_profile.context_documents == ()


def test_prepare_nutrition_prompt_without_db_plan_suggests_set_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = replace(_nutrition_profile(), nutrition_plan_path=None)
    monkeypatch.setattr(
        nutrition_orchestrator,
        "load_active_nutrition_plan",
        lambda *, user_id: None,
    )

    setup = prepare_nutrition_prompt(
        profile,
        "Hoy no entreno, que ceno?",
        internal_user_id=7,
    )

    assert setup.direct_answer is not None
    assert "/set_plan" in setup.direct_answer


def test_prepare_nutrition_prompt_without_db_plan_keeps_memory_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = replace(_nutrition_profile(), nutrition_plan_path=None)
    monkeypatch.setattr(
        nutrition_orchestrator,
        "load_active_nutrition_plan",
        lambda *, user_id: None,
    )

    setup = prepare_nutrition_prompt(
        profile,
        "Te acuerdas de lo ultimo que te dije?",
        internal_user_id=7,
    )

    assert setup.direct_answer is None
    assert setup.runtime_instructions == ()


def test_prepare_nutrition_prompt_shopping_list_uses_plan_and_memory() -> None:
    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Dame la lista de la compra.",
    )

    assert setup.direct_answer is None
    assert setup.include_memory is True
    payload = _payload(setup.runtime_instructions[0])
    assert payload["message_understanding"]["intent"] == "shopping_list"
    assert payload["nutrition_context"]["mode"] == "shopping_list"
    assert "no_entreno" in payload["nutrition_context"]["situations"]


def test_prepare_nutrition_prompt_uses_daily_log_for_short_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = NutritionDailyLog(
        id=10,
        user_id=7,
        bot_profile_id="nutrition",
        log_date=date(2026, 5, 24),
        plan_id="demo_nutrition_plan",
        situation_key="no_entreno",
        meals={},
        notes=(),
    )

    monkeypatch.setattr(
        nutrition_orchestrator.nutrition_daily_state,
        "load_daily_log",
        lambda **kwargs: log,
    )

    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "que ceno?",
        internal_user_id=7,
        current_date=date(2026, 5, 24),
    )

    assert setup.direct_answer is None
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["situation_key"] == "no_entreno"
    assert payload["nutrition_context"]["moment_key"] == "cena"
    assert payload["nutrition_context"]["daily_log"]["tipo_dia"] == "no_entreno"


def test_prepare_nutrition_prompt_uses_actual_day_after_training_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[object] = []
    log = NutritionDailyLog(
        id=11,
        user_id=7,
        bot_profile_id="nutrition",
        log_date=date(2026, 5, 24),
        plan_id="demo_nutrition_plan",
        situation_key="no_entreno",
        meals={},
        notes=({"text": "crossfit cancelado"},),
    )

    def fake_apply_daily_update(**kwargs: object) -> NutritionDailyLog:
        updates.append(kwargs["update"])
        return log

    monkeypatch.setattr(
        nutrition_orchestrator.nutrition_daily_state,
        "load_daily_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        nutrition_orchestrator.nutrition_daily_state,
        "apply_daily_update",
        fake_apply_daily_update,
    )

    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Al final no he ido al crossfit, que ceno?",
        internal_user_id=7,
        current_date=date(2026, 5, 24),
    )

    assert setup.direct_answer is None
    assert not updates
    assert setup.post_success_actions
    setup.post_success_actions[0]()
    assert getattr(updates[0], "situation_key") == "no_entreno"
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["situation_key"] == "no_entreno"
    assert payload["nutrition_context"]["moment_key"] == "cena"
    assert payload["nutrition_context"]["daily_log"]["tipo_dia"] == "no_entreno"


def test_prepare_nutrition_prompt_routes_activity_replacement_to_actual_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[object] = []
    log = NutritionDailyLog(
        id=12,
        user_id=7,
        bot_profile_id="nutrition",
        log_date=date(2026, 5, 24),
        plan_id="demo_nutrition_plan",
        situation_key="natacion",
        meals={},
        notes=({"text": "crossfit cambiado por natacion"},),
    )

    def fake_apply_daily_update(**kwargs: object) -> NutritionDailyLog:
        updates.append(kwargs["update"])
        return log

    monkeypatch.setattr(
        nutrition_orchestrator.nutrition_daily_state,
        "load_daily_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        nutrition_orchestrator.nutrition_daily_state,
        "apply_daily_update",
        fake_apply_daily_update,
    )

    setup = prepare_nutrition_prompt(
        _nutrition_profile(),
        "Al final cambio crossfit por natacion, que ceno?",
        internal_user_id=7,
        current_date=date(2026, 5, 24),
    )

    assert setup.direct_answer is None
    assert not updates
    assert setup.post_success_actions
    setup.post_success_actions[0]()
    assert getattr(updates[0], "situation_key") == "natacion"
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["situation_key"] == "natacion"
    assert payload["nutrition_context"]["moment_key"] == "cena"


@pytest.mark.asyncio
async def test_async_prompt_uses_llm_normalizer_with_user_plan_keys(
    tmp_path: Path,
) -> None:
    profile = replace(
        _nutrition_profile(),
        nutrition_plan_path=_write_custom_plan(tmp_path),
    )
    normalizer = FakeNormalizerClient(
        {
            "intent": "recommend_meal",
            "situation_key": "pilates",
            "situation_keys": ["pilates"],
            "target_moment_key": "media_manana",
            "mentioned_moment_keys": ["media_manana"],
            "logged_meals": [],
            "goal": "resolver snack personalizado",
            "confidence": "high",
        }
    )

    setup = await prepare_nutrition_prompt_async(
        profile,
        "Mi pareja va a pilates y quiere su snack de media manana",
        normalizer_client=normalizer,
        normalizer_model="nvidia/cheap-normalizer",
    )

    assert normalizer.models == ["nvidia/cheap-normalizer"]
    normalizer_prompt = normalizer.messages[0][0]["content"]
    assert "pilates" in normalizer_prompt
    assert "media_manana" in normalizer_prompt
    assert "snack_pilates" not in normalizer_prompt

    assert setup.direct_answer is None
    payload = _payload(setup.runtime_instructions[0])
    assert payload["normalized_message"]["situation_key"] == "pilates"
    assert payload["normalized_message"]["target_moment_key"] == "media_manana"
    assert payload["nutrition_context"]["situation_key"] == "pilates"
    assert payload["nutrition_context"]["moment_key"] == "media_manana"
    assert payload["nutrition_context"]["meal_block_key"] == "snack_pilates"


@pytest.mark.asyncio
async def test_async_prompt_sends_memory_to_normalizer(
    tmp_path: Path,
) -> None:
    profile = replace(
        _nutrition_profile(),
        nutrition_plan_path=_write_custom_plan(tmp_path),
    )
    normalizer = FakeNormalizerClient(
        {
            "intent": "recommend_meal",
            "situation_key": "pilates",
            "target_moment_key": "cena",
            "confidence": "high",
        }
    )

    setup = await prepare_nutrition_prompt_async(
        profile,
        "y para cenar?",
        compacted_user_memory="La conversacion activa era sobre pilates.",
        recent_conversation_messages=[
            {"role": "user", "content": "Hoy mi pareja va a pilates."},
        ],
        normalizer_client=normalizer,
        normalizer_model="nvidia/cheap-normalizer",
    )

    normalizer_prompt = normalizer.messages[0][0]["content"]
    assert "Conversation context" in normalizer_prompt
    assert "La conversacion activa era sobre pilates." in normalizer_prompt
    assert "Hoy mi pareja va a pilates." in normalizer_prompt
    assert setup.direct_answer is None


@pytest.mark.asyncio
async def test_async_prompt_ignores_invalid_llm_normalizer_keys(
    tmp_path: Path,
) -> None:
    profile = replace(
        _nutrition_profile(),
        nutrition_plan_path=_write_custom_plan(tmp_path),
    )
    normalizer = FakeNormalizerClient(
        {
            "intent": "recommend_meal",
            "situation_key": "futbol",
            "target_moment_key": "desayuno",
            "confidence": "high",
        }
    )

    setup = await prepare_nutrition_prompt_async(
        profile,
        "Pilates, que cena toca?",
        normalizer_client=normalizer,
        normalizer_model="nvidia/cheap-normalizer",
    )

    assert setup.direct_answer is None
    assert setup.normalized_message is not None
    assert setup.normalized_message.situation_key is None
    assert setup.normalized_message.target_moment_key is None
    assert "ignored_invalid_situation_key" in setup.normalized_message.warnings
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["situation_key"] == "pilates"
    assert payload["nutrition_context"]["moment_key"] == "cena"


@pytest.mark.asyncio
async def test_async_prompt_ignores_low_confidence_normalizer_route(
    tmp_path: Path,
) -> None:
    profile = replace(
        _nutrition_profile(),
        nutrition_plan_path=_write_custom_plan(tmp_path),
    )
    normalizer = FakeNormalizerClient(
        {
            "intent": "recommend_meal",
            "situation_key": "pilates",
            "target_moment_key": "cena",
            "confidence": "low",
        }
    )

    setup = await prepare_nutrition_prompt_async(
        profile,
        "resolver esto",
        normalizer_client=normalizer,
        normalizer_model="nvidia/cheap-normalizer",
    )

    assert setup.direct_answer is None
    assert setup.runtime_instructions == ()
    assert setup.normalized_message is not None
    assert setup.normalized_message.confidence == 0.3


@pytest.mark.asyncio
async def test_async_prompt_delegates_unclear_follow_up_to_llm_with_context() -> None:
    normalizer = FakeNormalizerClient(
        {
            "intent": "adjust_existing_meal",
            "goal": "seguir conversacion sobre batido de proteinas",
            "confidence": "medium",
        }
    )

    setup = await prepare_nutrition_prompt_async(
        _nutrition_profile(),
        "El batido de proteinas es un cacito de 70 ml de hsn evolate 2.0",
        compacted_user_memory=(
            "El usuario estaba valorando un batido para merienda en dia de futbol."
        ),
        recent_conversation_messages=[
            {"role": "user", "content": "Y si meriendo un batido de proteinas?"},
            {"role": "assistant", "content": "Lo revisamos con tu plan de futbol."},
        ],
        normalizer_client=normalizer,
        normalizer_model="nvidia/cheap-normalizer",
    )

    assert setup.direct_answer is None
    assert setup.include_memory is True
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["mode"] == "single_meal"
    assert payload["nutrition_context"]["situation_key"] == "futbol"
    assert payload["nutrition_context"]["moment_key"] == "merienda"


@pytest.mark.asyncio
async def test_async_prompt_uses_contextual_fallback_instead_of_looping() -> None:
    normalizer = FakeNormalizerClient(
        {
            "intent": "adjust_existing_meal",
            "goal": "seguir conversacion sobre batido de proteinas",
            "confidence": "medium",
        }
    )

    setup = await prepare_nutrition_prompt_async(
        _nutrition_profile(),
        "El batido de proteinas es un cacito de 70 ml de hsn evolate 2.0",
        recent_conversation_messages=[
            {"role": "user", "content": "Quiero ajustar el batido."},
        ],
        normalizer_client=normalizer,
        normalizer_model="nvidia/cheap-normalizer",
    )

    assert setup.direct_answer is None
    assert setup.include_memory is True
    payload = _payload(setup.runtime_instructions[0])
    assert payload["nutrition_context"]["mode"] == "unresolved_with_memory_fallback"
    assert payload["nutrition_context"]["resolution_status"] == "missing_situation"
