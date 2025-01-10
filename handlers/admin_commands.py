from telegram import Update
from telegram.ext import CallbackContext
from utils.logger import logger
from database.queries import (
    create_service, 
    create_specialist, 
    create_manager_in_db  # условные функции, нужно будет дописать
)
from config.settings import ADMIN_ID  # ваш telegram ID администратора
# handlers/admin_commands.py
from typing import Optional
from database.queries import set_service_duration

def admin_command_set_service_duration(update: Update, context: CallbackContext) -> None:
    """Админ: установить длительность услуги в минутах."""
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Использование: /set_service_duration <id_услуги> <минуты>")
        return
    
    try:
        service_id = int(args[0])
        duration = int(args[1])
    except ValueError:
        update.message.reply_text("Нужно ввести числа: /set_service_duration 2 60")
        return

    success = set_service_duration(service_id, duration)
    if success:
        update.message.reply_text(f"Длительность услуги (ID={service_id}) установлена на {duration} мин.")
    else:
        update.message.reply_text("Ошибка установки длительности (возможно, нет такой услуги).")


def admin_command_add_service(update: Update, context: CallbackContext) -> None:
    """Позволяет администратору добавить новую услугу в БД."""
    user_id = update.message.from_user.id
    # Проверяем, что команду выполняет именно админ
    if user_id != ADMIN_ID:
        update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Предположим, что команда приходит в формате:
    # /add_service <название_услуги> <цена>
    # Например: /add_service Массаж_ног 500
    # Разбираем аргументы
    args = context.args
    if len(args) < 2:
        update.message.reply_text(
            "Использование: /add_service <название_услуги> <цена>\n"
            "Пример: /add_service Массаж_ног 500"
        )
        return
    
    service_name = args[0]
    price_str = args[1]
    
    # Пытаемся преобразовать price_str в число
    try:
        price = float(price_str)
    except ValueError:
        update.message.reply_text("Цена должна быть числом (например, 500 или 499.99).")
        return
    
    created = create_service(service_name, price)
    if created:
        update.message.reply_text(f"Услуга '{service_name}' успешно добавлена (цена = {price}).")
    else:
        update.message.reply_text("Ошибка при создании услуги. Возможно она уже существует.")

def admin_command_add_specialist(update: Update, context: CallbackContext) -> None:
    """Позволяет администратору добавить нового специалиста."""
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # /add_specialist <ФИО_или_Имя> 
    args = context.args
    if len(args) < 1:
        update.message.reply_text(
            "Использование: /add_specialist <имя_специалиста>\n"
            "Пример: /add_specialist Анна_Иванова"
        )
        return
    
    spec_name = args[0]
    # Можно далее дополнять логику: добавить "специализацию" и т.д.
    created = create_specialist(spec_name)
    if created:
        update.message.reply_text(f"Специалист '{spec_name}' успешно добавлен.")
    else:
        update.message.reply_text(f"Ошибка при создании специалиста '{spec_name}'.")

def admin_command_add_manager(update: Update, context: CallbackContext) -> None:
    """Позволяет админу регистрировать нового менеджера."""
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    # /add_manager <chat_id> <username?>
    args = context.args
    if len(args) < 1:
        update.message.reply_text("Использование: /add_manager <chat_id> [username]")
        return

    manager_chat_id_str = args[0]
    manager_username = args[1] if len(args) >= 2 else None

    try:
        manager_chat_id = int(manager_chat_id_str)
    except ValueError:
        update.message.reply_text("chat_id должен быть числом")
        return
    
    created = create_manager_in_db(manager_chat_id, manager_username)
    if created:
        update.message.reply_text(
            f"Менеджер (chat_id={manager_chat_id}, user={manager_username}) успешно добавлен."
        )
    else:
        update.message.reply_text("Ошибка при создании менеджера (возможно уже есть).")

def admin_command_set_service_duration(update: Update, context: CallbackContext) -> None:
    """Админ: установить длительность услуги в минутах."""
    # Проверяем права, опускаем детали
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Использование: /set_service_duration <id_услуги> <минуты>")
        return
    
    service_id = int(args[0])
    duration = int(args[1])

    success = set_service_duration(service_id, duration)
    if success:
        update.message.reply_text(f"Длительность услуги (ID={service_id}) установлена на {duration} мин.")
    else:
        update.message.reply_text("Ошибка установки длительности.")

