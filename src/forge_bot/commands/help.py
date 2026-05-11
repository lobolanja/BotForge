from telegram import Update
from telegram.ext import ContextTypes


from forge_bot.database import is_admin


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    admin = is_admin(user_id)

    help_text = (
        "Comandos disponibles:\n"
        "/greet - Saluda al usuario\n"
        "/ping - Verifica la latencia del bot\n"
        "/translate - Traducir texto a otro idioma\n"
        "/time - Muestra la hora actual\n"
        "/help - Muestra los comandos disponibles\n"
        "/status - Verifica tu autenticación\n"
        "/policy - Muestra la política de uso\n"
        "/accept_policy - Aceptar la política de uso\n"
        "/decline_policy - Rechazar la política de uso\n"
    )
    if admin:
        help_text += "/invite - Generar un enlace de invitación (admin)\n"
    await update.message.reply_text(help_text)
