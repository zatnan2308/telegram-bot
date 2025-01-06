from flask import Flask, request
import logging
import telegram
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import psycopg2
import openai
import datetime

# Настройки
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
APP_URL = os.getenv("APP_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")

if not TOKEN or not APP_URL or not OPENAI_API_KEY or not MANAGER_CHAT_ID:
    raise ValueError("Переменные окружения 'TOKEN', 'APP_URL', 'OPENAI_API_KEY' и 'MANAGER_CHAT_ID' должны быть установлены.")

# Инициализация OpenAI
openai.api_key = OPENAI_API_KEY

# Логгер
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и Flask-приложения
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Подключение к базе данных
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Регистрация пользователя
def register_user(telegram_id, name, phone="0000000000"):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO users (telegram_id, name, phone)
    VALUES (%s, %s, %s)
    ON CONFLICT (telegram_id) DO NOTHING;
    """
    cursor.execute(query, (telegram_id, name, phone))
    conn.commit()
    cursor.close()
    conn.close()

# Получение списка услуг
def get_services():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, title FROM services;"
    cursor.execute(query)
    services = cursor.fetchall()
    cursor.close()
    conn.close()
    return services

# Получение списка специалистов
def get_specialists():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, name FROM specialists;"
    cursor.execute(query)
    specialists = cursor.fetchall()
    cursor.close()
    conn.close()
    return specialists

# Определение намерения пользователя через OpenAI
def determine_intent(user_message):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": (
                    "Ты - Telegram-бот для управления записями. "
                    "Твоя задача - определять намерения пользователя, такие как 'услуги', 'специалисты', 'записаться', или 'другое'."
                )},
                {"role": "user", "content": user_message}
            ],
            max_tokens=20
        )
        intent = response['choices'][0]['message']['content'].strip().lower()
        return intent
    except Exception as e:
        logger.error(f"Ошибка определения намерения: {e}")
        return "другое"

# Генерация ответа через OpenAI
def generate_ai_response(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ты — умный Telegram-бот, помогай пользователю."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"Ошибка: {e}"
        

def handle_message(update, context):
    """Обработка текстовых сообщений с использованием OpenAI и базы данных"""
    user_message = update.message.text.lower()
    user_id = update.message.chat_id

    # Регистрация пользователя
    register_user(user_id, update.message.chat.first_name)

    # Проверяем намерение
    intent = determine_intent(user_message)
    logger.info(f"User message: {user_message}, Determined intent: {intent}")

    if intent == "услуги":
        # Получение списка услуг из базы данных
        services = get_services()
        if services:
            service_list = "\n".join([f"{service[0]}. {service[1]}" for service in services])
            update.message.reply_text(f"Доступные услуги:\n{service_list}")
        else:
            update.message.reply_text("На данный момент нет доступных услуг.")
    elif intent == "специалисты":
        # Получение списка специалистов из базы данных
        specialists = get_specialists()
        if specialists:
            specialist_list = "\n".join([f"{specialist[0]}. {specialist[1]}" for specialist in specialists])
            update.message.reply_text(f"Доступные специалисты:\n{specialist_list}")
        else:
            update.message.reply_text("На данный момент нет доступных специалистов.")
    elif intent == "записаться":
        # Логика записи
        user_booking_state[user_id] = {'step': 'select_service'}
        services = get_services()
        service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
        update.message.reply_text(f"Доступные услуги:\n{service_list}\nВведите название услуги.")
    else:
        # Если намерение не определено, используем OpenAI для общего ответа
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)


# Telegram-обработчики
def start(update, context):
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, "
        "или задайте мне любой вопрос!"
    )

# Flask-маршруты
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

# Настройка диспетчера
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# Регистрация Webhook
def set_webhook():
    webhook_url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
