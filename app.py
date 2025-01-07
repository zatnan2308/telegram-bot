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
    raise ValueError("Не все переменные окружения установлены!")

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
    Пример создания таблиц. Предполагается, что у вас есть:
    - users(id BIGINT PRIMARY KEY, name, phone, ...)
    - bookings(user_id BIGINT REFERENCES users(id), ...)
    и т.д.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Пример — если у вас нет таблицы users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY,
        name VARCHAR(100),
        phone VARCHAR(20)
    );
    """)

    # Пример — если у вас нет таблицы user_state
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_state (
        user_id BIGINT PRIMARY KEY,
        step VARCHAR(50),
        service_id INT,
        specialist_id INT,
        chosen_time VARCHAR(50)
    );
    """)

    # booking_times
    cur.execute("""
    CREATE TABLE IF NOT EXISTS booking_times (
        id SERIAL PRIMARY KEY,
        specialist_id INT NOT NULL,
        service_id INT NOT NULL,
        slot_time TIMESTAMP NOT NULL,
        is_booked BOOLEAN NOT NULL DEFAULT FALSE
    );
    """)

    # bookings (убедитесь, что есть FOREIGN KEY (user_id) REFERENCES users(id))
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        service_id INT NOT NULL,
        specialist_id INT NOT NULL,
        date_time TIMESTAMP NOT NULL,
        date DATE,
        created_at TIMESTAMP DEFAULT NOW()
        -- FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # services
    cur.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id SERIAL PRIMARY KEY,
        title VARCHAR(100) NOT NULL
    );
    """)

    # specialists
    cur.execute("""
    CREATE TABLE IF NOT EXISTS specialists (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

# =============================================================================
# Регистрация пользователя
# =============================================================================
def register_user(user_id, user_name, phone="0000000000"):
    """
    Вставляем в users(id, name, phone).
    user_id = update.message.chat_id (BIGINT)
    """
    conn = get_db_connection()
    cur = conn.cursor()

    query = """
    INSERT INTO users (id, name, phone)
    VALUES (%s, %s, %s)
    ON CONFLICT (id) DO NOTHING;
    """
    cur.execute(query, (user_id, user_name, phone))

    conn.commit()
    cur.close()
    conn.close()

# =============================================================================
# user_state
# =============================================================================
def get_user_state(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT step, service_id, specialist_id, chosen_time
        FROM user_state
        WHERE user_id = %s
    """, (user_id,))
    row = cur.fetchone()
    cur.close()
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
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO user_state (user_id, step, service_id, specialist_id, chosen_time)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (user_id) DO UPDATE
    SET step = EXCLUDED.step,
        service_id = EXCLUDED.service_id,
        specialist_id = EXCLUDED.specialist_id,
        chosen_time = EXCLUDED.chosen_time
    """, (user_id, step, service_id, specialist_id, chosen_time))
    conn.commit()
    cur.close()
    conn.close()

def delete_user_state(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_state WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

# =============================================================================
# Таблицы services, specialists
# =============================================================================
def get_services():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title FROM services;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_specialists():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM specialists;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_service_name(service_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT title FROM services WHERE id = %s", (service_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def get_specialist_name(spec_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM specialists WHERE id = %s", (spec_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

# =============================================================================
# OpenAI (GPT) — определение намерения и ответы на общие вопросы
# =============================================================================
def determine_intent(user_message):
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":(
                    "Ты — Telegram-бот для управления записями. "
                    "Определи запрос: 'услуги', 'специалисты', 'записаться' или 'другое'."
                )},
                {"role":"user","content":user_message}
            ],
            max_tokens=10
        )
        intent = resp['choices'][0]['message']['content'].strip().lower()
        return intent
    except:
        return "другое"

def generate_ai_response(prompt):
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system", "content":"Ты — умный Telegram-бот, помогай пользователю."},
                {"role":"user", "content":prompt}
            ],
            max_tokens=150
        )
        return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        return "Ошибка: {}".format(e)

# =============================================================================
# booking_times + bookings
# =============================================================================
def get_available_times(spec_id, serv_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT slot_time
    FROM booking_times
    WHERE specialist_id = %s
      AND service_id = %s
      AND is_booked = FALSE
    ORDER BY slot_time
    """, (spec_id, serv_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    # Превратим datetime в строки
    result = []
    for row in rows:
        dt_str = row[0].strftime("%Y-%m-%d %H:%M")
        result.append(dt_str)
    return result

def create_booking(user_id, serv_id, spec_id, date_str):
    """
    1) Ставим is_booked = TRUE для этого слота
    2) INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
    """
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except:
        logger.error(f"Неверный формат даты: {date_str}")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    # Обновляем слот
    cur.execute("""
    UPDATE booking_times
    SET is_booked = TRUE
    WHERE specialist_id = %s
      AND service_id = %s
      AND slot_time = %s
    """, (spec_id, serv_id, chosen_dt))
    # Вставляем запись
    cur.execute("""
    INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
    VALUES (%s, %s, %s, %s)
    """,(user_id, serv_id, spec_id, chosen_dt))
    conn.commit()
    cur.close()
    conn.close()

# =============================================================================
# Поиск услуги в тексте (простая проверка подстроки)
# =============================================================================
def find_service_in_text(user_text):
    services = get_services()
    user_text_lower = user_text.lower()

    for (s_id, s_title) in services:
        if s_title.lower() in user_text_lower:
            return (s_id, s_title)
    return None

# =============================================================================
# parse_time_input
# =============================================================================
def parse_time_input(user_text, available_times):
    """
    Если пользователь ввёл 'HH:MM' и есть только одна дата, подставляем.
    Иначе ждём 'YYYY-MM-DD HH:MM'.
    """
    if not available_times:
        return None

    # Получим список уникальных дат
    unique_dates = list({ t.split()[0] for t in available_times })

    # Если ввёл только "HH:MM"
    if user_text.count(":") == 1 and user_text.count("-") == 0:
        # "10:00"
        if len(unique_dates) == 1:
            only_date = unique_dates[0]
            candidate = f"{only_date} {user_text}"
            if candidate in available_times:
                return candidate
            else:
                return None
        else:
            return None

    # Если ввёл полный "YYYY-MM-DD HH:MM"
    if user_text in available_times:
        return user_text

    return None

# =============================================================================
# match_specialist_with_gpt
# =============================================================================
def match_specialist_with_gpt(user_input, specialists):
    """
    GPT-помощник, чтобы понять, какой именно мастер имелся в виду.
    """
    spec_names = [sp[1] for sp in specialists]
    sys_prompt = (
        "Ты — ассистент, который сопоставляет имя специалиста. "
        f"Варианты: {', '.join(spec_names)}. "
        f"Ввод пользователя: '{user_input}'. "
        "Верни точное имя (из списка) или 'None', если не уверен."
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":sys_prompt},
                {"role":"user","content":user_input}
            ],
            max_tokens=30
        )
        recognized = resp['choices'][0]['message']['content'].strip()
        if recognized.lower() == "none":
            return None, None

        recognized_lower = recognized.lower()
        for sp_id, sp_name in specialists:
            if sp_name.lower() == recognized_lower:
                return sp_id, sp_name
        return None, None
    except Exception as e:
        logger.error(f"Ошибка GPT: {e}")
        return None, None

# =============================================================================
# Обработка сообщений
# =============================================================================
def handle_message(update, context):
    user_text = update.message.text.strip().lower()
    user_id = update.message.chat_id
    user_name = update.message.chat.first_name or "Unknown"

    # Регистрируем пользователя (user_id -> users.id)
    register_user(user_id, user_name)

    # Если есть текущее состояние
    st = get_user_state(user_id)
    if st:
        process_booking(update, user_id, user_text, st)
        return

    # Нет состояния => определяем намерение
    intent = determine_intent(user_text)

    if "хочу" in user_text:
        # Проверим, не упомянул ли пользователь услугу
        found = find_service_in_text(user_text)
        if found:
            # Сразу переходим к выбору специалиста
            s_id, s_title = found
            set_user_state(user_id, "select_specialist", service_id=s_id)
            sp_list = get_specialists()
            sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in sp_list])
            update.message.reply_text(
                f"Вы выбрали услугу: {s_title}\n"
                f"Пожалуйста, выберите специалиста:\n{sp_text}"
            )
            return
        else:
            # Не нашли услугу
            # Начинаем стандартный сценарий
            set_user_state(user_id, "select_service")
            all_services = get_services()
            s_list = "\n".join([f"{s[0]}. {s[1]}" for s in all_services])
            update.message.reply_text(
                f"Доступные услуги:\n{s_list}\n"
                f"Введите название услуги."
            )
            return

    if intent == "записаться":
        # Начинаем сценарий
        set_user_state(user_id, "select_service")
        servs = get_services()
        s_list = "\n".join([f"{s[0]}. {s[1]}" for s in servs])
        update.message.reply_text(
            f"Доступные услуги:\n{s_list}\nВведите название услуги."
        )

    elif intent == "услуги":
        servs = get_services()
        if servs:
            txt = "\n".join([f"{s[0]}. {s[1]}" for s in servs])
            update.message.reply_text(f"Доступные услуги:\n{txt}")
        else:
            update.message.reply_text("На данный момент нет услуг.")

    elif intent == "специалисты":
        sps = get_specialists()
        if sps:
            sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in sps])
            update.message.reply_text(f"Доступные специалисты:\n{sp_text}")
        else:
            update.message.reply_text("Нет доступных специалистов.")

    else:
        # свободная фраза => GPT
        bot_resp = generate_ai_response(user_text)
        update.message.reply_text(bot_resp)

# =============================================================================
# process_booking (пошаговая логика)
# =============================================================================
def process_booking(update, user_id, user_text, state):
    step = state['step']

    # Если вдруг пользователь заново пишет "хочу ..."
    if "хочу" in user_text:
        # Сброс и начало заново
        delete_user_state(user_id)
        found = find_service_in_text(user_text)
        if found:
            # Если нашли услугу
            s_id, s_title = found
            set_user_state(user_id, "select_specialist", service_id=s_id)
            sp_list = get_specialists()
            sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in sp_list])
            update.message.reply_text(
                f"Вы выбрали услугу: {s_title}\n"
                f"Пожалуйста, выберите специалиста:\n{sp_text}"
            )
        else:
            # Нет конкретной услуги
            set_user_state(user_id, "select_service")
            all_services = get_services()
            s_list = "\n".join([f"{s[0]}. {s[1]}" for s in all_services])
            update.message.reply_text(
                f"Доступные услуги:\n{s_list}\n"
                "Введите название услуги."
            )
        return

    if step == "select_service":
        # Проверка запроса на повтор списка услуг по ключевым словам
        if "повтори" in user_text or "какие услуги" in user_text or "услуги" in user_text:
            services = get_services()
            service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
            update.message.reply_text(f"Доступные услуги:\n{service_list}")
            return

        services = get_services()
        service = next((s for s in services if s[1].lower() == user_text), None)
        if service:
            set_user_state(user_id, "select_specialist", service_id=service[0])
            sp_list = get_specialists()
            sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in sp_list])
            update.message.reply_text(
                f"Вы выбрали услугу: {service[1]}\n"
                f"Пожалуйста, выберите специалиста:\n{sp_text}"
            )
        else:
            # Используем GPT для определения, хочет ли пользователь повторить список услуг
            system_prompt = (
                "Ты — эксперт в распознавании запросов на повторение списка услуг "
                "в контексте бронирования услуг."
            )
            user_prompt = (
                f"Пользователь на этапе выбора услуги ввёл: '{user_text}'. "
                "Определи, что он просит повторить список услуг. "
                "Ответь коротко 'да', если это запрос на повтор списка, иначе 'нет'."
            )
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=10,
                    temperature=0.3
                )
                answer = resp['choices'][0]['message']['content'].strip().lower()
            except Exception as e:
                logger.error(f"Ошибка GPT проверки услуги: {e}")
                answer = ""

            if "да" in answer or "повтор" in answer:
                services = get_services()
                service_list = "\n".join([f"{s[0]}. {s[1]}" for s in services])
                update.message.reply_text(f"Доступные услуги:\n{service_list}")
            else:
                update.message.reply_text("Такой услуги нет. Попробуйте снова.")


    elif step == "select_specialist":
        # Exact match
        specs = get_specialists()
        specialist = next((sp for sp in specs if sp[1].lower() == user_text), None)
        if specialist:
            set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=specialist[0])
            av_times = get_available_times(specialist[0], state['service_id'])
            if av_times:
                txt = "\n".join(av_times)
                update.message.reply_text(
                    f"Доступное время:\n{txt}\nВведите удобное время (YYYY-MM-DD HH:MM, "
                    "или 'HH:MM' если дат всего одна)."
                )
            else:
                update.message.reply_text("Нет свободных слотов для данного мастера.")
                delete_user_state(user_id)
        else:
            # GPT поиск
            sp_id, sp_name = match_specialist_with_gpt(user_text, specs)
            if sp_id:
                set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=sp_id)
                av_times = get_available_times(sp_id, state['service_id'])
                if av_times:
                    txt = "\n".join(av_times)
                    update.message.reply_text(
                        f"Похоже, вы имели в виду: {sp_name}\n"
                        f"Доступное время:\n{txt}\n"
                        "Введите удобное время."
                    )
                else:
                    update.message.reply_text("Нет свободных слотов для данного мастера.")
                    delete_user_state(user_id)
            else:
                update.message.reply_text("Не нашли такого специалиста. Попробуйте снова.")

    elif step == "select_time":
        serv_id = state['service_id']
        spec_id = state['specialist_id']
        av_times = get_available_times(spec_id, serv_id)
        chosen_time = parse_time_input(user_text, av_times)
        if chosen_time and chosen_time in av_times:
            # Переходим к confirm
            set_user_state(user_id, "confirm", service_id=serv_id, specialist_id=spec_id, chosen_time=chosen_time)

            srv_name = get_service_name(serv_id)
            sp_name = get_specialist_name(spec_id)
            update.message.reply_text(
                f"Вы выбрали:\n"
                f"Услуга: {srv_name}\n"
                f"Специалист: {sp_name}\n"
                f"Время: {chosen_time}\n"
                "Подтвердите запись (да/нет)."
            )
        else:
            update.message.reply_text("Неправильное или занятое время. Попробуйте снова.")

    elif step == "confirm":
        if user_text in ["да","да.","yes","yes."]:
            create_booking(
                user_id=user_id,
                serv_id=state['service_id'],
                spec_id=state['specialist_id'],
                date_str=state['chosen_time']
            )
            update.message.reply_text("Запись успешно создана! Спасибо!")
            delete_user_state(user_id)
        elif user_text in ["нет","нет.","no","no."]:
            update.message.reply_text("Запись отменена.")
            delete_user_state(user_id)
        else:
            update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")

# =============================================================================
# /start
# =============================================================================
def start(update, context):
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, или задайте мне любой вопрос!"
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
# set_webhook
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
