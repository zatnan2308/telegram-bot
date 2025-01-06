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
TOKEN = os.getenv("TOKEN")  # Токен Telegram-бота
DATABASE_URL = os.getenv("DATABASE_URL")  # URL базы данных PostgreSQL
APP_URL = os.getenv("APP_URL")  # URL приложения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # API-ключ OpenAI
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")  # ID менеджера

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


def handle_message(update, context):
    """Обработка текстовых сообщений с использованием базы данных и OpenAI GPT"""
    user_message = update.message.text.lower()
    user_id = update.message.chat_id

    # Регистрация пользователя
    register_user(user_id, update.message.chat.first_name)

    if "какие услуги есть" in user_message:
        # Получение списка услуг из базы данных
        services = get_services()
        if services:
            service_list = "\n".join([f"{service[0]}. {service[1]}" for service in services])
            update.message.reply_text(f"Доступные услуги:\n{service_list}")
        else:
            update.message.reply_text("На данный момент нет доступных услуг.")
    elif "специалисты" in user_message:
        # Получение списка специалистов
        specialists = get_specialists()
        if specialists:
            specialist_list = "\n".join([f"{specialist[0]}. {specialist[1]}" for specialist in specialists])
            update.message.reply_text(f"Доступные специалисты:\n{specialist_list}")
        else:
            update.message.reply_text("На данный момент нет доступных специалистов.")
    elif "записаться" in user_message:
        update.message.reply_text("Пожалуйста, выберите услугу и специалиста, чтобы записаться.")
    else:
        # Ответ через OpenAI
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)






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

# Получение записей для пользователя
def get_bookings_for_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    SELECT b.date, s.title AS service, sp.name AS specialist
    FROM bookings b
    JOIN services s ON b.service_id = s.id
    JOIN specialists sp ON b.specialist_id = sp.id
    WHERE b.user_id = %s
    ORDER BY b.date;
    """
    cursor.execute(query, (user_id,))
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"date": b[0], "service": b[1], "specialist": b[2]} for b in bookings]

# Создание записи
def create_booking(user_id, service_id, specialist_id, date):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO bookings (user_id, service_id, specialist_id, date)
    VALUES (%s, %s, %s, %s);
    """
    cursor.execute(query, (user_id, service_id, specialist_id, date))
    conn.commit()
    cursor.close()
    conn.close()

# Telegram-обработчики
def start(update, context):
    """Обработка команды /start"""
    user_id = update.message.chat_id
    name = update.message.chat.first_name

    # Регистрация пользователя
    register_user(user_id, name)

    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, "
        "или задайте мне любой вопрос!"
    )

def show_services(update, context):
    """Вывод списка услуг"""
    services = get_services()
    if services:
        service_list = "\n".join([f"{service[0]}. {service[1]}" for service in services])
        update.message.reply_text(f"Доступные услуги:\n{service_list}")
    else:
        update.message.reply_text("На данный момент нет доступных услуг.")

def show_specialists(update, context):
    """Вывод списка специалистов"""
    specialists = get_specialists()
    if specialists:
        specialist_list = "\n".join([f"{specialist[0]}. {specialist[1]}" for specialist in specialists])
        update.message.reply_text(f"Доступные специалисты:\n{specialist_list}")
    else:
        update.message.reply_text("На данный момент нет доступных специалистов.")

def check_booking(update, context):
    """Проверка записей пользователя"""
    user_id = update.message.chat_id
    bookings = get_bookings_for_user(user_id)
    if bookings:
        reply = "Ваши записи:\n" + "\n".join(
            [f"{b['date']} - {b['service']} (Специалист: {b['specialist']})" for b in bookings]
        )
    else:
        reply = "У вас нет активных записей."
    update.message.reply_text(reply)

def book_service(update, context):
    """Создание записи"""
    user_id = update.message.chat_id
    service_id = 1  # Пример ID услуги (можно запросить у пользователя)
    specialist_id = 1  # Пример ID специалиста (можно запросить у пользователя)
    date = "2025-01-07 14:00:00"  # Пример даты (можно запросить у пользователя)

    create_booking(user_id, service_id, specialist_id, date)
    update.message.reply_text("Вы успешно записались на услугу!")

def contact_manager(update, context):
    """Связь с менеджером"""
    user_id = update.message.chat_id
    user_message = update.message.text
    bot.send_message(
        chat_id=MANAGER_CHAT_ID,
        text=f"Сообщение от клиента {user_id}:\n{user_message}"
    )
    update.message.reply_text("Ваше сообщение было отправлено менеджеру. Мы скоро свяжемся с вами.")

def handle_message(update, context):
    """Обработка текстовых сообщений"""
    user_message = update.message.text.lower()
    user_id = update.message.chat_id

    # Автоматическая регистрация пользователя
    register_user(user_id, update.message.chat.first_name)

    if "у меня есть запись" in user_message:
        check_booking(update, context)
    elif "связаться с менеджером" in user_message:
        contact_manager(update, context)
    else:
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)

# Функция генерации ответа с использованием OpenAI GPT
def generate_ai_response(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
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
dispatcher.add_handler(CommandHandler("services", show_services))
dispatcher.add_handler(CommandHandler("specialists", show_specialists))
dispatcher.add_handler(CommandHandler("book", book_service))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# Регистрация Webhook
def set_webhook():
    webhook_url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
