"""Admin-only command to generate Telegram invite links for new users."""

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import (
    RESERVED_INVITE_ROLES,
    VALID_INVITE_ROLES,
    create_invite_token,
    get_user_by_telegram_id,
    normalize_invite_email,
)

from .auth_guard import admin_required
from .rate_limit_guard import reply_if_admin_invite_limited


@admin_required
async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a single-use invite link for an email and role."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    usage = "Usage: /invite <role> <email>\n\nExample: /invite user person@example.com"
    if len(args) == 0:
        await update.message.reply_text(usage)
        return

    if len(args) == 1:
        await update.message.reply_text(
            "Error: Missing email address.\n\n"
            "Usage: /invite <role> <email>\n\n"
            "Example: /invite user person@example.com"
        )
        return

    if len(args) > 2:
        await update.message.reply_text(
            "Error: Too many arguments.\n\nUsage: /invite <role> <email>"
        )
        return

    requested_role = args[0].lower()
    requested_email = normalize_invite_email(args[1])

    if requested_role in RESERVED_INVITE_ROLES:
        await update.message.reply_text("The 'professional' role is not available yet.")
        return

    if requested_role not in VALID_INVITE_ROLES:
        roles_list = ", ".join(sorted(VALID_INVITE_ROLES))
        await update.message.reply_text(
            f"Invalid role '{requested_role}'.\n\nAvailable roles: {roles_list}."
        )
        return

    if requested_email is None:
        await update.message.reply_text(
            "Invalid email address.\n\nUsage: /invite <role> <email>"
        )
        return

    admin_user = get_user_by_telegram_id(update.effective_user.id)
    if not admin_user:
        await update.message.reply_text("Error: Could not retrieve admin information.")
        return

    bot_username = context.bot.username
    if not bot_username:
        await update.message.reply_text(
            "Error: Bot username not configured. Please contact the administrator."
        )
        return

    if await reply_if_admin_invite_limited(update):
        return

    token_result = create_invite_token(
        role=requested_role,
        email=requested_email,
        created_by_user_id=admin_user["id"],
        bot_username=bot_username,
    )

    if not token_result:
        await update.message.reply_text(
            "Error: Could not generate invite token. Please try again later."
        )
        return

    expires_at_str = token_result.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    response = (
        "Invite link created!\n\n"
        "Invite link:\n"
        f"{token_result.invite_link}\n\n"
        f"Role: {requested_role}\n"
        f"Email: {requested_email}\n"
        f"Expires: {expires_at_str}"
    )

    await update.message.reply_text(response)
