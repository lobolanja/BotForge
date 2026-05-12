from telegram import Update
from telegram.ext import ContextTypes

from forge_bot.database import is_admin


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    admin = is_admin(update.effective_user.id)

    help_text = (
        "Comandos disponibles:\n"
        "/greet - Saluda al usuario\n"
        "/ping - Verifica la latencia del bot\n"
        "/translate - Traducir texto a otro idioma\n"
        "/time - Muestra la hora actual\n"
        "/help - Muestra los comandos disponibles\n"
        "/status - Verifica tu identidad vinculada\n"
        "/policy - Muestra la politica de uso\n"
        "/accept_policy - Aceptar la politica de uso\n"
        "/decline_policy - Rechazar la politica de uso\n"
    )
    if admin:
        help_text += (
            "\nComandos de administrador:\n"
            "/invite <role> <email> - Generar un enlace de invitacion\n"
            "/campaign_invite <role> <expires_at> <max_uses> - "
            "Generar un enlace de campana\n"
        )
    await update.message.reply_text(help_text)
