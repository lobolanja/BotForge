import asyncio
import html
import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import certifi
import ollama

from .bot_profile import BotProfile, load_active_bot_profile
from .config import get_settings
from .nutrition.orchestrator import prepare_nutrition_prompt_async
from .prompting import ChatMessage, assemble_prompt_messages

logger = logging.getLogger(__name__)

AI_TIMEOUT_FALLBACK = (
    "No he podido cerrar la respuesta tras varios minutos. No la reenvies de "
    "momento; prueba con una version mas corta si necesitas resolverlo ya."
)
AI_ERROR_FALLBACK = (
    "El servicio de IA no esta disponible ahora mismo. Prueba de nuevo en un momento."
)
FALLBACK_DISABLED_VALUES = {"", "none", "disabled", "off"}
PROFILE_PRIMARY_PROVIDER_VALUES = {"", "profile"}
NVIDIA_ALLOWED_URL_SCHEMES = {"https"}
AI_TIMEOUT_ERRORS = (TimeoutError, asyncio.TimeoutError)


class ProviderConfigurationError(RuntimeError):
    """Raised when a selected LLM provider is not configured for use."""


class GeneratedAnswer(str):
    """String response with optional post-success side effects."""

    post_success_actions: tuple[object, ...]

    def __new__(
        cls,
        value: str,
        *,
        post_success_actions: Sequence[object] = (),
    ) -> "GeneratedAnswer":
        instance = str.__new__(cls, value)
        instance.post_success_actions = tuple(post_success_actions)
        return instance


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
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def chat(self, *, model: str, messages: list[ChatMessage]) -> str:
        request_model = _nvidia_model_for_request(model, self._model)
        return await asyncio.wait_for(
            asyncio.to_thread(self._chat, messages, request_model),
            timeout=self._timeout_seconds,
        )

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
    ) -> AsyncIterator[str]:
        request_model = _nvidia_model_for_request(model, self._model)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

        def worker() -> None:
            try:
                for chunk in self._stream_chat(messages, request_model):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                item = await asyncio.wait_for(
                    queue.get(),
                    timeout=self._timeout_seconds,
                )
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            await worker_task

    def _chat(self, messages: list[ChatMessage], model: str) -> str:
        body = json.dumps(
            {
                "model": model,
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
                context=self._ssl_context,
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

    def _stream_chat(self, messages: list[ChatMessage], model: str) -> Iterator[str]:
        body = json.dumps(
            {
                "model": model,
                "messages": messages,
                "stream": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

        try:
            # The base URL is normalized by _validated_https_base_url().
            with urllib.request.urlopen(  # nosec B310
                request,
                timeout=self._timeout_seconds,
                context=self._ssl_context,
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = _nvidia_stream_delta(data)
                    if chunk:
                        yield chunk
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"NVIDIA NIM streaming request failed with HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("NVIDIA NIM streaming request failed.") from exc


async def answer(
    user: str,
    msg: str,
    profile: BotProfile | None = None,
    request_id: str | None = None,
    queue_wait_seconds: float = 0.0,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: list[ChatMessage] | None = None,
    internal_user_id: int | None = None,
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
        internal_user_id: Internal database user id for profile-specific state.

    Returns:
        The assistant response text produced by Ollama.
    """
    settings = get_settings()
    active_profile = _resolve_profile(profile)
    normalizer = _build_nutrition_normalizer(active_profile)
    now = _current_datetime(settings.bot_timezone)
    nutrition_prompt = await prepare_nutrition_prompt_async(
        active_profile,
        msg,
        compacted_user_memory=compacted_user_memory,
        recent_conversation_messages=recent_conversation_messages or [],
        normalizer_client=normalizer[0] if normalizer is not None else None,
        normalizer_model=normalizer[1] if normalizer is not None else None,
        internal_user_id=internal_user_id,
        current_date=now.date(),
    )
    if nutrition_prompt.direct_answer is not None:
        return GeneratedAnswer(
            nutrition_prompt.direct_answer,
            post_success_actions=nutrition_prompt.post_success_actions,
        )

    messages = assemble_prompt_messages(
        nutrition_prompt.prompt_profile,
        current_user_message=msg,
        user_display_name=user,
        compacted_user_memory=(
            compacted_user_memory if nutrition_prompt.include_memory else None
        ),
        recent_conversation_messages=(
            recent_conversation_messages or []
            if nutrition_prompt.include_memory
            else []
        ),
        runtime_safety_instructions=nutrition_prompt.runtime_instructions,
        now=now,
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
                return GeneratedAnswer(fallback_answer)

        logger.exception(
            "llm_chat_failed request_id=%s provider=%s model=%s message_chars=%s",
            request_id_text,
            provider_name,
            _logged_model(active_profile.llm_model, provider_name),
            len(msg),
        )
        return AI_ERROR_FALLBACK

    provider_name = _provider_name(provider)
    return GeneratedAnswer(
        _trim_response(
            content,
            provider=provider_name,
            model=_logged_model(active_profile.llm_model, provider_name),
            max_chars=settings.ai_max_response_chars,
        ),
        post_success_actions=nutrition_prompt.post_success_actions,
    )


async def answer_stream(
    user: str,
    msg: str,
    *,
    on_partial: Callable[[str], Awaitable[None]],
    profile: BotProfile | None = None,
    request_id: str | None = None,
    queue_wait_seconds: float = 0.0,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: list[ChatMessage] | None = None,
    internal_user_id: int | None = None,
) -> str:
    """Generate an answer and emit partial text when the provider supports it."""
    settings = get_settings()
    active_profile = _resolve_profile(profile)
    normalizer = _build_nutrition_normalizer(active_profile)
    now = _current_datetime(settings.bot_timezone)
    nutrition_prompt = await prepare_nutrition_prompt_async(
        active_profile,
        msg,
        compacted_user_memory=compacted_user_memory,
        recent_conversation_messages=recent_conversation_messages or [],
        normalizer_client=normalizer[0] if normalizer is not None else None,
        normalizer_model=normalizer[1] if normalizer is not None else None,
        internal_user_id=internal_user_id,
        current_date=now.date(),
    )
    if nutrition_prompt.direct_answer is not None:
        direct = GeneratedAnswer(
            nutrition_prompt.direct_answer,
            post_success_actions=nutrition_prompt.post_success_actions,
        )
        await on_partial(str(direct))
        return direct

    messages = assemble_prompt_messages(
        nutrition_prompt.prompt_profile,
        current_user_message=msg,
        user_display_name=user,
        compacted_user_memory=(
            compacted_user_memory if nutrition_prompt.include_memory else None
        ),
        recent_conversation_messages=(
            recent_conversation_messages or []
            if nutrition_prompt.include_memory
            else []
        ),
        runtime_safety_instructions=nutrition_prompt.runtime_instructions,
        now=now,
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
        if not isinstance(provider, NvidiaNimProvider):
            return await answer(
                user,
                msg,
                profile=active_profile,
                request_id=request_id,
                queue_wait_seconds=queue_wait_seconds,
                compacted_user_memory=compacted_user_memory,
                recent_conversation_messages=recent_conversation_messages,
                internal_user_id=internal_user_id,
            )

        started_at = time.monotonic()
        raw_parts: list[str] = []
        last_partial = ""
        async for chunk in provider.stream_chat(
            model=active_profile.llm_model,
            messages=messages,
        ):
            raw_parts.append(chunk)
            partial = _telegram_stream_partial(
                "".join(raw_parts),
                max_chars=settings.ai_max_response_chars,
            )
            if partial and partial != last_partial:
                await on_partial(partial)
                last_partial = partial
        duration_seconds = time.monotonic() - started_at
        logger.info(
            "llm_provider_used request_id=%s provider=%s fallback_reason=%s "
            "streaming=true duration_seconds=%.6f message_chars=%s",
            request_id_text,
            provider.name,
            fallback_reason,
            duration_seconds,
            len(msg),
        )
    except AI_TIMEOUT_ERRORS:
        logger.warning(
            "llm_chat_timeout request_id=%s provider=%s model=%s "
            "timeout_seconds=%s message_chars=%s streaming=true",
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
            "message_chars=%s streaming=true",
            request_id_text,
            fallback_reason,
            len(msg),
        )
        return AI_ERROR_FALLBACK
    except Exception:
        provider_name = _provider_name(provider)
        logger.exception(
            "llm_chat_failed request_id=%s provider=%s model=%s message_chars=%s "
            "streaming=true",
            request_id_text,
            provider_name,
            _logged_model(active_profile.llm_model, provider_name),
            len(msg),
        )
        partial_answer = _telegram_stream_partial(
            "".join(raw_parts) if "raw_parts" in locals() else "",
            max_chars=settings.ai_max_response_chars,
        )
        if partial_answer:
            return GeneratedAnswer(
                (
                    f"{partial_answer}\n\n"
                    "No he podido completar la respuesta, pero esto es lo que "
                    "llevaba preparado."
                ),
                post_success_actions=nutrition_prompt.post_success_actions,
            )
        return AI_ERROR_FALLBACK

    content = "".join(raw_parts)
    provider_name = _provider_name(provider)
    return GeneratedAnswer(
        _trim_response(
            content,
            provider=provider_name,
            model=_logged_model(active_profile.llm_model, provider_name),
            max_chars=settings.ai_max_response_chars,
        ),
        post_success_actions=nutrition_prompt.post_success_actions,
    )


def finalize_successful_answer(answer: str) -> None:
    """Run side effects that are only safe after the user received an answer."""
    actions = getattr(answer, "post_success_actions", ())
    for action in actions:
        try:
            if callable(action):
                action()
        except Exception:
            logger.exception("post_success_answer_action_failed")


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
    except AI_TIMEOUT_ERRORS:
        provider_name = _provider_name(provider)
        logger.warning(
            "memory_compaction_timeout request_id=%s provider=%s model=%s "
            "timeout_seconds=%s source_messages=%s",
            request_id_text,
            provider_name,
            _logged_model(profile.llm_model, provider_name),
            get_settings().ai_timeout_seconds,
            len(source_messages),
        )
        fallback_summary = await _answer_with_fallback(
            messages=messages,
            model=profile.llm_model,
            max_chars=max_chars,
            message_chars=sum(len(message["content"]) for message in source_messages),
            request_id=request_id_text,
            reason="memory_compaction_timeout",
            timeout_fallback=None,
        )
        if fallback_summary is None:
            logger.error(
                "memory_compaction_failed request_id=%s provider=%s source_messages=%s",
                request_id_text,
                provider_name,
                len(source_messages),
            )
        return fallback_summary
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
            timeout_fallback=None,
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


def _current_datetime(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


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


def _nvidia_model_for_request(request_model: str, default_model: str) -> str:
    return request_model if request_model.startswith("nvidia/") else default_model


def _nvidia_stream_delta(data: str) -> str:
    try:
        payload = json.loads(data)
        delta = payload["choices"][0].get("delta", {})
        return str(delta.get("content") or "")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        logger.debug("nvidia_stream_chunk_ignored")
        return ""


def _select_provider(
    *,
    profile_provider: str,
    queue_wait_seconds: float,
) -> OllamaProvider | NvidiaNimProvider:
    settings = get_settings()
    configured_primary_provider = settings.llm_primary_provider.lower()
    primary_provider = (
        profile_provider
        if configured_primary_provider in PROFILE_PRIMARY_PROVIDER_VALUES
        else configured_primary_provider
    )
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


def _build_nutrition_normalizer(
    profile: BotProfile,
) -> tuple[OllamaProvider | NvidiaNimProvider, str] | None:
    if profile.bot_profile_id != "nutrition":
        return None

    settings = get_settings()
    provider_name = settings.nutrition_normalizer_provider.lower()
    if provider_name in FALLBACK_DISABLED_VALUES:
        return None
    if provider_name in PROFILE_PRIMARY_PROVIDER_VALUES:
        provider_name = profile.llm_provider

    try:
        provider = _build_provider(provider_name)
    except ProviderConfigurationError:
        logger.warning(
            "nutrition_normalizer_unavailable provider=%s",
            provider_name,
            exc_info=True,
        )
        return None
    return provider, settings.nutrition_normalizer_model


def build_nutrition_normalizer(
    profile: BotProfile,
) -> tuple[OllamaProvider | NvidiaNimProvider, str] | None:
    """Return the configured model client for nutrition normalization tasks."""
    return _build_nutrition_normalizer(profile)


async def _answer_with_fallback(
    *,
    messages: list[ChatMessage],
    model: str,
    max_chars: int,
    message_chars: int,
    request_id: str,
    reason: str,
    timeout_fallback: str | None = AI_TIMEOUT_FALLBACK,
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
        return timeout_fallback
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
    cleaned = _telegram_plain_text(content)
    if len(cleaned) <= max_chars:
        return cleaned

    logger.info(
        "llm_response_truncated provider=%s model=%s original_chars=%s max_chars=%s",
        provider,
        model,
        len(cleaned),
        max_chars,
    )
    return cleaned[:max_chars].rstrip()


def _telegram_plain_text(content: str) -> str:
    """Normalize LLM output for Telegram HTML parse mode."""
    text = html.escape(content.strip())
    text = re.sub(r"```(?:\w+)?\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[\*\+]\s+", "- ", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = text.replace("*", "")
    text = re.sub(r"(?m)^\s*-{3,}\s*$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _telegram_stream_partial(content: str, *, max_chars: int) -> str:
    cleaned = _telegram_plain_text(content)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip()


def _logged_model(profile_model: str, provider: str) -> str:
    if provider == "nvidia":
        return get_settings().nvidia_model
    return profile_model


def _provider_name(provider: OllamaProvider | NvidiaNimProvider | None) -> str:
    if provider is None:
        return "unknown"
    return provider.name
