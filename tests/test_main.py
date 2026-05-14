from pathlib import Path


def test_runtime_processes_updates_concurrently() -> None:
    main_source = Path("src/forge_bot/main.py").read_text(encoding="utf-8")

    assert "MAX_CONCURRENT_UPDATES = 8" in main_source
    assert ".concurrent_updates(MAX_CONCURRENT_UPDATES)" in main_source
