from typing import Optional
from telegram import Update
from telegram.ext import CallbackContext
from database.queries import get_bookings_for_specialist, cancel_booking_by_id, get_specialist_name, get_available_times, add_service_to_specialist
from utils.logger import logger

def specialist_command_free_time(update: Update, context: CallbackContext):
    args = context.args
    if not args:
        update.message.reply_text("Укажите ID специалиста. Пример: /spec_free_time 3")
        return
    try:
        spec_id = int(args[0])
    except ValueError:
        update.message.reply_text("Укажите корректный ID специалиста (число). Пример: /spec_free_time 3")
        return
    spec_name = get_specialist_name(spec_id)
    if not spec_name:
        update.message.reply_text(f"Специалист с id={spec_id} не найден.")
        return
    free_times = get_available_times(spec_id=spec_id, serv_id=None)
    if not free_times:
        update.message.reply_text(f"У специалиста {spec_name} (id={spec_id}) нет свободного времени.")
        return
    times_str = "\n".join([f"🕐 {t}" for t in free_times])
    update.message.reply_text(f"Свободные слоты для {spec_name} (id={spec_id}):\n\n{times_str}")

def specialist_command_appointments(update: Update, context: CallbackContext):
    args = context.args
    if not args:
        update.message.reply_text("Укажите ID специалиста. Пример: /spec_appointments 3")
        return
    try:
        spec_id = int(args[0])
    except ValueError:
        update.message.reply_text("Укажите корректный ID специалиста (число). Пример: /spec_appointments 3")
        return
    spec_name = get_specialist_name(spec_id)
    if not spec_name:
        update.message.reply_text(f"Специалист с id={spec_id} не найден.")
        return
    bookings = get_bookings_for_specialist(spec_id)
    if not bookings:
        update.message.reply_text(f"У {spec_name} (id={spec_id}) нет активных записей.")
        return
    lines = []
    for b in bookings:
        lines.append(
            f"📅 ID брони: {b['id']}\n"
            f"   Дата/время: {b['date_time']}\n"
            f"   Услуга: {b['service_name']}\n"
            f"   Клиент: ID {b['user_id']} (Имя: {b['user_name']})"
        )
    msg = "\n\n".join(lines)
    update.message.reply_text(f"Активные записи для {spec_name} (id={spec_id}):\n\n{msg}")

def specialist_command_cancel_booking(update: Update, context: CallbackContext):
    args = context.args
    if not args:
        update.message.reply_text("Укажите ID брони для отмены. Пример: /spec_cancel_booking 42")
        return
    try:
        booking_id = int(args[0])
    except ValueError:
        update.message.reply_text("Укажите корректный ID брони (число). Пример: /spec_cancel_booking 42")
        return
    ok, message = cancel_booking_by_id(booking_id)
    update.message.reply_text(message)

def specialist_command_add_service(update: Update, context: CallbackContext):
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Укажите ID специалиста и ID услуги. Пример: /spec_add_service 3 2")
        return
    try:
        spec_id = int(args[0])
        serv_id = int(args[1])
    except ValueError:
        update.message.reply_text("Ожидались числовые ID. Пример: /spec_add_service 3 2")
        return
    result_msg = add_service_to_specialist(spec_id, serv_id)
    update.message.reply_text(result_msg)
