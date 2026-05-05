from telegram import Update
from telegram.ext import ContextTypes
import time as time_module
from deep_translator import GoogleTranslator
from datetime import datetime
from .database import login_user, verify_user, status_user, logout_user
from functools import wraps

# Here will be all the functions with the commands that are going to be executed


def require_login(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        user_id = update.effective_user.id
        if not verify_user(user_id):
            await update.message.reply_text(
                "🔒 Access denied. Please log in using /login [password] to use this command."
            )
            return
        return await func(update, context)

    return wrapper


# asynchronous function that is used to send a message with the available commands
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Available commands:\n"
        "/greet - Greet the user\n"
        "/ping - Check the bot's latency\n"
        "/translate - Translate text to another language\n"
        "/time - Show the current time\n"
        "/help - Show the available commands\n"
        "/login [password] - Log in to the system\n"
        "/logout - Log out of the system\n"
        "/status - Check your login status\n"
    )
    await update.message.reply_text(help_text)


# asynchronous function that is used to take the user's name and then greet them
async def greet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text("Hello " + user)


# asynchronous function that is used to calculate the latency of the bot and then send a message with the latency in milliseconds
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time_module.time()
    msg = await update.message.reply_text("Calculating latency...")
    end = time_module.time()

    latencia_ms = round((end - start) * 1000)
    await msg.edit_text(f"Latency: `{latencia_ms}ms`", parse_mode="Markdown")


# asynchronous function that is used to send a message when the user sends a command that is not recognized
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Command not found. Use /help to see the available commands."
    )


# asynchronous function that is used to translate text to another language
@require_login
async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
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
    except Exception as e:
        await update.message.reply_text(f"Error translating: {e}")
        return

    await update.message.reply_text(
        f"Translation to `{idioma_destino}`:\n{resultado}", parse_mode="Markdown"
    )


# asynchronous function that is used to send a message with the current time
async def time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    await update.message.reply_text(f"Current time: {now}")


# asynchronous function that is used to log in the user with a password and link their Telegram ID to the database
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: '/login username password'")
        return

    username, password = context.args[0], context.args[1]
    if login_user(username, password, update.effective_user.id):
        await update.message.reply_text(f"✅ Welcome {username}! You have logged in.")
    else:
        await update.message.reply_text("❌ Invalid username or password.")


# asynchronous function that is used to check if the user is logged or not
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = status_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"✅ You are logged in as: {user['username']}\n" f"Use /logout to log out."
        )
    else:
        await update.message.reply_text("❌ You are not logged in.")


# asynchronous function that is used to log out the user by setting their telegram_id to NULL in the database
@require_login
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if logout_user(update.effective_user.id):
        await update.message.reply_text("👋 Session closed successfully.")
    else:
        await update.message.reply_text("⚠️ Failed to close the session.")
