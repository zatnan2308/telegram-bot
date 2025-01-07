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
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
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

    # Создание таблицы bookings (для финальных записей)
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

    # (Опционально) можно добавить нужные FOREIGN KEY

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
    GPT-классфикатор: возвращает строку 'услуги', 'специалисты', 'записаться' или 'другое'.
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
    # Пробуем распарсить дату/время
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return  # Неверный формат, можно дополнительно обработать

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
    какой специалист имеется в виду при неточном вводе.
    
    specialists — список кортежей (id, name) из get_specialists().
    Возвращает (specialist_id, specialist_name) или (None, None).
    """
    # Подготовим список имён для GPT
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
        recognized = response['choices'][0]['message']['content'].strip()

        # Если GPT вернул "None" или ничего подходящего
        if recognized.lower() == "none":
            return None, None
        
        # Теперь попробуем найти точное совпадение recognized в specialists
        recognized_lower = recognized.lower()
        for sp_id, sp_name in specialists:
            if sp_name.lower() == recognized_lower:
                return sp_id, sp_name
        
        # Если GPT вернул что-то, но мы не нашли точного совпадения
        # Можно сделать подстрочное совпадение, либо сказать, что нет
        # Для простоты вернём None
        return None, None

    except Exception as e:
        logger.error(f"Ошибка GPT при сопоставлении специалиста: {e}")
        return None, None


def parse_time_input(user_input, available_times):
    """
    Позволяет пользователю вводить только "10:00", если есть ровно одна дата,
    и автоматически подставляет эту дату.
    otherwise — ожидаем полный формат YYYY-MM-DD HH:MM или проверяем GPT.
    
    Возвращает строку "YYYY-MM-DD HH:MM" или None, если не распознано.
    """
    # Список всех уникальных дат
    unique_dates = list(set(t.split()[0] for t in available_times))

    # Если пользователь ввёл "HH:MM" (2 двоеточия — 1, если без секунд)
    if user_input.count(":") == 1 and user_input.count("-") == 0:
        # Похоже на "10:00", без даты
        if len(unique_dates) == 1:
            # Если у нас только одна дата
            only_date = unique_dates[0]
            return f"{only_date} {user_input}"
        else:
            # Есть несколько дат, пусть уточняет полную дату
            return None

    # Если пользователь ввёл полное "YYYY-MM-DD HH:MM" и оно точно есть в списке
    if user_input in available_times:
        return user_input

    # (Опционально) можно добавить GPT-парсинг "завтра", "на 10:00", "послезавтра"...
    # Для упрощения примера — вернём None, если нет полного совпадения
    return None

# =============================================================================
# Обработка текстовых сообщений (главный вход)
# =============================================================================
def handle_message(update, context):
    user_message = update.message.text.strip()
    user_id = update.message.chat_id

    # Регистрируем пользователя
    register_user(user_id, update.message.chat.first_name)

    # Проверяем состояние (user_state)
    current_state = get_user_state(user_id)
    if current_state:
        process_booking(update, user_id, user_message, current_state)
        return

    # Если состояния нет — определяем намерение
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
        # Начинаем сценарий записи
        set_user_state(user_id, step="select_service")
        services = get_services()
        service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
        update.message.reply_text(
            f"Доступные услуги:\n{service_list}\nВведите название услуги."
        )
    else:
        # Свободный вопрос — ответим GPT
        bot_response = generate_ai_response(user_message)
        update.message.reply_text(bot_response)

# =============================================================================
# Пошаговая логика записи
# =============================================================================
def process_booking(update, user_id, user_message, state):
    step = state['step']

    if step == 'select_service':
        # Пользователь выбирает услугу
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
        # Пользователь выбирает специалиста
        specialists = get_specialists()
        # 1) Сначала пробуем exact match
        specialist = next((sp for sp in specialists if sp[1].lower() == user_message.lower()), None)
        if specialist:
            # Успех
            set_user_state(
                user_id,
                step='select_time',
                specialist_id=specialist[0],
                service_id=state['service_id']
            )
            available_times = get_available_times(specialist[0], state['service_id'])
            if available_times:
                time_list = "\n".join(available_times)
                update.message.reply_text(
                    f"Доступное время:\n{time_list}\n"
                    f"Введите удобное время в формате YYYY-MM-DD HH:MM или только 'HH:MM' (если дат всего одна)."
                )
            else:
                update.message.reply_text("К сожалению, нет свободных слотов для этого мастера.")
                delete_user_state(user_id)
            return
        else:
            # 2) Пробуем GPT для распознавания
            sp_id, sp_name = match_specialist_with_gpt(user_message, specialists)
            if sp_id is not None:
                # Найден мастер через GPT
                set_user_state(
                    user_id,
                    step='select_time',
                    specialist_id=sp_id,
                    service_id=state['service_id']
                )
                available_times = get_available_times(sp_id, state['service_id'])
                if available_times:
                    time_list = "\n".join(available_times)
                    update.message.reply_text(
                        f"Похоже, вы имели в виду: {sp_name}\n"
                        f"Доступное время:\n{time_list}\n"
                        f"Введите удобное время в формате YYYY-MM-DD HH:MM или только 'HH:MM' (если дат всего одна)."
                    )
                else:
                    update.message.reply_text("К сожалению, у этого мастера нет свободных слотов.")
                    delete_user_state(user_id)
            else:
                update.message.reply_text("Не удалось найти такого специалиста. Попробуйте снова.")

    elif step == 'select_time':
        service_id = state['service_id']
        specialist_id = state['specialist_id']
        available_times = get_available_times(specialist_id, service_id)

        # Пробуем «умную» функцию parse_time_input
        parsed_time = parse_time_input(user_message, available_times)
        if parsed_time and parsed_time in available_times:
            # Всё ок, переходим к confirm
            set_user_state(
                user_id,
                step='confirm',
                service_id=service_id,
                specialist_id=specialist_id,
                chosen_time=parsed_time
            )
            update.message.reply_text(
                f"Вы выбрали:\n"
                f"Услуга (ID): {service_id}\n"
                f"Специалист (ID): {specialist_id}\n"
                f"Время: {parsed_time}\n"
                "Подтвердите запись (да/нет)."
            )
        else:
            update.message.reply_text("Неправильное или занятое время. Попробуйте снова.")

   elif step == 'confirm':
    # Если пользователь написал "да"
    if user_message.lower() == 'да':
        ...
    # Если пользователь написал "нет"
    elif user_message.lower() == 'нет':
        ...
    else:
        # Проверяем, не "хочу" ли он что-то новое
        if "хочу" in user_message.lower():
            # Сбрасываем старую запись и начинаем заново
            delete_user_state(user_id)
            # И, например, сразу set_user_state(... "select_service") 
            update.message.reply_text("Хорошо, начнём новое бронирование!")
            # ... вызываем логику заново
        else:
            # Старое поведение
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
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
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
    webhook_url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

# =============================================================================
# Точка входа
# =============================================================================
if __name__ == "__main__":
    # Инициализация БД (создание таблиц, если их нет)
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
