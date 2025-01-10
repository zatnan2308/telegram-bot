# gpt_utils.py
import re
import json
import logging
import openai
import os

logger = logging.getLogger(__name__)

# Убедитесь, что OPENAI_API_KEY передаётся из окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("Не установлена переменная окружения OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

def clean_gpt_json(raw_text):
    """
    Удаляем из ответа GPT возможные тройные кавычки, бэктики и т.п.
    """
    cleaned = raw_text.strip().strip('```').strip()
    cleaned = re.sub(r"```(\w+)?", "", cleaned).strip()
    return cleaned

def clean_gpt_booking_response(raw_text):
    """
    Вспомогательная функция для обработки ответа GPT в логике бронирования.
    """
    cleaned = raw_text.strip().strip('```').strip()
    cleaned = re.sub(r"```(\w+)?", "", cleaned).strip()
    return cleaned

def determine_intent(user_message):
    """
    Определяет намерение пользователя:
     - SELECT_SPECIALIST
     - SPECIALIST_QUESTION
     - BOOKING_INTENT
     - UNKNOWN

    Возвращает JSON вида {"intent": "...", "confidence": 0..1, "extracted_info": {...}}
    """
    system_prompt = (
        "Ты — Telegram-бот для управления записями. "
        "Если пользователь пытается выбрать специалиста во время процесса записи, "
        "всегда возвращай intent: 'SELECT_SPECIALIST'. "
        "Возможные намерения: SELECT_SPECIALIST, SPECIALIST_QUESTION, BOOKING_INTENT, UNKNOWN. "
        "ВАЖНО: Верни ответ строго в формате JSON с двойными кавычками."
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=100,
            temperature=0
        )
        response_content = resp['choices'][0]['message']['content'].strip()
        response_content = clean_gpt_json(response_content)
        return json.loads(response_content)
    except json.JSONDecodeError as jerr:
        logger.error(f"JSONDecodeError в determine_intent: {jerr}\nСырой ответ: {response_content}")
        return {"intent": "UNKNOWN", "confidence": 0.0, "extracted_info": {}}
    except Exception as e:
        logger.error(f"Ошибка определения намерения через GPT: {e}")
        return {"intent": "UNKNOWN", "confidence": 0.0, "extracted_info": {}}

def generate_ai_response(prompt):
    """
    Общая функция для генерации ответа через GPT (без жёсткой структуры JSON).
    """
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system", "content":"Ты — умный Telegram-бот, помогай пользователю."},
                {"role":"user", "content":prompt}
            ],
            max_tokens=150
        )
        return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.error(f"Ошибка генерации ответа через GPT: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."
