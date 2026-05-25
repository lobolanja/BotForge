from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, cast

from langchain_core.runnables import Runnable, RunnableLambda

from ..bot_profile import BotProfile
from ..prompting import ChatMessage
from . import daily_state as nutrition_daily_state
from .intent import (
    INTENTS_THAT_NEED_PLAN_CONTEXT,
    NutritionMessageUnderstanding,
    classify_nutrition_message,
)
from .normalizer import (
    NormalizedNutritionMessage,
    NutritionNormalizerClient,
    normalize_message_with_llm,
)
from .plan import NutritionPlan, NutritionPlanError, load_nutrition_plan_file
from .plan_store import load_active_nutrition_plan
from .router import (
    MealResolution,
    SituationMatch,
    detect_situations,
    normalize_text,
    resolve_meal_context,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NutritionPromptSetup:
    """Nutrition-specific prompt setup returned to the generic engine."""

    prompt_profile: BotProfile
    runtime_instructions: tuple[str, ...] = ()
    direct_answer: str | None = None
    include_memory: bool = True
    understanding: NutritionMessageUnderstanding | None = None
    normalized_message: NormalizedNutritionMessage | None = None
    post_success_actions: tuple[Callable[[], None], ...] = ()


@dataclass(frozen=True)
class NutritionDailyLogContext:
    """Daily log state to read now and persist only after answer delivery."""

    log: nutrition_daily_state.NutritionDailyLog | None = None
    post_success_actions: tuple[Callable[[], None], ...] = ()


@dataclass(frozen=True)
class NutritionDailyLogCommit:
    """Deferred daily log write for a successfully answered turn."""

    user_id: int
    bot_profile_id: str
    log_date: date
    plan: NutritionPlan
    update: nutrition_daily_state.DailyNutritionUpdate

    def __call__(self) -> None:
        if not self.update.has_changes:
            return
        nutrition_daily_state.apply_daily_update(
            user_id=self.user_id,
            bot_profile_id=self.bot_profile_id,
            log_date=self.log_date,
            plan=self.plan,
            update=self.update,
        )


def prepare_nutrition_prompt(
    profile: BotProfile,
    message: str,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: Sequence[ChatMessage] | None = None,
    internal_user_id: int | None = None,
    current_date: date | None = None,
) -> NutritionPromptSetup:
    """Build nutrition runtime instructions with a LangChain orchestration chain."""
    if profile.bot_profile_id != "nutrition":
        return NutritionPromptSetup(prompt_profile=profile)

    chain = build_nutrition_orchestration_chain()
    return chain.invoke(
        {
            "profile": profile,
            "message": message,
            "compacted_user_memory": compacted_user_memory,
            "recent_conversation_messages": recent_conversation_messages or [],
            "internal_user_id": internal_user_id,
            "current_date": current_date,
        }
    )


async def prepare_nutrition_prompt_async(
    profile: BotProfile,
    message: str,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: Sequence[ChatMessage] | None = None,
    normalizer_client: NutritionNormalizerClient | None = None,
    normalizer_model: str | None = None,
    internal_user_id: int | None = None,
    current_date: date | None = None,
) -> NutritionPromptSetup:
    """Build nutrition prompt setup with an optional model normalization step."""
    if profile.bot_profile_id != "nutrition":
        return NutritionPromptSetup(prompt_profile=profile)

    chain = _build_nutrition_orchestration_chain(
        normalizer_enabled=normalizer_client is not None and bool(normalizer_model)
    )
    return await chain.ainvoke(
        {
            "profile": profile,
            "message": message,
            "compacted_user_memory": compacted_user_memory,
            "recent_conversation_messages": recent_conversation_messages or [],
            "normalizer_client": normalizer_client,
            "normalizer_model": normalizer_model,
            "internal_user_id": internal_user_id,
            "current_date": current_date,
        }
    )


def build_nutrition_orchestration_chain() -> Runnable[
    Mapping[str, Any],
    NutritionPromptSetup,
]:
    """Create the current nutrition orchestration pipeline.

    The first runnable is intentionally local and cheap. It normalizes and
    classifies the user message before any remote model sees the prompt. Later
    steps can be swapped for MCP-backed tools or model calls without changing
    the generic engine contract.
    """
    return _build_nutrition_orchestration_chain(normalizer_enabled=False)


def _build_nutrition_orchestration_chain(
    *,
    normalizer_enabled: bool,
) -> Runnable[
    Mapping[str, Any],
    NutritionPromptSetup,
]:
    route_step = (
        _route_plan_context_async if normalizer_enabled else _route_plan_context
    )
    return RunnableLambda(_understand_message).pipe(RunnableLambda(route_step))


def _understand_message(state: Mapping[str, Any]) -> dict[str, Any]:
    message = str(state["message"])
    return {
        **state,
        "prompt_profile": replace(state["profile"], context_documents=()),
        "understanding": classify_nutrition_message(message),
    }


def _route_plan_context(state: Mapping[str, Any]) -> NutritionPromptSetup:
    return _route_plan_context_loaded(state, normalized_message=None)


async def _route_plan_context_async(state: Mapping[str, Any]) -> NutritionPromptSetup:
    return await _route_plan_context_loaded_async(state)


def _route_plan_context_loaded(
    state: Mapping[str, Any],
    *,
    normalized_message: NormalizedNutritionMessage | None,
) -> NutritionPromptSetup:
    profile: BotProfile = state["profile"]
    prompt_profile: BotProfile = state["prompt_profile"]
    understanding: NutritionMessageUnderstanding = state["understanding"]

    try:
        plan = _load_plan_for_state(profile=profile, state=state)
    except NutritionPlanError:
        logger.exception(
            "nutrition_plan_load_failed profile=%s",
            profile.bot_profile_id,
        )
        return NutritionPromptSetup(
            prompt_profile=prompt_profile,
            direct_answer="No puedo leer el plan nutricional configurado ahora mismo.",
            understanding=understanding,
            normalized_message=normalized_message,
        )
    if plan is None:
        return _missing_active_plan_setup(
            prompt_profile=prompt_profile,
            message=str(state["message"]),
            understanding=understanding,
            normalized_message=normalized_message,
        )

    return _route_plan_context_loaded_with_plan(
        state,
        plan=plan,
        normalized_message=normalized_message,
    )


async def _route_plan_context_loaded_async(
    state: Mapping[str, Any],
) -> NutritionPromptSetup:
    profile: BotProfile = state["profile"]
    prompt_profile: BotProfile = state["prompt_profile"]
    understanding: NutritionMessageUnderstanding = state["understanding"]

    try:
        plan = _load_plan_for_state(profile=profile, state=state)
    except NutritionPlanError:
        logger.exception(
            "nutrition_plan_load_failed profile=%s",
            profile.bot_profile_id,
        )
        return NutritionPromptSetup(
            prompt_profile=prompt_profile,
            direct_answer="No puedo leer el plan nutricional configurado ahora mismo.",
            understanding=understanding,
        )
    if plan is None:
        return _missing_active_plan_setup(
            prompt_profile=prompt_profile,
            message=str(state["message"]),
            understanding=understanding,
            normalized_message=None,
        )

    normalized_message = await _normalize_with_model(
        state=state,
        plan=plan,
        understanding=understanding,
    )
    return _route_plan_context_loaded_with_plan(
        state,
        plan=plan,
        normalized_message=normalized_message,
    )


def _route_plan_context_loaded_with_plan(
    state: Mapping[str, Any],
    *,
    plan: NutritionPlan,
    normalized_message: NormalizedNutritionMessage | None,
) -> NutritionPromptSetup:
    copied_state = dict(state)
    copied_state["loaded_plan"] = plan
    return _route_plan_context_from_loaded_plan(
        copied_state,
        normalized_message=normalized_message,
    )


def _route_plan_context_from_loaded_plan(
    state: Mapping[str, Any],
    *,
    normalized_message: NormalizedNutritionMessage | None,
) -> NutritionPromptSetup:
    prompt_profile: BotProfile = state["prompt_profile"]
    message = str(state["message"])
    recent_conversation_messages: Sequence[ChatMessage] = state[
        "recent_conversation_messages"
    ]
    compacted_user_memory = _optional_state_text(state.get("compacted_user_memory"))
    understanding: NutritionMessageUnderstanding = state["understanding"]
    plan: NutritionPlan = state["loaded_plan"]

    if not _should_use_plan_context(
        understanding,
        message,
        plan=plan,
        normalized_message=normalized_message,
    ):
        return NutritionPromptSetup(
            prompt_profile=prompt_profile,
            understanding=understanding,
            normalized_message=normalized_message,
        )

    effective_intent = _effective_intent(understanding, normalized_message)
    daily_log_context = _load_daily_log_context(
        state=state,
        plan=plan,
        normalized_message=normalized_message,
    )
    if effective_intent in {"weekly_planning", "multi_person_meal_planning"}:
        return _weekly_planning_setup(
            plan=plan,
            prompt_profile=prompt_profile,
            message=message,
            understanding=understanding,
            normalized_message=normalized_message,
            daily_log_context=daily_log_context,
        )

    if effective_intent == "shopping_list":
        return _shopping_list_setup(
            plan=plan,
            prompt_profile=prompt_profile,
            understanding=understanding,
            normalized_message=normalized_message,
            daily_log_context=daily_log_context,
        )

    route_message = _routing_message_for_context(
        message,
        understanding,
        normalized_message=normalized_message,
    )
    route_message = _route_message_with_daily_log(
        plan=plan,
        message=message,
        route_message=route_message,
        daily_log=daily_log_context.log,
        understanding=understanding,
        normalized_message=normalized_message,
    )
    resolution = _resolve_nutrition_context_with_follow_up(
        plan,
        route_message,
        recent_conversation_messages,
        compacted_user_memory=compacted_user_memory,
    )
    if not resolution.is_resolved:
        if _should_defer_clarification_to_llm(
            understanding=understanding,
            normalized_message=normalized_message,
            resolution=resolution,
        ):
            return _unresolved_context_setup(
                plan=plan,
                prompt_profile=prompt_profile,
                resolution=resolution,
                understanding=understanding,
                normalized_message=normalized_message,
                daily_log_context=daily_log_context,
            )
        return NutritionPromptSetup(
            prompt_profile=prompt_profile,
            direct_answer=_nutrition_clarification(resolution),
            understanding=understanding,
            normalized_message=normalized_message,
            post_success_actions=daily_log_context.post_success_actions,
        )

    return NutritionPromptSetup(
        prompt_profile=prompt_profile,
        runtime_instructions=(
            _runtime_context_instruction(
                context=_attach_daily_log(
                    _nutrition_context_payload(resolution),
                    daily_log=daily_log_context.log,
                ),
                understanding=understanding,
                normalized_message=normalized_message,
            ),
        ),
        include_memory=True,
        understanding=understanding,
        normalized_message=normalized_message,
        post_success_actions=daily_log_context.post_success_actions,
    )


def _load_plan_for_state(
    *,
    profile: BotProfile,
    state: Mapping[str, Any],
) -> NutritionPlan | None:
    if profile.nutrition_plan_path is not None:
        return load_nutrition_plan_file(profile.nutrition_plan_path)

    user_id = state.get("internal_user_id")
    if not isinstance(user_id, int):
        return None
    return load_active_nutrition_plan(user_id=user_id)


def _missing_active_plan_setup(
    *,
    prompt_profile: BotProfile,
    message: str,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
) -> NutritionPromptSetup:
    if not _looks_like_nutrition_question_without_plan(understanding, message):
        return NutritionPromptSetup(
            prompt_profile=prompt_profile,
            understanding=understanding,
            normalized_message=normalized_message,
        )
    return NutritionPromptSetup(
        prompt_profile=prompt_profile,
        direct_answer=(
            "Todavia no tengo tu plan nutricional activo. Sube un JSON con "
            "/set_plan para poder darte cantidades y opciones concretas."
        ),
        understanding=understanding,
        normalized_message=normalized_message,
    )


async def _normalize_with_model(
    *,
    state: Mapping[str, Any],
    plan: NutritionPlan,
    understanding: NutritionMessageUnderstanding,
) -> NormalizedNutritionMessage | None:
    client = state.get("normalizer_client")
    model = state.get("normalizer_model")
    if client is None or not isinstance(model, str) or not model.strip():
        return None
    try:
        return await normalize_message_with_llm(
            client=client,
            model=model,
            plan=plan,
            message=str(state["message"]),
            local_understanding=understanding,
            compacted_user_memory=_optional_state_text(
                state.get("compacted_user_memory")
            ),
            recent_conversation_messages=cast(
                Sequence[ChatMessage],
                state.get("recent_conversation_messages", ()),
            ),
        )
    except Exception:
        logger.warning("nutrition_message_normalization_failed", exc_info=True)
        return None


def _should_use_plan_context(
    understanding: NutritionMessageUnderstanding,
    message: str,
    *,
    plan: NutritionPlan,
    normalized_message: NormalizedNutritionMessage | None = None,
) -> bool:
    if (
        normalized_message is not None
        and (
            normalized_message.has_route_signal
            or normalized_message.intent != "unknown"
        )
        and normalized_message.confidence >= 0.55
        and normalized_message.intent in INTENTS_THAT_NEED_PLAN_CONTEXT
    ):
        return True
    if understanding.intent in INTENTS_THAT_NEED_PLAN_CONTEXT:
        return True
    return _looks_like_nutrition_routing_query(message, plan=plan)


def _looks_like_nutrition_question_without_plan(
    understanding: NutritionMessageUnderstanding,
    message: str,
) -> bool:
    if understanding.intent in INTENTS_THAT_NEED_PLAN_CONTEXT:
        return True
    normalized = normalize_text(message)
    keywords = (
        "que como",
        "que comer",
        "que puedo comer",
        "que ceno",
        "que desayuno",
        "que meriendo",
        "plan nutricional",
        "mi plan",
        "comidas del dia",
        "lista de la compra",
    )
    return any(keyword in normalized for keyword in keywords)


def _effective_intent(
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
) -> str:
    if normalized_message is not None and normalized_message.intent != "unknown":
        return normalized_message.intent
    return understanding.intent


def _message_wants_day_overview(
    *,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
) -> bool:
    if _effective_intent(understanding, normalized_message) == "evaluate_day":
        return True
    return understanding.asks_for_full_day or (
        normalized_message is not None and normalized_message.wants_day_overview
    )


def _should_defer_clarification_to_llm(
    *,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
    resolution: MealResolution,
) -> bool:
    if resolution.status not in {"missing_situation", "missing_moment"}:
        return False
    effective_intent = _effective_intent(understanding, normalized_message)
    if effective_intent in {"recommend_meal", "weekly_planning"}:
        return False
    return True


def _unresolved_context_setup(
    *,
    plan: NutritionPlan,
    prompt_profile: BotProfile,
    resolution: MealResolution,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
    daily_log_context: NutritionDailyLogContext,
) -> NutritionPromptSetup:
    return NutritionPromptSetup(
        prompt_profile=prompt_profile,
        runtime_instructions=(
            _runtime_context_instruction(
                context=_attach_daily_log(
                    _unresolved_context_payload(
                        plan=plan,
                        resolution=resolution,
                    ),
                    daily_log=daily_log_context.log,
                ),
                understanding=understanding,
                normalized_message=normalized_message,
            ),
        ),
        include_memory=True,
        understanding=understanding,
        normalized_message=normalized_message,
        post_success_actions=daily_log_context.post_success_actions,
    )


def _weekly_planning_setup(
    *,
    plan: NutritionPlan,
    prompt_profile: BotProfile,
    message: str,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None = None,
    daily_log_context: NutritionDailyLogContext | None = None,
) -> NutritionPromptSetup:
    daily_log_context = daily_log_context or NutritionDailyLogContext()
    normalized_situations = (
        normalized_message.situation_keys if normalized_message is not None else ()
    )
    situation_matches = detect_situations(plan, message)
    if not situation_matches and not normalized_situations:
        options = _join_options(_available_situation_labels(plan.situations))
        return NutritionPromptSetup(
            prompt_profile=prompt_profile,
            direct_answer=(
                "Puedo montarlo, pero dime que tipo de dia tiene cada dia. "
                f"Opciones del plan: {options}."
            ),
            understanding=understanding,
            normalized_message=normalized_message,
            post_success_actions=daily_log_context.post_success_actions,
        )

    context = _planning_context_payload(
        plan=plan,
        situation_matches=situation_matches,
        situation_keys=normalized_situations,
        mode="weekly_planning",
    )
    return NutritionPromptSetup(
        prompt_profile=prompt_profile,
        runtime_instructions=(
            _runtime_context_instruction(
                context=_attach_daily_log(context, daily_log=daily_log_context.log),
                understanding=understanding,
                normalized_message=normalized_message,
            ),
        ),
        include_memory=True,
        understanding=understanding,
        normalized_message=normalized_message,
        post_success_actions=daily_log_context.post_success_actions,
    )


def _shopping_list_setup(
    *,
    plan: NutritionPlan,
    prompt_profile: BotProfile,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None = None,
    daily_log_context: NutritionDailyLogContext | None = None,
) -> NutritionPromptSetup:
    daily_log_context = daily_log_context or NutritionDailyLogContext()
    context = _planning_context_payload(
        plan=plan,
        situation_matches=(),
        mode="shopping_list",
    )
    return NutritionPromptSetup(
        prompt_profile=prompt_profile,
        runtime_instructions=(
            _runtime_context_instruction(
                context=_attach_daily_log(context, daily_log=daily_log_context.log),
                understanding=understanding,
                normalized_message=normalized_message,
            ),
        ),
        include_memory=True,
        understanding=understanding,
        normalized_message=normalized_message,
        post_success_actions=daily_log_context.post_success_actions,
    )


def _resolve_nutrition_context_with_follow_up(
    plan: NutritionPlan,
    message: str,
    recent_conversation_messages: Sequence[ChatMessage],
    *,
    compacted_user_memory: str | None = None,
) -> MealResolution:
    resolution = resolve_meal_context(plan, message)
    if resolution.is_resolved or resolution.status not in {
        "missing_situation",
        "missing_moment",
    }:
        return resolution

    recent_messages = [
        item["content"].strip()
        for item in recent_conversation_messages
        if item["content"].strip()
    ]
    context_candidates: list[str] = []
    if compacted_user_memory and compacted_user_memory.strip():
        context_candidates.append(compacted_user_memory.strip())
    context_candidates.extend(recent_messages[-8:])
    for previous_message in reversed(context_candidates):
        combined_resolution = resolve_meal_context(
            plan,
            f"{previous_message}\n{message}",
        )
        if combined_resolution.is_resolved:
            return combined_resolution
    return resolution


def _load_daily_log_context(
    *,
    state: Mapping[str, Any],
    plan: NutritionPlan,
    normalized_message: NormalizedNutritionMessage | None,
) -> NutritionDailyLogContext:
    user_id = state.get("internal_user_id")
    if not isinstance(user_id, int):
        return NutritionDailyLogContext()

    log_date = state.get("current_date")
    if not isinstance(log_date, date):
        log_date = nutrition_daily_state.today_local()

    try:
        bot_profile_id = cast(BotProfile, state["profile"]).bot_profile_id
        current_log = nutrition_daily_state.load_daily_log(
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            log_date=log_date,
        )
        update = nutrition_daily_state.build_daily_update(
            plan=plan,
            message=str(state["message"]),
            understanding=cast(NutritionMessageUnderstanding, state["understanding"]),
            normalized_message=normalized_message,
        )
        preview_log = nutrition_daily_state.preview_daily_update(
            log=current_log,
            user_id=user_id,
            bot_profile_id=bot_profile_id,
            log_date=log_date,
            plan=plan,
            update=update,
        )
        actions: tuple[Callable[[], None], ...] = (
            (
                NutritionDailyLogCommit(
                    user_id=user_id,
                    bot_profile_id=bot_profile_id,
                    log_date=log_date,
                    plan=plan,
                    update=update,
                ),
            )
            if update.has_changes
            else ()
        )
        return NutritionDailyLogContext(
            log=preview_log,
            post_success_actions=actions,
        )
    except Exception:
        logger.warning(
            "nutrition_daily_log_context_failed user_id=%s profile=%s",
            user_id,
            cast(BotProfile, state["profile"]).bot_profile_id,
            exc_info=True,
        )
        return NutritionDailyLogContext()


def _route_message_with_daily_log(
    *,
    plan: NutritionPlan,
    message: str,
    route_message: str,
    daily_log: nutrition_daily_state.NutritionDailyLog | None,
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
) -> str:
    if daily_log is None or not daily_log.situation_key:
        return route_message

    day_situation = daily_log.situation_key
    if nutrition_daily_state.message_changes_day_type(message):
        target_moment = _target_moment_for_routing(message, normalized_message)
        if target_moment:
            return f"{day_situation} {target_moment}"
        if _message_wants_day_overview(
            understanding=understanding,
            normalized_message=normalized_message,
        ):
            return f"{day_situation} todo el dia"
        return f"{day_situation} {route_message}".strip()

    if not detect_situations(plan, route_message):
        return f"{route_message} {day_situation}".strip()
    return route_message


def _target_moment_for_routing(
    message: str,
    normalized_message: NormalizedNutritionMessage | None,
) -> str | None:
    if normalized_message is not None and normalized_message.target_moment_key:
        return normalized_message.target_moment_key
    return _target_moment_from_message(normalize_text(message))


def _routing_message_for_context(
    message: str,
    understanding: NutritionMessageUnderstanding,
    *,
    normalized_message: NormalizedNutritionMessage | None = None,
) -> str:
    if normalized_message is not None and normalized_message.route_message:
        return normalized_message.route_message

    normalized = normalize_text(message)
    target_moment = _target_moment_from_message(normalized)

    route_message = normalized
    if "skipped_meal" in understanding.deviations:
        route_message = re.sub(
            r"\b(?:me he saltado|saltado|no he hecho)\s+"
            r"(?:la|el)?\s*"
            r"(?:media manana|desayuno|almuerzo|comida|merienda|cena)\b",
            " ",
            route_message,
        )

    if target_moment is not None:
        route_message = _remove_logged_meal_context(
            route_message,
            target_moment=target_moment,
        )

    if _message_wants_day_overview(
        understanding=understanding,
        normalized_message=normalized_message,
    ):
        route_message = f"{route_message} todo el dia"

    return re.sub(r"\s+", " ", route_message).strip()


def _target_moment_from_message(normalized_message: str) -> str | None:
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "cena",
            (
                r"\bque\s+(?:puedo\s+)?(?:tomar|comer|hacer|preparar)\s+"
                r"para\s+(?:la\s+)?cena\b",
                r"\bque\s+ceno\b",
                r"\bpara\s+cenar\b",
            ),
        ),
        (
            "almuerzo",
            (
                r"\bque\s+(?:puedo\s+)?(?:tomar|comer|hacer|preparar)\s+"
                r"para\s+(?:el\s+)?(?:almuerzo|mediodia|medio dia|comida)\b",
                r"\bque\s+como\s+(?:al\s+)?(?:mediodia|medio dia)\b",
            ),
        ),
        (
            "desayuno",
            (
                r"\bque\s+(?:puedo\s+)?(?:tomar|comer|hacer|preparar)\s+"
                r"para\s+(?:el\s+)?desayuno\b",
                r"\bque\s+desayuno\b",
            ),
        ),
        (
            "merienda",
            (
                r"\bque\s+(?:puedo\s+)?(?:tomar|comer|hacer|preparar)\s+"
                r"para\s+(?:la\s+)?merienda\b",
                r"\bque\s+meriendo\b",
            ),
        ),
    )
    for moment_key, moment_patterns in patterns:
        if any(
            re.search(pattern, normalized_message) is not None
            for pattern in moment_patterns
        ):
            return moment_key
    return None


def _remove_logged_meal_context(
    route_message: str,
    *,
    target_moment: str,
) -> str:
    moment_terms_by_key = {
        "desayuno": ("desayuno",),
        "media_manana": ("media manana",),
        "almuerzo": ("almuerzo", "comida", "mediodia", "medio dia"),
        "merienda": ("merienda",),
        "cena": ("cena",),
    }
    context_terms = [
        re.escape(term)
        for moment_key, terms in moment_terms_by_key.items()
        if moment_key != target_moment
        for term in terms
    ]
    if not context_terms:
        return route_message

    route_message = re.sub(
        rf"\ben\s+(?:el|la)?\s*(?:{'|'.join(context_terms)})\s+.*?"
        r"(?=\b(?:que|para)\b|$)",
        " ",
        route_message,
    )
    return re.sub(
        rf"\ben\s+(?:el|la)?\s*(?:{'|'.join(context_terms)})\b",
        " ",
        route_message,
    )


def _looks_like_nutrition_routing_query(message: str, *, plan: NutritionPlan) -> bool:
    normalized = normalize_text(message)
    plan_terms = [
        normalize_text(term)
        for situation_key, situation in plan.situations.items()
        for term in (situation_key, *_string_aliases(situation.get("aliases")))
    ]
    plan_terms.extend(
        normalize_text(term)
        for moment_key, moment in plan.moments.items()
        for term in (moment_key, *_string_aliases(moment.get("aliases")))
    )
    if any(term and term in normalized for term in plan_terms):
        return True

    keywords = (
        "que como",
        "que comer",
        "que puedo comer",
        "todo lo que puedo comer",
        "todo el dia",
        "dia completo",
        "plan del dia",
        "comidas del dia",
        "desayuno",
        "almuerzo",
        "comida",
        "mediodia",
        "merienda",
        "cena",
        "cenar",
        "ceno",
    )
    return any(keyword in normalized for keyword in keywords)


def _nutrition_clarification(resolution: MealResolution) -> str:
    if resolution.status == "missing_situation":
        options = _join_options(resolution.available_situations)
        return f"Para ajustarlo al plan, dime que tipo de dia es: {options}."
    if resolution.status == "missing_moment":
        options = _join_options(resolution.available_moments)
        return f"Te lo ajusto, pero dime el momento: {options}."
    if resolution.status == "ambiguous_situation":
        options = _join_options(match.label for match in resolution.situation_matches)
        return f"Te he entendido varios contextos posibles: {options}. Cual usamos?"
    if resolution.status == "ambiguous_moment":
        options = _join_options(match.key for match in resolution.moment_matches)
        return f"Te he entendido varios momentos posibles: {options}. Cual usamos?"
    return "No tengo configurado que bloque usar para ese contexto del plan."


def _join_options(options: Iterable[str]) -> str:
    cleaned = [option for option in options if option]
    if not cleaned:
        return "desayuno, almuerzo, merienda o cena"
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + " o " + cleaned[-1]


def _optional_state_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nutrition_context_payload(resolution: MealResolution) -> dict[str, Any]:
    if resolution.status == "resolved_day":
        return {
            "mode": "full_day",
            "situation_key": resolution.situation_key,
            "supplementation": list(resolution.supplementation),
            "meal_blocks": [
                {
                    "moment_key": day_meal.moment_key,
                    "moment_label": day_meal.moment_label,
                    "meal_block_key": day_meal.meal_block_key,
                    "meal_block": day_meal.meal_block,
                }
                for day_meal in resolution.day_meal_blocks
            ],
        }
    return {
        "mode": "single_meal",
        "situation_key": resolution.situation_key,
        "moment_key": resolution.moment_key,
        "meal_block_key": resolution.meal_block_key,
        "supplementation": list(resolution.supplementation),
        "meal_block": resolution.meal_block,
    }


def _unresolved_context_payload(
    *,
    plan: NutritionPlan,
    resolution: MealResolution,
) -> dict[str, Any]:
    selected_situations = (
        tuple(match.key for match in resolution.situation_matches)
        if resolution.situation_matches
        else tuple(plan.situations.keys())
    )
    meal_keys = _meal_keys_for_situations(plan, selected_situations)
    return {
        "mode": "unresolved_with_memory_fallback",
        "resolution_status": resolution.status,
        "available_situations": list(resolution.available_situations),
        "available_moments": list(resolution.available_moments),
        "candidate_situations": {
            situation_key: plan.situations[situation_key]
            for situation_key in selected_situations
            if situation_key in plan.situations
        },
        "candidate_meal_blocks": {
            meal_key: plan.meals[meal_key]
            for meal_key in meal_keys
            if meal_key in plan.meals
        },
    }


def _planning_context_payload(
    *,
    plan: NutritionPlan,
    situation_matches: Sequence[SituationMatch],
    situation_keys: Sequence[str] = (),
    mode: str,
) -> dict[str, Any]:
    selected_situations = (
        tuple(situation_keys)
        if situation_keys
        else (
            tuple(match.key for match in situation_matches)
            if situation_matches
            else tuple(plan.situations.keys())
        )
    )
    meal_keys = _meal_keys_for_situations(plan, selected_situations)
    return {
        "mode": mode,
        "plan_id": plan.plan_id,
        "situations": {
            situation_key: plan.situations[situation_key]
            for situation_key in selected_situations
            if situation_key in plan.situations
        },
        "meal_blocks": {
            meal_key: plan.meals[meal_key]
            for meal_key in meal_keys
            if meal_key in plan.meals
        },
    }


def _attach_daily_log(
    context: Mapping[str, Any],
    *,
    daily_log: nutrition_daily_state.NutritionDailyLog | None,
) -> dict[str, Any]:
    payload = dict(context)
    daily_log_payload = nutrition_daily_state.to_prompt_payload(daily_log)
    if daily_log_payload is not None:
        payload["daily_log"] = daily_log_payload
    return payload


def _meal_keys_for_situations(
    plan: NutritionPlan,
    situation_keys: Sequence[str],
) -> tuple[str, ...]:
    meal_keys: list[str] = []
    seen: set[str] = set()
    for situation_key in situation_keys:
        situation = plan.situations.get(situation_key, {})
        moments = situation.get("momentos", {})
        if not isinstance(moments, dict):
            continue
        for meal_key in moments.values():
            if isinstance(meal_key, str) and meal_key not in seen:
                seen.add(meal_key)
                meal_keys.append(meal_key)
    return tuple(meal_keys)


def _available_situation_labels(
    situations: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    labels: list[str] = []
    for situation_key, situation in situations.items():
        label = situation.get("label")
        labels.append(
            label.strip()
            if isinstance(label, str) and label.strip()
            else situation_key
        )
    return tuple(labels)


def _string_aliases(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _runtime_context_instruction(
    *,
    context: Mapping[str, Any],
    understanding: NutritionMessageUnderstanding,
    normalized_message: NormalizedNutritionMessage | None,
) -> str:
    payload = {
        "message_understanding": understanding.to_prompt_payload(),
        "normalized_message": (
            normalized_message.to_prompt_payload()
            if normalized_message is not None
            else None
        ),
        "nutrition_context": context,
    }
    return (
        "Resolved nutrition plan context. Nutrition orchestration context "
        "resolved before the LLM call. Use this as the active nutrition plan "
        "context for the current answer.\n"
        "- Use only foods, quantities, options, and meal blocks present here.\n"
        "- Do not invent extra foods, recipes, calories, or macros.\n"
        "- If the user asks for macros, use only macro values present in the "
        "provided meal blocks; if a macro is missing, say that exact value is "
        "not available.\n"
        "- If the user asks for a weekly plan, produce a concrete plan from the "
        "provided situations and meal blocks.\n"
        "- If context mode is unresolved_with_memory_fallback, use memory and "
        "conversation context to infer the situation or meal moment when it is "
        "clear. If it is still unclear, ask one natural, specific question and "
        "do not repeat a clarification that the user already answered.\n"
        "- If the user reports a deviation, keep the next meal prudent without "
        "punishment or aggressive compensation.\n"
        "- Telegram format: maximo 5 lineas for single-meal answers; weekly "
        "plans may be longer but still compact.\n"
        "- No raw JSON unless the user explicitly asks.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
