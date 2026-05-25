from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import is_admin
from forge_bot.messages import build_message


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    admin = is_admin(update.effective_user.id)

    help_text = (
        "Available commands\n\n"
        "/greet - Say hello.\n"
        "/ping - Check bot latency.\n"
        "/translate - Translate text.\n"
        "/time - Show the current time.\n"
        "/help - Show this command list.\n"
        "/status - Check your linked identity.\n"
        "/policy - Review the usage policy.\n"
        "/accept_policy - Accept the current policy.\n"
        "/decline_policy - Decline the current policy.\n"
        "/privacy - Review stored data and controls.\n"
        "/memory_clear - Clear personalization memory.\n"
        "/delete_my_data - Start data deletion.\n"
        "/set_plan - Upload your nutrition plan JSON files.\n"
        "/get_plan - Review or export your active nutrition plan."
    )
    if admin:
        help_text += (
            "\n\nAdmin commands\n"
            "/admin_users [limit] - List user identifiers for admin tools.\n"
            "/admin_memory <user_id|tg:telegram_id|email:value|username:value> "
            "[profile_id] - Inspect memory sections for a user.\n"
            "/invite <role> <email> - Create a single-use invite link.\n"
            "/campaign_invite <role> <expires_at> <max_uses> - Create a "
            "reusable campaign invite link."
        )
    await update.message.reply_text(build_message(help_text))
