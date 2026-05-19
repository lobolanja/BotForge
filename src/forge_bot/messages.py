"""Helpers for short, scannable Telegram bot messages."""

from collections.abc import Sequence


def build_message(
    summary: str,
    *,
    details: Sequence[tuple[str, str]] = (),
    link: str | None = None,
    link_label: str = "Link",
    actions: Sequence[str] = (),
) -> str:
    """Build a plain-text Telegram message with consistent spacing."""
    sections = [summary]

    if details:
        sections.append("\n".join(f"{label}: {value}" for label, value in details))

    if link:
        sections.append(f"{link_label}:\n{link}")

    if actions:
        sections.append("Available actions:\n" + "\n".join(actions))

    return "\n\n".join(sections)


def usage_message(command: str, *, example: str | None = None) -> str:
    """Return a copyable command usage block."""
    message = f"Usage:\n{command}"
    if example:
        message = f"{message}\n\nExample:\n{example}"
    return message


def validation_message(
    reason: str,
    *,
    command: str,
    example: str | None = None,
) -> str:
    """Return a standardized validation message with usage guidance."""
    return (
        f"I could not do that because {reason}.\n\n"
        f"{usage_message(command, example=example)}"
    )
