import ollama

from .bot_profile import BotProfile, load_active_bot_profile
from .config import get_settings
from .prompting import assemble_prompt_messages


async def answer(
    user: str,
    msg: str,
    profile: BotProfile | None = None,
) -> str:
    """Send a profile-aware prompt to Ollama and return the model response.

    Args:
        user: Telegram user's display name.
        msg: Current Telegram text message.
        profile: Optional profile override used by tests or future flows.

    Returns:
        The assistant response text produced by Ollama.
    """
    settings = get_settings()
    active_profile = profile or load_active_bot_profile(
        settings.bot_profile,
        settings.bot_profiles_dir,
    )
    client = ollama.Client(host=settings.ollama_host)
    messages = assemble_prompt_messages(
        active_profile,
        current_user_message=msg,
        user_display_name=user,
        compacted_user_memory=None,
        recent_conversation_messages=[],
        runtime_safety_instructions=[],
    )

    response = client.chat(
        model=active_profile.llm_model,
        messages=messages,
    )
    return response.message.content
