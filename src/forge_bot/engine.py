import asyncio
import logging
from typing import Any

import ollama

from .bot_profile import BotProfile, load_active_bot_profile
from .config import get_settings
from .prompting import assemble_prompt_messages

logger = logging.getLogger(__name__)

AI_TIMEOUT_FALLBACK = (
    "The AI response is taking longer than expected. Please try again in a moment."
)
AI_ERROR_FALLBACK = (
    "The AI service is temporarily unavailable. Please try again in a moment."
)


async def answer(
    user: str,
    msg: str,
    profile: BotProfile | None = None,
) -> str:
    """Send a profile-aware prompt to Ollama and return the model response.

    Args:
        user: Telegram user's display name.
        msg: Current Telegram text message.
        profile: Optional profile override used by tests or future flows.

    Returns:
        The assistant response text produced by Ollama.
    """
    settings = get_settings()
    active_profile = _resolve_profile(profile)
    client = _build_client(settings.ollama_host, settings.ai_timeout_seconds)
    messages = assemble_prompt_messages(
        active_profile,
        current_user_message=msg,
        user_display_name=user,
        compacted_user_memory=None,
        recent_conversation_messages=[],
        runtime_safety_instructions=[],
    )

    try:
        response = await _chat_with_timeout(
            client,
            model=active_profile.llm_model,
            messages=messages,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    except TimeoutError:
        logger.warning(
            "ollama_chat_timeout model=%s timeout_seconds=%s message_chars=%s",
            active_profile.llm_model,
            settings.ai_timeout_seconds,
            len(msg),
        )
        return AI_TIMEOUT_FALLBACK
    except Exception:
        logger.exception(
            "ollama_chat_failed model=%s message_chars=%s",
            active_profile.llm_model,
            len(msg),
        )
        return AI_ERROR_FALLBACK

    content = response.message.content or ""
    return _trim_response(
        content,
        model=active_profile.llm_model,
        max_chars=settings.ai_max_response_chars,
    )


def _resolve_profile(profile: BotProfile | None) -> BotProfile:
    if profile is not None:
        return profile

    settings = get_settings()
    return load_active_bot_profile(settings.bot_profile, settings.bot_profiles_dir)


def _build_client(host: str, timeout_seconds: int) -> ollama.Client:
    return ollama.Client(host=host, timeout=timeout_seconds)


async def _chat_with_timeout(
    client: ollama.Client,
    *,
    model: str,
    messages: Any,
    timeout_seconds: int,
) -> Any:
    return await asyncio.wait_for(
        asyncio.to_thread(
            client.chat,
            model=model,
            messages=messages,
        ),
        timeout=timeout_seconds,
    )


def _trim_response(content: str, *, model: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content

    logger.info(
        "ollama_response_truncated model=%s original_chars=%s max_chars=%s",
        model,
        len(content),
        max_chars,
    )
    return content[:max_chars].rstrip()
    return content
