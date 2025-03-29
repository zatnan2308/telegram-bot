from typing import Optional
import telegram
from telegram.ext import CallbackContext
from database.queries import (
    add_free_time_slot,
    remove_free_time_slot,
    get_free_time_slots
)
from services.gpt import resolve_free_time
from utils.logger import logger

# Команда для добавления свободного времени через меню или свободный ввод.
def add_freetime_command(update: telegram.Update, context: CallbackContext) -> None:
    """
    Обработка команды /add_freetime.
    Специалист или менеджер может добавить свободные слоты.
    Варианты ввода:
      - Через меню: команда запрашивает ID услуги, затем временной слот.
      - Через свободный ввод: например, "завтра весь день свободен", "освободи 27 числа в 15:00".
    """
    user_id = update.message.from_user.id
    # Если аргументы переданы, используем их напрямую
    args = context.args
    if args:
        # Предполагаем, что первый аргумент — ID услуги, а оставшиеся — временной слот или описание
        try:
            service_id = int(args[0])
        except ValueError:
            update.message.reply_text("Первый аргумент должен быть числом — ID услуги.")
            return
        free_time_input = " ".join(args[1:])
        # Если free_time_input содержит формат времени (например, "2025-03-27 15:00"), попробуем добавить один слот
        # Иначе, интерпретируем с помощью GPT
        if ":" in free_time_input and "-" in free_time_input:
            slots = [free_time_input]
        else:
            slots = resolve_free_time(free_time_input)
        successes = []
        for slot in slots:
            if add_free_time_slot(update.message.from_user.id, service_id, slot):
                successes.append(slot)
        if successes:
            update.message.reply_text(f"Добавлены следующие свободные слоты: {', '.join(successes)}")
        else:
            update.message.reply_text("Не удалось добавить свободное время. Проверьте ввод.")
    else:
        update.message.reply_text("Используйте команду: /add_freetime <ID услуги> <описание свободного времени>.\nНапример: /add_freetime 2 завтра весь день свободен")

# Команда для удаления свободного времени
def remove_freetime_command(update: telegram.Update, context: CallbackContext) -> None:
    """
    Обработка команды /remove_freetime.
    Пользователь указывает ID услуги и временной слот для удаления.
    Ввод может быть неструктурированным, поэтому можно использовать GPT для интерпретации.
    """
    args = context.args
    if args:
        try:
            service_id = int(args[0])
        except ValueError:
            update.message.reply_text("Первый аргумент должен быть числом — ID услуги.")
            return
        free_time_input = " ".join(args[1:])
        # Если формат точный, используем его, иначе интерпретируем через GPT
        if ":" in free_time_input and "-" in free_time_input:
            slots = [free_time_input]
        else:
            slots = resolve_free_time(free_time_input)
        removed = []
        for slot in slots:
            if remove_free_time_slot(update.message.from_user.id, service_id, slot):
                removed.append(slot)
        if removed:
            update.message.reply_text(f"Удалены следующие свободные слоты: {', '.join(removed)}")
        else:
            update.message.reply_text("Не найдено свободное время для удаления с указанными параметрами.")
    else:
        update.message.reply_text("Используйте команду: /remove_freetime <ID услуги> <описание времени для удаления>.\nНапример: /remove_freetime 2 освободи 27 числа в 15:00")

# Команда для просмотра свободного времени
def list_freetime_command(update: telegram.Update, context: CallbackContext) -> None:
    """
    Обработка команды /list_freetime.
    Возвращает список свободных слотов для специалиста.
    Если указан ID услуги, фильтрует по ней.
    """
    args = context.args
    user_id = update.message.from_user.id
    if args:
        try:
            service_id = int(args[0])
        except ValueError:
            update.message.reply_text("Первый аргумент должен быть числом — ID услуги, либо его можно опустить.")
            return
        slots = get_free_time_slots(user_id, service_id)
    else:
        slots = get_free_time_slots(user_id)
    if slots:
        update.message.reply_text("Ваши свободные слоты:\n" + "\n".join(slots))
    else:
        update.message.reply_text("Свободные слоты не найдены.")
