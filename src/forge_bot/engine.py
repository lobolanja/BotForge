import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import ollama

from .bot_profile import BotProfile, load_active_bot_profile
from .config import get_settings
from .prompting import ChatMessage, assemble_prompt_messages

logger = logging.getLogger(__name__)

AI_TIMEOUT_FALLBACK = (
    "The AI response is taking longer than expected. Please try again in a moment."
)
AI_ERROR_FALLBACK = (
    "The AI service is temporarily unavailable. Please try again in a moment."
)
FALLBACK_DISABLED_VALUES = {"", "none", "disabled", "off"}
NVIDIA_ALLOWED_URL_SCHEMES = {"https"}
AI_TIMEOUT_ERRORS = (TimeoutError, asyncio.TimeoutError)


class ProviderConfigurationError(RuntimeError):
    """Raised when a selected LLM provider is not configured for use."""


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, host: str, timeout_seconds: int) -> None:
        self._client = _build_client(host, timeout_seconds)
        self._timeout_seconds = timeout_seconds

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        response = await _chat_with_timeout(
            self._client,
            model=model,
            messages=messages,
            timeout_seconds=self._timeout_seconds,
        )
        return response.message.content or ""


class NvidiaNimProvider:
    name = "nvidia"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int,
    ) -> None:
        if not api_key:
            raise ProviderConfigurationError(
                "NVIDIA_API_KEY is required to use the NVIDIA NIM fallback provider."
            )
        if not base_url:
            raise ProviderConfigurationError(
                "NVIDIA_BASE_URL is required to use the NVIDIA NIM fallback provider."
            )
        if not model:
            raise ProviderConfigurationError(
                "NVIDIA_MODEL is required to use the NVIDIA NIM fallback provider."
            )

        self._api_key = api_key
        self._base_url = _validated_https_base_url(base_url)
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        del model
        return await asyncio.wait_for(
            asyncio.to_thread(self._chat, messages),
            timeout=self._timeout_seconds,
        )

    def _chat(self, messages: list[ChatMessage]) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "messages": messages,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            # The base URL is normalized by _validated_https_base_url().
            with urllib.request.urlopen(  # nosec B310
                request,
                timeout=self._timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"NVIDIA NIM request failed with HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("NVIDIA NIM request failed.") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "NVIDIA NIM response did not include message content."
            ) from exc
        return str(content or "")


async def answer(
    user: str,
    msg: str,
    profile: BotProfile | None = None,
    request_id: str | None = None,
    queue_wait_seconds: float = 0.0,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: list[ChatMessage] | None = None,
) -> str:
    """Send a profile-aware prompt to the configured LLM provider.

    Args:
        user: Telegram user's display name.
        msg: Current Telegram text message.
        profile: Optional profile override used by tests or future flows.
        request_id: Optional lifecycle request id for provider logs.
        queue_wait_seconds: Seconds between message receipt and processing start.
        compacted_user_memory: Durable summary for this user/profile.
        recent_conversation_messages: Recent raw messages for this user/profile.

    Returns:
        The assistant response text produced by Ollama.
    """
    settings = get_settings()
    active_profile = _resolve_profile(profile)
    messages = assemble_prompt_messages(
        active_profile,
        current_user_message=msg,
        user_display_name=user,
        compacted_user_memory=compacted_user_memory,
        recent_conversation_messages=recent_conversation_messages or [],
        runtime_safety_instructions=[],
    )
    request_id_text = request_id or "unknown"
    fallback_reason = _fallback_reason(
        queue_wait_seconds=queue_wait_seconds,
        threshold_seconds=settings.llm_fallback_queue_wait_seconds,
    )
    provider: OllamaProvider | NvidiaNimProvider | None = None

    try:
        provider = _select_provider(
            profile_provider=active_profile.llm_provider,
            queue_wait_seconds=queue_wait_seconds,
        )
        started_at = time.monotonic()
        content = await provider.chat(
            model=active_profile.llm_model,
            messages=messages,
        )
        duration_seconds = time.monotonic() - started_at
        logger.info(
            "llm_provider_used request_id=%s provider=%s fallback_reason=%s "
            "duration_seconds=%.6f message_chars=%s",
            request_id_text,
            provider.name,
            fallback_reason,
            duration_seconds,
            len(msg),
        )
    except AI_TIMEOUT_ERRORS:
        logger.warning(
            "llm_chat_timeout request_id=%s provider=%s model=%s "
            "timeout_seconds=%s message_chars=%s",
            request_id_text,
            _provider_name(provider),
            _logged_model(active_profile.llm_model, _provider_name(provider)),
            settings.ai_timeout_seconds,
            len(msg),
        )
        return AI_TIMEOUT_FALLBACK
    except ProviderConfigurationError:
        logger.exception(
            "llm_provider_configuration_failed request_id=%s provider_reason=%s "
            "message_chars=%s",
            request_id_text,
            fallback_reason,
            len(msg),
        )
        return AI_ERROR_FALLBACK
    except Exception:
        provider_name = _provider_name(provider)
        if provider_name != _fallback_provider_name():
            fallback_answer = await _answer_with_fallback(
                messages=messages,
                model=active_profile.llm_model,
                max_chars=settings.ai_max_response_chars,
                message_chars=len(msg),
                request_id=request_id_text,
                reason="primary_error",
            )
            if fallback_answer is not None:
                return fallback_answer

        logger.exception(
            "llm_chat_failed request_id=%s provider=%s model=%s message_chars=%s",
            request_id_text,
            provider_name,
            _logged_model(active_profile.llm_model, provider_name),
            len(msg),
        )
        return AI_ERROR_FALLBACK

    provider_name = _provider_name(provider)
    return _trim_response(
        content,
        provider=provider_name,
        model=_logged_model(active_profile.llm_model, provider_name),
        max_chars=settings.ai_max_response_chars,
    )


async def summarize_memory(
    *,
    profile: BotProfile,
    existing_summary: str | None,
    source_messages: Sequence[ChatMessage],
    max_chars: int,
    request_id: str | None = None,
) -> str | None:
    """Compact older chat messages into durable, user-scoped memory."""
    if not source_messages:
        return existing_summary

    request_id_text = request_id or "unknown"
    provider: OllamaProvider | NvidiaNimProvider | None = None
    messages = _memory_summary_prompt(
        existing_summary=existing_summary,
        source_messages=source_messages,
        max_chars=max_chars,
    )
    try:
        provider = _select_provider(
            profile_provider=profile.llm_provider,
            queue_wait_seconds=0.0,
        )
        content = await provider.chat(model=profile.llm_model, messages=messages)
    except Exception:
        provider_name = _provider_name(provider)
        logger.warning(
            "memory_compaction_primary_failed request_id=%s provider=%s "
            "source_messages=%s",
            request_id_text,
            provider_name,
            len(source_messages),
            exc_info=True,
        )
        fallback_summary = await _answer_with_fallback(
            messages=messages,
            model=profile.llm_model,
            max_chars=max_chars,
            message_chars=sum(len(message["content"]) for message in source_messages),
            request_id=request_id_text,
            reason="memory_compaction_primary_error",
        )
        if fallback_summary is None:
            logger.error(
                "memory_compaction_failed request_id=%s provider=%s source_messages=%s",
                request_id_text,
                provider_name,
                len(source_messages),
            )
        return fallback_summary

    return _trim_response(
        content,
        provider=_provider_name(provider),
        model=_logged_model(profile.llm_model, _provider_name(provider)),
        max_chars=max_chars,
    )


def _resolve_profile(profile: BotProfile | None) -> BotProfile:
    if profile is not None:
        return profile

    return load_default_profile()


def load_default_profile() -> BotProfile:
    """Load the configured bot profile for a runtime AI request."""
    settings = get_settings()
    return load_active_bot_profile(settings.bot_profile, settings.bot_profiles_dir)


def _memory_summary_prompt(
    *,
    existing_summary: str | None,
    source_messages: Sequence[ChatMessage],
    max_chars: int,
) -> list[ChatMessage]:
    transcript = "\n".join(
        f"{message['role']}: {message['content']}" for message in source_messages
    )
    existing = existing_summary.strip() if existing_summary else "None yet."
    return [
        {
            "role": "system",
            "content": (
                "Update the compacted memory for one BotForge user. Keep only "
                "durable context that may help future replies: dates, tastes, "
                "preferences, priorities, goals, constraints, and important "
                "facts. Do not include secrets, credentials, tokens, or private "
                "identifiers. Do not invent facts. Keep the result under "
                f"{max_chars} characters."
            ),
        },
        {
            "role": "user",
            "content": (
                "Existing memory:\n"
                f"{existing}\n\n"
                "New messages to compact:\n"
                f"{transcript}\n\n"
                "Return only the updated compacted memory."
            ),
        },
    ]


def _build_client(host: str, timeout_seconds: int) -> ollama.Client:
    return ollama.Client(host=host, timeout=timeout_seconds)


def _validated_https_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme.lower() not in NVIDIA_ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise ProviderConfigurationError(
            "NVIDIA_BASE_URL must be an HTTPS URL with a host."
        )
    if parsed.username or parsed.password:
        raise ProviderConfigurationError(
            "NVIDIA_BASE_URL must not include credentials."
        )
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError(
            "NVIDIA_BASE_URL must not include a query string or fragment."
        )
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _select_provider(
    *,
    profile_provider: str,
    queue_wait_seconds: float,
) -> OllamaProvider | NvidiaNimProvider:
    settings = get_settings()
    primary_provider = settings.llm_primary_provider or profile_provider
    fallback_provider = _fallback_provider_name()
    if (
        fallback_provider
        and queue_wait_seconds > settings.llm_fallback_queue_wait_seconds
    ):
        return _build_provider(fallback_provider)
    return _build_provider(primary_provider)


def _fallback_provider_name() -> str:
    configured = get_settings().llm_fallback_provider.lower()
    return "" if configured in FALLBACK_DISABLED_VALUES else configured


def _fallback_reason(
    *,
    queue_wait_seconds: float,
    threshold_seconds: int,
) -> str:
    if queue_wait_seconds > threshold_seconds and _fallback_provider_name():
        return "queue_wait_exceeded"
    return "none"


def _build_provider(name: str) -> OllamaProvider | NvidiaNimProvider:
    settings = get_settings()
    normalized = name.lower()
    if normalized == "ollama":
        return OllamaProvider(
            host=settings.ollama_host,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    if normalized == "nvidia":
        return NvidiaNimProvider(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            model=settings.nvidia_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )
    raise ProviderConfigurationError(f"Unsupported LLM provider: {name}.")


async def _answer_with_fallback(
    *,
    messages: list[ChatMessage],
    model: str,
    max_chars: int,
    message_chars: int,
    request_id: str,
    reason: str,
) -> str | None:
    fallback_provider_name = _fallback_provider_name()
    if not fallback_provider_name:
        return None

    try:
        provider = _build_provider(fallback_provider_name)
    except ProviderConfigurationError:
        logger.exception(
            "llm_fallback_unavailable request_id=%s provider=%s reason=%s "
            "message_chars=%s",
            request_id,
            fallback_provider_name,
            reason,
            message_chars,
        )
        return None

    try:
        started_at = time.monotonic()
        content = await provider.chat(model=model, messages=messages)
        duration_seconds = time.monotonic() - started_at
    except AI_TIMEOUT_ERRORS:
        logger.warning(
            "llm_chat_timeout request_id=%s provider=%s model=%s "
            "timeout_seconds=%s message_chars=%s",
            request_id,
            provider.name,
            _logged_model(model, provider.name),
            get_settings().ai_timeout_seconds,
            message_chars,
        )
        return AI_TIMEOUT_FALLBACK
    except Exception:
        logger.exception(
            "llm_chat_failed request_id=%s provider=%s model=%s "
            "fallback_reason=%s message_chars=%s",
            request_id,
            provider.name,
            _logged_model(model, provider.name),
            reason,
            message_chars,
        )
        return None

    logger.info(
        "llm_provider_used request_id=%s provider=%s fallback_reason=%s "
        "duration_seconds=%.6f message_chars=%s",
        request_id,
        provider.name,
        reason,
        duration_seconds,
        message_chars,
    )
    return _trim_response(
        content,
        provider=provider.name,
        model=_logged_model(model, provider.name),
        max_chars=max_chars,
    )


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


def _trim_response(
    content: str,
    *,
    provider: str,
    model: str,
    max_chars: int,
) -> str:
    if len(content) <= max_chars:
        return content

    logger.info(
        "llm_response_truncated provider=%s model=%s original_chars=%s max_chars=%s",
        provider,
        model,
        len(content),
        max_chars,
    )
    return content[:max_chars].rstrip()


def _logged_model(profile_model: str, provider: str) -> str:
    if provider == "nvidia":
        return get_settings().nvidia_model
    return profile_model


def _provider_name(provider: OllamaProvider | NvidiaNimProvider | None) -> str:
    if provider is None:
        return "unknown"
    return provider.name
