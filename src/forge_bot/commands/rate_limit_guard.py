from telegram import Update

from forge_bot.rate_limits import abuse_limiter


async def reply_if_admin_invite_limited(update: Update) -> bool:
    """Return true after replying when an admin invite rate limit is hit."""
    if not update.effective_user or not update.message:
        return True

    decision = abuse_limiter.check_admin_invite(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id if update.effective_chat else 0,
    )
    if decision.allowed:
        return False

    await update.message.reply_text(decision.message)
    return True
