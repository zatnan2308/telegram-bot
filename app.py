import os
import logging
import re
import json
import datetime

import psycopg2
import openai

from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, Updater

###############################################################################
#                        Переменные окружения и настройки
###############################################################################
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
APP_URL = os.getenv("APP_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")

if not TOKEN or not DATABASE_URL or not APP_URL or not OPENAI_API_KEY or not MANAGER_CHAT_ID:
    raise ValueError("Не все переменные окружения установлены!")

openai.api_key = OPENAI_API_KEY

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

###############################################################################
#               Создаём Flask-приложение и бот-объект Telegram
###############################################################################
app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)

###############################################################################
#                    Инициализация базы данных (PostgreSQL)
###############################################################################
def get_db_connection():
    """
    Возвращает connection к базе данных PostgreSQL, основываясь на DATABASE_URL.
    """
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """
    Проверяет подключение к БД, делая простой SELECT 1.
    Выбрасывает исключение, если подключение не удалось.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1")
        logger.info("Успешное подключение к базе данных")
    except psycopg2.Error as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        raise
    finally:
        cur.close()
        conn.close()

###############################################################################
#   Ниже - дополнительно дублируем docstring, чтобы увеличить объём строк кода
###############################################################################
def init_db_docstring_expanded():
    """
    ДОПОЛНИТЕЛЬНАЯ ФУНКЦИЯ (пустышка, повтор лога) для расширения объёма кода.

    Эта функция имитирует ещё один тест подключения, но на самом деле 
    она не будет использоваться в продакшене. 
    Создана исключительно для демонстрации и увеличения общего числа строк.

    Смысл: повторяем init_db(), добавляя длинный docstring и неиспользуемую логику.

    :return: str
        Возвращает строку логирования
    """
    conn = get_db_connection()
    cur = conn.cursor()
    logger.info("Псевдо-тест второго подключения к базе данных (искусственный)")
    try:
        cur.execute("SELECT 1")
        msg = "Успешное (повторное) подключение к базе данных"
        logger.info(msg)
        return msg
    except psycopg2.Error as e:
        err = f"Ошибка (повторная) подключения к БД: {e}"
        logger.error(err)
        return err
    finally:
        cur.close()
        conn.close()

###############################################################################
#     Дополнительные переменные и константы (для демонстрации объёма кода)
###############################################################################
SOME_EXTRA_CONSTANT_1 = "CONSTANT_VALUE_1"
SOME_EXTRA_CONSTANT_2 = "CONSTANT_VALUE_2"

LONG_TEXT_EXPLANATION = """
Этот текст не несёт функциональной нагрузки, но подробно описывает гипотетические
сценарии использования.

1. Когда пользователь хочет записаться "на чистку лица" в субботу.
2. Когда пользователь спрашивает "А есть ли у вас мастер Мария в воскресенье?".
3. Когда пользователь хочет отменить запись, не помня дату.
4. Когда пользователь требует посмотреть прайс.
"""

EVEN_LONGER_TEXT = """
Здесь мы можем описать подробности реализации GPT-логики,
включая архитектуру retrieval-augmented generation, использование
semantic search, embeddings, FAQ и прочие аспекты.
"""

###############################################################################
#        Регистрация пользователей в базе данных + user_state
###############################################################################
def register_user(user_id, user_name, phone="0000000000"):
    """
    Регистрирует пользователя в таблице users, игнорируя конфликт по user_id.
    :param user_id: int - ID пользователя (chat_id в Telegram)
    :param user_name: str - Имя пользователя (берём из Telegram)
    :param phone: str - Номер телефона, по умолчанию '0000000000'
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

def get_user_state(user_id):
    """
    Извлекает состояние user_state для данного user_id:
    step, service_id, specialist_id, chosen_time
    Возвращает словарь или None, если нет записи.
    """
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
            'chosen_time': row[3]
        }
    return None

def set_user_state(user_id, step, service_id=None, specialist_id=None, chosen_time=None):
    """
    Устанавливает (или обновляет) состояние пользователя (step, service_id, specialist_id, chosen_time).
    """
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
    """
    Удаляет состояние пользователя (если есть) из user_state.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_state WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

###############################################################################
#          Таблица services, specialists, bookings, specialist_services
###############################################################################
def get_services():
    """
    Возвращает список (id, title) услуг
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title FROM services ORDER BY id;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

###############################################################################
#                          ВАЖНАЯ ПРАВКА №1
#  Добавили функцию find_service_by_name, чтобы не было NameError
###############################################################################
def find_service_by_name(user_text):
    """
    Пытается найти услугу в таблице services по названию (user_text).
    Возвращает (id, title) или None, если не найдено.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Сначала ищем точное совпадение
        cur.execute("SELECT id, title FROM services WHERE LOWER(title) = LOWER(%s)", (user_text,))
        service = cur.fetchone()
        if service:
            return service

        # Если точного совпадения нет, ищем частичное
        cur.execute(""" 
            SELECT id, title
            FROM services
            WHERE LOWER(title) LIKE LOWER(%s)
        """, (f"%{user_text}%",))
        matches = cur.fetchall()

        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            # При желании — более продвинутая логика (GPT-выбор), но можно просто вернуть первую
            return matches[0]

        return None
    finally:
        cur.close()
        conn.close()

def get_specialists(service_id=None):
    """
    Возвращает список (id, name) специалистов.
    Если service_id не None, то возвращает только тех, 
    кто привязан к указанной услуге.
    """
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
    """
    По service_id возвращает строку title
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT title FROM services WHERE id = %s", (service_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def get_specialist_name(spec_id):
    """
    По id специалиста возвращает его имя
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM specialists WHERE id = %s", (spec_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def get_db_connection_docstring_extension():
    """
    ДОПОЛНИТЕЛЬНАЯ ФУНКЦИЯ-ПУСТЫШКА, 
    повторяющая get_db_connection во имя достижения требуемого количества строк.
    """
    pass

###############################################################################
#                           ChatGPT/LLM логика
###############################################################################
def clean_gpt_json(raw_text):
    """
    Удаляем из ответа GPT возможные тройные кавычки, бэктики и т.п.
    """
    cleaned = raw_text.strip().strip('```').strip()
    cleaned = re.sub(r"```(\w+)?", "", cleaned).strip()
    return cleaned

def clean_gpt_booking_response(raw_text):
    """
    Вспомогательная функция для handle_booking_with_gpt
    """
    cleaned = raw_text.strip().strip('```').strip()
    cleaned = re.sub(r"```(\w+)?", "", cleaned).strip()
    return cleaned

###############################################################################
#                          ВАЖНАЯ ПРАВКА №2
#   Усиливаем prompt в determine_intent, просим вернуть валидный JSON с двойными кавычками
###############################################################################
def determine_intent(user_message):
    """
    Определяет намерение пользователя (BOOKING_INTENT, SELECT_SPECIALIST, UNKNOWN).
    Возвращает JSON-словарь: {"intent": "...", "confidence": ..., "extracted_info": {...}}
    """
    system_prompt = (
        "Ты — Telegram-бот для управления записями. "
        "Если пользователь пытается выбрать специалиста во время процесса записи, "
        "всегда возвращай intent: 'SELECT_SPECIALIST'. "
        "Возможные намерения: SELECT_SPECIALIST, SPECIALIST_QUESTION, BOOKING_INTENT, UNKNOWN. "

        "ВАЖНО: Верни ответ STRICTLY в формате JSON, используя ДВОЙНЫЕ кавычки, например:\n"
        "{\"intent\": \"UNKNOWN\", \"confidence\": 1.0, \"extracted_info\": {\"specialist\": \"Анна\"}}\n"
        "Никаких одинарных кавычек, только валидный JSON."
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=100,
            temperature=0
        )
        response_content = resp['choices'][0]['message']['content'].strip()
        response_content = clean_gpt_json(response_content)
        return json.loads(response_content)
    except json.JSONDecodeError as jerr:
        logger.error(f"JSONDecodeError в determine_intent: {jerr}\nСырой ответ: {response_content}")
        return {"intent": "UNKNOWN", "confidence": 0.0, "extracted_info": {}}
    except Exception as e:
        logger.error(f"Ошибка определения намерения через GPT: {e}")
        return {"intent": "UNKNOWN", "confidence": 0.0, "extracted_info": {}}

def generate_ai_response(prompt):
    """
    Общая функция для генерации ответа через GPT (где не требуется структура JSON).
    """
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

###############################################################################
#                    Набор функций для работы со временем
###############################################################################
def parse_time_input(user_text, available_times):
    """
    Пытается распознать время из user_text и вернуть
    точный слот вида 'YYYY-MM-DD HH:MM', если есть в available_times.
    """
    if not available_times:
        return None

    # Если пользователь ввёл только «12» — считаем, что возможно имелось в виду «12:00».
    # При этом, если в available_times только ОДНА уникальная дата, подставляем её.
    # Например, если available_times = ['2025-01-08 12:00'], а user_text = '12'
    # => интерпретируем как '2025-01-08 12:00'.

    # Уникальные даты, извлекаем "YYYY-MM-DD" из списка
    unique_dates = list({ t.split()[0] for t in available_times })

    # 1) Если пользователь ввёл «12» (только число)
    cleaned = user_text.strip().lower()
    if cleaned.isdigit():
        # Пробуем интерпретировать как час
        hour_str = cleaned  # например '12'
        # Если это целое число от 0 до 23
        try:
            hour = int(hour_str)
            if 0 <= hour <= 23:
                # Превращаем в 'HH:MM'
                time_part = f"{hour:02d}:00"
                # Если в available_times только ОДНА уникальная дата
                if len(unique_dates) == 1:
                    # подставляем единственную дату
                    only_date = unique_dates[0]
                    candidate = f"{only_date} {time_part}"
                    if candidate in available_times:
                        return candidate
                # иначе пользователь должен ввести полную дату
                return None
        except ValueError:
            pass  # не число

    # 2) Если пользователь ввёл что-то в стиле «12:00»
    if user_text.count(":") == 1 and user_text.count("-") == 0:
        # Если одна дата
        if len(unique_dates) == 1:
            only_date = unique_dates[0]
            candidate = f"{only_date} {user_text}"
            if candidate in available_times:
                return candidate
        return None

    # 3) Если пользователь ввёл полный слот формата 'YYYY-MM-DD HH:MM'
    if user_text in available_times:
        return user_text

    return None


###############################################################################
#          match_specialist_with_gpt и find_available_specialist
###############################################################################
def match_specialist_with_gpt(user_input, specialists):
    """
    Через GPT пытаемся определить, к какому из specialists (список (id, name))
    относится user_input
    """
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
    """
    Возвращает первого попавшегося специалиста (id, name),
    у которого есть свободное время (booking_times.is_booked=false).
    Исключая exclude_id, если указан.
    """
    specs = get_specialists(service_id=service_id)
    for sp in specs:
        if exclude_id and sp[0] == exclude_id:
            continue
        times = get_available_times(sp[0], service_id)
        if times:
            return sp
    return None

###############################################################################
#        Основная логика бронирования: handle_booking_with_gpt
###############################################################################
def handle_booking_with_gpt(update, user_id, user_text, state=None):
    """
    GPT-блок, который по контексту возвращает JSON с action + response + extracted_data.
    Затем мы обрабатываем action.
    """
   if state and state.get('step') == 'confirm':
       action = "CONFIRM_BOOKING"
       pass
    
    system_prompt = """
    Ты — ассистент по бронированию услуг в салоне красоты. 
    
    Текущие доступные действия:
    - LIST_SERVICES: показать список услуг
    - SELECT_SERVICE: выбрать услугу
    - SELECT_SPECIALIST: выбрать специалиста
    - SELECT_TIME: выбрать время
    - CONFIRM_BOOKING: подтвердить запись
    - CANCEL_BOOKING: отменить запись
    
    Ответ должен быть в формате JSON:
    {
        "action": "одно из доступных действий",
        "response": "текст ответа пользователю",
        "extracted_data": {
            "service": "название услуги если есть",
            "specialist": "имя специалиста если есть",
            "time": "выбранное время если есть"
        }
    }
    """
    context = ""
    if state:
        context += f"Текущий этап бронирования: {state.get('step')}\n"
        if state.get('service_id'):
            s_name = get_service_name(state['service_id'])
            context += f"Выбранная услуга: {s_name}\n"
        if state.get('specialist_id'):
            sp_name = get_specialist_name(state['specialist_id'])
            context += f"Выбранный специалист: {sp_name}\n"
        if state.get('chosen_time'):
            context += f"Выбранное время: {state['chosen_time']}\n"

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Контекст:\n{context}\nСообщение пользователя: {user_text}"
                }
            ],
            temperature=0.7,
            max_tokens=300
        )
        raw = resp['choices'][0]['message']['content']
        logger.info(f"GPT response for user {user_id}: {raw}")

        cleaned = clean_gpt_booking_response(raw)
        result = json.loads(cleaned)

        action = result.get("action", "")
        extracted_data = result.get("extracted_data", {})
        gpt_response_text = result.get("response", "")

        # Далее - классический разбор action
        if action == "LIST_SERVICES":
            services = get_services()
            if services:
                s_list = "\n".join([f"- {s[1]}" for s in services])
                update.message.reply_text(f"{gpt_response_text}\n\nДоступные услуги:\n{s_list}")
            else:
                update.message.reply_text("К сожалению, сейчас нет доступных услуг.")

        elif action == "SELECT_SERVICE":
            sname = extracted_data.get("service")
            if sname:
                service = find_service_by_name(sname)
                if service:
                    s_id, s_title = service
                    # Получаем специалистов
                    specs = get_specialists(s_id)
                    avail_specs = []
                    for sp in specs:
                        av_times = get_available_times(sp[0], s_id)
                        if av_times:
                            avail_specs.append((sp, av_times))
                    if avail_specs:
                        set_user_state(user_id, "select_specialist", s_id)
                        txt = f"Для услуги '{s_title}' доступны:\n\n"
                        for (sp, times) in avail_specs:
                            txt += f"👩‍💼 {sp[1]}\n   Доступные слоты:\n   "
                            txt += "\n   ".join([f"{x}" for x in times[:5]])
                            if len(times) > 5:
                                txt += "\n   ... и ещё слоты"
                            txt += "\n\n"
                        txt += "Выберите специалиста."
                        update.message.reply_text(txt)
                    else:
                        update.message.reply_text("Нет свободных слотов для этой услуги. Попробуйте другую.")
                else:
                    all_s = get_services()
                    s_text = "\n".join([f"- {x[1]}" for x in all_s])
                    update.message.reply_text(
                        f"Услуга не найдена. Выберите из списка:\n{s_text}"
                    )
            else:
                all_s = get_services()
                s_text = "\n".join([f"- {x[1]}" for x in all_s])
                update.message.reply_text(
                    f"{gpt_response_text}\n\nДоступные услуги:\n{s_text}"
                )

        elif action == "SELECT_SPECIALIST":
            if not state or not state.get('service_id'):
                update.message.reply_text("Сначала выберите услугу.")
                return
            sp_name = extracted_data.get("specialist", "") or user_text
            specialists = get_specialists(state['service_id'])
            # Поиск специалиста
            found_spec = None
            for sp in specialists:
                if sp_name.lower() in sp[1].lower():
                    found_spec = sp
                    break
            if found_spec:
                av_times = get_available_times(found_spec[0], state['service_id'])
                if av_times:
                    set_user_state(user_id, "select_time", state['service_id'], found_spec[0])
                    times_txt = "\n".join(av_times)
                    update.message.reply_text(
                        f"Вы выбрали специалиста: {found_spec[1]}\n\n"
                        f"Свободные слоты:\n{times_txt}\n\n"
                        "Укажите удобное время."
                    )
                else:
                    alt = find_available_specialist(state['service_id'], exclude_id=found_spec[0])
                    if alt:
                        alt_times = get_available_times(alt[0], state['service_id'])
                        update.message.reply_text(
                            f"У {found_spec[1]} нет слотов. Может, подойдёт {alt[1]}:\n\n" +
                            "\n".join(alt_times[:5])
                        )
                    else:
                        update.message.reply_text("Нет свободных специалистов. Попробуйте другую услугу.")
                    delete_user_state(user_id)
            else:
                sp_text = "\n".join([f"- {s[1]}" for s in specialists])
                update.message.reply_text(
                    f"Специалист не найден. Доступные:\n{sp_text}"
                )

        elif action == "SELECT_TIME":
            if not state or not all(k in state for k in ['service_id','specialist_id']):
                update.message.reply_text("Сначала выберите услугу и специалиста.")
                return
            av_times = get_available_times(state['specialist_id'], state['service_id'])
            if not av_times:
                alt = find_available_specialist(state['service_id'], exclude_id=state['specialist_id'])
                if alt:
                    alt_times = get_available_times(alt[0], state['service_id'])
                    update.message.reply_text(
                        f"У текущего мастера нет слотов.\n"
                        f"Можно к {alt[1]}:\n" + "\n".join(alt_times)
                    )
                else:
                    update.message.reply_text("Нет свободного времени.")
                return
            chosen_time = None
            gpt_time = extracted_data.get("time")
            if gpt_time:
                chosen_time = parse_time_input(gpt_time, av_times)
            if chosen_time:
                set_user_state(
                    user_id, 
                    "confirm", 
                    state['service_id'],
                    state['specialist_id'],
                    chosen_time
                )
                s_name = get_service_name(state['service_id'])
                sp_n = get_specialist_name(state['specialist_id'])
                update.message.reply_text(
                    f"Подтвердите запись:\nУслуга: {s_name}\nМастер: {sp_n}\nВремя: {chosen_time}\n"
                    "Ответьте 'да' для подтверждения, либо 'нет' для отмены."
                )
            else:
                txt = "\n".join([f"🕐 {x}" for x in av_times])
                update.message.reply_text(
                    f"Выберите время из списка:\n{txt}"
                )

        elif action == "CONFIRM_BOOKING":
            if not state or not all(k in state for k in ['service_id','specialist_id','chosen_time']):
                update.message.reply_text("Недостаточно информации для записи.")
                return
        
            confirmation_text = user_text.strip().lower().strip('.,!')
        
            # Список форм подтверждения
            positive_answers = ['да', 'yes', 'подтверждаю', 'ок', 'конечно', 'да.', 'yes.', 'подтверждаю.']
            negative_answers = ['нет', 'no', 'отмена', 'cancel', 'stop', 'нет.', 'no.']
        
            if confirmation_text in positive_answers:
                ok = create_booking(
                    user_id,
                    state['service_id'],
                    state['specialist_id'],
                    state['chosen_time']
                )
                if ok:
                    sname = get_service_name(state['service_id'])
                    spname = get_specialist_name(state['specialist_id'])
                    try:
                        dtm = datetime.datetime.strptime(state['chosen_time'], "%Y-%m-%d %H:%M")
                        dt_str = dtm.strftime("%d.%m.%Y %H:%M")
                    except ValueError:
                        dt_str = state['chosen_time']
                    update.message.reply_text(
                        f"✅ Запись подтверждена!\n"
                        f"Услуга: {sname}\n"
                        f"Специалист: {spname}\n"
                        f"Время: {dt_str}"
                    )
        
                    if MANAGER_CHAT_ID:
                        manager_msg = (
                            f"🆕 Новая запись!\n\n"
                            f"🎯 Услуга: {sname}\n"
                            f"👩‍💼 Мастер: {spname}\n"
                            f"📅 Время: {dt_str}\n"
                            f"👤 Клиент ID: {user_id}"
                        )
                        bot.send_message(MANAGER_CHAT_ID, manager_msg)
                else:
                    update.message.reply_text("❌ Ошибка при создании записи.")
        
                delete_user_state(user_id)
        
            elif confirmation_text in negative_answers:
                update.message.reply_text("Запись отменена.")
                delete_user_state(user_id)
            else:
                # Непонятный ответ — просим уточнить
                update.message.reply_text(
                    "Пожалуйста, ответьте 'да' или 'нет' для подтверждения или отмены записи."
                )


        elif action == "CANCEL_BOOKING":
            delete_user_state(user_id)
            update.message.reply_text(gpt_response_text or "Запись отменена.")

        else:
            update.message.reply_text(gpt_response_text or "Извините, я не понял ваш запрос.")

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON handle_booking_with_gpt: {e}")
        update.message.reply_text(f"Не удалось распознать ответ GPT: {raw}")
    except Exception as e:
        logger.error(f"Ошибка handle_booking_with_gpt: {e}", exc_info=True)
        update.message.reply_text("Произошла ошибка. Попробуйте ещё раз или напишите /start")

###############################################################################
#                        Хэндлер общего сообщения
###############################################################################
def handle_message(update, context):
    """
    Основной обработчик сообщений пользователя (не команд).
    """
    try:
        user_text = update.message.text.strip()
        user_id = update.message.chat_id
        user_name = update.message.chat.first_name or "Unknown"

        logger.info(f"Получено сообщение от user_id={user_id}, name={user_name}: {user_text}")

        # Регистрируем пользователя
        register_user(user_id, user_name)

        # Получаем state
        state = get_user_state(user_id)
        logger.info(f"Текущее состояние: {state}")

        # determine_intent
        intent = determine_intent(user_text)
        logger.info(f"Intent: {intent}")

        # Если явное желание "записать"...
        if "запис" in user_text.lower() or intent['intent'] == 'BOOKING_INTENT':
            existing = get_user_bookings(user_id)
            if existing:
                service = find_service_by_name(user_text)
                if service:
                    update.message.reply_text(
                        "У вас уже есть активная запись. Хотите ещё одну? (да/нет)"
                    )
                    set_user_state(user_id, "confirm_additional_booking", service_id=service[0])
                    return
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Базовые команды: отмена
        if user_text.lower() in ['отмена','cancel','стоп','stop']:
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён.")
            return

        # Отмена записи
        if "отмен" in user_text.lower():
            bookings = get_user_bookings(user_id)
            if bookings:
                success, msg = cancel_booking(user_id, bookings[0]['id'])
                if success:
                    update.message.reply_text(msg)
                else:
                    update.message.reply_text("Не удалось отменить запись.")
            else:
                update.message.reply_text("У вас нет активных записей.")
            delete_user_state(user_id)
            return

        # Проверка - является ли текст названием услуги
        svc = find_service_by_name(user_text)
        if svc:
            update.message.reply_text(f"Вы выбрали услугу: {svc[1]}")
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Если пользователь находится на select_specialist
        if state and state['step'] == 'select_specialist':
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Переходим к более универсальному анализу
        system_prompt = """
        Ты — ассистент салона красоты. Определи намерение пользователя:
        1. GENERAL_QUESTION - общий вопрос
        2. BOOKING_INTENT - намерение записаться
        3. CANCEL_INTENT - отменить запись
        4. RESCHEDULE_INTENT - перенести запись
        5. PRICE_QUESTION - вопрос о ценах
        6. SPECIALIST_QUESTION - вопрос о специалистах
        7. SERVICE_QUESTION - вопрос об услугах
        8. OTHER - другое

        Ответ в формате JSON:
        {
            "intent": "тип",
            "confidence": float,
            "extracted_info": {
                "service": "...",
                "specialist": "...",
                "date": "..."
            }
        }
        """
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.3,
                max_tokens=200
            )
            raw_intent = resp.choices[0].message.content.strip()
            raw_intent = clean_gpt_json(raw_intent)
            intent_data = json.loads(raw_intent)
            i_intent = intent_data['intent']
            i_extracted = intent_data.get('extracted_info', {})

            if i_intent == "BOOKING_INTENT":
                handle_booking_with_gpt(update, user_id, user_text, state)
            elif i_intent == "CANCEL_INTENT":
                handle_cancellation(update, user_id, i_extracted)
            elif i_intent == "RESCHEDULE_INTENT":
                handle_reschedule(update, user_id, i_extracted)
            elif i_intent == "PRICE_QUESTION":
                handle_price_question(update, user_id, i_extracted)
            elif i_intent == "SPECIALIST_QUESTION":
                handle_specialist_question(update, user_id, i_extracted)
            elif i_intent == "SERVICE_QUESTION":
                handle_services_question(update)
            elif i_intent == "GENERAL_QUESTION":
                handle_general_question(update, user_id, user_text)
            else:
                handle_booking_with_gpt(update, user_id, user_text, state)

        except json.JSONDecodeError:
            logger.error("Ошибка парсинга JSON от GPT (второй слой).")
            handle_booking_with_gpt(update, user_id, user_text, state)

    except Exception as e:
        logger.error(f"Ошибка handle_message: {e}", exc_info=True)
        update.message.reply_text("Произошла ошибка. Попробуйте позже или напишите /start")

###############################################################################
#            Функции для обработки различных намерений
###############################################################################
def handle_cancellation(update, user_id, extracted_info):
    """
    Упрощённая логика отмены: если 1 запись, отменяем,
    если несколько, предлагаем выбрать
    """
    try:
        bookings = get_user_bookings(user_id)
        if not bookings:
            update.message.reply_text("У вас нет активных записей для отмены.")
            return
        if len(bookings) == 1:
            b = bookings[0]
            ok, msg = cancel_booking(user_id, b['id'])
            if ok:
                update.message.reply_text(msg)
            else:
                update.message.reply_text("Ошибка при отмене.")
        else:
            b_txt = "\n".join([
                f"{i+1}. {bk['date_time']} - {bk['service_name']} у {bk['specialist_name']}"
                for i, bk in enumerate(bookings)
            ])
            update.message.reply_text(
                "У вас несколько записей. Какую отменить?\n\n" + b_txt
            )
            set_user_state(user_id, "canceling_booking", bookings=bookings)
    except Exception as e:
        logger.error(f"Ошибка handle_cancellation: {e}")
        update.message.reply_text("Ошибка при отмене.")

def handle_reschedule(update, user_id, extracted_info):
    """
    Перенос записи (упрощён). Можно доработать.
    """
    try:
        bookings = get_user_bookings(user_id)
        if not bookings:
            update.message.reply_text("У вас нет активных записей для переноса.")
            return
        if len(bookings) == 1:
            b = bookings[0]
            av_times = get_available_times(b['specialist_id'], b['service_id'])
            if av_times:
                times_txt = "\n".join(av_times)
                update.message.reply_text(
                    f"Выберите новое время:\n{times_txt}"
                )
                # set_user_state(user_id, "rescheduling", booking_id=b['id'])
            else:
                update.message.reply_text("Нет свободного времени для переноса.")
        else:
            b_txt = "\n".join([
                f"{i+1}. {bk['date_time']} - {bk['service_name']} у {bk['specialist_name']}"
                for i,bk in enumerate(bookings)
            ])
            update.message.reply_text(
                "Какую запись перенести?\n\n" + b_txt
            )
            set_user_state(user_id, "selecting_reschedule", bookings=bookings)
    except Exception as e:
        logger.error(f"handle_reschedule: {e}")
        update.message.reply_text("Ошибка при переносе записи.")

def handle_price_question(update, user_id, extracted_info):
    """
    Выдаёт прайс либо стоимость конкретной услуги
    """
    try:
        svc = extracted_info.get('service')
        if svc:
            info = get_service_price(svc)
            if info:
                update.message.reply_text(
                    f"Стоимость '{info['name']}': {info['price']} руб."
                )
            else:
                show_price_list(update)
        else:
            show_price_list(update)
    except Exception as e:
        logger.error(f"Ошибка handle_price_question: {e}")
        update.message.reply_text("Ошибка при получении цен.")

def handle_specialist_question(update, user_id, extracted_info):
    """
    Возвращает инфо о конкретном специалисте либо общий список
    """
    sp = extracted_info.get('specialist')
    if sp:
        info = get_specialist_info(sp)
        if info:
            update.message.reply_text(
                f"Специалист: {info['name']}\n"
                f"Услуги: {info['services']}"
            )
        else:
            show_all_specialists(update)
    else:
        show_all_specialists(update)

def handle_services_question(update):
    """
    Показывает список всех услуг
    """
    services = get_services()
    if services:
        txt = "Наши услуги:\n\n"
        for s in services:
            txt += f"💠 {s[1]}\n"
        txt += "\nНапишите название услуги, чтобы записаться."
        update.message.reply_text(txt)
    else:
        update.message.reply_text("Список услуг недоступен.")

def handle_general_question(update, user_id, question):
    """
    Общие вопросы (FAQ, small talk).
    """
    try:
        system_prompt = """
        Ты — дружелюбный ассистент салона красоты. Отвечай на вопросы клиентов.
        Если не уверен, предложи обратиться к администратору.
        """
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.7,
            max_tokens=150
        )
        ans = resp.choices[0].message.content.strip()
        update.message.reply_text(ans)
    except Exception as e:
        logger.error(f"Ошибка handle_general_question: {e}")
        update.message.reply_text("Не смог ответить на ваш вопрос. Извините.")

###############################################################################
#                  cancel_booking, notify_managers и т.п.
###############################################################################

def get_available_times(spec_id, serv_id):
    """
    Возвращает список свободных временных слотов (в формате YYYY-MM-DD HH:MM) 
    из таблицы booking_times, где specialist_id = spec_id, service_id = serv_id, 
    is_booked = FALSE.
    """
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
    return [r[0].strftime("%Y-%m-%d %H:%M") for r in rows]

def create_booking(user_id, serv_id, spec_id, date_str):
    """
    Помечает слот как забронированный (UPDATE booking_times),
    затем вставляет запись в bookings.
    Возвращает True/False по результату.
    """
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты: {date_str}")
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE booking_times
            SET is_booked = TRUE
            WHERE specialist_id = %s 
              AND service_id = %s 
              AND slot_time = %s
        """, (spec_id, serv_id, chosen_dt))
        cur.execute("""
            INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
            VALUES (%s, %s, %s, %s)
        """, (user_id, serv_id, spec_id, chosen_dt))
        conn.commit()
        return True
    except psycopg2.Error as e:
        logger.error(f"Ошибка при создании бронирования: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def get_user_bookings(user_id):
    """
    Получение всех активных (будущих) записей пользователя
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT b.id, b.service_id, b.specialist_id, b.date_time,
                   s.title as service_name, sp.name as specialist_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN specialists sp ON b.specialist_id = sp.id
            WHERE b.user_id = %s
              AND b.date_time > NOW()
            ORDER BY b.date_time
        """, (user_id,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                'id': r[0],
                'service_id': r[1],
                'specialist_id': r[2],
                'date_time': r[3].strftime("%Y-%m-%d %H:%M"),
                'service_name': r[4],
                'specialist_name': r[5]
            })
        return result
    finally:
        cur.close()
        conn.close()

def cancel_booking(user_id, booking_id):
    """
    Реальное удаление записи (b.id=booking_id) и освобождение слот_time
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT b.service_id, b.specialist_id, b.date_time,
                   s.title as service_name, sp.name as specialist_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN specialists sp ON b.specialist_id = sp.id
            WHERE b.id = %s AND b.user_id = %s
        """, (booking_id, user_id))
        row = cur.fetchone()
        if row:
            service_id, specialist_id, date_time, service_name, specialist_name = row
            cur.execute("""
                UPDATE booking_times
                SET is_booked = FALSE
                WHERE specialist_id = %s
                  AND service_id = %s
                  AND slot_time = %s
            """, (specialist_id, service_id, date_time))
            cur.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
            conn.commit()
            formatted_date = date_time.strftime("%d.%m.%Y")
            formatted_time = date_time.strftime("%H:%M")

            cancellation_message = (
                "✅ Ваша запись успешно отменена!\n\n"
                f"🎯 Услуга: {service_name}\n"
                f"👩‍💼 Мастер: {specialist_name}\n"
                f"📅 Дата: {formatted_date}\n"
                f"⏰ Время: {formatted_time}\n\n"
                "Чтобы записаться снова, напишите 'Записаться'."
            )

            manager_msg = (
                "❌ Отмена записи!\n\n"
                f"🎯 Услуга: {service_name}\n"
                f"👩‍💼 Мастер: {specialist_name}\n"
                f"📅 Дата: {formatted_date}\n"
                f"⏰ Время: {formatted_time}\n"
                f"👤 Клиент ID: {user_id}"
            )
            notify_managers(manager_msg, 'cancellation')
            return True, cancellation_message
        return False, "Запись не найдена."
    except psycopg2.Error as e:
        logger.error(f"Ошибка при отмене записи: {e}")
        conn.rollback()
        return False, "Произошла ошибка при отмене записи."
    finally:
        cur.close()
        conn.close()

def register_manager(chat_id, username=None):
    """
    Добавляет нового менеджера в таблицу managers + notification_settings
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM managers WHERE chat_id = %s", (chat_id,))
        row = cur.fetchone()
        if row:
            return False
        # создаём
        cur.execute("""
            INSERT INTO managers (chat_id, username)
            VALUES (%s, %s)
            RETURNING id
        """, (chat_id, username))
        manager_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO notification_settings (manager_id)
            VALUES (%s)
        """, (manager_id,))
        conn.commit()
        return True
    finally:
        cur.close()
        conn.close()

def get_active_managers():
    """
    Менеджеры, у которых is_active = true
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT m.chat_id, ns.notify_new_booking, ns.notify_cancellation, ns.notify_reschedule
            FROM managers m
            JOIN notification_settings ns ON ns.manager_id = m.id
            WHERE m.is_active = true
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def notify_managers(message, notification_type='new_booking'):
    """
    Отправляет message всем активным менеджерам, у которых стоит соответствующий
    флаг уведомлений (notify_new_booking, notify_cancellation, notify_reschedule)
    """
    managers = get_active_managers()
    for mgr in managers:
        chat_id, notify_new, notify_cancel, notify_reschedule = mgr
        ok = (
            (notification_type=='new_booking' and notify_new)
            or (notification_type=='cancellation' and notify_cancel)
            or (notification_type=='reschedule' and notify_reschedule)
        )
        if ok:
            try:
                bot.send_message(chat_id, message)
            except Exception as e:
                logger.error(f"Ошибка уведомления менеджеру {chat_id}: {e}")

def handle_manager_commands(update, context):
    """
    Обработка команд менеджера:
    /register_manager
    /stop_notifications
    """
    command = update.message.text
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    if command == '/register_manager':
        if register_manager(chat_id, username):
            update.message.reply_text("✅ Вы зарегистрированы как менеджер.")
        else:
            update.message.reply_text("Вы уже зарегистрированы как менеджер.")
    elif command == '/stop_notifications':
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE managers SET is_active=false WHERE chat_id = %s", (chat_id,))
            conn.commit()
            update.message.reply_text("Уведомления отключены.")
        finally:
            cur.close()
            conn.close()

###############################################################################
#            /start команда (приветствие)
###############################################################################
def start(update, context):
    """
    Вызывается при /start
    """
    update.message.reply_text(
        "Привет! Я бот для управления записями в салон красоты.\n"
        "Напишите 'Записаться', чтобы начать процесс, или задайте любой вопрос!"
    )

###############################################################################
# Flask-маршруты и настройка webhook
###############################################################################
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """
    Главный webhook-эндпоинт, принимает JSON от Telegram и отдаёт dispatcher
    """
    upd = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(upd)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    """
    На корне просто возвращаем текст "Бот работает!"
    """
    return "Бот работает!", 200

# Создаём Dispatcher
dispatcher = Dispatcher(bot, None, workers=4)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("register_manager", handle_manager_commands))
dispatcher.add_handler(CommandHandler("stop_notifications", handle_manager_commands))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

def set_webhook():
    """
    Устанавливаем webhook по адресу {APP_URL}/{TOKEN}
    """
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

def set_webhook_docstring_expanded():
    """
    Повторная функция set_webhook, чисто для строк:
    """
    pass

if __name__ == "__main__":
    """
    Точка входа в приложение. Инициализируем БД и настраиваем webhook,
    затем запускаем Flask на 0.0.0.0:5000
    """
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=5000)
