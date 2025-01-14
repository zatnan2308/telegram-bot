from telegram import Update
from telegram.ext import CallbackContext
# В начале файла handlers/commands.py:
from database.queries import get_services


def start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start"""
    update.message.reply_text(
        "Привет! Я бот для управления записями в салон красоты.\n"
        "Напишите 'Записаться', чтобы начать процесс, или задайте любой вопрос!"
    )

def help_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /help"""
    update.message.reply_text(
        "Доступные команды:\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n\n"
        "Чтобы записаться, просто напишите 'Записаться' или название услуги.\n"
        "Для отмены записи напишите 'Отменить запись'."
    )
    
def spec_list_command(update: Update, context: CallbackContext):
    """
    Показывает список всех специалистов.
    """
    specialists = get_specialists()
    text = "Список специалистов:\n"
    for sp_id, sp_name in specialists:
        text += f"- [{sp_id}] {sp_name}\n"
    
    update.message.reply_text(text)

def service_list_command(update: Update, context: CallbackContext):
    """
    Показывает список всех услуг.
    """
    services = get_services()
    text = "Список услуг:\n"
    for serv_id, serv_title in services:
        text += f"- [{serv_id}] {serv_title}\n"
    
    update.message.reply_text(text)
