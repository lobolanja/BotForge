from dataclasses import replace
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from forge_bot.bot_profile import BotProfile, BotProfileError
from forge_bot.memory_backend import (
    LangChainPostgresMemoryBackend,
    _session_id,
    memory_backend_for_profile,
)


def fake_profile() -> BotProfile:
    return BotProfile(
        bot_profile_id="nutrition",
        bot_display_name="Nutrition",
        bot_description="Test profile",
        system_prompt="Be helpful.",
        domain_rules=("Do not leak secrets.",),
        disclaimer_text="Test only.",
        default_language="es",
        llm_provider="nvidia",
        llm_model="nvidia/test-model",
        memory_enabled=True,
        memory_backend="postgres",
        analytics_enabled=False,
    )


def fake_settings(**overrides: object) -> SimpleNamespace:
    values = {
        "memory_recent_messages": 2,
        "memory_compaction_trigger_messages": 3,
        "memory_compaction_source_messages": 2,
        "memory_max_message_chars": 4000,
        "memory_compacted_max_chars": 2000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_profile_memory_backend_selects_langchain_postgres() -> None:
    profile = replace(fake_profile(), memory_backend="langchain_postgres")

    backend = memory_backend_for_profile(profile)

    assert isinstance(backend, LangChainPostgresMemoryBackend)


def test_profile_memory_backend_rejects_unknown_value() -> None:
    profile = replace(fake_profile(), memory_backend="unknown_backend")

    with pytest.raises(BotProfileError, match="Unsupported memory backend"):
        memory_backend_for_profile(profile)


def test_session_id_is_stable_uuid_for_user_profile_pair() -> None:
    session_id = _session_id(user_id=42, bot_profile_id="nutrition")

    assert session_id == _session_id(user_id=42, bot_profile_id="nutrition")
    assert session_id != _session_id(user_id=42, bot_profile_id="default_dev")
    assert len(session_id) == 36


def test_langchain_backend_returns_prompt_context_from_official_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LangChainPostgresMemoryBackend()
    monkeypatch.setattr("forge_bot.memory_backend.get_settings", fake_settings)
    monkeypatch.setattr(backend, "_ensure_session_mapping", lambda **kwargs: True)
    monkeypatch.setattr(
        backend,
        "_read_summary_state",
        lambda **kwargs: ("prefiere cenas simples", 0),
    )
    monkeypatch.setattr(
        backend,
        "_get_recent_langchain_messages",
        lambda **kwargs: [
            HumanMessage(content="Que ceno?"),
            AIMessage(content="Merluza con verduras."),
        ],
    )

    context = backend.get_context(user_id=1, bot_profile_id="nutrition")

    assert context.compacted_user_memory == "prefiere cenas simples"
    assert context.recent_conversation_messages == [
        {"role": "user", "content": "Que ceno?"},
        {"role": "assistant", "content": "Merluza con verduras."},
    ]


def test_langchain_backend_stores_turn_with_truncated_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LangChainPostgresMemoryBackend()
    stored_messages: list[BaseMessage] = []

    monkeypatch.setattr(
        "forge_bot.memory_backend.get_settings",
        lambda: fake_settings(memory_max_message_chars=5),
    )
    monkeypatch.setattr(backend, "_ensure_session_mapping", lambda **kwargs: True)
    monkeypatch.setattr(
        backend,
        "_add_langchain_messages",
        lambda *, messages, **kwargs: stored_messages.extend(messages),
    )

    stored = backend.store_successful_turn(
        user_id=1,
        bot_profile_id="nutrition",
        user_message="hola usuario",
        assistant_message="respuesta larga",
    )

    assert stored is True
    assert isinstance(stored_messages[0], HumanMessage)
    assert stored_messages[0].content == "hola"
    assert isinstance(stored_messages[1], AIMessage)
    assert stored_messages[1].content == "respu"


@pytest.mark.asyncio
async def test_langchain_backend_compacts_unsummarized_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LangChainPostgresMemoryBackend()
    saved: list[dict[str, object]] = []
    summarized_inputs: list[list[dict[str, str]]] = []

    monkeypatch.setattr(
        "forge_bot.memory_backend.get_settings",
        lambda: fake_settings(
            memory_compaction_trigger_messages=3,
            memory_compaction_source_messages=2,
            memory_compacted_max_chars=7,
        ),
    )
    monkeypatch.setattr(
        backend,
        "_read_summary_state",
        lambda **kwargs: ("resumen previo", 1),
    )
    monkeypatch.setattr(
        backend,
        "_get_unsummarized_langchain_messages",
        lambda **kwargs: [
            AIMessage(content="respuesta 1"),
            HumanMessage(content="pregunta 2"),
            AIMessage(content="respuesta 2"),
        ],
    )
    monkeypatch.setattr(
        backend,
        "_save_summary_state",
        lambda **kwargs: saved.append(kwargs),
    )

    async def summarize(
        existing_summary: str | None,
        source_messages: list[dict[str, str]],
        max_chars: int,
    ) -> str:
        assert existing_summary == "resumen previo"
        assert max_chars == 7
        summarized_inputs.append(source_messages)
        return "resumen actualizado largo"

    await backend.compact_memory_if_needed(
        user_id=1,
        bot_profile_id="nutrition",
        summarizer=summarize,
    )

    assert summarized_inputs == [
        [
            {"role": "assistant", "content": "respuesta 1"},
            {"role": "user", "content": "pregunta 2"},
        ]
    ]
    assert saved == [
        {
            "user_id": 1,
            "bot_profile_id": "nutrition",
            "summary": "resumen",
            "source_message_count": 3,
        }
    ]
