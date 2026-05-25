import json
from types import SimpleNamespace
from typing import Any

import pytest

from forge_bot.commands import auth_guard
from forge_bot.commands import get_plan as get_plan_module
from forge_bot.commands.get_plan import get_plan
from forge_bot.nutrition.plan_store import ActiveNutritionPlanDocuments


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.documents: list[tuple[str, bytes]] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)

    async def reply_document(self, *, document: Any, filename: str) -> None:
        self.documents.append((filename, document.getvalue()))


def update() -> Any:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=FakeMessage(),
    )


def active_documents() -> ActiveNutritionPlanDocuments:
    situations = {
        "plan_id": "active_plan",
        "situaciones": {
            "no_entreno": {
                "suplementacion": [],
                "momentos": {"cena": "comida_1"},
            }
        },
    }
    meals = {
        "plan_id": "active_plan",
        "comidas": {
            "comida_1": {
                "descripcion": "Cena",
                "and": ["200g merluza", "verdura"],
            }
        },
    }
    return ActiveNutritionPlanDocuments(
        plan_uuid="plan-uuid",
        documents={"situaciones": situations, "comidas": meals},
        combined={
            "plan_id": "active_plan",
            "situaciones": situations["situaciones"],
            "comidas": meals["comidas"],
        },
    )


@pytest.fixture(autouse=True)
def authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
    monkeypatch.setattr(
        auth_guard,
        "has_current_policy_acceptance",
        lambda telegram_id: True,
    )
    monkeypatch.setattr(
        get_plan_module,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 7},
    )


@pytest.mark.asyncio
async def test_get_plan_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        get_plan_module,
        "load_active_nutrition_plan_documents",
        lambda user_id: active_documents(),
    )
    request = update()

    await get_plan(request, SimpleNamespace(args=[]))

    assert "Plan nutricional activo" in request.message.replies[0]
    assert "Plan: active_plan" in request.message.replies[0]
    assert "- no_entreno: 1 momentos" in request.message.replies[0]


@pytest.mark.asyncio
async def test_get_plan_exports_meals_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        get_plan_module,
        "load_active_nutrition_plan_documents",
        lambda user_id: active_documents(),
    )
    request = update()

    await get_plan(request, SimpleNamespace(args=["comidas"]))

    assert request.message.documents[0][0] == "comidas.json"
    payload = json.loads(request.message.documents[0][1].decode("utf-8"))
    assert payload["comidas"]["comida_1"]["descripcion"] == "Cena"


@pytest.mark.asyncio
async def test_get_plan_without_active_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        get_plan_module,
        "load_active_nutrition_plan_documents",
        lambda user_id: None,
    )
    request = update()

    await get_plan(request, SimpleNamespace(args=[]))

    assert "no tienes un plan nutricional activo" in request.message.replies[0]
