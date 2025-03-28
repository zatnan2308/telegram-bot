import json
import openai
from typing import Dict, Optional
from config.settings import OPENAI_API_KEY, GPT_MODEL
from utils.logger import logger
from database.queries import get_service_name, get_specialist_name

# Устанавливаем API ключ
openai.api_key = OPENAI_API_KEY

def get_booking_system_prompt() -> str:
    """Возвращает системный промпт для бронирования"""
    return """
    Ты — ассистент по бронированию услуг в салоне красоты. 
    
    Текущие доступные действия:
    - LIST_SERVICES: показать список услуг
    - SELECT_SERVICE: выбрать услугу
    - SELECT_SPECIALIST: выбрать специалиста
    - SELECT_TIME: выбрать время
    - CONFIRM_BOOKING: подтвердить запись
    - CANCEL_BOOKING: отменить запись
    
    Ответ должен быть в формате JSON:
    {
        "action": "одно из доступных действий",
        "response": "текст ответа пользователю",
        "extracted_data": {
            "service": "название услуги если есть",
            "specialist": "имя специалиста если есть",
            "time": "выбранное время если есть"
        }
    }
    """

def get_booking_context(state: Optional[Dict]) -> str:
    """Формирует контекст для GPT на основе текущего состояния"""
    context = ""
    if state:
        context = f"Текущий этап бронирования: {state['step']}\n"
        if state.get('service_id'):
            service_name = get_service_name(state['service_id'])
            context += f"Выбранная услуга: {service_name}\n"
        if state.get('specialist_id'):
            specialist_name = get_specialist_name(state['specialist_id'])
            context += f"Выбранный специалист: {specialist_name}\n"
        if state.get('chosen_time'):
            context += f"Выбранное время: {state['chosen_time']}\n"
    return context

def determine_intent(user_id: int, user_text: str, state: Optional[Dict] = None) -> Dict:
    """Определяет намерение пользователя с помощью GPT"""
    try:
        system_prompt = get_booking_system_prompt()
        context = get_booking_context(state)
        
        response = openai.ChatCompletion.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Контекст:\n{context}\nСообщение пользователя: {user_text}"}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        gpt_response = response.choices[0].message.content
        logger.info(f"GPT response for user {user_id}: {gpt_response}")
        
        return json.loads(gpt_response)

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON от GPT для user {user_id}: {e}")
        return {
            "action": None,
            "response": "Извините, произошла ошибка. Попробуйте еще раз.",
            "extracted_data": {}
        }
    except Exception as e:
        logger.error(f"Ошибка при обработке GPT для user {user_id}: {e}", exc_info=True)
        return {
            "action": None,
            "response": "Извините, произошла ошибка. Попробуйте еще раз или начните сначала.",
            "extracted_data": {}
        }

def get_gpt_response(user_id: int, user_text: str, state: Optional[Dict] = None) -> Dict:
    """Получает ответ от GPT"""
    return determine_intent(user_id, user_text, state)

def resolve_specialist_name(input_text: str, specialists: list) -> str:
    """
    Принимает ввод пользователя (например, "Иван" или "Ваня") и список специалистов 
    (список кортежей вида (id, full_name)).
    Возвращает полное имя специалиста, выбранное ChatGPT.
    """
    specialist_names = [s[1] for s in specialists]
    prompt = (
        f"У меня есть список специалистов: {', '.join(specialist_names)}. "
        f"Пользователь ввёл: '{input_text}'. "
        f"Какой специалист имеется в виду? Ответь только точным именем из списка."
    )
    
    response = openai.ChatCompletion.create(
         model=GPT_MODEL,
         messages=[
             {"role": "system", "content": "Ты помощник по бронированию услуг в салоне красоты."},
             {"role": "user", "content": prompt}
         ],
         temperature=0.3,
         max_tokens=20
    )
    
    resolved_name = response.choices[0].message.content.strip()
    logger.info(f"Resolved specialist name: {resolved_name} for input: {input_text}")
    return resolved_name
