import asyncio
import logging
import ssl
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from forge_bot import engine
from forge_bot.bot_profile import BotProfile, BotProfileContextDocument
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
        memory_backend="postgres",
        analytics_enabled=False,
    )


def fake_settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "ollama_host": "http://ollama:11434",
        "llm_primary_provider": "profile",
        "llm_fallback_provider": "nvidia",
        "llm_fallback_queue_wait_seconds": 100,
        "nvidia_api_key": "",
        "nvidia_base_url": "https://integrate.api.nvidia.com/v1",
        "nvidia_model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nutrition_normalizer_provider": "off",
        "nutrition_normalizer_model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "bot_profile": "default_dev",
        "bot_profiles_dir": "bot_profiles",
        "bot_timezone": "Europe/Madrid",
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


def test_nvidia_provider_uses_certifi_ssl_context() -> None:
    provider = engine.NvidiaNimProvider(
        api_key="secret-key",
        base_url="https://example.test/v1/",
        model="nvidia/test-model",
        timeout_seconds=1,
    )

    assert isinstance(provider._ssl_context, ssl.SSLContext)


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
async def test_ai_response_is_normalized_for_telegram_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def successful_to_thread(*args: object, **kwargs: object) -> object:
        return SimpleNamespace(
            message=SimpleNamespace(
                content="### **Cena**\n* 330g de merluza\n* `20g aceite`"
            )
        )

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr("forge_bot.engine.ollama.Client", fake_ollama_client)
    monkeypatch.setattr("forge_bot.engine.asyncio.to_thread", successful_to_thread)

    result = await engine.answer("Ada", "hello")

    assert result == "<b>Cena</b>\n- 330g de merluza\n- 20g aceite"


@pytest.mark.asyncio
async def test_memory_query_sends_recent_conversation_to_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[list[dict[str, str]]] = []

    class FakeProvider:
        name = "ollama"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model
            captured_messages.append(messages)
            return "Lo ultimo que me preguntaste fue que cenar dia de no entreno."

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer(
        "Ada",
        "Que ha sido lo ultimo que te he preguntado?",
        recent_conversation_messages=[
            {"role": "user", "content": "Que ceno hoy dia de no entreno?"},
            {"role": "assistant", "content": "Cena de no entreno..."},
        ],
    )

    assert result == "Lo ultimo que me preguntaste fue que cenar dia de no entreno."
    system_message = captured_messages[0][0]["content"]
    assert "Available conversation context" in system_message
    assert "Do not say you have no memory" in system_message
    assert "user: Que ceno hoy dia de no entreno?" in system_message


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
async def test_fallback_provider_timeout_returns_timeout_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        name = "ollama"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            raise RuntimeError("ollama is down")

    class TimeoutProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            raise asyncio.TimeoutError

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "load_active_bot_profile", lambda *args: fake_profile())
    monkeypatch.setattr(
        engine,
        "_build_provider",
        lambda name: TimeoutProvider() if name == "nvidia" else FailingProvider(),
    )

    result = await engine.answer("Ada", "hello", request_id="req-1")

    assert result == engine.AI_TIMEOUT_FALLBACK


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
async def test_profile_primary_provider_uses_profile_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used_providers: list[str] = []

    class FakeProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            used_providers.append(self.name)
            return f"{self.name} answer"

    nvidia_profile = replace(
        fake_profile(),
        llm_provider="nvidia",
        llm_model="nvidia/test-model",
    )

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nvidia_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider(name))

    result = await engine.answer("Ada", "hello")

    assert result == "nvidia answer"
    assert used_providers == ["nvidia"]


@pytest.mark.asyncio
async def test_explicit_primary_provider_overrides_profile_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used_providers: list[str] = []

    class FakeProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            used_providers.append(self.name)
            return f"{self.name} answer"

    nvidia_profile = replace(
        fake_profile(),
        llm_provider="nvidia",
        llm_model="nvidia/test-model",
    )

    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(llm_primary_provider="ollama"),
    )
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nvidia_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider(name))

    result = await engine.answer("Ada", "hello")

    assert result == "ollama answer"
    assert used_providers == ["ollama"]


@pytest.mark.asyncio
async def test_nutrition_profile_sends_only_resolved_plan_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[list[dict[str, str]]] = []

    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model
            captured_messages.append(messages)
            return "nutrition answer"

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
        context_documents=(
            BotProfileContextDocument(
                name="sample_plan.json",
                content='{"comida_5": "should not be sent"}',
            ),
        ),
    )
    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer(
        "Ada",
        "Hoy tengo crossfit, que como al mediodia?",
    )

    assert result == "nutrition answer"
    system_message = captured_messages[0][0]["content"]
    assert "Resolved nutrition plan context" in system_message
    assert '"meal_block_key": "comida_2"' in system_message
    assert "Profile context documents:" not in system_message
    assert "comida_5" not in system_message


@pytest.mark.asyncio
async def test_nutrition_profile_uses_configured_normalizer_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used_models: list[str] = []

    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            used_models.append(model)
            system_message = messages[0]["content"]
            if "Normalize one Spanish nutrition-bot user message" in system_message:
                return (
                    '{"intent":"recommend_meal","situation_key":"futbol",'
                    '"situation_keys":["futbol"],"target_moment_key":"cena",'
                    '"mentioned_moment_keys":["cena"],"logged_meals":[],'
                    '"goal":"resolver cena","confidence":"high"}'
                )
            return "nutrition answer"

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        llm_model="nvidia/final-answer-model",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
    )
    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(
            nutrition_normalizer_provider="nvidia",
            nutrition_normalizer_model="nvidia/cheap-normalizer",
        ),
    )
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer(
        "Ada",
        "Hola, hoy es dia de futbol, que puedo tomar para la cena?",
    )

    assert result == "nutrition answer"
    assert used_models == ["nvidia/cheap-normalizer", "nvidia/final-answer-model"]


@pytest.mark.asyncio
async def test_nutrition_profile_sanitizes_resolved_answer_without_extra_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model, messages
            return "### **Cena**\n* " + ("respuesta larga " * 200)

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
    )
    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: fake_settings(ai_max_response_chars=4000),
    )
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer("Ada", "Hoy no entreno, que ceno?")

    assert len(result) > 900
    assert "*" not in result
    assert "###" not in result
    assert result.startswith("<b>Cena</b>\n- respuesta larga")


@pytest.mark.asyncio
async def test_nutrition_profile_sends_resolved_full_day_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[list[dict[str, str]]] = []

    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model
            captured_messages.append(messages)
            return "full day nutrition answer"

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
        context_documents=(
            BotProfileContextDocument(
                name="sample_plan.json",
                content='{"comida_5": "should not be sent"}',
            ),
        ),
    )
    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer(
        "Ada",
        "Dame todo lo que puedo comer hoy dia de ciclismo",
    )

    assert result == "full day nutrition answer"
    system_message = captured_messages[0][0]["content"]
    assert '"mode": "full_day"' in system_message
    assert '"situation_key": "ciclismo"' in system_message
    assert '"moment_key": "desayuno"' in system_message
    assert '"moment_key": "almuerzo"' in system_message
    assert '"moment_key": "merienda"' in system_message
    assert '"moment_key": "cena"' in system_message
    assert '"meal_block_key": "comida_5"' not in system_message
    assert "Profile context documents:" not in system_message


@pytest.mark.asyncio
async def test_nutrition_profile_missing_moment_asks_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_called = False

    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            nonlocal provider_called
            del model, messages
            provider_called = True
            return "should not be used"

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
    )
    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer("Ada", "Hoy tengo crossfit")

    assert "dime el momento" in result
    assert not provider_called


@pytest.mark.asyncio
async def test_nutrition_profile_resolves_follow_up_moment_from_recent_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[list[dict[str, str]]] = []

    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model
            captured_messages.append(messages)
            return "cena no entreno"

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
    )
    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer(
        "Ada",
        "Cena",
        recent_conversation_messages=[
            {"role": "user", "content": "Que como hoy dia de no entreno?"},
            {"role": "assistant", "content": "Te lo ajusto, pero dime el momento."},
        ],
    )

    assert result == "cena no entreno"
    system_message = captured_messages[0][0]["content"]
    assert '"situation_key": "no_entreno"' in system_message
    assert '"moment_key": "cena"' in system_message
    assert '"meal_block_key": "comida_3"' in system_message
    assert "Recent conversation:" in system_message


@pytest.mark.asyncio
async def test_nutrition_profile_resolves_follow_up_situation_from_recent_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[list[dict[str, str]]] = []

    class FakeProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model
            captured_messages.append(messages)
            return "cena no entreno"

    nutrition_profile = replace(
        fake_profile(),
        bot_profile_id="nutrition",
        llm_provider="nvidia",
        nutrition_plan_path=Path("tests/fixtures/nutrition_plan.json"),
    )
    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "load_active_bot_profile",
        lambda *args: nutrition_profile,
    )
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.answer(
        "Ada",
        "No entreno",
        recent_conversation_messages=[
            {"role": "user", "content": "Cena"},
            {"role": "assistant", "content": "Dime que tipo de dia es."},
        ],
    )

    assert result == "cena no entreno"
    system_message = captured_messages[0][0]["content"]
    assert '"situation_key": "no_entreno"' in system_message
    assert '"moment_key": "cena"' in system_message
    assert '"meal_block_key": "comida_3"' in system_message
    assert "Recent conversation:" in system_message


@pytest.mark.asyncio
async def test_memory_summary_uses_compaction_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[list[dict[str, str]]] = []

    class FakeProvider:
        name = "ollama"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model
            captured_messages.append(messages)
            return "Prefers vegetarian meals."

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "_build_provider", lambda name: FakeProvider())

    result = await engine.summarize_memory(
        profile=fake_profile(),
        existing_summary="Likes quick dinners.",
        source_messages=[{"role": "user", "content": "I am vegetarian."}],
        max_chars=2000,
        request_id="req-1",
    )

    assert result == "Prefers vegetarian meals."
    assert "Existing memory" in captured_messages[0][1]["content"]
    assert "I am vegetarian." in captured_messages[0][1]["content"]


@pytest.mark.asyncio
async def test_memory_summary_timeout_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutProvider:
        name = "ollama"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model, messages
            raise asyncio.TimeoutError

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(engine, "_build_provider", lambda name: TimeoutProvider())

    result = await engine.summarize_memory(
        profile=fake_profile(),
        existing_summary="Likes quick dinners.",
        source_messages=[{"role": "user", "content": "I am vegetarian."}],
        max_chars=2000,
        request_id="req-1",
    )

    assert result is None


@pytest.mark.asyncio
async def test_memory_summary_fallback_timeout_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        name = "ollama"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model, messages
            raise RuntimeError("ollama is down")

    class TimeoutProvider:
        name = "nvidia"

        async def chat(self, *, model: str, messages: list[dict[str, str]]) -> str:
            del model, messages
            raise asyncio.TimeoutError

    monkeypatch.setattr(engine, "get_settings", lambda: fake_settings())
    monkeypatch.setattr(
        engine,
        "_build_provider",
        lambda name: TimeoutProvider() if name == "nvidia" else FailingProvider(),
    )

    result = await engine.summarize_memory(
        profile=fake_profile(),
        existing_summary="Likes quick dinners.",
        source_messages=[{"role": "user", "content": "I am vegetarian."}],
        max_chars=2000,
        request_id="req-1",
    )

    assert result is None


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
