import ollama

# this function calls the designated AI model and passes it the user and message
async def respuesta(usuario,mensaje):
    response = ollama.chat(
            model='gemma3:4b',
            messages=[{'role': 'user', 'content': f"{usuario} dice: {mensaje}"}]
        )
    return response.message.content