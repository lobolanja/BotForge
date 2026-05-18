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


@pytest.mark.asyncio
async def test_processing_start_can_be_moved_after_queue_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge_bot import request_state

    initial_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    after_global_queue = initial_now + timedelta(seconds=12)
    received_at = initial_now - timedelta(seconds=5)
    times = iter([initial_now, after_global_queue])

    monkeypatch.setattr(request_state, "_utc_now", lambda: next(times))

    state = UserRequestState()
    active = await state.try_start(
        user_id=123,
        chat_id=456,
        received_at=received_at,
        provider="ollama",
    )

    assert active is not None
    assert active.queue_wait_seconds == 5

    updated = await state.mark_processing_started(
        user_id=123,
        request_id=active.request_id,
    )

    assert updated is not None
    assert updated.queue_wait_seconds == 17
