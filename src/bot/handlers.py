from telegram import Update
from telegram.ext import ContextTypes

# Here will be all the functions with the commands that are going to be executed 

# asynchronous function that is used to take the user's name and then greet them
async def saludar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text("hola " + user)