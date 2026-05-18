import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

REQUEST_WAITING_MESSAGE = (
    "I am still processing your previous message. "
    "I will be able to continue once it finishes."
)


@dataclass(frozen=True)
class ActiveUserRequest:
    user_id: int
    chat_id: int
    request_id: str
    received_at: datetime
    processing_started_at: datetime
    provider: str

    @property
    def queue_wait_seconds(self) -> float:
        return max(
            0.0,
            (self.processing_started_at - self.received_at).total_seconds(),
        )


@dataclass(frozen=True)
class FinishedUserRequest:
    user_id: int
    chat_id: int
    request_id: str
    received_at: datetime
    processing_started_at: datetime
    processing_finished_at: datetime
    queue_wait_seconds: float
    processing_seconds: float
    status: str
    provider: str


class UserRequestState:
    """Track one in-flight AI request per Telegram user in process memory."""

    def __init__(self) -> None:
        self._active: dict[int, ActiveUserRequest] = {}
        self._lock = asyncio.Lock()

    async def try_start(
        self,
        *,
        user_id: int,
        chat_id: int,
        received_at: datetime | None,
        provider: str,
    ) -> ActiveUserRequest | None:
        async with self._lock:
            if user_id in self._active:
                active_request = self._active[user_id]
                logger.info(
                    "user_request_already_active user_id=%s chat_id=%s "
                    "request_id=%s active_request_id=%s status=already_active",
                    user_id,
                    chat_id,
                    str(uuid4()),
                    active_request.request_id,
                )
                return None

            now = _utc_now()
            request = ActiveUserRequest(
                user_id=user_id,
                chat_id=chat_id,
                request_id=str(uuid4()),
                received_at=_normalize_datetime(received_at, fallback=now),
                processing_started_at=now,
                provider=provider,
            )
            self._active[user_id] = request

        logger.info(
            "user_request_started user_id=%s chat_id=%s request_id=%s "
            "received_at=%s processing_started_at=%s queue_wait_seconds=%.6f "
            "status=processing provider=%s",
            request.user_id,
            request.chat_id,
            request.request_id,
            request.received_at.isoformat(),
            request.processing_started_at.isoformat(),
            request.queue_wait_seconds,
            request.provider,
        )
        return request

    async def finish(
        self,
        *,
        user_id: int,
        request_id: str,
        status: str,
    ) -> FinishedUserRequest | None:
        async with self._lock:
            request = self._active.get(user_id)
            if request is None or request.request_id != request_id:
                return None
            del self._active[user_id]

        finished_at = _utc_now()
        finished = FinishedUserRequest(
            user_id=request.user_id,
            chat_id=request.chat_id,
            request_id=request.request_id,
            received_at=request.received_at,
            processing_started_at=request.processing_started_at,
            processing_finished_at=finished_at,
            queue_wait_seconds=request.queue_wait_seconds,
            processing_seconds=max(
                0.0,
                (finished_at - request.processing_started_at).total_seconds(),
            ),
            status=status,
            provider=request.provider,
        )
        logger.info(
            "user_request_finished user_id=%s chat_id=%s request_id=%s "
            "received_at=%s processing_started_at=%s processing_finished_at=%s "
            "queue_wait_seconds=%.6f processing_seconds=%.6f status=%s "
            "provider=%s",
            finished.user_id,
            finished.chat_id,
            finished.request_id,
            finished.received_at.isoformat(),
            finished.processing_started_at.isoformat(),
            finished.processing_finished_at.isoformat(),
            finished.queue_wait_seconds,
            finished.processing_seconds,
            finished.status,
            finished.provider,
        )
        return finished

    async def mark_processing_started(
        self,
        *,
        user_id: int,
        request_id: str,
    ) -> ActiveUserRequest | None:
        async with self._lock:
            request = self._active.get(user_id)
            if request is None or request.request_id != request_id:
                return None

            updated = replace(request, processing_started_at=_utc_now())
            self._active[user_id] = updated

        logger.info(
            "user_request_processing_started user_id=%s chat_id=%s request_id=%s "
            "received_at=%s processing_started_at=%s queue_wait_seconds=%.6f "
            "provider=%s",
            updated.user_id,
            updated.chat_id,
            updated.request_id,
            updated.received_at.isoformat(),
            updated.processing_started_at.isoformat(),
            updated.queue_wait_seconds,
            updated.provider,
        )
        return updated

    async def active_for_user(self, user_id: int) -> ActiveUserRequest | None:
        async with self._lock:
            return self._active.get(user_id)


request_state = UserRequestState()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime | None, *, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
