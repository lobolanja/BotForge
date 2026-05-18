from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from helpers import make_settings

from forge_bot import engine, router
from forge_bot import request_state as request_state_module
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

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))


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
