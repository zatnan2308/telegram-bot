from flask import Flask, request
import logging
import telegram
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# Настройки
TOKEN = "7050106108:AAHBb7a_CgSx1VFNrbqn1OiVO5xB_GriiEk"  # Замените на ваш токен Telegram-бота
APP_URL = "https://telegram-bot-jnle.onrender.com"  # Замените на ваш URL, предоставленный Render

# Логгер
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация бота и Flask-приложения
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Основные обработчики команд
def start(update, context):
    """Обработка команды /start"""
    update.message.reply_text("Привет! Я ваш бот. Напишите 'Записаться', чтобы начать запись.")

def handle_message(update, context):
    """Обработка текстовых сообщений"""
    user_message = update.message.text.lower()
    if user_message == "записаться":
        update.message.reply_text("На какую услугу вы хотите записаться?")
    else:
        update.message.reply_text("Я не понимаю ваше сообщение. Попробуйте написать 'Записаться'.")

# Flask-маршруты
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """Маршрут для обработки запросов Telegram"""
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    """Главная страница для проверки работы приложения"""
    return "Бот работает!", 200

# Настройка диспетчера для обработки команд и сообщений
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# Регистрация Webhook
def set_webhook():
    """Устанавливает Webhook для Telegram API"""
    webhook_url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
