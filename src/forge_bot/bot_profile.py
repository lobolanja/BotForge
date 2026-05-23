from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROFILE_FILE_NAME = "profile.json"
MAX_CONTEXT_DOCUMENT_CHARS = 120_000


class BotProfileError(RuntimeError):
    """Raised when a bot profile cannot be loaded or validated."""


@dataclass(frozen=True)
class BotProfileContextDocument:
    """Read-only context bundled with one bot profile."""

    name: str
    content: str


@dataclass(frozen=True)
class BotProfile:
    """Domain-specific configuration for one deployable bot.

    Generic BotForge code uses this object to understand the bot identity,
    prompt, model choice, and feature flags without hardcoding domain behavior.
    """

    bot_profile_id: str
    bot_display_name: str
    bot_description: str
    system_prompt: str
    domain_rules: tuple[str, ...]
    disclaimer_text: str
    default_language: str
    llm_provider: str
    llm_model: str
    memory_enabled: bool
    analytics_enabled: bool
    context_documents: tuple[BotProfileContextDocument, ...] = ()


def load_active_bot_profile(
    profile_id: str,
    profiles_dir: str | Path,
    base_path: Path | None = None,
) -> BotProfile:
    """Load the profile selected by application settings.

    Args:
        profile_id: Name of the active profile folder.
        profiles_dir: Directory that contains all profile folders.
        base_path: Optional project root for tests or non-standard runtimes.

    Returns:
        A validated bot profile ready to use for prompt assembly.
    """
    return load_bot_profile(profile_id, Path(profiles_dir), base_path=base_path)


def load_bot_profile(
    profile_id: str,
    profiles_dir: Path,
    base_path: Path | None = None,
) -> BotProfile:
    """Load and validate one bot profile from disk.

    The expected layout is:
        bot_profiles/<profile_id>/profile.json
        bot_profiles/<profile_id>/system_prompt.md
    """
    cleaned_profile_id = profile_id.strip()
    if not cleaned_profile_id:
        raise BotProfileError("BOT_PROFILE must not be empty.")

    root = base_path or Path.cwd()
    profile_root = _resolve_path(profiles_dir, root) / cleaned_profile_id
    profile_file = profile_root / PROFILE_FILE_NAME

    if not profile_file.is_file():
        raise BotProfileError(
            f"Bot profile '{cleaned_profile_id}' was not found at {profile_file}."
        )

    data = _read_profile_json(profile_file, cleaned_profile_id)
    loaded_id = _required_text(data, "bot_profile_id")
    if loaded_id != cleaned_profile_id:
        raise BotProfileError(
            "Bot profile id mismatch: "
            f"expected '{cleaned_profile_id}', got '{loaded_id}'."
        )

    return BotProfile(
        bot_profile_id=loaded_id,
        bot_display_name=_required_text(data, "bot_display_name"),
        bot_description=_required_text(data, "bot_description"),
        system_prompt=_load_system_prompt(data, profile_root, cleaned_profile_id),
        domain_rules=_required_rules(data),
        disclaimer_text=_required_text(data, "disclaimer_text"),
        default_language=_required_text(data, "default_language"),
        llm_provider=_required_text(data, "llm_provider"),
        llm_model=_required_text(data, "llm_model"),
        memory_enabled=_required_bool(data, "memory_enabled"),
        analytics_enabled=_required_bool(data, "analytics_enabled"),
        context_documents=_load_context_documents(data, profile_root),
    )


def _resolve_path(path: Path, base_path: Path) -> Path:
    """Resolve relative profile directories from the project root."""
    return path if path.is_absolute() else base_path / path


def _read_profile_json(profile_file: Path, profile_id: str) -> Mapping[str, Any]:
    """Read the JSON profile file and ensure it is an object."""
    try:
        data = json.loads(profile_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BotProfileError(f"Bot profile '{profile_id}' is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise BotProfileError(f"Bot profile '{profile_id}' must be a JSON object.")
    return data


def _required_text(data: Mapping[str, Any], field: str) -> str:
    """Return a required string field after trimming whitespace."""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BotProfileError(
            f"Bot profile field '{field}' must be a non-empty string."
        )
    return value.strip()


def _required_bool(data: Mapping[str, Any], field: str) -> bool:
    """Return a required boolean field."""
    value = data.get(field)
    if not isinstance(value, bool):
        raise BotProfileError(f"Bot profile field '{field}' must be a boolean.")
    return value


def _required_rules(data: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate and return the ordered domain rules for the profile."""
    value = data.get("domain_rules")
    if not isinstance(value, list) or not value:
        raise BotProfileError(
            "Bot profile field 'domain_rules' must be a non-empty list."
        )

    rules: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise BotProfileError(
                "Bot profile field 'domain_rules' must contain only non-empty "
                f"strings; item {index} is invalid."
            )
        rules.append(item.strip())
    return tuple(rules)


def _load_system_prompt(
    data: Mapping[str, Any],
    profile_root: Path,
    profile_id: str,
) -> str:
    """Load the main system prompt from inline JSON or a Markdown file."""
    inline_prompt = data.get("system_prompt")
    prompt_file = data.get("system_prompt_file")

    if isinstance(inline_prompt, str) and inline_prompt.strip():
        return inline_prompt.strip()

    if not isinstance(prompt_file, str) or not prompt_file.strip():
        raise BotProfileError(
            "Bot profile must define either 'system_prompt' or 'system_prompt_file'."
        )

    prompt_path = profile_root / prompt_file
    if not prompt_path.is_file():
        raise BotProfileError(
            f"System prompt file for bot profile '{profile_id}' was not found at "
            f"{prompt_path}."
        )

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise BotProfileError(
            f"System prompt file for bot profile '{profile_id}' must not be empty."
        )
    return prompt


def _load_context_documents(
    data: Mapping[str, Any],
    profile_root: Path,
) -> tuple[BotProfileContextDocument, ...]:
    """Load optional profile context files declared in profile.json."""
    value = data.get("context_files", [])
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BotProfileError(
            "Bot profile field 'context_files' must be a list of relative paths."
        )

    documents: list[BotProfileContextDocument] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise BotProfileError(
                "Bot profile field 'context_files' must contain only non-empty "
                f"strings; item {index} is invalid."
            )
        context_path = _resolve_profile_file(profile_root, item.strip())
        if not context_path.is_file():
            raise BotProfileError(
                f"Bot profile context file was not found at {context_path}."
            )

        content = context_path.read_text(encoding="utf-8").strip()
        if not content:
            raise BotProfileError(
                f"Bot profile context file '{item.strip()}' must not be empty."
            )
        if len(content) > MAX_CONTEXT_DOCUMENT_CHARS:
            raise BotProfileError(
                f"Bot profile context file '{item.strip()}' is too large "
                f"({len(content)} chars; max {MAX_CONTEXT_DOCUMENT_CHARS})."
            )
        documents.append(
            BotProfileContextDocument(name=item.strip(), content=content)
        )
    return tuple(documents)


def _resolve_profile_file(profile_root: Path, relative_path: str) -> Path:
    """Resolve a profile file while preventing accidental path traversal."""
    path = Path(relative_path)
    if path.is_absolute():
        raise BotProfileError("Bot profile context files must use relative paths.")

    profile_root_resolved = profile_root.resolve()
    resolved = (profile_root / path).resolve()
    if resolved != profile_root_resolved and profile_root_resolved not in (
        resolved.parents
    ):
        raise BotProfileError(
            "Bot profile context files must stay inside the profile folder."
        )
    return resolved
