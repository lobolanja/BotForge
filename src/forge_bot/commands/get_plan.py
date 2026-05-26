from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.commands.auth_guard import require_login
from forge_bot.database import get_user_by_telegram_id
from forge_bot.messages import build_message
from forge_bot.nutrition.plan import parse_nutrition_plan
from forge_bot.nutrition.plan_store import (
    NUTRITION_PLAN_MEALS_DOCUMENT_TYPE,
    NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE,
    load_active_nutrition_plan_documents,
)

EXPORT_OPTIONS = frozenset(
    {
        "all",
        "todo",
        "combined",
        "combinado",
        "situaciones",
        "comidas",
    }
)


@require_login
async def get_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or export the authenticated user's active nutrition plan."""
    if not update.message or not update.effective_user:
        return

    user = get_user_by_telegram_id(update.effective_user.id)
    if not user or user.get("id") is None:
        await update.message.reply_text("No puedo localizar tu usuario interno ahora.")
        return

    active_documents = load_active_nutrition_plan_documents(user_id=int(user["id"]))
    if active_documents is None:
        await update.message.reply_text(
            "Todavia no tienes un plan nutricional activo. Sube situaciones y "
            "comidas con /set_plan."
        )
        return

    option = _export_option(context.args or [])
    if option is None:
        await update.message.reply_text(_summary_message(active_documents.combined))
        return

    content, filename = _export_payload(active_documents.documents, option)
    if content is None:
        await update.message.reply_text("No tengo ese documento en tu plan activo.")
        return

    await update.message.reply_document(
        document=_json_file(content),
        filename=filename,
    )


def _export_option(args: list[str]) -> str | None:
    if not args:
        return None
    option = args[0].strip().lower()
    return option if option in EXPORT_OPTIONS else None


def _summary_message(combined: Any) -> str:
    plan = parse_nutrition_plan(combined)
    situation_lines = []
    for situation_key, situation in plan.situations.items():
        moments = situation.get("momentos")
        moment_count = len(moments) if isinstance(moments, dict) else 0
        situation_lines.append(f"- {situation_key}: {moment_count} momentos")

    summary = build_message(
        "Plan nutricional activo",
        details=(
            ("Plan", plan.plan_id),
            ("Situaciones", str(len(plan.situations))),
            ("Comidas", str(len(plan.meals))),
            ("Revisar", "/get_plan situaciones | /get_plan comidas | /get_plan all"),
        ),
    )
    if situation_lines:
        summary = f"{summary}\n\nSituaciones:\n" + "\n".join(situation_lines[:12])
    return summary


def _export_payload(
    documents: Any,
    option: str,
) -> tuple[Any | None, str]:
    if option in {"situaciones"}:
        return (
            documents.get(NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE),
            "situaciones.json",
        )
    if option in {"comidas"}:
        return documents.get(NUTRITION_PLAN_MEALS_DOCUMENT_TYPE), "comidas.json"
    return _combined_payload(documents), "plan_nutricional.json"


def _combined_payload(documents: Any) -> dict[str, Any] | None:
    situations = documents.get(NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE)
    meals = documents.get(NUTRITION_PLAN_MEALS_DOCUMENT_TYPE)
    if not isinstance(situations, dict) or not isinstance(meals, dict):
        return None

    combined: dict[str, Any] = {}
    plan_id = situations.get("plan_id") or meals.get("plan_id")
    if isinstance(plan_id, str) and plan_id.strip():
        combined["plan_id"] = plan_id.strip()
    if isinstance(situations.get("situaciones"), dict):
        combined["situaciones"] = situations["situaciones"]
    if isinstance(meals.get("comidas"), dict):
        combined["comidas"] = meals["comidas"]
    for optional_key in ("reglas_adaptacion", "recetas"):
        optional = documents.get(optional_key)
        if isinstance(optional, dict) and optional_key in optional:
            combined[optional_key] = optional[optional_key]
    return combined


def _json_file(content: Any) -> BytesIO:
    payload = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
    file_obj = BytesIO(payload)
    file_obj.name = "plan.json"
    return file_obj
