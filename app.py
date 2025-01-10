from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

from config.settings import TOKEN, APP_URL
from database.connection import init_db
from handlers.commands import start, help_command
from handlers.messages import handle_message
from handlers.manager import handle_manager_commands
from utils.logger import logger

# Инициализация Flask и Telegram бота
app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)

# Создаём Dispatcher
dispatcher = Dispatcher(bot, None, workers=4)

# Регистрируем обработчики
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("register_manager", handle_manager_commands))
dispatcher.add_handler(CommandHandler("stop_notifications", handle_manager_commands))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """Обработчик вебхука от Telegram"""
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    """Корневой маршрут"""
    return "Бот работает!", 200

def set_webhook():
    """Установка вебхука"""
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

if __name__ == "__main__":
    # Инициализация базы данных
    init_db()
    # Установка вебхука
    set_webhook()
    # Запуск Flask-приложения
    app.run(host="0.0.0.0", port=5000)
