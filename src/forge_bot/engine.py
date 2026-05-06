import os

import ollama

DEFAULT_OLLAMA_MODEL = "gemma2:2b"


# this function calls the designated AI model and passes it the user and message
async def answer(user, msg):
    settings = get_settings()
    client = ollama.Client(host=settings.ollama_host)

    response = client.chat(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": f"{user} dice: {msg}"}],
    )
    return response.message.content
