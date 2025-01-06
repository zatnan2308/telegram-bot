from flask import Flask, request
import logging
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import os
import psycopg2
import openai
import datetime

# Настройки окружения
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

# ------------------------------------------------------------------------------
# Подключение к базе данных
# ------------------------------------------------------------------------------
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """
    Создаёт таблицу booking_times (и при необходимости bookings),
    если они не существуют. Пример для упрощённой демонстрации.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Создание таблицы booking_times (для хранения слотов)
    create_booking_times_table = """
    CREATE TABLE IF NOT EXISTS booking_times (
        id SERIAL PRIMARY KEY,
        specialist_id INT NOT NULL,
        service_id INT NOT NULL,
        slot_time TIMESTAMP NOT NULL,
        is_booked BOOLEAN NOT NULL DEFAULT FALSE
        -- Можно добавить FOREIGN KEY, если нужно
    );
    """
    cur.execute(create_booking_times_table)

    # Создание таблицы bookings (если у вас её ещё нет)
    create_bookings_table = """
    CREATE TABLE IF NOT EXISTS bookings (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        service_id INT NOT NULL,
        specialist_id INT NOT NULL,
        date_time TIMESTAMP NOT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """
    cur.execute(create_bookings_table)

    conn.commit()
    cur.close()
    conn.close()

# ------------------------------------------------------------------------------
# Работа с таблицей users
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# Работа с таблицей user_state (храним шаги записи)
# ------------------------------------------------------------------------------
def get_user_state(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT step, service_id, specialist_id, chosen_time
        FROM user_state
        WHERE user_id = %s
    """
    cursor.execute(query, (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {
            'step': row[0],
            'service_id': row[1],
            'specialist_id': row[2],
            'chosen_time': row[3],
        }
    else:
        return None

def set_user_state(user_id, step, service_id=None, specialist_id=None, chosen_time=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO user_state (user_id, step, service_id, specialist_id, chosen_time)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (user_id)
    DO UPDATE SET
        step = EXCLUDED.step,
        service_id = EXCLUDED.service_id,
        specialist_id = EXCLUDED.specialist_id,
        chosen_time = EXCLUDED.chosen_time
    """
    cursor.execute(query, (user_id, step, service_id, specialist_id, chosen_time))
    conn.commit()
    cursor.close()
    conn.close()

def delete_user_state(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "DELETE FROM user_state WHERE user_id = %s"
    cursor.execute(query, (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

# ------------------------------------------------------------------------------
# Работа с таблицей services
# ------------------------------------------------------------------------------
def get_services():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, title FROM services;"
    cursor.execute(query)
    services = cursor.fetchall()
    cursor.close()
    conn.close()
    return services

# ------------------------------------------------------------------------------
# Работа с таблицей specialists
# ------------------------------------------------------------------------------
def get_specialists():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, name FROM specialists;"
    cursor.execute(query)
    specialists = cursor.fetchall()
    cursor.close()
    conn.close()
    return specialists

# ------------------------------------------------------------------------------
# Определение намерения пользователя через OpenAI
# ------------------------------------------------------------------------------
def determine_intent(user_message):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты — Telegram-бот для управления записями. "
                        "Определяй запрос пользователя как одно из намерений: 'услуги', 'специалисты', 'записаться', или 'другое'. "
                        "Если запрос связан с услугами, возвращай 'услуги'. "
                        "Если связан со специалистами, возвращай 'специалисты'. "
                        "Если пользователь хочет записаться, возвращай 'записаться'. "
                        "Для остальных запросов возвращай 'другое'."
                    )
                },
                {"role": "user", "content": user_message}
            ],
            max_tokens=10,
            temperature=0.5
        )
        return response['choices'][0]['message']['content'].strip().lower()
    except Exception as e:
        logger.error(f"Ошибка определения намерения: {e}")
        return "другое"

# ------------------------------------------------------------------------------
# Генерация ответа через OpenAI
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# Получаем доступные слоты (дата/время) из новой таблицы booking_times
# ------------------------------------------------------------------------------
def get_available_times(specialist_id, service_id):
    """
    Возвращает список доступных (не забронированных) дат/времени (строкой)
    для конкретного мастера и услуги, на основании booking_times.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    SELECT slot_time
    FROM booking_times
    WHERE specialist_id = %s
      AND service_id = %s
      AND is_booked = FALSE
    ORDER BY slot_time
    """
    cursor.execute(query, (specialist_id, service_id))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Превратим каждый slot_time в строку формата "YYYY-MM-DD HH:MM"
    available = []
    for row in rows:
        # row[0] — это тип datetime
        slot_str = row[0].strftime("%Y-%m-%d %H:%M")
        available.append(slot_str)

    return available

# ------------------------------------------------------------------------------
# Создание записи (bookings), а также пометка, что слот занят (is_booked = TRUE)
# ------------------------------------------------------------------------------
def create_booking(user_id, service_id, specialist_id, date_str):
    """
    1) Парсит строку date_str -> datetime
    2) Помечает слот в booking_times как занятый
    3) Создаёт запись в таблице bookings
    """
    # Парсим строку вида "2025-01-08 14:00" в datetime
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        # Если вдруг неверный формат строки
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) Помечаем is_booked = TRUE для данного слота
    query_update_slot = """
    UPDATE booking_times
    SET is_booked = TRUE
    WHERE specialist_id = %s
      AND service_id = %s
      AND slot_time = %s
    """
    cursor.execute(query_update_slot, (specialist_id, service_id, chosen_dt))

    # 2) Создаём финальную запись в таблице bookings
    query_insert_booking = """
    INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
    VALUES (%s, %s, %s, %s)
    """
    cursor.execute(query_insert_booking, (user_id, service_id, specialist_id, chosen_dt))

    conn.commit()
    cursor.close()
    conn.close()

# ------------------------------------------------------------------------------
# Обработка текстовых сообщений
# ------------------------------------------------------------------------------
def handle_message(update, context):
    user_message = update.message.text.strip()
    user_id = update.message.chat_id

    # Регистрируем пользователя (в таблице users)
    register_user(user_id, update.message.chat.first_name)

    # Проверяем текущее состояние (user_state)
    current_state = get_user_state(user_id)
    if current_state:
        process_booking(update, user_id, user_message, current_state)
        return

    # Если нет состояния, определяем намерение
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
        set_user_state(user_id, step="select_service")
        services = get_services()
        service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
        update.message.reply_text(
            f"Доступные услуги:\n{service_list}\nВведите название услуги."
        )
    else:
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)

# ------------------------------------------------------------------------------
# Пошаговая логика записи
# ------------------------------------------------------------------------------
def process_booking(update, user_id, user_message, state):
    step = state['step']

    if step == 'select_service':
        services = get_services()
        service = next((s for s in services if s[1].lower() == user_message.lower()), None)
        if service:
            set_user_state(user_id, step='select_specialist', service_id=service[0])
            specialist_list = "\n".join([f"{sp[0]}. {sp[1]}" for sp in get_specialists()])
            update.message.reply_text(
                f"Вы выбрали услугу: {service[1]}\n"
                f"Пожалуйста, введите имя специалиста:\n{specialist_list}"
            )
        else:
            update.message.reply_text("Такой услуги нет. Попробуйте снова.")

    elif step == 'select_specialist':
        specialists = get_specialists()
        specialist = next((sp for sp in specialists if sp[1].lower() == user_message.lower()), None)
        if specialist:
            set_user_state(
                user_id, 
                step='select_time', 
                specialist_id=specialist[0],
                service_id=state['service_id']  # перенесём, чтобы не потерять
            )
            available_times = get_available_times(specialist[0], state['service_id'])
            if available_times:
                time_list = "\n".join(available_times)
                update.message.reply_text(
                    f"Доступное время:\n{time_list}\n"
                    f"Введите удобное время в формате YYYY-MM-DD HH:MM"
                )
            else:
                update.message.reply_text("К сожалению, нет свободных слотов для этого мастера. Попробуйте другого.")
                # Можно сбросить состояние или предложить что-то ещё
        else:
            update.message.reply_text("Такого специалиста нет. Попробуйте снова.")

    elif step == 'select_time':
        # Проверяем, ввёл ли пользователь время, которое есть в списке
        service_id = state['service_id']
        specialist_id = state['specialist_id']
        available_times = get_available_times(specialist_id, service_id)

        if user_message in available_times:
            # Всё ок, переходим к подтверждению
            set_user_state(
                user_id, 
                step='confirm',
                service_id=service_id,
                specialist_id=specialist_id,
                chosen_time=user_message
            )
            update.message.reply_text(
                f"Вы выбрали:\n"
                f"Услуга (ID): {service_id}\n"
                f"Специалист (ID): {specialist_id}\n"
                f"Время: {user_message}\n"
                "Подтвердите запись (да/нет)."
            )
        else:
            update.message.reply_text("Неправильное или занятое время. Попробуйте снова.")

    elif step == 'confirm':
        if user_message.lower() == 'да':
            create_booking(
                user_id=user_id,
                service_id=state['service_id'],
                specialist_id=state['specialist_id'],
                date_str=state['chosen_time']
            )
            update.message.reply_text("Запись успешно создана! Спасибо!")
            delete_user_state(user_id)
        elif user_message.lower() == 'нет':
            update.message.reply_text("Запись отменена.")
            delete_user_state(user_id)
        else:
            update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")

# ------------------------------------------------------------------------------
# /start команда
# ------------------------------------------------------------------------------
def start(update, context):
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, "
        "или задайте мне любой вопрос!"
    )

# ------------------------------------------------------------------------------
# Flask-маршруты
# ------------------------------------------------------------------------------
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

# ------------------------------------------------------------------------------
# Настройка диспетчера
# ------------------------------------------------------------------------------
from telegram.ext import Dispatcher
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# ------------------------------------------------------------------------------
# Регистрация Webhook
# ------------------------------------------------------------------------------
def set_webhook():
    webhook_url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

# ------------------------------------------------------------------------------
# Точка входа
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    # Инициализация БД (создание таблиц, если их нет)
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
