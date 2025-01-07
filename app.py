from flask import Flask, request
import logging
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import os
import psycopg2
import openai
import datetime

# =============================================================================
# Настройки окружения
# =============================================================================
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
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация бота и Flask-приложения
bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# =============================================================================
# Подключение к базе данных
# =============================================================================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """
    Создаёт таблицы booking_times, bookings (и другие),
    если их нет. Для упрощения демонстрации.
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
    );
    """
    cur.execute(create_booking_times_table)

    # Создание таблицы bookings (если её нет)
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

    # (Опционально) можно добавить FOREIGN KEY на specialists, services

    conn.commit()
    cur.close()
    conn.close()

# =============================================================================
# Работа с таблицей users
# =============================================================================
def register_user(telegram_id, name, phone="0000000000"):
    """
    Сохраняем пользователя в таблицу users, если его там нет.
    """
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

# =============================================================================
# Работа с таблицей user_state (хранение шагов записи)
# =============================================================================
def get_user_state(user_id):
    """
    Получаем текущее состояние пользователя (шаг диалога) из user_state.
    Возвращаем dict или None, если записи нет.
    """
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
    """
    Сохраняем/обновляем состояние пользователя в user_state.
    """
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
    """
    Удаляем состояние пользователя (сброс сценария записи).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "DELETE FROM user_state WHERE user_id = %s"
    cursor.execute(query, (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

# =============================================================================
# Работа с таблицей services
# =============================================================================
def get_services():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, title FROM services;"
    cursor.execute(query)
    services = cursor.fetchall()
    cursor.close()
    conn.close()
    return services

# =============================================================================
# Работа с таблицей specialists
# =============================================================================
def get_specialists():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, name FROM specialists;"
    cursor.execute(query)
    specialists = cursor.fetchall()
    cursor.close()
    conn.close()
    return specialists

# =============================================================================
# Определение намерения пользователя через OpenAI
# =============================================================================
def determine_intent(user_message):
    """
    GPT-классификатор: возвращает строку 'услуги', 'специалисты', 'записаться' или 'другое'.
    """
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

# =============================================================================
# Генерация ответа через OpenAI (для свободных вопросов)
# =============================================================================
def generate_ai_response(prompt):
    """
    GPT-сгенерированный ответ для неструктурированных вопросов пользователя.
    """
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

# =============================================================================
# Получаем доступные слоты (дата/время) из booking_times
# =============================================================================
def get_available_times(specialist_id, service_id):
    """
    Возвращает список доступных (is_booked=FALSE) дат/времени (формат 'YYYY-MM-DD HH:MM')
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

    available = []
    for row in rows:
        slot_str = row[0].strftime("%Y-%m-%d %H:%M")
        available.append(slot_str)
    return available

# =============================================================================
# Создание записи (bookings) + пометка слота is_booked=TRUE
# =============================================================================
def create_booking(user_id, service_id, specialist_id, date_str):
    """
    1) Парсим date_str -> datetime
    2) UPDATE booking_times SET is_booked=TRUE
    3) INSERT INTO bookings
    """
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        # Если формат неверный, можно отправить сообщение об ошибке или что-то ещё
        logger.error(f"Неверный формат даты/времени: {date_str}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) Помечаем слот занят
    query_update_slot = """
    UPDATE booking_times
    SET is_booked = TRUE
    WHERE specialist_id = %s
      AND service_id = %s
      AND slot_time = %s
    """
    cursor.execute(query_update_slot, (specialist_id, service_id, chosen_dt))

    # 2) Создаём запись в bookings
    query_insert_booking = """
    INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
    VALUES (%s, %s, %s, %s)
    """
    cursor.execute(query_insert_booking, (user_id, service_id, specialist_id, chosen_dt))

    conn.commit()
    cursor.close()
    conn.close()

# =============================================================================
# Дополнительные "умные" функции GPT для "живого" общения
# =============================================================================

def match_specialist_with_gpt(user_input, specialists):
    """
    Пример функции, которая обращается к GPT, чтобы понять,
    какой специалист имеется в виду при неточном вводе (только имя, и т.д.).
    
    specialists — список кортежей (id, name) из get_specialists().
    Возвращает (specialist_id, specialist_name) или (None, None).
    """
    specialists_names = [sp[1] for sp in specialists]
    sys_prompt = (
        "Ты — ассистент, который сопоставляет имя специалиста. "
        f"Возможные варианты: {', '.join(specialists_names)}. "
        "Пользователь ввёл: "
        f"'{user_input}'. "
        "Верни точное имя специалиста (из списка) или 'None' если не уверено."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_input}
            ],
            max_tokens=30,
            temperature=0.3
        )
        recognized = response['c
