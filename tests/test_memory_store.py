import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from forge_bot.memory_store import (
    ConversationMemoryStore,
    ConversationMessage,
    _CachedMemory,
)


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        memory_recent_messages=10,
        memory_compaction_trigger_messages=6,
        memory_compaction_source_messages=5,
        memory_max_message_chars=4000,
        memory_compacted_max_chars=2000,
    )


def message(message_id: int, role: str = "user") -> ConversationMessage:
    return ConversationMessage(
        id=message_id,
        role=role,
        content=f"{role} {message_id}",
        created_at=datetime.now(timezone.utc),
    )


def test_memory_context_is_loaded_once_per_user_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConversationMemoryStore()
    loads: list[tuple[int, str]] = []

    def load(
        user_id: int,
        bot_profile_id: str,
        exclude_inbound_message_id: int | None = None,
    ) -> _CachedMemory:
        del exclude_inbound_message_id
        loads.append((user_id, bot_profile_id))
        return _CachedMemory(
            compacted_user_memory="likes vegetarian dinners",
            recent_messages=[message(1)],
        )

    monkeypatch.setattr(store, "_load_from_database", load)

    first = store.get_context(user_id=7, bot_profile_id="default_dev")
    second = store.get_context(user_id=7, bot_profile_id="default_dev")

    assert first.compacted_user_memory == "likes vegetarian dinners"
    assert second.recent_conversation_messages == [
        {"role": "user", "content": "user 1"}
    ]
    assert loads == [(7, "default_dev")]


def test_empty_conversation_memory_bootstraps_from_answered_inbound_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConversationMemoryStore()
    bootstrap_calls: list[dict[str, object]] = []

    class Cursor:
        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, *args: object) -> None:
            return None

        def fetchone(self) -> None:
            return None

        def fetchall(self) -> list[dict[str, object]]:
            return []

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            return None

    def bootstrap(**kwargs: object) -> list[ConversationMessage]:
        bootstrap_calls.append(kwargs)
        return [message(41)]

    monkeypatch.setattr("forge_bot.memory_store.get_settings", settings)
    monkeypatch.setattr("forge_bot.memory_store.conect_db", lambda: Connection())
    monkeypatch.setattr(store, "_load_recent_inbound_messages", bootstrap)

    context = store.get_context(
        user_id=7,
        bot_profile_id="default_dev",
        exclude_inbound_message_id=99,
    )

    assert context.recent_conversation_messages == [
        {"role": "user", "content": "user 41"}
    ]
    assert bootstrap_calls == [
        {
            "user_id": 7,
            "limit": 10,
            "exclude_inbound_message_id": 99,
        }
    ]


@pytest.mark.asyncio
async def test_successful_turn_compacts_first_five_unsummarized_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConversationMemoryStore()
    cached = _CachedMemory(
        compacted_user_memory=None,
        recent_messages=[
            message(1),
            message(2, "assistant"),
            message(3),
            message(4, "assistant"),
        ],
    )
    saved: list[tuple[str, list[int]]] = []
    summarized_inputs: list[list[dict[str, str]]] = []

    monkeypatch.setattr("forge_bot.memory_store.get_settings", settings)
    monkeypatch.setattr(
        store,
        "_get_or_load",
        lambda user_id, bot_profile_id: cached,
    )
    monkeypatch.setattr(
        store,
        "_insert_turn",
        lambda **kwargs: [message(5), message(6, "assistant")],
    )

    def save_summary_and_mark_sources(**kwargs: object) -> bool:
        saved.append(
            (
                str(kwargs["summary"]),
                [int(item) for item in kwargs["source_ids"]],
            )
        )
        return True

    monkeypatch.setattr(
        store,
        "_save_summary_and_mark_sources",
        save_summary_and_mark_sources,
    )

    async def summarize(
        existing_summary: str | None,
        source_messages: list[dict[str, str]],
        max_chars: int,
    ) -> str:
        assert existing_summary is None
        assert max_chars == 2000
        summarized_inputs.append(source_messages)
        return "Updated compact memory"

    await store.add_successful_turn(
        user_id=7,
        bot_profile_id="default_dev",
        user_message="hello",
        assistant_message="hi",
        summarizer=summarize,
    )

    assert summarized_inputs == [
        [
            {"role": "user", "content": "user 1"},
            {"role": "assistant", "content": "assistant 2"},
            {"role": "user", "content": "user 3"},
            {"role": "assistant", "content": "assistant 4"},
            {"role": "user", "content": "user 5"},
        ]
    ]
    assert saved == [("Updated compact memory", [1, 2, 3, 4, 5])]
    assert cached.compacted_user_memory == "Updated compact memory"
    assert cached.recent_messages[0].summarized_at is not None
    assert cached.recent_messages[5].summarized_at is None


@pytest.mark.asyncio
async def test_compaction_is_serialized_per_user_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConversationMemoryStore()
    cached = _CachedMemory(
        compacted_user_memory=None,
        recent_messages=[message(1), message(2, "assistant")],
    )
    summarizer_calls: list[list[dict[str, str]]] = []
    first_started = asyncio.Event()
    allow_first_to_finish = asyncio.Event()

    monkeypatch.setattr(
        "forge_bot.memory_store.get_settings",
        lambda: SimpleNamespace(
            memory_recent_messages=10,
            memory_compaction_trigger_messages=2,
            memory_compaction_source_messages=2,
            memory_max_message_chars=4000,
            memory_compacted_max_chars=2000,
        ),
    )
    monkeypatch.setattr(
        store,
        "_get_or_load",
        lambda user_id, bot_profile_id: cached,
    )
    monkeypatch.setattr(
        store,
        "_save_summary_and_mark_sources",
        lambda **kwargs: True,
    )

    async def summarize(
        existing_summary: str | None,
        source_messages: list[dict[str, str]],
        max_chars: int,
    ) -> str:
        del existing_summary, max_chars
        summarizer_calls.append(source_messages)
        first_started.set()
        await allow_first_to_finish.wait()
        return "Compacted once"

    first_task = asyncio.create_task(
        store.compact_memory_if_needed(
            user_id=7,
            bot_profile_id="default_dev",
            summarizer=summarize,
        )
    )
    await first_started.wait()

    second_task = asyncio.create_task(
        store.compact_memory_if_needed(
            user_id=7,
            bot_profile_id="default_dev",
            summarizer=summarize,
        )
    )

    allow_first_to_finish.set()
    await asyncio.gather(first_task, second_task)

    assert summarizer_calls == [
        [
            {"role": "user", "content": "user 1"},
            {"role": "assistant", "content": "assistant 2"},
        ]
    ]
    assert cached.compacted_user_memory == "Compacted once"
    assert all(item.summarized_at is not None for item in cached.recent_messages)
