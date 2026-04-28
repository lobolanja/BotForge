from telegram.ext import Application, CommandHandler, MessageHandler, filters
from . import preguntar_ia, saludar
import os
from dotenv import load_dotenv

# Loads environment variables from the .env file into the system
load_dotenv()

def main():
    # Retrieve the token from the environment variables
    token = os.getenv("TELEGRAM_TOKEN")
    
    if not token:
        print("Error: TELEGRAM_TOKEN not found in .env file")
        return
    
    # variable that contains the bot that is the one you are working with
    bot = Application.builder().token(token).build()
    
    # call to the 'saludar' command
    bot.add_handler(CommandHandler("saludar", saludar))
    
    # call to the ia
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, preguntar_ia))

    # to make sure it is running
    print("Bot en ejecución...")
    bot.run_polling()

# Entry point: ensures main() only runs if script is executed directly
if __name__ == '__main__':
    main()