# handlers.py
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

# Импортируем функции из db.py, booking_logic.py, gpt_utils.py и т.п.
from db import init_db, get_db_connection, register_user, get_user_state, set_user_state, delete_user_state
from booking_logic import (
    get_available_times,
    parse_time_input,
    create_booking,
    cancel_booking,
    get_user_bookings,
)
from gpt_utils import determine_intent

logger = logging.getLogger(__name__)

MANAGER_CHAT_ID = None  # Или подставьте os.getenv("MANAGER_CHAT_ID")


def handle_manager_commands(update, context):
    """
    Обработка команд менеджера:
    /register_manager
    /stop_notifications
    """
    command = update.message.text
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    # Реализуйте при необходимости
    if command == '/register_manager':
        update.message.reply_text("Здесь логика регистрации менеджера")
    elif command == '/stop_notifications':
        update.message.reply_text("Здесь логика отключения уведомлений")


def start(update, context):
    """
    Приветственное сообщение по /start
    """
    update.message.reply_text(
        "Привет! Я бот для управления записями в салон красоты.\n"
        "Напишите 'Записаться', чтобы начать процесс, или задайте любой вопрос!"
    )


def handle_message(update, context):
    """
    Основной обработчик сообщений (не команд).
    Здесь вся логика: проверка state, confirm, intent и т.п.
    """
    try:
        user_text = update.message.text.strip()
        user_id = update.message.chat_id
        user_name = update.message.chat.first_name or "Unknown"

        logger.info(f"Получено сообщение от user_id={user_id}, name={user_name}: {user_text}")

        # Регистрируем (или обновляем) пользователя в базе
        register_user(user_id, user_name)

        # Получаем текущее состояние пользователя
        state = get_user_state(user_id)
        logger.info(f"Текущее состояние: {state}")

        # 1. Если пользователь уже на шаге "confirm", обрабатываем "да"/"нет" напрямую
        if state and state.get('step') == 'confirm':
            confirmation_text = user_text.strip().lower().strip('.,!?')
            positive_answers = ['да','yes','подтверждаю','ок','конечно','да.','yes.','подтверждаю.','да!','yes!']
            negative_answers = ['нет','no','отмена','cancel','stop','нет.','no.','нет!','no!']

            if confirmation_text in positive_answers:
                ok = create_booking(
                    user_id,
                    state['service_id'],
                    state['specialist_id'],
                    state['chosen_time']
                )
                if ok:
                    # Дополнительно можно получить название услуги, специалиста, вывести время
                    update.message.reply_text("✅ Запись подтверждена!")
                else:
                    update.message.reply_text("❌ Ошибка при создании записи.")
                delete_user_state(user_id)
                return

            elif confirmation_text in negative_answers:
                update.message.reply_text("Запись отменена.")
                delete_user_state(user_id)
                return

            else:
                update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")
                return

        # 2. Иначе обычная схема: определяем intent
        intent_data = determine_intent(user_text)
        logger.info(f"Определён intent: {intent_data}")
        intent = intent_data['intent']

        # Явное желание «записаться»
        if "запис" in user_text.lower() or intent == 'BOOKING_INTENT':
            # Проверяем, нет ли уже активных записей
            existing = get_user_bookings(user_id)
            if existing:
                update.message.reply_text("У вас уже есть активная запись.")
                # Можете добавить логику «доп.запись?»
                return
            # Иначе переходим к логике бронирования...
            # handle_booking_with_gpt(...) или любая другая функция
            update.message.reply_text("Здесь вызов логики бронирования")
            return

        # Обработка «отмена»
        if user_text.lower() in ['отмена','cancel','стоп','stop']:
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён.")
            return

        if "отмен" in user_text.lower():
            # Логика отмены
            bookings = get_user_bookings(user_id)
            if bookings:
                success = cancel_booking(user_id, bookings[0]['id'])
                if success:
                    update.message.reply_text("Запись отменена.")
                else:
                    update.message.reply_text("Не удалось отменить запись.")
            else:
                update.message.reply_text("У вас нет активных записей.")
            delete_user_state(user_id)
            return

        # И т.д. (обработка других намерений, либо общий GPT-ответ)
        update.message.reply_text("Здесь можно добавить другую логику ответа")

    except Exception as e:
        logger.error(f"Ошибка handle_message: {e}", exc_info=True)
        update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже или напишите /start")
