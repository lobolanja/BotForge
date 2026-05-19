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
from forge_bot.messages import build_message, usage_message, validation_message

from .auth_guard import admin_required
from .rate_limit_guard import reply_if_admin_invite_limited

INVITE_USAGE = "/invite <role> <email>"
INVITE_EXAMPLE = "/invite user person@example.com"


@admin_required
async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a single-use invite link for an email and role."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    usage = usage_message(INVITE_USAGE, example=INVITE_EXAMPLE)
    if len(args) == 0:
        await update.message.reply_text(usage)
        return

    if len(args) == 1:
        await update.message.reply_text(
            validation_message(
                "the email address is missing",
                command=INVITE_USAGE,
                example=INVITE_EXAMPLE,
            )
        )
        return

    if len(args) > 2:
        await update.message.reply_text(
            validation_message(
                "too many arguments were provided",
                command=INVITE_USAGE,
                example=INVITE_EXAMPLE,
            )
        )
        return

    requested_role = args[0].lower()
    requested_email = normalize_invite_email(args[1])

    if requested_role in RESERVED_INVITE_ROLES:
        await update.message.reply_text(
            "I could not create the invite because the 'professional' role is not "
            "available yet."
        )
        return

    if requested_role not in VALID_INVITE_ROLES:
        roles_list = ", ".join(sorted(VALID_INVITE_ROLES))
        await update.message.reply_text(
            f"I could not create the invite because '{requested_role}' is not a "
            f"supported role.\n\nAvailable roles: {roles_list}.\n\n"
            f"{usage_message(INVITE_USAGE, example=INVITE_EXAMPLE)}"
        )
        return

    if requested_email is None:
        await update.message.reply_text(
            validation_message(
                "the email address is invalid",
                command=INVITE_USAGE,
                example=INVITE_EXAMPLE,
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
            "Invite creation is temporarily unavailable. Please contact the "
            "administrator."
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
            "Invite creation is temporarily unavailable. Please try again in a "
            "moment."
        )
        return

    expires_at_str = token_result.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    response = build_message(
        "Invite link created.",
        details=(
            ("Role", requested_role),
            ("Email", requested_email),
            ("Expires", expires_at_str),
        ),
        link=token_result.invite_link,
    )

    await update.message.reply_text(response)
