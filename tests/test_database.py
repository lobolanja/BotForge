from typing import Any

from forge_bot.database import clear_memory_for_telegram_user


class FakeCursor:
    def __init__(self) -> None:
        self.rowcount = 0
        self.statements: list[str] = []
        self._fetchone_queue: list[dict[str, Any] | None] = [{"id": 7, "role": "user"}]

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[Any, ...]) -> None:
        del params
        normalized = " ".join(statement.split())
        self.statements.append(normalized)
        if "SELECT id, role FROM users" in normalized:
            self.rowcount = 1
        elif "DELETE FROM conversation_messages" in normalized:
            self.rowcount = 3
        elif "DELETE FROM langchain_chat_history" in normalized:
            self.rowcount = 5
        elif "DELETE FROM langchain_chat_sessions" in normalized:
            self.rowcount = 2
        elif "DELETE FROM nutrition_daily_logs" in normalized:
            self.rowcount = 2
        elif "DELETE FROM user_memory_summaries" in normalized:
            self.rowcount = 1
        elif "UPDATE inbound_messages" in normalized:
            self.rowcount = 4
        else:
            self.rowcount = 0

    def fetchone(self) -> dict[str, Any] | None:
        return self._fetchone_queue.pop(0)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_memory_clear_also_scrubs_answered_inbound_bootstrap(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    cache_clears: list[int] = []

    monkeypatch.setattr("forge_bot.database.conect_db", lambda: connection)
    monkeypatch.setattr(
        "forge_bot.memory_store.clear_cached_user_memory",
        lambda *, user_id, bot_profile_id=None: cache_clears.append(user_id),
    )

    result = clear_memory_for_telegram_user(telegram_id=456)

    assert result is not None
    assert result.conversation_memory == 10
    assert result.compacted_memory == 1
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert cache_clears == [7]
    assert any(
        "UPDATE inbound_messages SET text = NULL, raw_update = NULL" in statement
        and "status = 'answered'" in statement
        and "message_type = 'text'" in statement
        for statement in connection.cursor_obj.statements
    )
    assert any(
        "DELETE FROM langchain_chat_history WHERE session_id IN" in statement
        for statement in connection.cursor_obj.statements
    )
    assert any(
        "DELETE FROM langchain_chat_sessions WHERE user_id = %s" in statement
        for statement in connection.cursor_obj.statements
    )
    assert any(
        "DELETE FROM nutrition_daily_logs WHERE user_id = %s" in statement
        for statement in connection.cursor_obj.statements
    )
