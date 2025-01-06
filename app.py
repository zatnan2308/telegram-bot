from flask import Flask, request
import logging
import telegram
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import os
import psycopg2
import openai

# Настройки
TOKEN = os.getenv("TOKEN")  # Токен Telegram-бота
DATABASE_URL = os.getenv("DATABASE_URL")  # URL базы данных PostgreSQL
APP_URL = os.getenv("APP_URL")  # URL приложения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # API-ключ OpenAI

if not TOKEN or not APP_URL or not OPENAI_API_KEY:
    raise ValueError("Переменные окружения 'TOKEN', 'APP_URL' и 'OPENAI_API_KEY' должны быть установлены.")

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
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# Основные функции для работы с базой данных
def get_bookings_for_user(user_id):
    """Получение записей для конкретного пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    SELECT b.date, s.title AS service, sp.name AS specialist
    FROM bookings b
    JOIN services s ON b.service_id = s.id
    JOIN specialists sp ON b.specialist_id = sp.id
    WHERE b.user_id = %s
    """
    cursor.execute(query, (user_id,))
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()

    # Преобразуем записи в удобный формат
    return [{"date": b[0], "service": b[1], "specialist": b[2]} for b in bookings]

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

# Функция для генерации ответа с использованием OpenAI GPT
def generate_ai_response(prompt):
    """Генерация ответа от OpenAI GPT"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Или "gpt-4", если требуется более мощная модель
            messages=[
                {"role": "system", "content": "Ты — умный Telegram-бот, помогай пользователю."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )
        return response['choices'][0]['message']['content'].strip()
    except openai.error.RateLimitError:
        return "Извините, я временно не могу обработать ваш запрос. Попробуйте позже."
    except Exception as e:
        return f"Произошла ошибка: {e}"

# Telegram-обработчики
def start(update, context):
    """Обработка команды /start"""
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, "
        "или задайте мне любой вопрос!"
    )

def handle_message(update, context):
    """Обработка текстовых сообщений с использованием OpenAI GPT и локальной логики"""
    user_message = update.message.text.lower()
    user_id = update.message.chat_id

    # Если пользователь спрашивает про свои записи
    if "у меня есть запись" in user_message:
        bookings = get_bookings_for_user(user_id)
        if bookings:
            reply = "Ваши записи:\n" + "\n".join(
                [f"{b['date']} - {b['service']} (Специалист: {b['specialist']})" for b in bookings]
            )
        else:
            reply = "У вас нет записей."
        update.message.reply_text(reply)
    else:
        # Используем OpenAI для ответа
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)

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
