from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ContextTypes

from .auth_guard import require_login


@require_login
async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Correct usage: /translate <language> <text>\n"
            "Example: /translate en Hello world"
        )
        return

    idioma_destino = args[0]
    texto = " ".join(args[1:])

    try:
        resultado = GoogleTranslator(source="auto", target=idioma_destino).translate(
            texto
        )
    except Exception as error:
        await update.message.reply_text(f"Error translating: {error}")
        return

    await update.message.reply_text(
        f"Translation to `{idioma_destino}`:\n{resultado}", parse_mode="Markdown"
    )
