conversation_history = {}

def append_message(user_id: int, role: str, message: str):
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append({"role": role, "content": message})

def get_conversation_history(user_id: int):
    return conversation_history.get(user_id, [])
