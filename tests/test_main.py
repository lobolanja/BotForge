from pathlib import Path
from types import SimpleNamespace

import pytest

from forge_bot import main
from forge_bot.message_store import QueuedInboundMessage


def test_runtime_processes_updates_concurrently() -> None:
    main_source = Path("src/forge_bot/main.py").read_text(encoding="utf-8")

    assert "MAX_CONCURRENT_UPDATES = 8" in main_source
    assert ".concurrent_updates(MAX_CONCURRENT_UPDATES)" in main_source
    assert ".post_init(recover_and_drain_queued_messages)" in main_source


def test_document_uploads_can_continue_set_plan_without_caption() -> None:
    main_source = Path("src/forge_bot/main.py").read_text(encoding="utf-8")
    document_handler = "MessageHandler(\n            filters.Document.ALL,"

    assert document_handler in main_source
    assert "filters.CaptionRegex" not in main_source


@pytest.mark.asyncio
async def test_startup_drain_replays_recoverable_queued_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed_updates: list[object] = []
    failed_updates: list[tuple[int, str]] = []
    raw_update = {"update_id": 42}
    telegram_update = object()

    async def process_update(update: object) -> None:
        processed_updates.append(update)

    application = SimpleNamespace(
        bot=object(),
        process_update=process_update,
    )

    monkeypatch.setattr(main, "fail_unrecoverable_queued_messages", lambda reason: 1)
    monkeypatch.setattr(
        main,
        "list_recoverable_queued_messages",
        lambda *, limit: [
            QueuedInboundMessage(telegram_update_id=42, raw_update=raw_update)
        ],
    )
    monkeypatch.setattr(
        main.Update,
        "de_json",
        lambda data, bot: telegram_update,
    )
    monkeypatch.setattr(
        main,
        "fail_queued_message",
        lambda update_id, reason: failed_updates.append((update_id, reason)),
    )

    summary = await main.drain_recovered_queued_messages(application)

    assert summary.replayed == 1
    assert summary.failed_unrecoverable == 1
    assert summary.failed_replay == 0
    assert processed_updates == [telegram_update]
    assert failed_updates == [(42, "Startup recovery did not claim queued message")]


@pytest.mark.asyncio
async def test_startup_drain_fails_replay_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_updates: list[tuple[int, str]] = []

    monkeypatch.setattr(main, "fail_unrecoverable_queued_messages", lambda reason: 0)
    monkeypatch.setattr(
        main,
        "list_recoverable_queued_messages",
        lambda *, limit: [
            QueuedInboundMessage(telegram_update_id=43, raw_update={"update_id": 43})
        ],
    )
    monkeypatch.setattr(
        main.Update,
        "de_json",
        lambda data, bot: (_ for _ in ()).throw(ValueError("bad update")),
    )
    monkeypatch.setattr(
        main,
        "mark_failed",
        lambda update_id, reason: failed_updates.append((update_id, reason)),
    )

    summary = await main.drain_recovered_queued_messages(SimpleNamespace(bot=object()))

    assert summary.replayed == 0
    assert summary.failed_replay == 1
    assert failed_updates == [(43, "Startup recovery replay failed")]
