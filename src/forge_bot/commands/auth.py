from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import redeem_invite_token, status_user
from forge_bot.messages import build_message

from .policy import policy_action_keyboard, policy_prompt

INVITE_PROMPT = build_message(
    "Welcome to BotForge.",
    details=(("Next step", "Open your invite link to connect your identity"),),
)
ALREADY_LINKED_START = build_message(
    "Welcome back to BotForge.",
    details=(("Status", "This Telegram account is already linked"),),
)
REDEMPTION_FAILURE_MESSAGES = {
    "already_linked": build_message(
        "This Telegram account is already linked.",
        actions=("/status",),
    ),
    "expired": "I could not accept that invite because it has expired.",
    "used": "I could not accept that invite because it has already been used.",
    "campaign_full": (
        "I could not accept that invite because it has reached its use limit."
    ),
    "invalid": "I could not accept that invite because it is invalid.",
}
REDEMPTION_UNAVAILABLE = (
    "Invite redemption is temporarily unavailable. Please try again in a moment."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    args = context.args or []

    if not args:
        user = status_user(update.effective_user.id)
        if user:
            await update.message.reply_text(ALREADY_LINKED_START)
            return
        await update.message.reply_text(INVITE_PROMPT)
        return

    await update.message.reply_text(INVITE_PROMPT)
    await _reply_to_invite_redemption(update, args[0], update.effective_user.id)


async def _reply_to_invite_redemption(
    update: Update,
    token: str,
    telegram_id: int,
) -> None:
    if not update.message:
        return

    redemption = redeem_invite_token(token, telegram_id)
    if redemption.status == "success":
        await update.message.reply_text(
            f"{build_message('Invite accepted.')}\n\n{policy_prompt()}",
            reply_markup=policy_action_keyboard(),
        )
        return

    message = REDEMPTION_FAILURE_MESSAGES.get(
        redemption.status,
        REDEMPTION_UNAVAILABLE,
    )
    await update.message.reply_text(message)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = status_user(update.effective_user.id)
    if user:
        email = user.get("email")
        if email:
            await update.message.reply_text(
                build_message(
                    "Identity linked.",
                    details=(
                        ("Email", str(email)),
                        ("Role", str(user["role"])),
                    ),
                )
            )
            return
        await update.message.reply_text(
            build_message(
                "Identity linked.",
                details=(("Role", str(user["role"])),),
            )
        )
    else:
        await update.message.reply_text(
            build_message(
                "Identity not linked.",
                details=(
                    ("Next step", "Open your invite link to connect your account"),
                ),
            )
        )
