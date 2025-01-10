import json
import openai
from typing import Dict, Optional

from config.settings import OPENAI_API_KEY
from utils.logger import logger

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
    from database.queries import get_service_name, get_specialist_name
    
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

def get_gpt_response(user_id: int, user_text: str, state: Optional[Dict] = None) -> Dict:
    """Получает ответ от GPT"""
    try:
        system_prompt = get_booking_system_prompt()
        context = get_booking_context(state)
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Контекст:\n{context}\nСообщение пользователя: {user_text}"}
            ],
            temperature=0.7,
            max_tokens=200,
            response_format={ "type": "json_object" }
        )
        
        gpt_response = response.choices[0].message.content
        logger.info(f"GPT response for user {user_id}: {gpt_response}")
        
        return json.loads(gpt_response)
    
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON от GPT для user {user_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке GPT для user {user_id}: {e}", exc_info=True)
        raise
