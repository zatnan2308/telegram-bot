from typing import Optional, Dict
import telegram

from database.queries import get_user_state, get_user_bookings
from services.gpt import determine_intent
from handlers.booking import handle_booking_with_gpt
from utils.logger import logger

def handle_message(update: telegram.Update, context) -> None:
    """Основной обработчик всех текстовых сообщений"""
    try:
        user_id = update.message.from_user.id
        user_text = update.message.text
        state = get_user_state(user_id)

        # Если пользователь на этапе подтверждения
        if state and state.get('step') == 'confirm':
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Определяем намерение через GPT
        intent = determine_intent(user_text)
        logger.info(f"Intent for user {user_id}: {intent}")

        # Обработка намерения "записаться"
        if "запис" in user_text.lower() or intent['intent'] == 'BOOKING_INTENT':
            existing = get_user_bookings(user_id)
            if existing:
                update.message.reply_text(
                    "У вас уже есть активная запись. Хотите записаться ещё раз? (да/нет)"
                )
                set_user_state(user_id, "confirm_additional_booking")
                return
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Базовые команды отмены
        if user_text.lower() in ['отмена', 'cancel', 'стоп', 'stop']:
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён.")
            return

        # Отмена существующей записи
        if "отмен" in user_text.lower():
            handle_cancellation(update, user_id)
            return

        # Если пользователь в процессе выбора специалиста
        if state and state['step'] == 'select_specialist':
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Для всех остальных случаев
        handle_general_question(update, user_id, user_text)

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте позже или напишите /start"
        )
