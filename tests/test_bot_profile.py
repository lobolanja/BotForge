import json
from pathlib import Path

import pytest

from forge_bot.bot_profile import BotProfileError, load_active_bot_profile
from forge_bot.prompting import assemble_prompt_messages


def write_profile(
    root: Path,
    profile_id: str = "nutrition_dev",
    overrides: dict[str, object] | None = None,
) -> Path:
    """Create a temporary profile folder for profile-loading tests."""
    profile_dir = root / "bot_profiles" / profile_id
    profile_dir.mkdir(parents=True)
    (profile_dir / "system_prompt.md").write_text(
        "You are a nutrition assistant.",
        encoding="utf-8",
    )

    data: dict[str, object] = {
        "bot_profile_id": profile_id,
        "bot_display_name": "Nutrition Dev",
        "bot_description": "Development nutrition assistant.",
        "system_prompt_file": "system_prompt.md",
        "domain_rules": ["Avoid medical diagnosis.", "Prefer practical guidance."],
        "disclaimer_text": "For education only.",
        "default_language": "en",
        "llm_provider": "ollama",
        "llm_model": "gemma2:2b",
        "memory_enabled": False,
        "analytics_enabled": False,
    }
    if overrides:
        data.update(overrides)

    (profile_dir / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    return profile_dir


def test_load_default_bot_profile_successfully() -> None:
    profile = load_active_bot_profile("default_dev", "bot_profiles")

    assert profile.bot_profile_id == "default_dev"
    assert profile.system_prompt.startswith("You are the default BotForge")
    assert profile.llm_provider == "ollama"


def test_fail_when_selected_profile_is_missing(tmp_path: Path) -> None:
    with pytest.raises(BotProfileError, match="was not found"):
        load_active_bot_profile(
            "missing",
            "bot_profiles",
            base_path=tmp_path,
        )


def test_fail_when_required_profile_field_is_empty(tmp_path: Path) -> None:
    write_profile(tmp_path, overrides={"bot_display_name": ""})

    with pytest.raises(BotProfileError, match="bot_display_name"):
        load_active_bot_profile(
            "nutrition_dev",
            "bot_profiles",
            base_path=tmp_path,
        )


def test_prompt_assembly_includes_system_prompt_before_user_message(
    tmp_path: Path,
) -> None:
    write_profile(tmp_path)
    profile = load_active_bot_profile(
        "nutrition_dev",
        "bot_profiles",
        base_path=tmp_path,
    )

    messages = assemble_prompt_messages(
        profile,
        current_user_message="What should I eat after training?",
        user_display_name="Alex",
        compacted_user_memory="Prefers vegetarian meals.",
        recent_conversation_messages=[
            {"role": "assistant", "content": "How can I help today?"}
        ],
        runtime_safety_instructions=["Escalate emergency symptoms."],
    )

    assert messages[0]["role"] == "system"
    assert "You are a nutrition assistant." in messages[0]["content"]
    assert "Avoid medical diagnosis." in messages[0]["content"]
    assert messages[1]["content"] == "Compacted user memory:\nPrefers vegetarian meals."
    assert messages[2] == {"role": "assistant", "content": "How can I help today?"}
    assert messages[-1] == {
        "role": "user",
        "content": "Alex says: What should I eat after training?",
    }


def test_changing_profile_changes_prompt_without_code_changes(tmp_path: Path) -> None:
    write_profile(tmp_path, profile_id="nutrition_dev")
    write_profile(
        tmp_path,
        profile_id="finance_dev",
        overrides={
            "bot_display_name": "Finance Dev",
            "bot_description": "Development finance assistant.",
            "domain_rules": ["Do not provide personalized investment advice."],
        },
    )
    finance_prompt = tmp_path / "bot_profiles" / "finance_dev" / "system_prompt.md"
    finance_prompt.write_text("You are a finance assistant.", encoding="utf-8")

    nutrition = load_active_bot_profile(
        "nutrition_dev",
        "bot_profiles",
        base_path=tmp_path,
    )
    finance = load_active_bot_profile(
        "finance_dev",
        "bot_profiles",
        base_path=tmp_path,
    )

    assert nutrition.system_prompt == "You are a nutrition assistant."
    assert finance.system_prompt == "You are a finance assistant."
