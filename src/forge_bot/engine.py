import ollama

# this function calls the designated AI model and passes it the user and message
async def answer(user,msg):
    
    response = ollama.chat(
            model='gemma3:4b',
            messages=[{'role': 'user', 'content': f"{user} dice: {msg}"}]
        )
    return response.message.content