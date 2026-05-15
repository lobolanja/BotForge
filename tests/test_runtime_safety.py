import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

from forge_bot import engine
from forge_bot.bot_profile import BotProfile
from forge_bot.commands import auth_guard


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def fake_profile() -> BotProfile:
    return BotProfile(
        bot_profile_id="default_dev",
        bot_display_name="BotForge",
        bot_description="Test profile",
        system_prompt="Be helpful.",
        domain_rules=("Do not leak secrets.",),
        disclaimer_text="Test only.",
        default_language="en",
        llm_provider="ollama",
        llm_model="test-model",
        memory_enabled=False,
        analytics_enabled=False,
    )


def fake_settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "ollama_host": "http://ollama:11434",
        "llm_primary_provider": "ollama",
        "llm_fallback_provider": "nvidia",
        "llm_fallback_queue_wait_seconds": 100,
        "nvidia_api_key": "",
        "nvidia_base_url": "https://integrate.api.nvidia.com/v1",
        "nvidia_model": "nvidia/test-model",
        "bot_profile": "default_dev",
        "bot_profiles_dir": "bot_profiles",
        "ai_timeout_seconds": 1,
        "ai_max_response_chars": 4000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def fake_ollama_client(**kwargs: object) -> SimpleNamespace:
    del kwargs
    return SimpleNamespace(chat=lambda **kw: object())


def test_nvidia_provider_rejects_non_https_base_url() -> None:
    with pytest.raises(engine.ProviderConfigurationError, match="HTTPS URL"):
        engine.NvidiaNimProvider(
            api_key="secret-key",
            base_url="file:///tmp/socket",
            model="nvidia/test-model",
            timeout_seconds=1,
        )


def test_nvidia_provider_normalizes_https_base_url() -> None:
    provider = engine.NvidiaNimProvider(
        api_key="secret-key",
        base_url="https://example.test/v1/",
        model="nvidia/test-model",
        timeout_seconds=1,
    )

    assert provider._base_url == "https://example.test/v1"


@pytest.mark.asyncio
async def test_ai_timeout_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_to_thread(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(1)
        return object()

    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(ai_timeout_seconds=0.01),
    )
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr("forge_bot.engine.ollama.Client", fake_ollama_client)
    monkeypatch.setattr("forge_bot.engine.asyncio.to_thread", slow_to_thread)

    result = await engine.answer("Ada", "hello")

    assert result == engine.AI_TIMEOUT_FALLBACK


@pytest.mark.asyncio
async def test_ai_exception_returns_fallback_without_logging_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_message = "my secret token is 123"

    async def failing_to_thread(*args: object, **kwargs: object) -> object:
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr("forge_bot.engine.ollama.Client", fake_ollama_client)
    monkeypatch.setattr("forge_bot.engine.asyncio.to_thread", failing_to_thread)

    with caplog.at_level(logging.ERROR):
        result = await engine.answer("Ada", private_message)

    assert result == engine.AI_ERROR_FALLBACK
    assert private_message not in caplog.text
    assert "message_chars=" in caplog.text


@pytest.mark.asyncio
async def test_ai_response_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def successful_to_thread(*args: object, **kwargs: object) -> object:
        return SimpleNamespace(message=SimpleNamespace(content="abcdef"))

    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(ai_max_response_chars=3),
    )
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr("forge_bot.engine.ollama.Client", fake_ollama_client)
    monkeypatch.setattr("forge_bot.engine.asyncio.to_thread", successful_to_thread)

    result = await engine.answer("Ada", "hello")

    assert result == "abc"


@pytest.mark.asyncio
async def test_fallback_provider_answers_when_ollama_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        name = "ollama"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            raise RuntimeError("ollama is down")

    class FallbackProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            return "fallback answer"

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr(
        engine,
        "_build_provider",
        lambda name: FallbackProvider() if name == "nvidia" else FailingProvider(),
    )

    result = await engine.answer("Ada", "hello", request_id="req-1")

    assert result == "fallback answer"


@pytest.mark.asyncio
async def test_queue_wait_over_threshold_uses_fallback_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used_providers: list[str] = []

    class FakeProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            used_providers.append(self.name)
            return f"{self.name} answer"

    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(llm_fallback_queue_wait_seconds=100),
    )
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider(name))

    result = await engine.answer("Ada", "hello", queue_wait_seconds=101)

    assert result == "nvidia answer"
    assert used_providers == ["nvidia"]


@pytest.mark.asyncio
async def test_queue_wait_under_threshold_uses_primary_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used_providers: list[str] = []

    class FakeProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            used_providers.append(self.name)
            return f"{self.name} answer"

    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(llm_fallback_queue_wait_seconds=100),
    )
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider(name))

    result = await engine.answer("Ada", "hello", queue_wait_seconds=99)

    assert result == "ollama answer"
    assert used_providers == ["ollama"]


@pytest.mark.asyncio
async def test_missing_nvidia_api_key_fails_only_when_fallback_is_needed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())

    with caplog.at_level(logging.ERROR):
        result = await engine.answer("Ada", "hello", queue_wait_seconds=101)

    assert result == engine.AI_ERROR_FALLBACK
    assert "NVIDIA_API_KEY" in caplog.text


@pytest.mark.asyncio
async def test_login_guard_reports_identity_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        message=message,
    )
    context = SimpleNamespace()
    called = False

    async def protected_handler(update: object, context: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: None)

    wrapped = auth_guard.require_login(protected_handler)
    await wrapped(cast(Any, update), cast(Any, context))

    assert not called
    assert message.replies == [auth_guard.IDENTITY_UNAVAILABLE_MESSAGE]
