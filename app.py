from flask import Flask, request
import logging
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import os
import psycopg2
import openai
import datetime
import json

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

# =============================================================================
# Инициализация базы данных
# =============================================================================
def init_db():
    """
    Создаёт таблицы, если они не существуют.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    # Таблицы создаются через внешние SQL-скрипты, поэтому здесь можно оставить pass
    # Или добавить дополнительные настройки, если необходимо
    cur.close()
    conn.close()

# =============================================================================
# Регистрация пользователя
# =============================================================================
def register_user(user_id, user_name, phone="0000000000"):
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
# Функции работы с user_state
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
# Функции для работы с услугами и специалистами
# =============================================================================
def get_services():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title FROM services ORDER BY id;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_specialists(service_id=None):
    conn = get_db_connection()
    cur = conn.cursor()
    if service_id:
        cur.execute("""
            SELECT s.id, s.name
            FROM specialists s
            JOIN specialist_services ss ON s.id = ss.specialist_id
            WHERE ss.service_id = %s
            ORDER BY s.id;
        """, (service_id,))
    else:
        cur.execute("SELECT id, name FROM specialists ORDER BY id;")
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
# OpenAI — определение намерения и ответы
# =============================================================================
def determine_intent(user_message):
    """
    Использует OpenAI для определения намерения и извлечения сущностей из сообщения пользователя.
    Возвращает словарь с 'intent' и 'entities'.
    """
    system_prompt = (
        "Ты — Telegram-бот для управления записями. Определи намерение пользователя и извлеки сущности из его сообщения. "
        "Возможные намерения: LIST_SERVICES (список всех услуг), LIST_SPECIALIST_SERVICES (список услуг конкретного специалиста), BOOK_SERVICE (запись на услугу), UNKNOWN (неизвестное намерение). "
        "Сущности могут включать 'specialist_name'. "
        "Отвечай в формате JSON без пояснений."
    )
    user_prompt = user_message

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":user_prompt}
            ],
            max_tokens=100,
            temperature=0
        )
        response_content = resp['choices'][0]['message']['content'].strip()
        intent_data = json.loads(response_content)
        return intent_data
    except Exception as e:
        logger.error(f"Ошибка определения намерения через GPT: {e}")
        return {"intent": "UNKNOWN"}

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
        logger.error(f"Ошибка генерации ответа через GPT: {e}")
        return "Извините, произошла ошибка при обработке вашего запроса."

# =============================================================================
# Функции для работы со слотами и бронированием
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
    result = []
    for row in rows:
        dt_str = row[0].strftime("%Y-%m-%d %H:%M")
        result.append(dt_str)
    return result

def create_booking(user_id, serv_id, spec_id, date_str):
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты: {date_str}")
        return False

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
    return True

# =============================================================================
# Вспомогательные функции
# =============================================================================
def find_service_in_text(user_text):
    services = get_services()
    user_text_lower = user_text.lower()
    for (s_id, s_title) in services:
        if s_title.lower() in user_text_lower:
            return (s_id, s_title)
    return None

def parse_time_input(user_text, available_times):
    if not available_times:
        return None
    unique_dates = list({ t.split()[0] for t in available_times })
    if user_text.count(":") == 1 and user_text.count("-") == 0:
        if len(unique_dates) == 1:
            only_date = unique_dates[0]
            candidate = f"{only_date} {user_text}"
            if candidate in available_times:
                return candidate
            else:
                return None
        else:
            return None
    if user_text in available_times:
        return user_text
    return None

def match_specialist_with_gpt(user_input, specialists):
    spec_names = [sp[1] for sp in specialists]
    system_prompt = (
        "Ты — ассистент, который сопоставляет имя специалиста. "
        f"Варианты: {', '.join(spec_names)}. "
        f"Ввод пользователя: '{user_input}'. "
        "Верни точное имя (из списка) или 'None', если не уверен."
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            max_tokens=30,
            temperature=0.3
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

def find_available_specialist(service_id, exclude_id=None):
    specialists = get_specialists(service_id=service_id)
    for sp in specialists:
        if exclude_id and sp[0] == exclude_id:
            continue
        available = get_available_times(sp[0], service_id)
        if available:
            return sp  # Возвращает первого специалиста с доступными слотами
    return None

# =============================================================================
# Обработка входящих сообщений
# =============================================================================
def handle_message(update, context):
    user_text = update.message.text.strip().lower()
    user_id = update.message.chat_id
    user_name = update.message.chat.first_name or "Unknown"

    register_user(user_id, user_name)

    # Специальная обработка запросов
    if "какие" in user_text and "услуги" in user_text:
        # Проверка, спрашивает ли пользователь о всех услугах или о конкретном специалисте
        if "у" in user_text:
            # Предполагается, что пользователь спрашивает о конкретном специалисте
            # Извлечём имя специалиста
            system_prompt = (
                "Ты — ассистент, который извлекает имя специалиста из пользовательского запроса. "
                "Введи только имя специалиста или 'None', если не уверен."
            )
            user_prompt = user_text
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=50,
                    temperature=0.3
                )
                specialist_name = resp['choices'][0]['message']['content'].strip()
                if specialist_name.lower() == "none" or not specialist_name:
                    update.message.reply_text("Не удалось определить специалиста. Пожалуйста, уточните запрос.")
                    return
                # Найдём специалиста по имени
                specialists = get_specialists()
                matched_specialist = next((sp for sp in specialists if sp[1].lower() == specialist_name.lower()), None)
                if not matched_specialist:
                    update.message.reply_text(f"Специалист '{specialist_name}' не найден.")
                    return
                # Получим услуги этого специалиста
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT s.title
                    FROM services s
                    JOIN specialist_services ss ON s.id = ss.service_id
                    WHERE ss.specialist_id = %s
                """, (matched_specialist[0],))
                services = cur.fetchall()
                cur.close()
                conn.close()
                if services:
                    service_list = "\n".join([f"- {s[0]}" for s in services])
                    update.message.reply_text(f"Услуги специалиста {matched_specialist[1]}:\n{service_list}")
                else:
                    update.message.reply_text(f"Специалист {matched_specialist[1]} не предлагает никаких услуг.")
            except Exception as e:
                logger.error(f"Ошибка при обработке запроса о специалисте: {e}")
                update.message.reply_text("Произошла ошибка при обработке вашего запроса.")
        else:
            # Пользователь спрашивает о всех услугах
            services = get_services()
            unique_services = sorted({s[1] for s in services})
            if unique_services:
                service_list = "\n".join([f"- {s}" for s in unique_services])
                update.message.reply_text(f"Доступные услуги:\n{service_list}")
            else:
                update.message.reply_text("На данный момент нет услуг.")
        return

    # Проверка наличия текущего состояния пользователя
    st = get_user_state(user_id)
    if st:
        process_booking(update, user_id, user_text, st)
        return

    # Определение намерения пользователя через GPT
    intent_data = determine_intent(user_text)
    intent = intent_data.get("intent", "UNKNOWN")
    entities = intent_data.get("entities", {})

    if intent == "LIST_SERVICES":
        services = get_services()
        unique_services = sorted({s[1] for s in services})
        if unique_services:
            service_list = "\n".join([f"- {s}" for s in unique_services])
            update.message.reply_text(f"Доступные услуги:\n{service_list}")
        else:
            update.message.reply_text("На данный момент нет услуг.")
    elif intent == "LIST_SPECIALIST_SERVICES":
        specialist_name = entities.get("specialist_name", "").strip()
        if not specialist_name:
            update.message.reply_text("Не удалось определить специалиста. Пожалуйста, уточните запрос.")
            return
        specialists = get_specialists()
        matched_specialist = next((sp for sp in specialists if sp[1].lower() == specialist_name.lower()), None)
        if not matched_specialist:
            update.message.reply_text(f"Специалист '{specialist_name}' не найден.")
            return
        # Получим услуги этого специалиста
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.title
            FROM services s
            JOIN specialist_services ss ON s.id = ss.service_id
            WHERE ss.specialist_id = %s
        """, (matched_specialist[0],))
        services = cur.fetchall()
        cur.close()
        conn.close()
        if services:
            service_list = "\n".join([f"- {s[0]}" for s in services])
            update.message.reply_text(f"Услуги специалиста {matched_specialist[1]}:\n{service_list}")
        else:
            update.message.reply_text(f"Специалист {matched_specialist[1]} не предлагает никаких услуг.")
    elif intent == "BOOK_SERVICE":
        service_title = entities.get("service_title", "").strip()
        if not service_title:
            update.message.reply_text("Не удалось определить услугу. Пожалуйста, уточните запрос.")
            return
        # Найдём услугу по названию
        services = get_services()
        matched_service = next((s for s in services if s[1].lower() == service_title.lower()), None)
        if not matched_service:
            update.message.reply_text(f"Услуга '{service_title}' не найдена.")
            return
        # Получим специалистов, предлагающих эту услугу
        specialists = get_specialists(service_id=matched_service[0])
        if not specialists:
            update.message.reply_text("Нет специалистов, предлагающих эту услугу.")
            return
        # Установим состояние для выбора специалиста
        set_user_state(user_id, "select_specialist", service_id=matched_service[0])
        sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in specialists])
        update.message.reply_text(
            f"Вы выбрали услугу: {matched_service[1]}\n"
            f"Пожалуйста, выберите специалиста:\n{sp_text}"
        )
    elif intent == "UNKNOWN":
        # Свободная фраза => GPT
        bot_resp = generate_ai_response(user_text)
        update.message.reply_text(bot_resp)
    else:
        update.message.reply_text("Извините, я не понял ваш запрос. Пожалуйста, попробуйте снова.")

# =============================================================================
# Функция пошаговой логики бронирования
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
            sp_list = get_specialists(service_id=s_id)
            if not sp_list:
                update.message.reply_text("Нет специалистов, предлагающих эту услугу.")
                delete_user_state(user_id)
                return
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
                f"Доступные услуги:\n{s_list}\nВведите название услуги."
            )
        return

    # Шаги
    if step == "select_service":
        # Проверка запроса на повтор списка услуг по ключевым словам
        if "повтори" in user_text or "какие услуги" in user_text or "услуги" in user_text:
            services = get_services()
            unique_services = sorted({s[1] for s in services})
            if unique_services:
                service_list = "\n".join([f"- {s}" for s in unique_services])
                update.message.reply_text(f"Доступные услуги:\n{service_list}")
            else:
                update.message.reply_text("На данный момент нет услуг.")
            return

        # Попытка найти введённую услугу
        services = get_services()
        service = next((s for s in services if s[1].lower() == user_text), None)
        if service:
            set_user_state(user_id, "select_specialist", service_id=service[0])
            sp_list = get_specialists(service_id=service[0])
            if not sp_list:
                update.message.reply_text("Нет специалистов, предлагающих эту услугу.")
                delete_user_state(user_id)
                return
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
                unique_services = sorted({s[1] for s in services})
                if unique_services:
                    service_list = "\n".join([f"- {s}" for s in unique_services])
                    update.message.reply_text(f"Доступные услуги:\n{service_list}")
                else:
                    update.message.reply_text("На данный момент нет услуг.")
            else:
                update.message.reply_text("Такой услуги нет. Попробуйте снова.")

    elif step == "select_specialist":
        # Проверка точного совпадения имени специалиста
        specs = get_specialists(service_id=state['service_id'])
        specialist = next((sp for sp in specs if sp[1].lower() == user_text), None)
        if specialist:
            av_times = get_available_times(specialist[0], state['service_id'])
            if av_times:
                set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=specialist[0])
                txt = "\n".join(av_times)
                update.message.reply_text(
                    f"Доступное время:\n{txt}\nВведите удобное время (YYYY-MM-DD HH:MM, "
                    "или 'HH:MM' если дат всего одна)."
                )
            else:
                # Предложить другого специалиста
                another_spec = find_available_specialist(state['service_id'], exclude_id=specialist[0])
                if another_spec:
                    set_user_state(user_id, "select_specialist", service_id=state['service_id'])
                    update.message.reply_text(
                        f"Нет свободных слотов у {specialist[1]}.\n"
                        f"Может быть, вам подойдет другой специалист:\n"
                        f"{another_spec[0]}. {another_spec[1]}"
                    )
                else:
                    update.message.reply_text("Нет свободных специалистов для этой услуги. Попробуйте позже.")
                    delete_user_state(user_id)
        else:
            # GPT-помощник для распознавания специалиста
            sp_id, sp_name = match_specialist_with_gpt(user_text, specs)
            if sp_id:
                av_times = get_available_times(sp_id, state['service_id'])
                if av_times:
                    set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=sp_id)
                    txt = "\n".join(av_times)
                    update.message.reply_text(
                        f"Похоже, вы имели в виду: {sp_name}\n"
                        f"Доступное время:\n{txt}\nВведите удобное время."
                    )
                else:
                    # Предложить другого специалиста
                    another_spec = find_available_specialist(state['service_id'], exclude_id=sp_id)
                    if another_spec:
                        set_user_state(user_id, "select_specialist", service_id=state['service_id'])
                        update.message.reply_text(
                            f"Нет свободных слотов у {sp_name}.\n"
                            f"Может быть, вам подойдет другой специалист:\n"
                            f"{another_spec[0]}. {another_spec[1]}"
                        )
                    else:
                        update.message.reply_text("Нет свободных специалистов для этой услуги. Попробуйте позже.")
                        delete_user_state(user_id)
            else:
                update.message.reply_text("Не нашли такого специалиста. Попробуйте снова.")

    elif step == "select_time":
        serv_id = state['service_id']
        spec_id = state['specialist_id']
        av_times = get_available_times(spec_id, serv_id)
        chosen_time = parse_time_input(user_text, av_times)
        if chosen_time and chosen_time in av_times:
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
        if user_text in ["да", "да.", "yes", "yes."]:
            success = create_booking(
                user_id=user_id,
                serv_id=state['service_id'],
                spec_id=state['specialist_id'],
                date_str=state['chosen_time']
            )
            if success:
                update.message.reply_text("Запись успешно создана! Спасибо!")
            else:
                update.message.reply_text("Произошла ошибка при создании записи. Пожалуйста, попробуйте позже.")
            delete_user_state(user_id)
        elif user_text in ["нет", "нет.", "no", "no."]:
            update.message.reply_text("Запись отменена.")
            delete_user_state(user_id)
        else:
            update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")

# =============================================================================
# /start команда
# =============================================================================
def start(update, context):
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, или задайте мне любой вопрос!"
    )

# =============================================================================
# Flask-маршруты и настройка диспетчера
# =============================================================================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    upd = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(upd)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

dispatcher = Dispatcher(bot, None, workers=4)  # Увеличено количество рабочих потоков для асинхронной обработки
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

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
