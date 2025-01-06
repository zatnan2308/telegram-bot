from flask import Flask, request
import logging
import telegram
from telegram import Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import os
import psycopg2
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")



def generate_ai_response(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.7
        )
        return response['choices'][0]['message']['content'].strip()
    except openai.error.RateLimitError:
        return "Извините, я временно не могу ответить. Попробуйте позже."
    except Exception as e:
        return f"Произошла ошибка: {e}"



# Настройки
TOKEN = os.getenv("TOKEN")  # Токен Telegram-бота из переменных окружения Render
DATABASE_URL = os.getenv("postgresql://telegram_bot_db_m0yt_user:Mb7sLI6eTJqaewWfSeitowpxUhue2l6s@dpg-cttkgbd2ng1s73ca4g1g-a/telegram_bot_db_m0yt")  # URL базы данных PostgreSQL из Render
APP_URL = os.getenv("APP_URL")  # URL приложения на Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # API-ключ OpenAI

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

# Функции для работы с ИИ
def generate_ai_response(prompt):
    """Генерация ответа от OpenAI GPT"""
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",  # Модель OpenAI
            prompt=prompt,
            max_tokens=150,
            temperature=0.7
        )
        return response.choices[0].text.strip()
    except Exception as e:
        return f"Ошибка: {e}"

# Telegram-обработчики
def start(update, context):
    """Обработка команды /start"""
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, "
        "или задайте мне любой вопрос!"
    )

def handle_message(update, context):
    """Обработка текстовых сообщений с помощью ИИ"""
    user_message = update.message.text

    # Если пользователь хочет записаться
    if "записаться" in user_message.lower():
        update.message.reply_text("На какую услугу вы хотите записаться?")
        # Логика для записи может быть добавлена здесь
    elif "мои записи" in user_message.lower():
        # Пример получения записей для специалиста
        specialist_id = 1  # Подставьте ID специалиста из базы
        bookings = get_bookings_for_specialist(specialist_id)
        if bookings:
            reply = "Ваши записи:\n" + "\n".join(
                [f"{b[0]} - {b[1]} (Клиент: {b[2]}, Телефон: {b[3]})" for b in bookings]
            )
        else:
            reply = "У вас нет предстоящих записей."
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
