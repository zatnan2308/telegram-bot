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
    raise ValueError("Не заданы все обязательные переменные окружения!")

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
    если их нет. Для упрощения.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # booking_times
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

    # bookings
    create_bookings_table = """
    CREATE TABLE IF NOT EXISTS bookings (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        service_id INT NOT NULL,
        specialist_id INT NOT NULL,
        date_time TIMESTAMP NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        date DATE  -- Можно оставить, но теперь оно NULLABLE (по вашему ALTER)
    );
    """
    cur.execute(create_bookings_table)

    # (Опционально) user_state
    create_user_state_table = """
    CREATE TABLE IF NOT EXISTS user_state (
        user_id BIGINT PRIMARY KEY,
        step VARCHAR(50),
        service_id INT,
        specialist_id INT,
        chosen_time VARCHAR(50)
    );
    """
    cur.execute(create_user_state_table)

    # (Опционально) users
    create_users_table = """
    CREATE TABLE IF NOT EXISTS users (
        telegram_id BIGINT PRIMARY KEY,
        name VARCHAR(100),
        phone VARCHAR(20)
    );
    """
    cur.execute(create_users_table)

    conn.commit()
    cur.close()
    conn.close()

# =============================================================================
# Работа с таблицей users
# =============================================================================
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

# =============================================================================
# user_state (хранение шагов записи)
# =============================================================================
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

# =============================================================================
# Таблица services и specialists
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

def get_specialists():
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT id, name FROM specialists;"
    cursor.execute(query)
    specialists = cursor.fetchall()
    cursor.close()
    conn.close()
    return specialists

def get_service_name_by_id(service_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM services WHERE id = %s", (service_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None

def get_specialist_name_by_id(spec_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM specialists WHERE id = %s", (spec_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None

# =============================================================================
# Определение намерения пользователя через OpenAI
# =============================================================================
def determine_intent(user_message):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты — Telegram-бот для управления записями. "
                        "Определи запрос пользователя как одно из намерений: 'услуги', 'специалисты', 'записаться', или 'другое'. "
                        "Если запрос связан с услугами, верни 'услуги'. "
                        "Если связан со специалистами, верни 'специалисты'. "
                        "Если пользователь хочет записаться, верни 'записаться'. "
                        "Для остальных случаев верни 'другое'."
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
        logger.error(f"Ошибка OpenAI: {e}")
        return f"Ошибка: {e}"

# =============================================================================
# booking_times + создание записи в bookings
# =============================================================================
def get_available_times(specialist_id, service_id):
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
        # row[0] => datetime
        slot_str = row[0].strftime("%Y-%m-%d %H:%M")
        available.append(slot_str)
    return available

def create_booking(user_id, service_id, specialist_id, date_str):
    """
    Создаём запись в bookings + помечаем слот is_booked=TRUE
    """
    # Парсим дату
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты/времени: {date_str}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1) is_booked=TRUE
    query_update_slot = """
    UPDATE booking_times
    SET is_booked = TRUE
    WHERE specialist_id = %s
      AND service_id = %s
      AND slot_time = %s
    """
    cursor.execute(query_update_slot, (specialist_id, service_id, chosen_dt))

    # 2) вставка в bookings
    query_insert_booking = """
    INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
    VALUES (%s, %s, %s, %s)
    """
    cursor.execute(query_insert_booking, (user_id, service_id, specialist_id, chosen_dt))

    conn.commit()
    cursor.close()
    conn.close()

# =============================================================================
# «Умные» функции для обработки имени мастера и времени
# =============================================================================
def match_specialist_with_gpt(user_input, specialists):
    specialists_names = [sp[1] for sp in specialists]
    prompt = (
        "Ты — ассистент, который сопоставляет имя специалиста. "
        f"Возможные варианты: {', '.join(specialists_names)}. "
        f"Пользователь ввёл: '{user_input}'. "
        "Верни точное имя (из списка) или 'None' если не уверено."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input}
            ],
            max_tokens=30
        )
        recognized = response['choices'][0]['message']['content'].strip()
        if recognized.lower() == "none":
            return None, None

        # Пытаемся найти точное совпадение
        recognized_lower = recognized.lower()
        for sp_id, sp_name in specialists:
            if sp_name.lower() == recognized_lower:
                return sp_id, sp_name

        return None, None
    except Exception as e:
        logger.error(f"Ошибка GPT: {e}")
        return None, None

def parse_time_input(user_input, available_times):
    """
    Разрешаем ввод 'HH:MM' если только одна дата.
    Иначе ждём 'YYYY-MM-DD HH:MM'.
    """
    unique_dates = list(set(t.split()[0] for t in available_times))

    # Если ввёл только HH:MM
    if user_input.count(":") == 1 and user_input.count("-") == 0:
        if len(unique_dates) == 1:
            # Дополним дату
            only_date = unique_dates[0]
            candidate = f"{only_date} {user_input}"
            if candidate in available_times:
                return candidate
            return None
        else:
            return None

    # Если ввёл полный формат и он есть среди свободных
    if user_input in available_times:
        return user_input

    return None

# =============================================================================
# Логика: если пользователь в фразе уже указал услугу
# =============================================================================
def find_service_in_text(user_message):
    """
    Пытаемся найти название услуги (из списка services)
    в тексте user_message (низкосложный вариант).
    Возвращаем (id, title) или None.
    """
    user_lower = user_message.lower()
    services = get_services()
    for s_id, s_title in services:
        if s_title.lower() in user_lower:
            return (s_id, s_title)
    return None

# =============================================================================
# Обработка всех входящих текстовых сообщений
# =============================================================================
def handle_message(update, context):
    user_message = update.message.text.strip().lower()
    user_id = update.message.chat_id

    # Регистрируем пользователя
    register_user(user_id, update.message.chat.first_name)

    # Смотрим, есть ли состояние
    current_state = get_user_state(user_id)
    if current_state:
        process_booking(update, user_id, user_message, current_state)
        return

    # Если состояния нет, определяем намерение
    intent = determine_intent(user_message)

    if intent == "записаться":
        # Проверим, не упоминается ли услуга уже в тексте
        matched_service = find_service_in_text(user_message)
        if matched_service:
            # Сразу переходим к выбору мастера
            set_user_state(user_id, "select_specialist", service_id=matched_service[0])
            specialists_list = get_specialists()
            spec_list_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in specialists_list])
            update.message.reply_text(
                f"Вы выбрали услугу: {matched_service[1]}\n"
                f"Пожалуйста, введите имя специалиста:\n{spec_list_text}"
            )
        else:
            # Иначе обычный сценарий
            set_user_state(user_id, "select_service")
            services = get_services()
            service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
            update.message.reply_text(
                f"Доступные услуги:\n{service_list}\nВведите название услуги."
            )

    elif intent == "услуги":
        all_services = get_services()
        if all_services:
            s_list = "\n".join([f"{s[0]}. {s[1]}" for s in all_services])
            update.message.reply_text(f"Доступные услуги:\n{s_list}")
        else:
            update.message.reply_text("На данный момент нет доступных услуг.")

    elif intent == "специалисты":
        specs = get_specialists()
        if specs:
            spec_list_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in specs])
            update.message.reply_text(f"Доступные специалисты:\n{spec_list_text}")
        else:
            update.message.reply_text("На данный момент нет доступных специалистов.")

    else:
        # Свободный вопрос
        bot_resp = generate_ai_response(user_message)
        update.message.reply_text(bot_resp)

# =============================================================================
# Основная пошаговая логика записи
# =============================================================================
def process_booking(update, user_id, user_message, state):
    step = state['step']

    if step == 'select_service':
        # Пользователь вводит название услуги
        services = get_services()
        service = next((s for s in services if s[1].lower() == user_message), None)
        if service:
            set_user_state(user_id, "select_specialist", service_id=service[0])
            specs = get_specialists()
            spec_list_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in specs])
            update.message.reply_text(
                f"Вы выбрали услугу: {service[1]}\n"
                f"Пожалуйста, введите имя специалиста:\n{spec_list_text}"
            )
        else:
            update.message.reply_text("Такой услуги нет. Попробуйте снова.")

    elif step == 'select_specialist':
        # Проверяем exact match
        specialists = get_specialists()
        specialist = next((sp for sp in specialists if sp[1].lower() == user_message), None)
        if specialist:
            set_user_state(user_id, "select_time", specialist_id=specialist[0], service_id=state['service_id'])
            av_times = get_available_times(specialist[0], state['service_id'])
            if av_times:
                times_text = "\n".join(av_times)
                update.message.reply_text(
                    f"Доступное время:\n{times_text}\n"
                    "Введите удобное время в формате YYYY-MM-DD HH:MM или только 'HH:MM' (если дат всего одна)."
                )
            else:
                update.message.reply_text("Нет доступных слотов для этого мастера.")
                delete_user_state(user_id)
        else:
            # Пробуем GPT
            sp_id, sp_name = match_specialist_with_gpt(user_message, specialists)
            if sp_id:
                set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=sp_id)
                av_times = get_available_times(sp_id, state['service_id'])
                if av_times:
                    times_text = "\n".join(av_times)
                    update.message.reply_text(
                        f"Похоже, вы имели в виду: {sp_name}\n"
                        f"Доступное время:\n{times_text}\n"
                        "Введите удобное время в формате YYYY-MM-DD HH:MM или только 'HH:MM'."
                    )
                else:
                    update.message.reply_text("У этого мастера нет свободных слотов.")
                    delete_user_state(user_id)
            else:
                update.message.reply_text("Не удалось найти такого специалиста. Попробуйте снова.")

    elif step == 'select_time':
        # Пользователь вводит дату/время
        service_id = state['service_id']
        spec_id = state['specialist_id']
        av_times = get_available_times(spec_id, service_id)

        parsed = parse_time_input(user_message, av_times)
        if parsed and parsed in av_times:
            set_user_state(user_id, "confirm", service_id=service_id, specialist_id=spec_id, chosen_time=parsed)
            # Выводим названия, не ID
            srv_name = get_service_name_by_id(service_id)
            sp_name = get_specialist_name_by_id(spec_id)
            update.message.reply_text(
                f"Вы выбрали:\n"
                f"Услуга: {srv_name}\n"
                f"Специалист: {sp_name}\n"
                f"Время: {parsed}\n"
                "Подтвердите запись (да/нет)."
            )
        else:
            update.message.reply_text("Неправильное или занятое время. Попробуйте снова.")

    elif step == 'confirm':
        if user_message in ["да", "да.", "yes", "yes."]:
            create_booking(
                user_id=user_id,
                service_id=state['service_id'],
                specialist_id=state['specialist_id'],
                date_str=state['chosen_time']
            )
            update.message.reply_text("Запись успешно создана! Спасибо!")
            delete_user_state(user_id)

        elif user_message in ["нет", "нет.", "no", "no."]:
            update.message.reply_text("Запись отменена.")
            delete_user_state(user_id)

        else:
            # Если вдруг пользователь опять пишет "хочу что-то ещё"
            if "хочу" in user_message:
                delete_user_state(user_id)
                update.message.reply_text("Хорошо, начнём новое бронирование!")
            else:
                update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")

# =============================================================================
# /start команда
# =============================================================================
def start(update, context):
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, "
        "или задайте мне любой вопрос!"
    )

# =============================================================================
# Flask-маршруты
# =============================================================================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    upd = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(upd)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

# =============================================================================
# Настройка диспетчера
# =============================================================================
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# =============================================================================
# Регистрация Webhook
# =============================================================================
def set_webhook():
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

# =============================================================================
# Точка входа
# =============================================================================
if __name__ == "__main__":
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
