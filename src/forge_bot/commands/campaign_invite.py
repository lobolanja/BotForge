"""Admin-only command to create reusable campaign invite links."""

from datetime import date, datetime, time, timezone

from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import (
    RESERVED_INVITE_ROLES,
    VALID_INVITE_ROLES,
    create_campaign_invite_token,
    get_user_by_telegram_id,
)

from .auth_guard import admin_required
from .rate_limit_guard import reply_if_admin_invite_limited


def parse_campaign_expiration(value: str) -> datetime | None:
    """Parse YYYY-MM-DD as the end of that UTC day."""
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        return None
    return datetime.combine(parsed_date, time(23, 59, 59), tzinfo=timezone.utc)


@admin_required
async def campaign_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a reusable campaign invite link."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    usage = (
        "Usage: /campaign_invite <role> <expires_at> <max_uses>\n\n"
        "Example: /campaign_invite user 2026-06-30 100"
    )
    if len(args) == 0:
        await update.message.reply_text(usage)
        return

    if len(args) < 3:
        await update.message.reply_text(f"Error: Missing arguments.\n\n{usage}")
        return

    if len(args) > 3:
        await update.message.reply_text(
            "Error: Too many arguments.\n\n"
            "Usage: /campaign_invite <role> <expires_at> <max_uses>"
        )
        return

    requested_role = args[0].lower()
    if requested_role in RESERVED_INVITE_ROLES:
        await update.message.reply_text("The 'professional' role is not available yet.")
        return

    if requested_role not in VALID_INVITE_ROLES:
        roles_list = ", ".join(sorted(VALID_INVITE_ROLES))
        await update.message.reply_text(
            f"Invalid role '{requested_role}'.\n\nAvailable roles: {roles_list}."
        )
        return

    expires_at = parse_campaign_expiration(args[1])
    if expires_at is None:
        await update.message.reply_text(
            "Invalid expiration date. Use YYYY-MM-DD, for example 2026-06-30."
        )
        return

    try:
        max_uses = int(args[2])
    except ValueError:
        await update.message.reply_text("Invalid max uses. Use a positive integer.")
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

    try:
        token_result = create_campaign_invite_token(
            role=requested_role,
            expires_at=expires_at,
            max_uses=max_uses,
            created_by_user_id=admin_user["id"],
            bot_username=bot_username,
        )
    except ValueError as error:
        await update.message.reply_text(str(error))
        return

    if not token_result:
        await update.message.reply_text(
            "Error: Could not generate campaign invite token. Please try again later."
        )
        return

    expires_at_str = token_result.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    response = (
        "Campaign invite link created!\n\n"
        "Invite link:\n"
        f"{token_result.invite_link}\n\n"
        f"Role: {requested_role}\n"
        f"Expires: {expires_at_str}\n"
        f"Max uses: {max_uses}"
    )

    await update.message.reply_text(response)
