import json
from typing import Optional, Dict
import telegram
from config.settings import TOKEN, MANAGER_CHAT_ID
from database.queries import (
    get_services,
    find_service_by_name,
    get_specialists,
    get_available_times,
    create_booking,
    get_service_name,
    get_specialist_name,
    find_available_specialist,
    set_user_state,
    delete_user_state
)
from services.gpt import get_gpt_response, resolve_specialist_name
from utils.logger import logger
from utils.time_utils import parse_time_input
from services.scheduler import get_available_start_times
from conversation import append_message

def show_free_slots(update, context):
    # Здесь нужно получить specialist_id, service_id, date_obj из состояния или параметров
    slots = get_available_start_times(specialist_id, date_obj, service_id)
    if not slots:
        update.message.reply_text("К сожалению, нет свободных слотов в этот день.")
    else:
        update.message.reply_text("Свободные интервалы:\n" + "\n".join(slots))

def handle_list_services(update: telegram.Update, gpt_response_text: str):
    services = get_services()
    if services:
        service_list = "\n".join([f"- {s[1]}" for s in services])
        update.message.reply_text(f"{gpt_response_text}\n\nДоступные услуги:\n{service_list}")
    else:
        update.message.reply_text("К сожалению, сейчас нет доступных услуг.")

def handle_select_service(update: telegram.Update, user_id: int, extracted_data: Dict, gpt_response_text: str):
    service_name = extracted_data.get('service')
    if not service_name:
        services = get_services()
        service_list = "\n".join([f"- {s[1]}" for s in services])
        update.message.reply_text(f"{gpt_response_text}\n\nДоступные услуги:\n{service_list}")
        return
    service = find_service_by_name(service_name)
    if not service:
        services = get_services()
        service_list = "\n".join([f"- {s[1]}" for s in services])
        update.message.reply_text(f"Услуга не найдена. Выберите из списка:\n\n{service_list}")
        return
    service_id, service_name = service
    specialists = get_specialists(service_id=service_id)
    if not specialists:
        update.message.reply_text("К сожалению, нет доступных специалистов.")
        return
    set_user_state(user_id, "select_specialist", service_id=service_id)
    specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
    update.message.reply_text(f"Вы выбрали услугу '{service_name}'. Теперь выберите специалиста:\n{specialists_text}")

def handle_select_specialist(update: telegram.Update, user_id: int, state: Dict, extracted_data: Dict, gpt_response_text: str):
    if not state or not state.get('service_id'):
        update.message.reply_text("Сначала выберите услугу.")
        return
    specialist_input = extracted_data.get('specialist')
    specialists = get_specialists(state['service_id'])
    if not specialist_input:
        specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
        update.message.reply_text(f"{gpt_response_text}\n\nДоступные специалисты:\n{specialists_text}")
        return
    specialist = next((s for s in specialists if s[1].strip().lower() == specialist_input.strip().lower()), None)
    if not specialist:
        resolved_name = resolve_specialist_name(specialist_input, specialists)
        specialist = next((s for s in specialists if s[1].strip().lower() == resolved_name.strip().lower()), None)
    if not specialist:
        specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
        update.message.reply_text(f"Специалист не найден. Выберите из списка:\n\n{specialists_text}")
        return
    available_times = get_available_times(specialist[0], state['service_id'])
    if available_times:
        set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=specialist[0])
        times_text = "\n".join([f"- {t}" for t in available_times])
        update.message.reply_text(f"{gpt_response_text}\n\nДоступное время:\n{times_text}")
    else:
        update.message.reply_text(f"К сожалению, у специалиста {specialist[1]} нет свободного времени.")

def handle_select_time(update: telegram.Update, user_id: int, state: Dict, extracted_data: Dict, bot: telegram.Bot):
    if not state or not all(k in state for k in ['service_id', 'specialist_id']):
        services = get_services()
        if services:
            services_text = "\n".join([f"- {s[1]}" for s in services])
            update.message.reply_text("Сначала выберите услугу из списка:\n\n" + services_text)
        return
    available_times = get_available_times(state['specialist_id'], state['service_id'])
    if not available_times:
        alternative_specialist = find_available_specialist(state['service_id'], state['specialist_id'])
        if alternative_specialist:
            set_user_state(user_id, "select_specialist", service_id=state['service_id'])
            update.message.reply_text("К сожалению, у выбранного специалиста нет свободного времени.\n" +
                f"Вы можете записаться к {alternative_specialist[1]}. Хотите посмотреть доступное время?")
        else:
            update.message.reply_text("К сожалению, сейчас нет свободного времени для записи.\n" +
                "Попробуйте выбрать другую услугу или свяжитесь с администратором.")
        return
    chosen_time = None
    gpt_time = extracted_data.get('time')
    if gpt_time:
        chosen_time = parse_time_input(gpt_time, available_times)
    if chosen_time:
        set_user_state(user_id, "confirm", service_id=state['service_id'], specialist_id=state['specialist_id'], chosen_time=chosen_time)
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
        update.message.reply_text(f"Пожалуйста, выберите точное время из списка:\n\n{times_text}")

def handle_confirm_booking(update: telegram.Update, user_id: int, state: Dict, user_text: str, gpt_response_text: str, bot: telegram.Bot):
    if not state or not all(k in state for k in ['service_id', 'specialist_id', 'chosen_time']):
        update.message.reply_text("Недостаточно информации для создания записи.")
        return
    if user_text.lower() in ['да', 'yes', 'подтверждаю']:
        success = create_booking(user_id=user_id, serv_id=state['service_id'], spec_id=state['specialist_id'], date_str=state['chosen_time'])
        if success:
            service_name = get_service_name(state['service_id'])
            specialist_name = get_specialist_name(state['specialist_id'])
            update.message.reply_text(f"{gpt_response_text}")
            if MANAGER_CHAT_ID:
                bot.send_message(MANAGER_CHAT_ID,
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
    # Добавляем сообщение пользователя в историю
    from conversation import append_message
    append_message(user_id, "user", user_text)
    
    # Если пользователь явно ввёл название услуги (например, "стрижка")
    service_candidate = find_service_by_name(user_text)
    if service_candidate:
        if (not state) or (state.get('service_id') != service_candidate[0]):
            set_user_state(user_id, "select_specialist", service_id=service_candidate[0])
            specialists = get_specialists(service_candidate[0])
            if specialists:
                specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
                update.message.reply_text(f"Вы выбрали услугу '{service_candidate[1]}'. Теперь выберите специалиста:\n{specialists_text}")
            else:
                update.message.reply_text("К сожалению, нет доступных специалистов для выбранной услуги.")
            return

    try:
        result = get_gpt_response(user_id, user_text, state)
        action = result.get('action')
        extracted_data = result.get('extracted_data', {})
        gpt_response_text = result.get('response', '')
        append_message(user_id, "assistant", gpt_response_text)
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
        update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте сформулировать ваш запрос иначе или начните сначала.")
