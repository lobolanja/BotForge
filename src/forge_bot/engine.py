import ollama
import os

DEFAULT_OLLAMA_MODEL = "gemma2:2b"


# this function calls the designated AI model and passes it the user and message
async def answer(user, msg):
    model = os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL

    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": f"{user} dice: {msg}"}],
    )
    return response.message.content
