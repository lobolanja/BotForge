from telegram import Update
from telegram.ext import ContextTypes
from . import engine

# This file manages the conversation logic: 
# It receives the message, triggers the "typing" status, and calls the AI.

async def preguntar_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Variables containing the user's message and first name
    message = update.message.text
    user = update.effective_user.first_name
    
    # Send "typing..." action to Telegram to provide visual feedback to the user
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, 
        action="typing"
    )
    
    # Call the 'respuesta' function from your ia.py file and wait for the result
    answer = await engine.respuesta(user, message)
    
    # Send the AI's response back to the user in Telegram
    await update.message.reply_text(answer)