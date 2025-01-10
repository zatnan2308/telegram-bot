import json
from typing import Optional, Dict
import telegram

from config.settings import TOKEN, DATABASE_URL, GPT_MODEL, MANAGER_CHAT_ID
from database.queries import (
    get_services,
    find_service_by_name,
    get_specialists,
    get_available_times,
    create_booking,
    get_service_name,
    get_specialist_name,
    find_available_specialist
)
from database.models import set_user_state, delete_user_state
from services.gpt import get_gpt_response
from utils.logger import logger
from utils.time_utils import parse_time_input

def handle_list_services(update: telegram.Update, gpt_response_text: str):
    """Обработка action LIST_SERVICES"""
    services = get_services()
    if services:
        service_list = "\n".join([f"- {s[1]}" for s in services])
        update.message.reply_text(f"{gpt_response_text}\n\nДоступные услуги:\n{service_list}")
    else:
        update.message.reply_text("К сожалению, сейчас нет доступных услуг.")

def handle_select_service(
    update: telegram.Update,
    user_id: int,
    extracted_data: Dict,
    gpt_response_text: str
):
    """Обработка action SELECT_SERVICE"""
    service_name = extracted_data.get('service')
    if not service_name:
        services = get_services()
        service_list = "\n".join([f"- {s[1]}" for s in services])
        update.message.reply_text(
            f"{gpt_response_text}\n\n"
            f"Доступные услуги:\n{service_list}"
        )
        return

    service = find_service_by_name(service_name)
    if not service:
        services = get_services()
        service_list = "\n".join([f"- {s[1]}" for s in services])
        update.message.reply_text(
            f"Услуга не найдена. Выберите из списка:\n\n{service_list}"
        )
        return

    service_id, service_name = service
    specialists = get_specialists(service_id=service_id)
    if not specialists:
        update.message.reply_text("К сожалению, нет доступных специалистов.")
        return

    set_user_state(user_id, "select_specialist", service_id=service_id)
    specialists_info = []
    for spec in specialists:
        available_times = get_available_times(spec[0], service_id)
        if available_times:
            specialists_info.append(
                f"👩‍💼 {spec[1]}\n   Доступное время:\n   " + 
                "\n   ".join([f"🕐 {t}" for t in available_times])
            )
    
    if specialists_info:
        update.message.reply_text(
            f"Для услуги '{service_name}' доступны следующие специалисты:\n\n" +
            "\n\n".join(specialists_info)
        )
    else:
        update.message.reply_text("К сожалению, нет доступного времени у специалистов.")

def handle_select_specialist(
    update: telegram.Update,
    user_id: int,
    state: Dict,
    extracted_data: Dict,
    gpt_response_text: str
):
    """Обработка action SELECT_SPECIALIST"""
    if not state or not state.get('service_id'):
        update.message.reply_text("Сначала выберите услугу.")
        return

    specialist_name = extracted_data.get('specialist')
    specialists = get_specialists(state['service_id'])
    
    if not specialist_name:
        specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
        update.message.reply_text(
            f"{gpt_response_text}\n\n"
            f"Доступные специалисты:\n{specialists_text}"
        )
        return

    specialist = next(
        (s for s in specialists if s[1].lower() == specialist_name.lower()),
        None
    )
    
    if not specialist:
        specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
        update.message.reply_text(
            f"Специалист не найден. Выберите из списка:\n\n{specialists_text}"
        )
        return

    available_times = get_available_times(specialist[0], state['service_id'])
    if available_times:
        set_user_state(
            user_id, 
            "select_time",
            service_id=state['service_id'],
            specialist_id=specialist[0]
        )
        times_text = "\n".join([f"- {t}" for t in available_times])
        update.message.reply_text(
            f"{gpt_response_text}\n\n"
            f"Доступное время:\n{times_text}"
        )
    else:
        update.message.reply_text(
            f"К сожалению, у специалиста {specialist[1]} нет свободного времени."
        )

def handle_select_time(
    update: telegram.Update,
    user_id: int,
    state: Dict,
    extracted_data: Dict,
    bot: telegram.Bot
):
    """Обработка action SELECT_TIME"""
    if not state or not all(k in state for k in ['service_id', 'specialist_id']):
        services = get_services()
        if services:
            services_text = "\n".join([f"- {s[1]}" for s in services])
            update.message.reply_text(
                "Сначала выберите услугу из списка:\n\n"
                f"{services_text}"
            )
        return

    available_times = get_available_times(state['specialist_id'], state['service_id'])
    
    if not available_times:
        alternative_specialist = find_available_specialist(state['service_id'], state['specialist_id'])
        if alternative_specialist:
            set_user_state(
                user_id,
                "select_specialist",
                service_id=state['service_id']
            )
            update.message.reply_text(
                "К сожалению, у выбранного специалиста нет свободного времени.\n"
                f"Вы можете записаться к {alternative_specialist[1]}. Хотите посмотреть доступное время?"
            )
        else:
            update.message.reply_text(
                "К сожалению, сейчас нет свободного времени для записи.\n"
                "Попробуйте выбрать другую услугу или свяжитесь с администратором."
            )
        return

    chosen_time = None
    gpt_time = extracted_data.get('time')
    if gpt_time:
        chosen_time = parse_time_input(gpt_time, available_times)

    if chosen_time:
        set_user_state(
            user_id,
            "confirm",
            service_id=state['service_id'],
            specialist_id=state['specialist_id'],
            chosen_time=chosen_time
        )
        service_name = get_service_name(state['service_id'])
        specialist_name = get_specialist_name(state['specialist_id'])
        update.message.reply_text(
            f"Подтвердите запись:\n\n"
            f"🎯 Услуга: {service_name}\n"
            f"👩‍💼 Специалист: {specialist_name}\n"
            f"📅 Время: {chosen_time}\n\n"
            "Для подтверждения напишите 'да' или 'нет' для отмены."
        )
    else:
        times_text = "\n".join([f"🕐 {t}" for t in available_times])
        update.message.reply_text(
            f"Пожалуйста, выберите точное время из списка:\n\n{times_text}"
        )

def handle_confirm_booking(
    update: telegram.Update,
    user_id: int,
    state: Dict,
    user_text: str,
    gpt_response_text: str,
    bot: telegram.Bot
):
    """Обработка action CONFIRM_BOOKING"""
    if not state or not all(k in state for k in ['service_id', 'specialist_id', 'chosen_time']):
        update.message.reply_text("Недостаточно информации для создания записи.")
        return

    if user_text.lower() in ['да', 'yes', 'подтверждаю']:
        success = create_booking(
            user_id=user_id,
            serv_id=state['service_id'],
            spec_id=state['specialist_id'],
            date_str=state['chosen_time']
        )
        if success:
            service_name = get_service_name(state['service_id'])
            specialist_name = get_specialist_name(state['specialist_id'])
            update.message.reply_text(f"{gpt_response_text}")
            
            if MANAGER_CHAT_ID:
                bot.send_message(
                    MANAGER_CHAT_ID,
                    f"Новая запись!\n"
                    f"Услуга: {service_name}\n"
                    f"Специалист: {specialist_name}\n"
                    f"Время: {state['chosen_time']}\n"
                    f"Клиент ID: {user_id}"
                )
        else:
            update.message.reply_text("Произошла ошибка при создании записи. Пожалуйста, попробуйте позже.")
    else:
        update.message.reply_text(f"{gpt_response_text}")
    
    delete_user_state(user_id)

def handle_booking_with_gpt(update: telegram.Update, user_id: int, user_text: str, state: Optional[Dict] = None):
    """Основной обработчик бронирования с использованием GPT"""
    try:
        result = get_gpt_response(user_id, user_text, state)
        
        action = result.get('action')
        extracted_data = result.get('extracted_data', {})
        gpt_response_text = result.get('response', '')

        if action == "LIST_SERVICES":
            handle_list_services(update, gpt_response_text)
            
        elif action == "SELECT_SERVICE":
            handle_select_service(update, user_id, extracted_data, gpt_response_text)
            
        elif action == "SELECT_SPECIALIST":
            handle_select_specialist(update, user_id, state, extracted_data, gpt_response_text)
            
        elif action == "SELECT_TIME":
            handle_select_time(update, user_id, state, extracted_data, update.message.bot)
            
        elif action == "CONFIRM_BOOKING":
            handle_confirm_booking(update, user_id, state, user_text, gpt_response_text, update.message.bot)
            
        elif action == "CANCEL_BOOKING":
            delete_user_state(user_id)
            update.message.reply_text(f"{gpt_response_text}")
            
        else:
            update.message.reply_text(gpt_response_text or "Извините, я не понял ваш запрос.")

    except Exception as e:
        logger.error(f"Ошибка при обработке GPT для user {user_id}: {e}", exc_info=True)
        update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте сформулировать ваш запрос иначе или начните сначала."
        )
