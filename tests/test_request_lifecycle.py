import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from helpers import make_settings

import forge_bot.request_state as request_state_module
from forge_bot import engine, router
from forge_bot.bot_profile import BotProfile
from forge_bot.commands import auth_guard
from forge_bot.rate_limits import MESSAGE_TOO_LONG_MESSAGE, AbuseLimiter
from forge_bot.request_state import REQUEST_WAITING_MESSAGE, UserRequestState


class FakeMessage:
    def __init__(self, text: str = "hello") -> None:
        self.text = text
        self.date = datetime.now(timezone.utc)
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeBot:
    def __init__(self) -> None:
        self.chat_actions: list[tuple[int, str]] = []
        self.drafts: list[dict[str, object]] = []

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        text: str,
        parse_mode: str | None = None,
    ) -> bool:
        self.drafts.append(
            {
                "chat_id": chat_id,
                "draft_id": draft_id,
                "text": text,
                "parse_mode": parse_mode,
            }
        )
        return True


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


def fake_memory_profile() -> BotProfile:
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
        memory_enabled=True,
        memory_backend="postgres",
        analytics_enabled=False,
    )


def fake_nvidia_profile() -> BotProfile:
    return BotProfile(
        bot_profile_id="nutrition",
        bot_display_name="BotForge",
        bot_description="Test profile",
        system_prompt="Be helpful.",
        domain_rules=("Do not leak secrets.",),
        disclaimer_text="Test only.",
        default_language="en",
        llm_provider="nvidia",
        llm_model="nvidia/test-model",
        memory_enabled=False,
        memory_backend="postgres",
        analytics_enabled=False,
    )


class FakeMemoryBackend:
    def __init__(self) -> None:
        self.context = SimpleNamespace(
            compacted_user_memory=None,
            recent_conversation_messages=[],
        )
        self.stored_turns: list[dict[str, object]] = []

    def get_context(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        return self.context

    def store_successful_turn(self, **kwargs: object) -> bool:
        self.stored_turns.append(kwargs)
        return True

    async def compact_memory_if_needed(self, **kwargs: object) -> None:
        del kwargs


def fake_update(*, update_id: int = 1001, text: str = "hello") -> SimpleNamespace:
    return SimpleNamespace(
        update_id=update_id,
        message=FakeMessage(text),
        effective_user=SimpleNamespace(id=123, first_name="Ada"),
        effective_chat=SimpleNamespace(id=456),
    )


def authorize_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_guard, "verify_user", lambda telegram_id: True)
    monkeypatch.setattr(
        auth_guard,
        "has_current_policy_acceptance",
        lambda telegram_id: True,
    )


@pytest.fixture(autouse=True)
def default_abuse_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "abuse_limiter", AbuseLimiter(make_settings))
    monkeypatch.setattr(router, "get_settings", lambda: make_settings())


@pytest.mark.asyncio
async def test_second_message_while_active_receives_waiting_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    monkeypatch.setattr(router, "request_state", state)
    active = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=datetime.now(timezone.utc),
        provider="ollama",
    )
    marked_ignored: list[int] = []
    update = fake_update(update_id=2002)

    assert active is not None

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(
        router,
        "mark_ignored",
        lambda update_id: marked_ignored.append(update_id),
    )
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == [REQUEST_WAITING_MESSAGE]
    assert marked_ignored == [2002]


@pytest.mark.asyncio
async def test_long_message_is_rejected_before_active_request_waiting_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    monkeypatch.setattr(router, "request_state", state)
    active = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=datetime.now(timezone.utc),
        provider="ollama",
    )
    update = fake_update(update_id=2003, text="too long")
    marked_ignored: list[int] = []

    assert active is not None

    monkeypatch.setattr(
        router,
        "abuse_limiter",
        AbuseLimiter(lambda: make_settings(max_message_chars=3)),
    )
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(
        router,
        "mark_ignored",
        lambda update_id: marked_ignored.append(update_id),
    )

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == [MESSAGE_TOO_LONG_MESSAGE]
    assert marked_ignored == [2003]


@pytest.mark.asyncio
async def test_request_state_is_cleared_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    monkeypatch.setattr(router, "request_state", state)
    update = fake_update(update_id=3003)

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del profile, kwargs
        return f"done for {user}"

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == ["done for Ada"]
    assert await state.active_for_user(123) is None


@pytest.mark.asyncio
async def test_slow_ai_response_sends_progress_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(router, "PROCESSING_NOTICE_INITIAL_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(router, "PROCESSING_NOTICE_INTERVAL_SECONDS", 10)
    update = fake_update(update_id=30032)

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        await asyncio.sleep(0.02)
        return "done"

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == [router.PROCESSING_NOTICE_MESSAGE, "done"]


@pytest.mark.asyncio
async def test_nvidia_profile_streams_drafts_before_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    bot = FakeBot()
    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(router, "STREAM_DRAFT_UPDATE_INTERVAL_SECONDS", 0)
    update = fake_update(update_id=30034)

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_nvidia_profile)

    async def answer_stream(
        user: str,
        msg: str,
        *,
        on_partial: Any,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        await on_partial("preparando")
        await on_partial("preparando cena")
        return "cena lista"

    monkeypatch.setattr(engine, "answer_stream", answer_stream)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=bot)))

    streamed_drafts = [
        draft["text"] for draft in bot.drafts if draft["text"] not in {".", "..", "..."}
    ]
    assert streamed_drafts == [
        "preparando",
        "preparando cena",
    ]
    assert bot.drafts[0]["draft_id"] == 30034
    assert update.message.replies == ["cena lista"]


@pytest.mark.asyncio
async def test_streaming_profile_shows_loading_dots_before_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    bot = FakeBot()
    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(router, "STREAM_LOADING_DRAFT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(router, "STREAM_DRAFT_UPDATE_INTERVAL_SECONDS", 0)
    update = fake_update(update_id=30035)

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_nvidia_profile)

    async def answer_stream(
        user: str,
        msg: str,
        *,
        on_partial: Any,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        await asyncio.sleep(0.035)
        await on_partial("respuesta parcial")
        return "respuesta final"

    monkeypatch.setattr(engine, "answer_stream", answer_stream)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=bot)))

    draft_texts = [draft["text"] for draft in bot.drafts]
    assert draft_texts[:3] == [".", "..", "..."]
    assert "respuesta parcial" in draft_texts
    assert update.message.replies == ["respuesta final"]


@pytest.mark.asyncio
async def test_very_slow_ai_response_sends_repeated_progress_notices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(router, "PROCESSING_NOTICE_INITIAL_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(router, "PROCESSING_NOTICE_INTERVAL_SECONDS", 0.01)
    update = fake_update(update_id=30033)

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        await asyncio.sleep(0.035)
        return "done"

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies[:2] == [
        router.PROCESSING_NOTICE_MESSAGE,
        router.PROCESSING_NOTICE_REPEAT_MESSAGE,
    ]
    assert update.message.replies[-1] == "done"


@pytest.mark.asyncio
async def test_successful_turn_is_offered_to_debug_conversation_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    update = fake_update(update_id=30031, text="Que ceno?")
    debug_turns: list[object] = []

    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"id": 91, "status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"id": 91, "status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)
    monkeypatch.setattr(
        router,
        "append_debug_conversation_turn",
        lambda turn: debug_turns.append(turn) or True,
    )

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        return "Merluza con verduras."

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == ["Merluza con verduras."]
    assert len(debug_turns) == 1
    turn = debug_turns[0]
    assert turn.bot_profile_id == "default_dev"
    assert turn.telegram_user_id == 123
    assert turn.telegram_chat_id == 456
    assert turn.inbound_message_id == 91
    assert turn.user_message == "Que ceno?"
    assert turn.assistant_message == "Merluza con verduras."


@pytest.mark.asyncio
async def test_engine_receives_wait_time_after_global_ai_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    initial_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    after_global_queue = initial_now.replace(second=12)
    finished_now = initial_now.replace(second=13)
    times = iter([initial_now, after_global_queue, finished_now])
    state = UserRequestState()
    update = fake_update(update_id=3004)
    update.message.date = initial_now
    queue_waits: list[float] = []

    monkeypatch.setattr(request_state_module, "_utc_now", lambda: next(times))
    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile
        queue_waits.append(float(kwargs["queue_wait_seconds"]))
        return "done"

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == ["done"]
    assert queue_waits == [12]


@pytest.mark.asyncio
async def test_memory_context_is_sent_to_engine_and_turn_is_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    update = fake_update(update_id=3005)
    answer_kwargs: list[dict[str, object]] = []
    memory_backend = FakeMemoryBackend()
    memory_backend.context = SimpleNamespace(
        compacted_user_memory="Prefers vegetarian dinners.",
        recent_conversation_messages=[{"role": "user", "content": "I am vegetarian."}],
    )

    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"id": 55, "status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"id": 55, "status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_memory_profile)
    monkeypatch.setattr(router, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        router,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 777, "username": "ada"},
    )
    monkeypatch.setattr(
        router,
        "memory_backend_for_profile",
        lambda profile: memory_backend,
    )

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile
        answer_kwargs.append(kwargs)
        return "try a vegetable stew"

    monkeypatch.setattr(engine, "answer", answer)

    async def compact_turn(**kwargs: object) -> None:
        del kwargs

    monkeypatch.setattr(router, "_compact_successful_turn", compact_turn)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == ["try a vegetable stew"]
    assert answer_kwargs[0]["compacted_user_memory"] == "Prefers vegetarian dinners."
    assert answer_kwargs[0]["recent_conversation_messages"] == [
        {"role": "user", "content": "I am vegetarian."}
    ]
    assert answer_kwargs[0]["internal_user_id"] == 777
    assert memory_backend.stored_turns[0]["user_id"] == 777
    assert memory_backend.stored_turns[0]["bot_profile_id"] == "default_dev"
    assert memory_backend.stored_turns[0]["user_message"] == "hello"
    assert memory_backend.stored_turns[0]["assistant_message"] == (
        "try a vegetable stew"
    )


@pytest.mark.asyncio
async def test_operational_fallback_is_not_stored_as_memory_or_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    update = fake_update(update_id=30051)
    memory_backend = FakeMemoryBackend()
    debug_turns: list[object] = []
    compacted: list[object] = []

    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"id": 57, "status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"id": 57, "status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_memory_profile)
    monkeypatch.setattr(router, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        router,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 777, "username": "ada"},
    )
    monkeypatch.setattr(
        router,
        "memory_backend_for_profile",
        lambda profile: memory_backend,
    )
    monkeypatch.setattr(
        router,
        "append_debug_conversation_turn",
        lambda turn: debug_turns.append(turn) or True,
    )

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        return engine.GeneratedAnswer(
            engine.AI_TIMEOUT_FALLBACK,
            debug_log=False,
            store_in_memory=False,
        )

    async def compact_turn(**kwargs: object) -> None:
        compacted.append(kwargs)

    monkeypatch.setattr(engine, "answer", answer)
    monkeypatch.setattr(router, "_compact_successful_turn", compact_turn)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == [engine.AI_TIMEOUT_FALLBACK]
    assert debug_turns == []
    assert memory_backend.stored_turns == []
    assert compacted == []


@pytest.mark.asyncio
async def test_memory_compaction_runs_after_ai_lease_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    update = fake_update(update_id=3006)
    events: list[str] = []
    memory_backend = FakeMemoryBackend()

    class FakeLease:
        def __init__(self) -> None:
            self.released = False

        async def release(self) -> None:
            self.released = True
            events.append("release")

    lease = FakeLease()

    class FakeLimiter:
        def check_message_length(
            self, *, user_id: int, chat_id: int, text: str
        ) -> SimpleNamespace:
            del user_id, chat_id, text
            return SimpleNamespace(allowed=True)

        def check_message_rate(self, *, user_id: int, chat_id: int) -> SimpleNamespace:
            del user_id, chat_id
            return SimpleNamespace(allowed=True)

        async def acquire_ai_request(self, *, user_id: int, chat_id: int) -> FakeLease:
            del user_id, chat_id
            events.append("acquire")
            return lease

        def check_user_ai_request(
            self, *, user_id: int, chat_id: int
        ) -> SimpleNamespace:
            del user_id, chat_id
            return SimpleNamespace(allowed=True)

    monkeypatch.setattr(router, "request_state", state)
    monkeypatch.setattr(router, "abuse_limiter", FakeLimiter())
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"id": 56, "status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"id": 56, "status": "processing"},
    )
    monkeypatch.setattr(router, "mark_answered", lambda update_id: None)
    monkeypatch.setattr(engine, "load_default_profile", fake_memory_profile)
    monkeypatch.setattr(router, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        router,
        "get_user_by_telegram_id",
        lambda telegram_id: {"id": 777, "username": "ada"},
    )
    monkeypatch.setattr(
        router,
        "memory_backend_for_profile",
        lambda profile: memory_backend,
    )

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        events.append("answer")
        return "done"

    async def compact_turn(**kwargs: object) -> None:
        del kwargs
        assert lease.released is True
        events.append("compact")

    monkeypatch.setattr(engine, "answer", answer)
    monkeypatch.setattr(router, "_compact_successful_turn", compact_turn)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == ["done"]
    assert events == ["acquire", "answer", "release", "compact"]


@pytest.mark.asyncio
async def test_request_state_is_cleared_after_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    state = UserRequestState()
    monkeypatch.setattr(router, "request_state", state)
    update = fake_update(update_id=4004)
    failed: list[tuple[int, str]] = []

    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(router, "mark_queued", lambda update_id: {"status": "queued"})
    monkeypatch.setattr(
        router,
        "mark_processing",
        lambda update_id: {"status": "processing"},
    )
    monkeypatch.setattr(
        router,
        "mark_failed",
        lambda update_id, reason: failed.append((update_id, reason)),
    )
    monkeypatch.setattr(engine, "load_default_profile", fake_profile)

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, msg, profile, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert failed == [(4004, "RuntimeError")]
    assert await state.active_for_user(123) is None


@pytest.mark.asyncio
async def test_message_above_max_length_is_ignored_before_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize_user(monkeypatch)
    update = fake_update(update_id=5005, text="too long")
    marked_ignored: list[int] = []
    answered: list[str] = []

    monkeypatch.setattr(
        router,
        "abuse_limiter",
        AbuseLimiter(lambda: make_settings(max_message_chars=3)),
    )
    monkeypatch.setattr(
        router,
        "persist_update",
        lambda update: {"status": "persisted"},
    )
    monkeypatch.setattr(
        router,
        "mark_ignored",
        lambda update_id: marked_ignored.append(update_id),
    )

    async def answer(
        user: str,
        msg: str,
        profile: BotProfile | None = None,
        **kwargs: object,
    ) -> str:
        del user, profile, kwargs
        answered.append(msg)
        return "should not happen"

    monkeypatch.setattr(engine, "answer", answer)

    await router.ask_ia(cast(Any, update), cast(Any, SimpleNamespace(bot=FakeBot())))

    assert update.message.replies == [MESSAGE_TOO_LONG_MESSAGE]
    assert marked_ignored == [5005]
    assert answered == []
