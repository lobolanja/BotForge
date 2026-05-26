from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ..prompting import ChatMessage
from .normalizer import parse_json_object
from .plan import NutritionPlan, NutritionPlanError, parse_nutrition_plan

logger = logging.getLogger(__name__)


class NutritionPlanNormalizerClient(Protocol):
    """Small chat interface used to normalize uploaded nutrition plans."""

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        """Return the provider response for the normalization prompt."""


@dataclass(frozen=True)
class NormalizedPlanDocument:
    """Validated uploaded nutrition plan ready to persist."""

    content: Mapping[str, Any]
    plan: NutritionPlan
    normalized_by_llm: bool


async def normalize_uploaded_plan(
    *,
    raw_text: str,
    client: NutritionPlanNormalizerClient | None,
    model: str | None,
) -> NormalizedPlanDocument:
    """Normalize and validate an uploaded JSON plan document."""
    local_payload = _json_object_from_text(raw_text)
    if client is not None and model:
        try:
            llm_payload = await _normalize_with_llm(
                raw_text=raw_text,
                client=client,
                model=model,
                local_payload=local_payload,
            )
            return _validated_document(llm_payload, normalized_by_llm=True)
        except Exception:
            logger.warning("nutrition_plan_llm_normalization_failed", exc_info=True)

    if local_payload is None:
        raise NutritionPlanError(
            "El fichero debe contener JSON valido o poder normalizarse con el LLM."
        )
    return _validated_document(local_payload, normalized_by_llm=False)


async def _normalize_with_llm(
    *,
    raw_text: str,
    client: NutritionPlanNormalizerClient,
    model: str,
    local_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    response = await client.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "Normaliza un plan nutricional en JSON estricto para un bot. "
                    "Devuelve solo un objeto JSON. No inventes comidas ni "
                    "cantidades: conserva lo que exista en la entrada. Si la "
                    "entrada ya contiene JSON correcto, limpialo y normalizalo "
                    "sin cambiar el significado.\n\n"
                    "Contrato obligatorio:\n"
                    "{"
                    '"plan_id": string, '
                    '"momentos": {"moment_key": {"label": string, '
                    '"aliases": string[]}}, '
                    '"situaciones": {'
                    '"situation_key": {'
                    '"label": string, '
                    '"aliases": string[], '
                    '"tipo_dia": string|null, '
                    '"suplementacion": string[], '
                    '"momentos": {"moment_key": "comida_key"}'
                    "}"
                    "}, "
                    '"comidas": {'
                    '"comida_key": {'
                    '"descripcion": string, '
                    '"macros_plan": object|null, '
                    '"and": array, '
                    '"or": array'
                    "}"
                    "}, "
                    '"reglas_adaptacion": object|null, '
                    '"recetas": array|null'
                    "}\n\n"
                    "Reglas:\n"
                    "- Todas las referencias situaciones.*.momentos deben apuntar "
                    "a claves existentes en comidas.\n"
                    "- Si la entrada trae ficheros separados de situaciones.json "
                    "y comidas.json dentro del mismo objeto, conserva ambas "
                    "raices como `situaciones` y `comidas`.\n"
                    "- Los nombres de claves deben ser snake_case sin acentos.\n"
                    "- Mantén grupos and/or anidados si existen.\n"
                    "- Conserva macros_plan cuando exista; no calcules macros "
                    "nuevos.\n"
                    "- Conserva reglas_adaptacion si existen porque guian "
                    "conversiones y ajustes de recetas.\n"
                    "- Conserva recetas si existen, sin usarlas para cambiar "
                    "cantidades del plan.\n"
                    "- Si faltan aliases, crea aliases obvios desde label/clave.\n"
                    "- Si falta plan_id, usa user_nutrition_plan.\n"
                    "- No añadas situaciones ni alimentos nuevos.\n"
                    "- No expliques nada fuera del JSON."
                ),
            },
            {
                "role": "user",
                "content": _normalizer_user_payload(
                    raw_text=raw_text,
                    local_payload=local_payload,
                ),
            },
        ],
    )
    payload = parse_json_object(response)
    if payload is None:
        raise NutritionPlanError("El LLM no devolvio JSON valido.")
    return payload


def _normalizer_user_payload(
    *,
    raw_text: str,
    local_payload: Mapping[str, Any] | None,
) -> str:
    if local_payload is not None:
        return json.dumps(local_payload, ensure_ascii=False)
    return raw_text[:120_000]


def _validated_document(
    payload: Mapping[str, Any],
    *,
    normalized_by_llm: bool,
) -> NormalizedPlanDocument:
    plan = parse_nutrition_plan(payload)
    return NormalizedPlanDocument(
        content=payload,
        plan=plan,
        normalized_by_llm=normalized_by_llm,
    )


def _json_object_from_text(raw_text: str) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = parse_json_object(raw_text)
    return payload if isinstance(payload, dict) else None
