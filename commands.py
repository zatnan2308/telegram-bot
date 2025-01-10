from telegram import Update
from telegram.ext import CallbackContext

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
