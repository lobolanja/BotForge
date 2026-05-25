from __future__ import annotations

import logging

from telegram import Document, Update
from telegram.ext import ContextTypes

from forge_bot import engine
from forge_bot.bot_profile import BotProfileError
from forge_bot.commands.auth_guard import require_login
from forge_bot.database import get_user_by_telegram_id
from forge_bot.messages import build_message
from forge_bot.nutrition.normalizer import parse_json_object
from forge_bot.nutrition.plan import NutritionPlanError
from forge_bot.nutrition.plan_normalizer import normalize_uploaded_plan
from forge_bot.nutrition.plan_store import (
    NUTRITION_PLAN_MEALS_DOCUMENT_TYPE,
    NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE,
    NutritionPlanStoreError,
    save_active_nutrition_plan,
    save_nutrition_plan_part,
)

logger = logging.getLogger(__name__)

MAX_PLAN_UPLOAD_BYTES = 300_000
SUPPORTED_MIME_TYPES = frozenset(
    {
        "application/json",
        "text/plain",
        "application/octet-stream",
    }
)


@require_login
async def set_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store a user's active nutrition plan from pasted JSON or an attached file."""
    if not update.message or not update.effective_user:
        return

    message = update.message
    raw_text: str | None = None
    source_filename: str | None = None
    if message.document is not None:
        document_result = await _read_plan_document(message.document)
        if isinstance(document_result, str):
            raw_text = document_result
            source_filename = message.document.file_name
        else:
            await message.reply_text(document_result["message"])
            return
    else:
        raw_text = _command_text(message.text or "", context.args or [])

    if not raw_text or not raw_text.strip():
        await message.reply_text(
            build_message(
                "Listo para cargar tu plan.",
                details=(
                    (
                        "Paso 1",
                        "Envia situaciones.json como documento.",
                    ),
                    (
                        "Paso 2",
                        "Envia comidas.json como documento.",
                    ),
                    (
                        "Nota",
                        "Desde movil no hace falta caption en los ficheros.",
                    ),
                ),
            )
        )
        return

    user = get_user_by_telegram_id(update.effective_user.id)
    if not user or user.get("id") is None:
        await message.reply_text("No puedo localizar tu usuario interno ahora mismo.")
        return

    try:
        profile = engine.load_default_profile()
        if profile.bot_profile_id != "nutrition":
            await message.reply_text(
                "Este comando solo esta disponible con el perfil nutrition."
            )
            return
        partial_payload = _partial_plan_payload(raw_text)
        if partial_payload is not None:
            partial = save_nutrition_plan_part(
                user_id=int(user["id"]),
                document_type=partial_payload[0],
                content=partial_payload[1],
                source_filename=source_filename,
            )
            if not partial.activated:
                await message.reply_text(
                    build_message(
                        "Parte del plan guardada.",
                        details=(
                            ("Recibido", partial.document_type),
                            (
                                "Falta",
                                ", ".join(partial.missing_document_types),
                            ),
                        ),
                    )
                )
                return
            plan = partial.activated_plan
            if plan is None:
                await message.reply_text("No he podido activar el plan ahora mismo.")
                return
            source = "validacion local"
        else:
            normalizer = engine.build_nutrition_normalizer(profile)
            normalized = await normalize_uploaded_plan(
                raw_text=raw_text,
                client=normalizer[0] if normalizer is not None else None,
                model=normalizer[1] if normalizer is not None else None,
            )
            saved = save_active_nutrition_plan(
                user_id=int(user["id"]),
                plan_data=normalized.content,
                source_filename=source_filename,
            )
            plan = saved.plan
            source = "LLM" if normalized.normalized_by_llm else "validacion local"
    except (NutritionPlanError, NutritionPlanStoreError, BotProfileError) as exc:
        await message.reply_text(
            build_message(
                "No he podido guardar el plan.",
                details=(("Motivo", str(exc)),),
            )
        )
        return
    except Exception:
        logger.exception(
            "set_plan_failed telegram_user_id=%s",
            update.effective_user.id,
        )
        await message.reply_text("No he podido guardar el plan ahora mismo.")
        return

    await message.reply_text(
        build_message(
            "Plan nutricional activo actualizado.",
            details=(
                ("Plan", plan.plan_id),
                ("Situaciones", str(len(plan.situations))),
                ("Comidas", str(len(plan.meals))),
                ("Normalizacion", source),
            ),
        )
    )


async def _read_plan_document(document: Document) -> str | dict[str, str]:
    filename = document.file_name or "plan"
    if not _is_supported_document(document):
        return {
            "message": (
                "Sube un fichero .json o .txt con situaciones o comidas."
            )
        }
    if document.file_size and document.file_size > MAX_PLAN_UPLOAD_BYTES:
        return {
            "message": (
                "El fichero es demasiado grande para esta primera version. "
                f"Maximo: {MAX_PLAN_UPLOAD_BYTES // 1000} KB."
            )
        }

    telegram_file = await document.get_file()
    content = await telegram_file.download_as_bytearray()
    if len(content) > MAX_PLAN_UPLOAD_BYTES:
        return {
            "message": (
                "El fichero es demasiado grande para esta primera version. "
                f"Maximo: {MAX_PLAN_UPLOAD_BYTES // 1000} KB."
            )
        }
    try:
        return bytes(content).decode("utf-8")
    except UnicodeDecodeError:
        return {"message": f"No puedo leer {filename} como texto UTF-8."}


def _is_supported_document(document: Document) -> bool:
    filename = (document.file_name or "").lower()
    mime_type = document.mime_type or ""
    return filename.endswith((".json", ".txt")) or mime_type in SUPPORTED_MIME_TYPES


def _command_text(text: str, args: list[str]) -> str:
    if args:
        return " ".join(args)
    if text.startswith("/set_plan"):
        return text.removeprefix("/set_plan").strip()
    return text.strip()


def _partial_plan_payload(raw_text: str) -> tuple[str, dict[str, object]] | None:
    payload = parse_json_object(raw_text)
    if not isinstance(payload, dict):
        return None

    has_situations = isinstance(payload.get("situaciones"), dict)
    has_meals = isinstance(payload.get("comidas"), dict)
    if has_situations and has_meals:
        return None
    if has_situations:
        return (
            NUTRITION_PLAN_SITUATIONS_DOCUMENT_TYPE,
            {
                key: value
                for key, value in payload.items()
                if key in {"plan_id", "momentos", "situaciones"}
            },
        )
    if has_meals:
        return (
            NUTRITION_PLAN_MEALS_DOCUMENT_TYPE,
            {
                key: value
                for key, value in payload.items()
                if key in {"plan_id", "comidas"}
            },
        )
    return None
