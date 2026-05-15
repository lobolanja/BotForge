import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from helpers import make_settings

from forge_bot.rate_limits import (
    ADMIN_INVITE_RATE_LIMIT_MESSAGE,
    BOT_BUSY_MESSAGE,
    MESSAGE_TOO_LONG_MESSAGE,
    TOO_MANY_MESSAGES_MESSAGE,
    AbuseLimiter,
    AiRequestLease,
)


class Clock:
    now = datetime(2026, 5, 15, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def test_user_below_and_above_message_limit() -> None:
    clock = Clock()
    limiter = AbuseLimiter(
        lambda: make_settings(user_messages_per_minute=2),
        now=clock,
    )

    assert limiter.check_message_rate(user_id=1, chat_id=10).allowed
    assert limiter.check_message_rate(user_id=1, chat_id=10).allowed
    over_limit = limiter.check_message_rate(user_id=1, chat_id=10)

    assert not over_limit.allowed
    assert over_limit.message == TOO_MANY_MESSAGES_MESSAGE

    clock.advance(timedelta(minutes=1, seconds=1))
    assert limiter.check_message_rate(user_id=1, chat_id=10).allowed


def test_message_above_max_length_is_rejected(caplog: pytest.LogCaptureFixture) -> None:
    limiter = AbuseLimiter(lambda: make_settings(max_message_chars=5))

    decision = limiter.check_message_length(user_id=1, chat_id=10, text="too long")

    assert not decision.allowed
    assert decision.message == MESSAGE_TOO_LONG_MESSAGE
    assert "too long" not in caplog.text


def test_admin_invite_command_respects_hourly_limit() -> None:
    limiter = AbuseLimiter(lambda: make_settings(admin_invites_per_hour=1))

    assert limiter.check_admin_invite(user_id=1, chat_id=10).allowed
    over_limit = limiter.check_admin_invite(user_id=1, chat_id=10)

    assert not over_limit.allowed
    assert over_limit.message == ADMIN_INVITE_RATE_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_global_active_request_limit_prevents_overload() -> None:
    limiter = AbuseLimiter(
        lambda: make_settings(global_active_ai_requests=1, global_ai_queue_size=0)
    )

    first = await limiter.acquire_ai_request(user_id=1, chat_id=10)
    assert isinstance(first, AiRequestLease)

    second = await limiter.acquire_ai_request(user_id=2, chat_id=10)

    assert not second.allowed
    assert second.message == BOT_BUSY_MESSAGE
    await first.release()


@pytest.mark.asyncio
async def test_global_ai_queue_waits_for_capacity() -> None:
    limiter = AbuseLimiter(
        lambda: make_settings(global_active_ai_requests=1, global_ai_queue_size=1)
    )
    first = await limiter.acquire_ai_request(user_id=1, chat_id=10)
    assert isinstance(first, AiRequestLease)

    waiter = asyncio.create_task(limiter.acquire_ai_request(user_id=2, chat_id=10))
    await asyncio.sleep(0)
    assert not waiter.done()

    await first.release()
    second = await waiter

    assert isinstance(second, AiRequestLease)
    await second.release()
