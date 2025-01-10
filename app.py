# app.py
import os
import logging

from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# Импортируем функции из наших модулей
from db import init_db
from handlers import handle_message, handle_manager_commands, start

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
APP_URL = os.getenv("APP_URL")

if not TOKEN or not APP_URL:
    raise ValueError("Не все переменные окружения установлены (TOKEN, APP_URL)!")

app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)

# Создаём Dispatcher для Telegram
dispatcher = Dispatcher(bot, None, workers=4)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("register_manager", handle_manager_commands))
dispatcher.add_handler(CommandHandler("stop_notifications", handle_manager_commands))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """
    Главный webhook-эндпоинт, принимает JSON от Telegram и отдаёт dispatcher
    """
    upd = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(upd)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    """
    На корне просто возвращаем "Бот работает!"
    """
    return "Бот работает!", 200

def set_webhook():
    """
    Устанавливаем webhook по адресу {APP_URL}/{TOKEN}
    """
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

def set_webhook_docstring_expanded():
    """
    Повторная функция set_webhook, чисто для демонстрации.
    """
    pass

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
