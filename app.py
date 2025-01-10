# ------------------- main.py -------------------
from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# Подтягиваем настройки: токен бота и URL
from config.settings import TOKEN, APP_URL

# Инициализация БД
from database.connection import init_db

# Обычные команды
from handlers.commands import start, help_command

# Основной обработчик сообщений
from handlers.messages import handle_message

# Обработка команд менеджера (пример: /register_manager, /stop_notifications)
from handlers.manager import handle_manager_commands

# Админские команды:
from handlers.admin_commands import (
    admin_command_add_service,
    admin_command_add_specialist,
    admin_command_add_manager
)

# Логгер
from utils.logger import logger

# Импортируем BotCommand для настройки списка команд
from telegram import BotCommand

app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)

# -----------------------------------------------------------------------------
# Функция для установки списка команд, чтобы при вводе / в Телеграме
# пользователю отображались подсказки.
# -----------------------------------------------------------------------------
def setup_commands(bot):
    """
    Устанавливает список команд бота, 
    которые будут отображаться при вводе '/' в Telegram.
    """
    commands = [
        BotCommand("start", "Начать работу"),
        BotCommand("help", "Получить справку"),
        BotCommand("add_service", "Добавить услугу"),
        BotCommand("add_specialist", "Добавить специалиста"),
        BotCommand("add_manager", "Добавить менеджера"),
        # Можно добавлять другие команды по вашему желанию
    ]
    bot.set_my_commands(commands)

# -----------------------------------------------------------------------------
# Создаём Dispatcher и регистрируем все обработчики.
# Обратите внимание, что порядок регистрации тоже может иметь значение.
# -----------------------------------------------------------------------------
dispatcher = Dispatcher(bot, None, workers=4)

# Базовые команды
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))

# Команды менеджера
dispatcher.add_handler(CommandHandler("register_manager", handle_manager_commands))
dispatcher.add_handler(CommandHandler("stop_notifications", handle_manager_commands))

# Админские команды
dispatcher.add_handler(CommandHandler("add_service", admin_command_add_service))
dispatcher.add_handler(CommandHandler("add_specialist", admin_command_add_specialist))
dispatcher.add_handler(CommandHandler("add_manager", admin_command_add_manager))

# Основной обработчик всех остальных текстовых сообщений
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# -----------------------------------------------------------------------------
# Функции Flask для вебхука
# -----------------------------------------------------------------------------
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """Главный обработчик вебхука от Telegram."""
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    """Корневой маршрут, просто возвращает текст."""
    return "Бот работает!", 200

def set_webhook():
    """Устанавливаем вебхук на URL, указанный в APP_URL."""
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

# -----------------------------------------------------------------------------
# Точка входа
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Инициализируем базу
    init_db()

    # Настраиваем вебхук
    set_webhook()

    # Устанавливаем список команд (подсказки при вводе /)
    setup_commands(bot)

    # Запуск Flask
    app.run(host="0.0.0.0", port=5000)
