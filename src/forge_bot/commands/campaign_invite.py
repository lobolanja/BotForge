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
from forge_bot.messages import build_message, usage_message, validation_message

from .auth_guard import admin_required
from .rate_limit_guard import reply_if_admin_invite_limited

CAMPAIGN_INVITE_USAGE = "/campaign_invite <role> <expires_at> <max_uses>"
CAMPAIGN_INVITE_EXAMPLE = "/campaign_invite user 2026-06-30 100"


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
    usage = usage_message(
        CAMPAIGN_INVITE_USAGE,
        example=CAMPAIGN_INVITE_EXAMPLE,
    )
    if len(args) == 0:
        await update.message.reply_text(usage)
        return

    if len(args) < 3:
        await update.message.reply_text(
            validation_message(
                "one or more arguments are missing",
                command=CAMPAIGN_INVITE_USAGE,
                example=CAMPAIGN_INVITE_EXAMPLE,
            )
        )
        return

    if len(args) > 3:
        await update.message.reply_text(
            validation_message(
                "too many arguments were provided",
                command=CAMPAIGN_INVITE_USAGE,
                example=CAMPAIGN_INVITE_EXAMPLE,
            )
        )
        return

    requested_role = args[0].lower()
    if requested_role in RESERVED_INVITE_ROLES:
        await update.message.reply_text(
            "I could not create the campaign invite because the 'professional' role "
            "is not available yet."
        )
        return

    if requested_role not in VALID_INVITE_ROLES:
        roles_list = ", ".join(sorted(VALID_INVITE_ROLES))
        await update.message.reply_text(
            f"I could not create the campaign invite because '{requested_role}' is "
            f"not a supported role.\n\nAvailable roles: {roles_list}.\n\n"
            f"{usage_message(CAMPAIGN_INVITE_USAGE, example=CAMPAIGN_INVITE_EXAMPLE)}"
        )
        return

    expires_at = parse_campaign_expiration(args[1])
    if expires_at is None:
        await update.message.reply_text(
            validation_message(
                "the expiration date is invalid",
                command=CAMPAIGN_INVITE_USAGE,
                example=CAMPAIGN_INVITE_EXAMPLE,
            )
        )
        return

    try:
        max_uses = int(args[2])
    except ValueError:
        await update.message.reply_text(
            validation_message(
                "max uses must be a positive integer",
                command=CAMPAIGN_INVITE_USAGE,
                example=CAMPAIGN_INVITE_EXAMPLE,
            )
        )
        return

    admin_user = get_user_by_telegram_id(update.effective_user.id)
    if not admin_user:
        await update.message.reply_text(
            "Admin details are temporarily unavailable. Please try again in a moment."
        )
        return

    bot_username = context.bot.username
    if not bot_username:
        await update.message.reply_text(
            "Campaign invite creation is temporarily unavailable. Please contact "
            "the administrator."
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
        await update.message.reply_text(
            f"I could not create the campaign invite because "
            f"{str(error).rstrip('.')}.\n\n"
            f"{usage_message(CAMPAIGN_INVITE_USAGE, example=CAMPAIGN_INVITE_EXAMPLE)}"
        )
        return

    if not token_result:
        await update.message.reply_text(
            "Campaign invite creation is temporarily unavailable. Please try again "
            "in a moment."
        )
        return

    expires_at_str = token_result.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    response = build_message(
        "Campaign invite link created.",
        details=(
            ("Role", requested_role),
            ("Expires", expires_at_str),
            ("Max uses", str(max_uses)),
        ),
        link=token_result.invite_link,
    )

    await update.message.reply_text(response)
