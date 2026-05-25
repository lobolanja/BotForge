from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
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
    now: datetime | None = None,
) -> list[ChatMessage]:
    """Build the ordered message list sent to the configured LLM.

    The order is intentionally explicit so later memory work can plug into the
    contract without changing Telegram routing or generic runtime code.
    """
    memory_content = _memory_content(
        compacted_user_memory=compacted_user_memory,
        recent_conversation_messages=recent_conversation_messages,
    )
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": _system_content(
                profile,
                runtime_safety_instructions,
                memory_content=memory_content,
                now=now or datetime.now().astimezone(),
            ),
        }
    ]
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
        "Available conversation context for this same authenticated user and "
        "bot profile. This is the bot's memory for the current answer. Treat it "
        "as authoritative conversation context supplied by the application.\n\n"
        "Rules:\n"
        "- If the user asks what they said, asked, or discussed before, answer "
        "from the recent conversation below.\n"
        "- Do not say you have no memory or no access to previous messages when "
        "the relevant information appears below.\n"
        "- If the answer is not present below, say that you do not have that "
        "specific previous detail available.\n\n" + "\n\n".join(sections)
    )


def _system_content(
    profile: BotProfile,
    runtime_safety_instructions: Iterable[str] | None,
    *,
    memory_content: str | None = None,
    now: datetime,
) -> str:
    """Combine profile instructions and runtime safety rules."""
    sections = [
        profile.system_prompt.strip(),
        "Domain rules:\n" + "\n".join(f"- {rule}" for rule in profile.domain_rules),
        f"Default language: {profile.default_language}",
        f"Disclaimer: {profile.disclaimer_text}",
        _current_datetime_content(now),
    ]
    if memory_content:
        sections.append(memory_content)

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


def _current_datetime_content(now: datetime) -> str:
    local_now = now if now.tzinfo is not None else now.astimezone()
    return (
        "Current runtime date and time:\n"
        f"- ISO datetime: {local_now.isoformat()}\n"
        f"- Date: {local_now.date().isoformat()}\n"
        f"- Timezone: {local_now.tzname() or 'local'}\n"
        "- Use this as the real current date/time for relative references like "
        "today, tomorrow, yesterday, this week, or tonight."
    )
