from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from ..prompting import ChatMessage
from .intent import (
    ALL_NUTRITION_INTENTS,
    NutritionIntent,
    NutritionMessageUnderstanding,
)
from .plan import NutritionPlan


class NutritionNormalizerClient(Protocol):
    """Small chat interface used by the message-normalization chain step."""

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        """Return the provider response for the normalization prompt."""


@dataclass(frozen=True)
class NormalizedNutritionMessage:
    """Validated normalized interpretation of one user message."""

    intent: NutritionIntent
    situation_key: str | None = None
    situation_keys: tuple[str, ...] = ()
    target_moment_key: str | None = None
    mentioned_moment_keys: tuple[str, ...] = ()
    logged_meals: tuple[Mapping[str, str | None], ...] = ()
    goal: str | None = None
    wants_day_overview: bool = False
    confidence: float = 0.0
    route_message: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def has_route_signal(self) -> bool:
        return bool(
            self.situation_key
            or self.situation_keys
            or self.target_moment_key
            or self.mentioned_moment_keys
            or self.logged_meals
            or self.wants_day_overview
        )

    def to_prompt_payload(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "situation_key": self.situation_key,
            "situation_keys": list(self.situation_keys),
            "target_moment_key": self.target_moment_key,
            "mentioned_moment_keys": list(self.mentioned_moment_keys),
            "logged_meals": list(self.logged_meals),
            "goal": self.goal,
            "wants_day_overview": self.wants_day_overview,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


async def normalize_message_with_llm(
    *,
    client: NutritionNormalizerClient,
    model: str,
    plan: NutritionPlan,
    message: str,
    local_understanding: NutritionMessageUnderstanding,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: Sequence[ChatMessage] | None = None,
) -> NormalizedNutritionMessage | None:
    """Ask a small model to map free text to plan-specific routing keys."""
    response = await client.chat(
        model=model,
        messages=_normalization_prompt(
            plan=plan,
            message=message,
            compacted_user_memory=compacted_user_memory,
            recent_conversation_messages=recent_conversation_messages or (),
        ),
    )
    payload = parse_json_object(response)
    if payload is None:
        return None
    return validate_normalized_payload(
        payload,
        plan=plan,
        local_understanding=local_understanding,
    )


def validate_normalized_payload(
    payload: Mapping[str, Any],
    *,
    plan: NutritionPlan,
    local_understanding: NutritionMessageUnderstanding,
) -> NormalizedNutritionMessage:
    """Validate model output against the active user's plan."""
    warnings: list[str] = []
    situation_keys = _plan_situation_keys(plan)
    moment_keys = _plan_moment_keys(plan)

    raw_intent = payload.get("intent")
    intent = (
        cast(NutritionIntent, raw_intent)
        if isinstance(raw_intent, str) and raw_intent in ALL_NUTRITION_INTENTS
        else local_understanding.intent
    )
    if intent == "unknown" and local_understanding.intent != "unknown":
        intent = local_understanding.intent

    situation_key = _validated_optional_key(
        payload.get("situation_key"),
        allowed=situation_keys,
        warning_name="situation_key",
        warnings=warnings,
    )
    selected_situation_keys = _validated_key_tuple(
        payload.get("situation_keys"),
        allowed=situation_keys,
        warning_name="situation_keys",
        warnings=warnings,
    )
    if situation_key and situation_key not in selected_situation_keys:
        selected_situation_keys = (situation_key, *selected_situation_keys)

    target_moment_key = _validated_optional_key(
        payload.get("target_moment_key"),
        allowed=moment_keys,
        warning_name="target_moment_key",
        warnings=warnings,
    )
    mentioned_moment_keys = _validated_key_tuple(
        payload.get("mentioned_moment_keys"),
        allowed=moment_keys,
        warning_name="mentioned_moment_keys",
        warnings=warnings,
    )
    if target_moment_key and target_moment_key not in mentioned_moment_keys:
        mentioned_moment_keys = (target_moment_key, *mentioned_moment_keys)

    logged_meals = _validated_logged_meals(
        payload.get("logged_meals"),
        moment_keys=moment_keys,
    )
    goal = _optional_text(payload.get("goal"))
    wants_day_overview = _optional_bool(payload.get("wants_day_overview"))
    confidence = _confidence(payload.get("confidence"))
    route_message = _route_message(
        situation_key=situation_key,
        target_moment_key=target_moment_key,
        wants_day_overview=wants_day_overview,
    )

    return NormalizedNutritionMessage(
        intent=intent,
        situation_key=situation_key,
        situation_keys=selected_situation_keys,
        target_moment_key=target_moment_key,
        mentioned_moment_keys=mentioned_moment_keys,
        logged_meals=logged_meals,
        goal=goal,
        wants_day_overview=wants_day_overview,
        confidence=confidence,
        route_message=route_message,
        warnings=tuple(warnings),
    )


def _normalization_prompt(
    *,
    plan: NutritionPlan,
    message: str,
    compacted_user_memory: str | None,
    recent_conversation_messages: Sequence[ChatMessage],
) -> list[ChatMessage]:
    options = {
        "allowed_intents": list(ALL_NUTRITION_INTENTS),
        "situations": {
            key: {
                "label": _optional_text(situation.get("label")) or key,
                "aliases": _string_list(situation.get("aliases")),
            }
            for key, situation in plan.situations.items()
        },
        "moments": _moment_options(plan),
    }
    conversation_context = _normalizer_conversation_context(
        compacted_user_memory=compacted_user_memory,
        recent_conversation_messages=recent_conversation_messages,
    )
    return [
        {
            "role": "system",
            "content": (
                "/no_think\n"
                "Normalize one Spanish nutrition-bot user message into strict "
                "JSON. Use only the allowed situation and moment keys supplied "
                "by the active user's plan. Do not infer quantities or foods "
                "from the meal plan. Distinguish past logged meals from the "
                "target meal the user wants to resolve.\n\n"
                "Use the conversation context to resolve short follow-ups like "
                "'eso', 'lo de antes', 'fútbol', 'para cenar', or corrections. "
                "If the current message asks for macros, all meals, the whole "
                "day, or 'entre todas las comidas', set wants_day_overview=true. "
                "If the current message is just adding context to the previous "
                "topic, keep the same situation/moment when it is clear from "
                "conversation context. If it is not clear, leave keys null "
                "instead of guessing.\n\n"
                "Return only one JSON object with this schema:\n"
                "{"
                '"intent": string, '
                '"situation_key": string|null, '
                '"situation_keys": string[], '
                '"target_moment_key": string|null, '
                '"mentioned_moment_keys": string[], '
                '"logged_meals": [{"moment_key": string|null, "text": string}], '
                '"goal": string|null, '
                '"wants_day_overview": boolean, '
                '"confidence": "low|medium|high"'
                "}\n\n"
                f"Allowed options:\n{json.dumps(options, ensure_ascii=False)}"
                f"{conversation_context}"
            ),
        },
        {"role": "user", "content": message},
    ]


def parse_json_object(content: str) -> Mapping[str, Any] | None:
    """Extract a JSON object from plain text or fenced model output."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    decoder = json.JSONDecoder()
    try:
        payload = decoder.decode(cleaned)
    except json.JSONDecodeError:
        payload = None
        for index, char in enumerate(cleaned):
            if char != "{":
                continue
            try:
                candidate, _end = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
    return payload if isinstance(payload, dict) else None


def _plan_situation_keys(plan: NutritionPlan) -> frozenset[str]:
    return frozenset(plan.situations.keys())


def _plan_moment_keys(plan: NutritionPlan) -> frozenset[str]:
    keys = set(plan.moments.keys())
    for situation in plan.situations.values():
        moments = situation.get("momentos", {})
        if isinstance(moments, dict):
            keys.update(str(moment_key) for moment_key in moments)
    return frozenset(keys)


def _moment_options(plan: NutritionPlan) -> dict[str, dict[str, object]]:
    options: dict[str, dict[str, object]] = {}
    for key in sorted(_plan_moment_keys(plan)):
        moment = plan.moments.get(key, {})
        label = moment.get("label") if isinstance(moment, dict) else None
        aliases = moment.get("aliases") if isinstance(moment, dict) else None
        options[key] = {
            "label": label.strip() if isinstance(label, str) and label.strip() else key,
            "aliases": _string_list(aliases),
        }
    return options


def _validated_optional_key(
    value: object,
    *,
    allowed: frozenset[str],
    warning_name: str,
    warnings: list[str],
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value in allowed:
        return value
    warnings.append(f"ignored_invalid_{warning_name}")
    return None


def _validated_key_tuple(
    value: object,
    *,
    allowed: frozenset[str],
    warning_name: str,
    warnings: list[str],
) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    keys: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str) and item in allowed and item not in seen:
            seen.add(item)
            keys.append(item)
        elif item is not None:
            warnings.append(f"ignored_invalid_{warning_name}")
    return tuple(keys)


def _validated_logged_meals(
    value: object,
    *,
    moment_keys: frozenset[str],
) -> tuple[Mapping[str, str | None], ...]:
    if not isinstance(value, list):
        return ()
    meals: list[Mapping[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        moment = item.get("moment_key")
        text = item.get("text")
        moment_key = (
            moment if isinstance(moment, str) and moment in moment_keys else None
        )
        meal_text = text.strip() if isinstance(text, str) and text.strip() else None
        meals.append(
            {
                "moment_key": moment_key,
                "text": meal_text,
            }
        )
    return tuple(meals)


def _route_message(
    *,
    situation_key: str | None,
    target_moment_key: str | None,
    wants_day_overview: bool,
) -> str | None:
    parts = [part for part in (situation_key, target_moment_key) if part]
    if wants_day_overview:
        parts.append("todo el dia")
    return " ".join(parts) if parts else None


def _confidence(value: object) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    if not isinstance(value, str):
        return 0.0
    normalized = value.strip().lower()
    if normalized == "high":
        return 0.9
    if normalized == "medium":
        return 0.6
    if normalized == "low":
        return 0.3
    return 0.0


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_bool(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalizer_conversation_context(
    *,
    compacted_user_memory: str | None,
    recent_conversation_messages: Sequence[ChatMessage],
) -> str:
    sections: list[str] = []
    if compacted_user_memory and compacted_user_memory.strip():
        sections.append("Compacted memory:\n" + compacted_user_memory.strip()[:2500])
    recent = [
        f"{message['role']}: {message['content'].strip()[:500]}"
        for message in recent_conversation_messages[-8:]
        if message["content"].strip()
    ]
    if recent:
        sections.append("Recent conversation:\n" + "\n".join(recent))
    if not sections:
        return ""
    return "\n\nConversation context:\n" + "\n\n".join(sections)
