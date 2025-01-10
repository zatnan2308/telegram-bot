from typing import Optional, Dict
import telegram
from telegram.ext import CallbackContext

from database.queries import get_user_state, get_user_bookings, set_user_state, delete_user_state
from services.gpt import determine_intent
from handlers.booking import handle_booking_with_gpt
from utils.logger import logger

def handle_message(update: telegram.Update, context: CallbackContext) -> None:
    """Основной обработчик всех текстовых сообщений"""
    try:
        user_id = update.message.from_user.id
        user_text = update.message.text
        
        # Получаем текущее состояние пользователя
        state = get_user_state(user_id)
        
        # Если текст начинается с '/', это команда
        if user_text.startswith('/'):
            handle_commands(update, user_id, user_text)
            return

        # Если пользователь на этапе подтверждения
        if state and state.get('step') == 'confirm':
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Базовые команды отмены
        if user_text.lower() in ['отмена', 'cancel', 'стоп', 'stop']:
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён.")
            return

        # В остальных случаях обрабатываем как часть процесса бронирования
        handle_booking_with_gpt(update, user_id, user_text, state)
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        update.message.reply_text(
            "Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте еще раз."
        )

def handle_commands(update: telegram.Update, user_id: int, command: str) -> None:
    """Обработчик команд"""
    if command == '/start':
        update.message.reply_text(
            "Добро пожаловать! Я помогу вам записаться на услуги нашего салона красоты. "
            "Что вы хотели бы сделать?"
        )
    elif command == '/help':
        update.message.reply_text(
            "Я могу помочь вам:\n"
            "- Показать список доступных услуг\n"
            "- Записать вас к специалисту\n"
            "- Показать ваши текущие записи\n\n"
            "Просто напишите, что вы хотите сделать, и я помогу!"
        )
    elif command == '/bookings':
        bookings = get_user_bookings(user_id)
        if bookings:
            message = "Ваши активные записи:\n\n"
            for booking in bookings:
                message += (
                    f"📅 {booking['date_time']}\n"
                    f"🎯 Услуга: {booking['service_name']}\n"
                    f"👩‍💼 Специалист: {booking['specialist_name']}\n"
                    "-------------------\n"
                )
            update.message.reply_text(message)
        else:
            update.message.reply_text("У вас нет активных записей.")
    else:
        update.message.reply_text(
            "Неизвестная команда. Используйте:\n"
            "/start - начать работу с ботом\n"
            "/help - получить справку\n"
            "/bookings - посмотреть ваши записи"
        )

def handle_cancellation(update: telegram.Update, user_id: int) -> None:
    """Обработка отмены записи"""
    bookings = get_user_bookings(user_id)
    if not bookings:
        update.message.reply_text("У вас нет активных записей для отмены.")
        return

    message = "Какую запись вы хотите отменить?\n\n"
    for i, booking in enumerate(bookings, 1):
        message += (
            f"{i}. {booking['date_time']}\n"
            f"Услуга: {booking['service_name']}\n"
            f"Специалист: {booking['specialist_name']}\n"
            "-------------------\n"
        )
    update.message.reply_text(message)
    set_user_state(user_id, "cancelling_booking")
