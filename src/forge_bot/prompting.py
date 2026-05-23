from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypedDict

from .bot_profile import BotProfile


class ChatMessage(TypedDict):
    """Message structure expected by Ollama chat models."""

    role: str
    content: str


def assemble_prompt_messages(
    profile: BotProfile,
    current_user_message: str,
    user_display_name: str | None = None,
    compacted_user_memory: str | None = None,
    recent_conversation_messages: Sequence[ChatMessage] | None = None,
    runtime_safety_instructions: Iterable[str] | None = None,
) -> list[ChatMessage]:
    """Build the ordered message list sent to the configured LLM.

    The order is intentionally explicit so later memory work can plug into the
    contract without changing Telegram routing or generic runtime code.
    """
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": _system_content(profile, runtime_safety_instructions),
        }
    ]

    memory_content = _memory_content(
        compacted_user_memory=compacted_user_memory,
        recent_conversation_messages=recent_conversation_messages,
    )
    if memory_content:
        messages.append({"role": "system", "content": memory_content})

    messages.append({"role": "user", "content": current_user_message.strip()})
    return messages


def _memory_content(
    *,
    compacted_user_memory: str | None,
    recent_conversation_messages: Sequence[ChatMessage] | None,
) -> str | None:
    sections: list[str] = []
    if compacted_user_memory and compacted_user_memory.strip():
        sections.append("Compacted memory:\n" + compacted_user_memory.strip())

    if recent_conversation_messages:
        transcript = "\n".join(
            f"{message['role']}: {message['content'].strip()}"
            for message in recent_conversation_messages
            if message["content"].strip()
        )
        if transcript:
            sections.append("Recent conversation:\n" + transcript)

    if not sections:
        return None

    return (
        "User memory for this same authenticated user and bot profile. "
        "Use it as previous conversation context. If the user asks about their "
        "name, preferences, priorities, dates, or earlier statements, answer "
        "from this memory when it contains the information.\n\n" + "\n\n".join(sections)
    )


def _system_content(
    profile: BotProfile,
    runtime_safety_instructions: Iterable[str] | None,
) -> str:
    """Combine profile instructions and runtime safety rules."""
    sections = [
        profile.system_prompt.strip(),
        "Domain rules:\n" + "\n".join(f"- {rule}" for rule in profile.domain_rules),
        f"Default language: {profile.default_language}",
        f"Disclaimer: {profile.disclaimer_text}",
    ]
    if profile.context_documents:
        context_sections = [
            (
                f"Document: {document.name}\n"
                "Use this as read-only profile context. Do not expose raw JSON "
                "unless the user explicitly asks for it.\n"
                f"{document.content}"
            )
            for document in profile.context_documents
        ]
        sections.append(
            "Profile context documents:\n\n" + "\n\n".join(context_sections)
        )

    if runtime_safety_instructions:
        instructions = [
            item.strip() for item in runtime_safety_instructions if item.strip()
        ]
        if instructions:
            sections.append(
                "Runtime safety instructions:\n"
                + "\n".join(f"- {instruction}" for instruction in instructions)
            )

    return "\n\n".join(sections)
