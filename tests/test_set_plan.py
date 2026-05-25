import json
from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.bot_profile import BotProfile
from forge_bot.commands import auth_guard
from forge_bot.commands import set_plan as set_plan_module
from forge_bot.commands.set_plan import set_plan
from forge_bot.nutrition.plan import parse_nutrition_plan


class FakeMessage:
    def __init__(self, text: str | None, document: object | None = None) -> None:
        self.text = text
        self.document = document
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def nutrition_profile() -> BotProfile:
    return BotProfile(
        bot_profile_id="nutrition",
        bot_display_name="Nutrition",
        bot_description="Nutrition bot",
        system_prompt="Be useful.",
        domain_rules=("Use the plan.",),
        disclaimer_text="Test.",
        default_language="es",
        llm_provider="nvidia",
        llm_model="nvidia/test",
        memory_enabled=True,
        memory_backend="langchain_postgres",
        analytics_enabled=False,
    )


def sample_plan_data() -> dict[str, Any]:
    return {
        "plan_id": "uploaded_plan",
        "momentos": {"cena": {"label": "Cena", "aliases": ["cena"]}},
        "situaciones": {
            "no_entreno": {
                "label": "No entreno",
                "aliases": ["no entreno"],
                "suplementacion": [],
                "momentos": {"cena": "comida_1"},
            }
        },
        "comidas": {
            "comida_1": {
                "descripcion": "Cena",
                "and": ["200g merluza", "verdura"],
            }
        },
    }


def update_with_text(text: str) -> Any:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=FakeMessage(text),
    )


class FakeTelegramFile:
    def __init__(self, content: str) -> None:
        self.content = content

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self.content.encode("utf-8"))


class FakeDocument:
    def __init__(self, *, file_name: str, content: str) -> None:
        self.file_name = file_name
        self.mime_type = "application/json"
        self.file_size = len(content.encode("utf-8"))
        self.content = content

    async def get_file(self) -> FakeTelegramFile:
        return FakeTelegramFile(self.content)


def update_with_document(document: FakeDocument) -> Any:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=FakeMessage(None, document=document),
    )


@pytest.fixture(autouse=True)
def authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
    monkeypatch.setattr(
        auth_guard,
        "has_current_policy_acceptance",
        lambda telegram_id: True,
    )


@pytest.mark.asyncio
async def test_set_plan_pasted_json_saves_active_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_payloads: list[dict[str, Any]] = []

    def fake_save_active_nutrition_plan(**kwargs: object) -> SimpleNamespace:
        saved_payloads.append(dict(kwargs["plan_data"]))  # type: ignore[index]
        return SimpleNamespace(plan=parse_nutrition_plan(kwargs["plan_data"]))  # type: ignore[arg-type]

    monkeypatch.setattr(
        set_plan_module,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 7},
    )
    monkeypatch.setattr(
        set_plan_module.engine,
        "load_default_profile",
        nutrition_profile,
    )
    monkeypatch.setattr(
        set_plan_module.engine,
        "build_nutrition_normalizer",
        lambda profile: None,
    )
    monkeypatch.setattr(
        set_plan_module,
        "save_active_nutrition_plan",
        fake_save_active_nutrition_plan,
    )
    update = update_with_text("/set_plan " + json.dumps(sample_plan_data()))

    await set_plan(update, SimpleNamespace(args=[]))

    assert saved_payloads[0]["plan_id"] == "uploaded_plan"
    assert "Plan nutricional activo actualizado." in update.message.replies[0]
    assert "Normalizacion: validacion local" in update.message.replies[0]


@pytest.mark.asyncio
async def test_set_plan_accepts_partial_situations_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_calls: list[dict[str, object]] = []

    def fake_save_nutrition_plan_part(**kwargs: object) -> SimpleNamespace:
        partial_calls.append(dict(kwargs))
        return SimpleNamespace(
            activated=False,
            document_type="situaciones",
            missing_document_types=("comidas",),
        )

    monkeypatch.setattr(
        set_plan_module,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 7},
    )
    monkeypatch.setattr(
        set_plan_module.engine,
        "load_default_profile",
        nutrition_profile,
    )
    monkeypatch.setattr(
        set_plan_module,
        "save_nutrition_plan_part",
        fake_save_nutrition_plan_part,
    )
    update = update_with_text(
        "/set_plan "
        + json.dumps(
            {
                "momentos": {
                    "cena": {"label": "Cena", "aliases": ["cena", "noche"]}
                },
                "situaciones": {
                    "no_entreno": {
                        "momentos": {"cena": "comida_1"},
                        "suplementacion": [],
                    }
                }
            }
        )
    )

    await set_plan(update, SimpleNamespace(args=[]))

    assert partial_calls[0]["document_type"] == "situaciones"
    assert partial_calls[0]["content"]["momentos"] == {
        "cena": {"label": "Cena", "aliases": ["cena", "noche"]}
    }
    assert "Parte del plan guardada." in update.message.replies[0]
    assert "Falta: comidas" in update.message.replies[0]


@pytest.mark.asyncio
async def test_set_plan_accepts_document_without_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_calls: list[dict[str, object]] = []

    def fake_save_nutrition_plan_part(**kwargs: object) -> SimpleNamespace:
        partial_calls.append(dict(kwargs))
        return SimpleNamespace(
            activated=False,
            document_type="comidas",
            missing_document_types=("situaciones",),
        )

    monkeypatch.setattr(
        set_plan_module,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 7},
    )
    monkeypatch.setattr(
        set_plan_module.engine,
        "load_default_profile",
        nutrition_profile,
    )
    monkeypatch.setattr(
        set_plan_module,
        "save_nutrition_plan_part",
        fake_save_nutrition_plan_part,
    )
    document = FakeDocument(
        file_name="comidas.json",
        content=json.dumps({"comidas": sample_plan_data()["comidas"]}),
    )

    await set_plan(update_with_document(document), SimpleNamespace(args=[]))

    assert partial_calls[0]["document_type"] == "comidas"
    assert partial_calls[0]["source_filename"] == "comidas.json"


@pytest.mark.asyncio
async def test_set_plan_without_payload_explains_mobile_upload_flow() -> None:
    update = update_with_text("/set_plan")

    await set_plan(update, SimpleNamespace(args=[]))

    assert "Listo para cargar tu plan." in update.message.replies[0]
    assert "Desde movil no hace falta caption" in update.message.replies[0]
