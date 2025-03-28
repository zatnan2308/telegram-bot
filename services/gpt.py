import json
import openai
from typing import Dict, Optional
from config.settings import OPENAI_API_KEY, GPT_MODEL
from utils.logger import logger
from database.queries import get_service_name, get_specialist_name
from conversation import get_conversation_history

openai.api_key = OPENAI_API_KEY

def get_booking_system_prompt() -> str:
    return """
    Ты — ассистент по бронированию услуг в салоне красоты. 
    Отвечай максимально человечно, эмпатично и дружелюбно. 
    Твои ответы должны быть подробными и адаптивными, учитывая контекст беседы.
    
    Доступные действия:
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

def get_booking_context(state: Optional[Dict], user_id: int) -> str:
    context = ""
    if state:
        context += f"Текущий этап бронирования: {state.get('step')}\n"
        if state.get('service_id'):
            service_name = get_service_name(state['service_id'])
            context += f"Выбранная услуга: {service_name}\n"
        if state.get('specialist_id'):
            specialist_name = get_specialist_name(state['specialist_id'])
            context += f"Выбранный специалист: {specialist_name}\n"
        if state.get('chosen_time'):
            context += f"Выбранное время: {state['chosen_time']}\n"
    history = get_conversation_history(user_id)
    if history:
        context += "История беседы:\n"
        for msg in history:
            context += f"{msg['role']}: {msg['content']}\n"
    return context

def determine_intent(user_id: int, user_text: str, state: Optional[Dict] = None) -> Dict:
    try:
        system_prompt = get_booking_system_prompt()
        context = get_booking_context(state, user_id)
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
    return determine_intent(user_id, user_text, state)

def resolve_specialist_name(input_text: str, specialists: list) -> str:
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
