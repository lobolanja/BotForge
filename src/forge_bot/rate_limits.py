import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings, get_settings

logger = logging.getLogger(__name__)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)

TOO_MANY_MESSAGES_MESSAGE = (
    "You are sending messages too quickly. Please wait a moment and try again."
)
MESSAGE_TOO_LONG_MESSAGE = (
    "Your message is too long to process well. Please split it into smaller parts."
)
TOO_MANY_AI_REQUESTS_MESSAGE = (
    "You have reached the AI message limit for now. Please wait and try again later."
)
BOT_BUSY_MESSAGE = (
    "I am processing too many requests right now. Please wait a moment and try again."
)
ADMIN_INVITE_RATE_LIMIT_MESSAGE = (
    "Invite creation is temporarily limited. Please wait a moment before "
    "creating another link."
)


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    limit_name: str = ""
    message: str = ""


class AiRequestLease:
    def __init__(self, limiter: "AbuseLimiter") -> None:
        self._limiter = limiter
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._limiter.release_ai_request()


class AbuseLimiter:
    """In-memory abuse prevention for the private beta runtime."""

    def __init__(
        self,
        settings_provider: Callable[[], Settings] = get_settings,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._now = now or _utc_now
        self._user_messages: dict[int, deque[datetime]] = defaultdict(deque)
        self._chat_messages: dict[int, deque[datetime]] = defaultdict(deque)
        self._user_ai_requests: dict[int, deque[datetime]] = defaultdict(deque)
        self._admin_invites: dict[int, deque[datetime]] = defaultdict(deque)
        self._active_ai_requests = 0
        self._queued_ai_requests = 0
        self._condition = asyncio.Condition()

    def check_message_length(
        self, *, user_id: int, chat_id: int, text: str
    ) -> LimitDecision:
        settings = self._settings_provider()
        if len(text) <= settings.max_message_chars:
            return LimitDecision(True)

        return self._reject(
            "max_message_chars",
            user_id=user_id,
            chat_id=chat_id,
            message=MESSAGE_TOO_LONG_MESSAGE,
            metadata={"message_chars": len(text), "limit": settings.max_message_chars},
        )

    def check_message_rate(self, *, user_id: int, chat_id: int) -> LimitDecision:
        settings = self._settings_provider()
        for events, limit, name in (
            (
                self._user_messages[user_id],
                settings.user_messages_per_minute,
                "user_messages_per_minute",
            ),
            (
                self._chat_messages[chat_id],
                settings.chat_messages_per_minute,
                "chat_messages_per_minute",
            ),
        ):
            decision = self._check_window(
                events,
                limit=limit,
                window=MINUTE,
                limit_name=name,
                user_id=user_id,
                chat_id=chat_id,
                message=TOO_MANY_MESSAGES_MESSAGE,
            )
            if not decision.allowed:
                return decision
        return LimitDecision(True)

    def check_user_ai_request(self, *, user_id: int, chat_id: int) -> LimitDecision:
        settings = self._settings_provider()
        return self._check_window(
            self._user_ai_requests[user_id],
            limit=settings.user_ai_requests_per_hour,
            window=HOUR,
            limit_name="user_ai_requests_per_hour",
            user_id=user_id,
            chat_id=chat_id,
            message=TOO_MANY_AI_REQUESTS_MESSAGE,
        )

    async def acquire_ai_request(
        self,
        *,
        user_id: int,
        chat_id: int,
    ) -> AiRequestLease | LimitDecision:
        settings = self._settings_provider()
        async with self._condition:
            if self._active_ai_requests >= settings.global_active_ai_requests:
                if self._queued_ai_requests >= settings.global_ai_queue_size:
                    return self._reject(
                        "global_ai_queue_size",
                        user_id=user_id,
                        chat_id=chat_id,
                        message=BOT_BUSY_MESSAGE,
                        metadata={
                            "active": self._active_ai_requests,
                            "queued": self._queued_ai_requests,
                        },
                    )

                self._queued_ai_requests += 1
                try:
                    while (
                        self._active_ai_requests >= settings.global_active_ai_requests
                    ):
                        await self._condition.wait()
                finally:
                    self._queued_ai_requests -= 1

            self._active_ai_requests += 1
            return AiRequestLease(self)

    async def release_ai_request(self) -> None:
        async with self._condition:
            self._active_ai_requests = max(0, self._active_ai_requests - 1)
            self._condition.notify()

    def check_admin_invite(self, *, user_id: int, chat_id: int) -> LimitDecision:
        settings = self._settings_provider()
        return self._check_window(
            self._admin_invites[user_id],
            limit=settings.admin_invites_per_hour,
            window=HOUR,
            limit_name="admin_invites_per_hour",
            user_id=user_id,
            chat_id=chat_id,
            message=ADMIN_INVITE_RATE_LIMIT_MESSAGE,
        )

    def _check_window(
        self,
        events: deque[datetime],
        *,
        limit: int,
        window: timedelta,
        limit_name: str,
        user_id: int,
        chat_id: int,
        message: str,
    ) -> LimitDecision:
        if self._record_window(events, limit=limit, window=window, now=self._now()):
            return LimitDecision(True)
        return self._reject(
            limit_name, user_id=user_id, chat_id=chat_id, message=message
        )

    def _reject(
        self,
        limit_name: str,
        *,
        user_id: int,
        chat_id: int,
        message: str,
        metadata: dict[str, int] | None = None,
    ) -> LimitDecision:
        logger.warning(
            "abuse_limit_exceeded limit_name=%s user_id=%s chat_id=%s "
            "timestamp=%s metadata=%s",
            limit_name,
            user_id,
            chat_id,
            self._now().isoformat(),
            metadata or {},
        )
        return LimitDecision(False, limit_name, message)

    @staticmethod
    def _record_window(
        events: deque[datetime],
        *,
        limit: int,
        window: timedelta,
        now: datetime,
    ) -> bool:
        cutoff = now - window
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


abuse_limiter = AbuseLimiter()
