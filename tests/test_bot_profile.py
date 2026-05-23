import json
from pathlib import Path

import pytest

from forge_bot.bot_profile import (
    MAX_CONTEXT_DOCUMENT_CHARS,
    BotProfileError,
    load_active_bot_profile,
)
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
    assert profile.system_prompt.startswith(
        "You are an AI assistant integrated into Telegram."
    )
    assert "Do not reveal internal reasoning" in profile.system_prompt
    assert profile.llm_provider == "ollama"


def test_load_nutrition_bot_profile_successfully() -> None:
    profile = load_active_bot_profile("nutrition", "bot_profiles")

    assert profile.bot_profile_id == "nutrition"
    assert profile.bot_display_name == "Bot Nutricionista"
    assert profile.default_language == "es"
    assert profile.llm_provider == "nvidia"
    assert profile.llm_model == "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    assert profile.memory_enabled is True
    assert profile.context_documents == ()
    assert profile.nutrition_plan_path is not None
    assert profile.nutrition_plan_path.name == "demo_plan.json"
    assert "no finjas que lo hay" in profile.system_prompt
    assert "No diagnostiques" in profile.system_prompt
    assert any("no inventes dietas" in rule for rule in profile.domain_rules)


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


def test_fail_when_context_file_is_missing(tmp_path: Path) -> None:
    write_profile(tmp_path, overrides={"context_files": ["missing.json"]})

    with pytest.raises(BotProfileError, match="context file was not found"):
        load_active_bot_profile(
            "nutrition_dev",
            "bot_profiles",
            base_path=tmp_path,
        )


def test_fail_when_context_file_leaves_profile_folder(tmp_path: Path) -> None:
    write_profile(tmp_path, overrides={"context_files": ["../outside.json"]})
    (tmp_path / "bot_profiles" / "outside.json").write_text("{}", encoding="utf-8")

    with pytest.raises(BotProfileError, match="inside the profile folder"):
        load_active_bot_profile(
            "nutrition_dev",
            "bot_profiles",
            base_path=tmp_path,
        )


def test_fail_when_context_file_is_too_large(tmp_path: Path) -> None:
    profile_dir = write_profile(tmp_path, overrides={"context_files": ["large.txt"]})
    (profile_dir / "large.txt").write_text(
        "x" * (MAX_CONTEXT_DOCUMENT_CHARS + 1),
        encoding="utf-8",
    )

    with pytest.raises(BotProfileError, match="too large"):
        load_active_bot_profile(
            "nutrition_dev",
            "bot_profiles",
            base_path=tmp_path,
        )


def test_fail_when_nutrition_plan_file_is_missing(tmp_path: Path) -> None:
    write_profile(tmp_path, overrides={"nutrition_plan_file": "missing.json"})

    with pytest.raises(BotProfileError, match="nutrition_plan_file"):
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
    assert "Available conversation context" in messages[0]["content"]
    assert "Do not say you have no memory" in messages[0]["content"]
    assert "Compacted memory:\nPrefers vegetarian meals." in messages[0]["content"]
    assert (
        "Recent conversation:\nassistant: How can I help today?"
        in messages[0]["content"]
    )
    assert messages[-1] == {
        "role": "user",
        "content": "What should I eat after training?",
    }


def test_nutrition_profile_prompt_assembly_includes_guardrails() -> None:
    profile = load_active_bot_profile("nutrition", "bot_profiles")

    messages = assemble_prompt_messages(
        profile,
        current_user_message="Hoy tengo crossfit, que como al mediodia?",
        compacted_user_memory="El usuario prefiere cenas sencillas.",
    )

    system_message = messages[0]["content"]
    assert "Eres un bot nutricionista conversacional" in system_message
    assert "Las cantidades, opciones y ajustes concretos deben salir del plan" in (
        system_message
    )
    assert "No muestres macros, calorias ni calculos detallados" in system_message
    assert "Disclaimer: Este bot ayuda a interpretar un plan nutricional" in (
        system_message
    )
    assert "Profile context documents:" not in system_message
    assert "Document: demo_plan.json" not in system_message
    assert '"crossfit"' not in system_message
    assert '"comida_2"' not in system_message
    assert "El usuario prefiere cenas sencillas." in messages[0]["content"]


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
