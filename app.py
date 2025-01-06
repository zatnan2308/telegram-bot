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

# Получение доступных дат и времени для записи
def get_available_times(specialist_id, service_id):
    # Здесь должна быть логика получения доступного расписания (заглушка для примера)
    return [
        "2025-01-08 10:00:00",
        "2025-01-08 12:00:00",
        "2025-01-08 14:00:00"
    ]

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

# Состояния для записи
user_booking_state = {}

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

# Обработка сообщений пользователя
def handle_message(update, context):
    user_message = update.message.text
    user_id = update.message.chat_id

    # Регистрация пользователя
    register_user(user_id, update.message.chat.first_name)

    # Проверяем, находится ли пользователь в процессе записи
    if user_id in user_booking_state:
        process_booking(update, user_id, user_message)
        return

    # Определяем намерение пользователя
    intent = determine_intent(user_message)
    if intent == "услуги":
        services = get_services()
        if services:
            service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
            update.message.reply_text(f"Доступные услуги:\n{service_list}")
        else:
            update.message.reply_text("На данный момент нет доступных услуг.")
    elif intent == "специалисты":
        specialists = get_specialists()
        if specialists:
            specialist_list = "\n".join([f"{s[0]}. {s[1]}" for s in specialists])
            update.message.reply_text(f"Доступные специалисты:\n{specialist_list}")
        else:
            update.message.reply_text("На данный момент нет доступных специалистов.")
    elif intent == "записаться":
        user_booking_state[user_id] = {'step': 'select_service'}
        services = get_services()
        service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
        update.message.reply_text(f"Доступные услуги:\n{service_list}\nВведите название услуги.")
    else:
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)

# Обработка записи
def process_booking(update, user_id, user_message):
    state = user_booking_state[user_id]

    if state['step'] == 'select_service':
        services = get_services()
        service = next((s for s in services if s[1].lower() == user_message.lower()), None)
        if service:
            state['service_id'] = service[0]
            state['step'] = 'select_specialist'
            specialists = get_specialists()
            specialist_list = "\n".join([f"{s[0]}. {s[1]}" for s in specialists])
            update.message.reply_text(f"Вы выбрали услугу: {service[1]}\nПожалуйста, выберите специалиста:\n{specialist_list}")
        else:
            update.message.reply_text("Такой услуги нет. Попробуйте снова.")
    elif state['step'] == 'select_specialist':
        specialists = get_specialists()
        specialist = next((s for s in specialists if s[1].lower() == user_message.lower()), None)
        if specialist:
            state['specialist_id'] = specialist[0]
            state['step'] = 'select_time'
            available_times = get_available_times(state['specialist_id'], state['service_id'])
            time_list = "\n".join(available_times)
            update.message.reply_text(f"Доступное время:\n{time_list}\nВведите удобное время.")
        else:
            update.message.reply_text("Такого специалиста нет. Попробуйте снова.")
    elif state['step'] == 'select_time':
        available_times = get_available_times(state['specialist_id'], state['service_id'])
        if user_message in available_times:
            state['date'] = user_message
            state['step'] = 'confirm'
            update.message.reply_text(f"Вы выбрали:\nУслуга: {state['service_id']}\nСпециалист: {state['specialist_id']}\nВремя: {state['date']}\nПодтвердите запись (да/нет).")
        else:
            update.message.reply_text("Неправильное время. Попробуйте снова.")
    elif state['step'] == 'confirm':
        if user_message.lower() == 'да':
            create_booking(user_id, state['service_id'], state['specialist_id'], state['date'])
            update.message.reply_text("Запись успешно создана! Спасибо!")
            del user_booking_state[user_id]
        elif user_message.lower() == 'нет':
            update.message.reply_text("Запись отменена.")
            del user_booking_state[user_id]
        else:
            update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")

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
