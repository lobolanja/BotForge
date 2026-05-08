"""Admin-only command to generate Telegram invite links for new users."""

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import (
    VALID_INVITE_ROLES,
    create_invite_token,
    get_user_by_telegram_id,
)

from .auth_guard import admin_required


@admin_required
async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate an invite link for a new user.

    Usage:
        /invite user

    Only admins can use this command. The generated token is single-use and expires.
    """
    if not update.message or not update.effective_user:
        return

    # Validate arguments
    args = context.args or []
    if len(args) == 0:
        await update.message.reply_text(
            "Usage: /invite <role>\n\nExample: /invite user"
        )
        return

    if len(args) > 1:
        await update.message.reply_text(
            "Error: Too many arguments.\n\nUsage: /invite <role>"
        )
        return

    requested_role = args[0].lower()

    # Reject professional role (not yet implemented)
    if requested_role == "professional":
        await update.message.reply_text("The 'professional' role is not available yet.")
        return

    # Validate role
    if requested_role not in VALID_INVITE_ROLES:
        await update.message.reply_text(
            f"Invalid role '{requested_role}'.\n\n"
            f"Available roles: {', '.join(sorted(VALID_INVITE_ROLES - {'professional'}))}."
        )
        return

    # Get admin user ID from database
    admin_user = get_user_by_telegram_id(update.effective_user.id)
    if not admin_user:
        # This shouldn't happen because admin_required decorator checks this
        await update.message.reply_text("Error: Could not retrieve admin information.")
        return

    admin_user_id = admin_user["id"]

    # Get bot username
    bot_username = context.bot.username
    if not bot_username:
        await update.message.reply_text(
            "Error: Bot username not configured. Please contact the administrator."
        )
        return

    # Create the invite token
    token_result = create_invite_token(
        role=requested_role,
        created_by_user_id=admin_user_id,
        bot_username=bot_username,
    )

    if not token_result:
        await update.message.reply_text(
            "Error: Could not generate invite token. Please try again later."
        )
        return

    # Format the response
    expires_at_str = token_result.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    response = (
        f"✅ Invite link created!\n\n"
        f"Invite link:\n"
        f"{token_result.invite_link}\n\n"
        f"Role: {requested_role}\n"
        f"Expires: {expires_at_str}"
    )

    await update.message.reply_text(response)
