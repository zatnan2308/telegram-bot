from flask import Flask, request
import logging
import telegram
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# Настройки
TOKEN = "7050106108:AAHBb7a_CgSx1VFNrbqn1OiVO5xB_GriiEk"  # Замените на ваш токен Telegram-бота
APP_URL = "https://telegram-bot-jnle.onrender.com"  # Замените на ваш URL, предоставленный Render

from flask import Flask, request
import logging
import telegram
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import os
import psycopg2

# Настройки
TOKEN = os.getenv("7050106108:AAHBb7a_CgSx1VFNrbqn1OiVO5xB_GriiEk")  # Токен Telegram-бота из переменных окружения Render
DATABASE_URL = os.getenv("postgresql://telegram_bot_db_m0yt_user:Mb7sLI6eTJqaewWfSeitowpxUhue2l6s@dpg-cttkgbd2ng1s73ca4g1g-a/telegram_bot_db_m0yt")  # URL базы данных PostgreSQL из Render
APP_URL = os.getenv("https://telegram-bot-jnle.onrender.com")  # URL приложения на Render

# Логгер
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и Flask-приложения
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# Подключение к базе данных
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# Основные функции для работы с базой данных
def create_booking(org_id, client_name, client_phone, service_id, specialist_id, date):
    """Добавление новой записи"""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO bookings (org_id, client_name, client_phone, service_id, specialist_id, date)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    cursor.execute(query, (org_id, client_name, client_phone, service_id, specialist_id, date))
    conn.commit()
    cursor.close()
    conn.close()

def get_bookings_for_specialist(specialist_id):
    """Получение записей для специалиста"""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    SELECT b.date, s.title AS service, b.client_name, b.client_phone
    FROM bookings b
    JOIN services s ON b.service_id = s.id
    WHERE b.specialist_id = %s AND b.date >= NOW()
    ORDER BY b.date
    """
    cursor.execute(query, (specialist_id,))
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    return bookings

# Telegram-обработчики
def start(update, context):
    """Обработка команды /start"""
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись."
    )

def handle_message(update, context):
    """Обработка текстовых сообщений"""
    user_message = update.message.text.lower()
    if user_message == "записаться":
        # Здесь вы можете добавить логику выбора услуги, специалиста и времени
        update.message.reply_text("На какую услугу вы хотите записаться?")
    elif user_message == "мои записи":
        # Получение записей для специалиста
        specialist_id = 1  # Здесь подставьте реальный ID специалиста (например, из базы)
        bookings = get_bookings_for_specialist(specialist_id)
        if bookings:
            reply = "Ваши записи:\n" + "\n".join(
                [f"{b[0]} - {b[1]} (Клиент: {b[2]}, Телефон: {b[3]})" for b in bookings]
            )
        else:
            reply = "У вас нет предстоящих записей."
        update.message.reply_text(reply)
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

# Настройка диспетчера
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
