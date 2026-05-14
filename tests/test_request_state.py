from datetime import datetime, timedelta, timezone

import pytest

from forge_bot.request_state import UserRequestState


@pytest.mark.asyncio
async def test_active_request_registration_rejects_second_request() -> None:
    state = UserRequestState()
    received_at = datetime.now(timezone.utc) - timedelta(seconds=2)

    first = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=received_at,
        provider="ollama",
    )
    second = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=datetime.now(timezone.utc),
        provider="ollama",
    )

    assert first is not None
    assert second is None
    assert first.queue_wait_seconds >= 0


@pytest.mark.asyncio
async def test_active_request_cleanup_after_finish() -> None:
    state = UserRequestState()
    active = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=datetime.now(timezone.utc),
        provider="ollama",
    )

    assert active is not None

    finished = await state.finish(
        user_id=123,
        request_id=active.request_id,
        status="answered",
    )
    next_request = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=datetime.now(timezone.utc),
        provider="ollama",
    )

    assert finished is not None
    assert finished.status == "answered"
    assert finished.processing_seconds >= 0
    assert next_request is not None


@pytest.mark.asyncio
async def test_active_request_cleanup_after_exception_status() -> None:
    state = UserRequestState()
    active = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=datetime.now(timezone.utc),
        provider="ollama",
    )

    assert active is not None

    finished = await state.finish(
        user_id=123,
        request_id=active.request_id,
        status="failed",
    )
    active_after_failure = await state.active_for_user(123)

    assert finished is not None
    assert finished.status == "failed"
    assert active_after_failure is None
