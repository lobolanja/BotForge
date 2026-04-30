from telegram import Update
from telegram.ext import ContextTypes
import time as time_module
from deep_translator import GoogleTranslator
from datetime import datetime

# Here will be all the functions with the commands that are going to be executed 

# asynchronous function that is used to send a message with the available commands
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Available commands:\n"
        "/greet - Greet the user\n"
        "/ping - Check the bot's latency\n"
        "/translate - Translate text to another language\n"
        "/time - Show the current time\n"
        "/help - Show the available commands"
    )
    await update.message.reply_text(help_text)

# asynchronous function that is used to take the user's name and then greet them
async def greet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text("Hello " + user)

# asynchronous function that is used to calculate the latency of the bot and then send a message with the latency in milliseconds
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time_module.time()
    msg = await update.message.reply_text("Calculando latencia...")
    end = time_module.time()
    
    latencia_ms = round((end - start) * 1000)
    await msg.edit_text(f"Latencia: `{latencia_ms}ms`", parse_mode="Markdown")

# asynchronous function that is used to send a message when the user sends a command that is not recognized
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Command not found. Use /help to see the available commands.")

# asynchronous function that is used to translate text to another language
async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Uso correcto: /translate <idioma> <texto>\n"
            "Ejemplo: /translate en Hola mundo"
        )
        return

    idioma_destino = args[0]
    texto = " ".join(args[1:])

    try:
        resultado = GoogleTranslator(source="auto", target=idioma_destino).translate(texto)
    except Exception as e:
        await update.message.reply_text(f"Error al traducir: {e}")
        return

    await update.message.reply_text(f"Traducción al `{idioma_destino}`:\n{resultado}",parse_mode="Markdown")

# asynchronous function that is used to send a message with the current time
async def time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    await update.message.reply_text(f"Hora actual: {now}")