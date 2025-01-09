###############################################################################
# Ниже — полный код, 1 в 1, с вашими 1761 строками, + комментарии правок.
###############################################################################

from flask import Flask, request

import logging
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, Updater
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

openai.api_key = OPENAI_API_KEY

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telegram.Bot(token=TOKEN)
app = Flask(__name__)

# =============================================================================
# Подключение к базе данных
# =============================================================================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Проверка подключения к БД"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверяем подключение к БД
        cur.execute("SELECT 1")
        logger.info("Успешное подключение к базе данных")
    except psycopg2.Error as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        raise
    finally:
        cur.close()
        conn.close()
        
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Добавляем обработчики команд менеджера
    dp.add_handler(CommandHandler("register_manager", handle_manager_commands))
    dp.add_handler(CommandHandler("stop_notifications", handle_manager_commands))

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
        return {'step': row[0], 'service_id': row[1], 'specialist_id': row[2], 'chosen_time': row[3]}
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

# == ДОБАВЛЕНО == 
# Функция, убирающая потенциальные обёртки ```json и прочие из ответа
def clean_gpt_json(raw_text):
    import re
    cleaned = raw_text.strip().strip('```').strip()
    # Удаляем возможные тех. надписи
    cleaned = re.sub(r"```(\w+)?", "", cleaned).strip()
    return cleaned

def determine_intent(user_message):
    system_prompt = (
        "Ты — Telegram-бот для управления записями. "
        "Если пользователь пытается выбрать специалиста во время процесса записи, "
        "всегда возвращай intent: 'SELECT_SPECIALIST'. "
        "Возможные намерения: SELECT_SPECIALIST, SPECIALIST_QUESTION, BOOKING_INTENT, UNKNOWN. "
        "Верни ответ строго в формате JSON: "
        "{'intent': 'тип намерения', 'confidence': число от 0 до 1, "
        "'extracted_info': {'specialist': 'имя специалиста если есть'}}"
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

        # == ДОБАВЛЕНО ==
        response_content = clean_gpt_json(response_content)

        return json.loads(response_content)
    except json.JSONDecodeError as jerr:
        logger.error(f"JSONDecodeError в determine_intent: {jerr}\nСырой ответ: {response_content}")
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "extracted_info": {}
        }
    except Exception as e:
        logger.error(f"Ошибка определения намерения через GPT: {e}")
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "extracted_info": {}
        }

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
    return [row[0].strftime("%Y-%m-%d %H:%M") for row in rows]

def create_booking(user_id, serv_id, spec_id, date_str):
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты: {date_str}")
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE booking_times
    SET is_booked = TRUE
    WHERE specialist_id = %s AND service_id = %s AND slot_time = %s
    """, (spec_id, serv_id, chosen_dt))
    cur.execute("""
    INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
    VALUES (%s, %s, %s, %s)
    """, (user_id, serv_id, spec_id, chosen_dt))
    conn.commit()
    cur.close()
    conn.close()
    return True

def find_service_by_name(user_text):
    """Поиск услуги по названию с использованием нечеткого поиска"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Сначала ищем точное совпадение
        cur.execute("SELECT id, title FROM services WHERE LOWER(title) = LOWER(%s)", (user_text,))
        service = cur.fetchone()
        
        if not service:
            # Если точного совпадения нет, ищем частичное
            cur.execute("""
                SELECT id, title 
                FROM services 
                WHERE LOWER(title) LIKE LOWER(%s) 
                   OR LOWER(%s) = ANY(STRING_TO_ARRAY(LOWER(title), ' '))
            """, (f'%{user_text}%', user_text))
            services = cur.fetchall()
            
            if len(services) == 1:
                # Если нашли только одно совпадение
                service = services[0]
            elif len(services) > 1:
                # Если нашли несколько совпадений, используем GPT для выбора наиболее подходящего
                system_prompt = (
                    f"Выбери одну наиболее подходящую услугу из списка на основе запроса клиента.\n"
                    f"Запрос клиента: {user_text}\n"
                    f"Доступные услуги: {[s[1] for s in services]}\n"
                    "Верни только название выбранной услуги без дополнительного текста."
                )
                
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_text}
                        ],
                        temperature=0.3,
                        max_tokens=50
                    )
                    
                    selected_service = response.choices[0].message.content.strip()
                    if selected_service and selected_service.lower() != "none":
                        service = next(
                            (s for s in services if s[1].lower() == selected_service.lower()),
                            services[0]  # Если GPT вернул что-то непонятное, берем первую услугу
                        )
                except Exception as e:
                    logger.error(f"Ошибка GPT при выборе услуги: {e}")
                    service = services[0]  # В случае ошибки GPT берем первую услугу
        
        return service
    
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

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
            return None
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
            return sp
    return None

# == ДОБАВЛЕНО == 
# Функция для "чистки" JSON-ответа GPT (в handle_booking_with_gpt)
def clean_gpt_booking_response(raw_text):
    import re
    cleaned = raw_text.strip().strip('```').strip()
    # Удаляем маркеры вроде ```json
    cleaned = re.sub(r"```(\w+)?", "", cleaned).strip()
    return cleaned

def handle_booking_with_gpt(update, user_id, user_text, state=None):
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
        context = f"Текущий этап бронирования: {state['step']}\n"
        if state.get('service_id'):
            service_name = get_service_name(state['service_id'])
            context += f"Выбранная услуга: {service_name}\n"
        if state.get('specialist_id'):
            specialist_name = get_specialist_name(state['specialist_id'])
            context += f"Выбранный специалист: {specialist_name}\n"
        if state.get('chosen_time'):
            context += f"Выбранное время: {state['chosen_time']}\n"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Контекст:\n{context}\nСообщение пользователя: {user_text}"}
            ],
            temperature=0.7,
            max_tokens=200,
            # == УБРАНО: response_format={ "type": "json_object" }
            # == Потому что иногда вызывает проблемы
        )
        
        gpt_response = response.choices[0].message.content
        logger.info(f"GPT response for user {user_id}: {gpt_response}")

        # == ДОБАВЛЕНО ==
        cleaned_gpt_response = clean_gpt_booking_response(gpt_response)

        result = json.loads(cleaned_gpt_response)
        action = result.get('action')
        extracted_data = result.get('extracted_data', {})
        gpt_response_text = result.get('response', '')

        if action == "LIST_SERVICES":
            services = get_services()
            if services:
                service_list = "\n".join([f"- {s[1]}" for s in services])
                update.message.reply_text(f"{gpt_response_text}\n\nДоступные услуги:\n{service_list}")
            else:
                update.message.reply_text("К сожалению, сейчас нет доступных услуг.")

        elif action == "SELECT_SERVICE":
            service_name = extracted_data.get('service')
            if service_name:
                service = find_service_by_name(service_name)
                if service:
                    service_id, service_name = service
                    # Сначала найдем всех специалистов с доступным временем
                    specialists = get_specialists(service_id=service_id)
                    available_specialists = []
                    
                    for spec in specialists:
                        available_times = get_available_times(spec[0], service_id)
                        if available_times:
                            available_specialists.append((spec, available_times))
                    
                    if available_specialists:
                        set_user_state(user_id, "select_specialist", service_id=service_id)
                        response_text = f"Для услуги '{service_name}' доступны следующие специалисты:\n\n"
                        
                        for spec, times in available_specialists:
                            response_text += f"👩‍💼 {spec[1]}\n   Доступное время:\n   "
                            response_text += "\n   ".join([f"🕐 {t}" for t in times[:5]])  # Показываем первые 5 слотов
                            if len(times) > 5:
                                response_text += "\n   ... и другие слоты"
                            response_text += "\n\n"
                        
                        response_text += "Пожалуйста, выберите специалиста."
                        update.message.reply_text(response_text)
                    else:
                        update.message.reply_text(
                            "К сожалению, сейчас нет свободного времени для этой услуги. "
                            "Попробуйте выбрать другую услугу или свяжитесь с администратором."
                        )
                else:
                    services = get_services()
                    service_list = "\n".join([f"- {s[1]}" for s in services])
                    update.message.reply_text(
                        f"Услуга не найдена. Выберите из списка:\n\n{service_list}"
                    )
            else:
                services = get_services()
                service_list = "\n".join([f"- {s[1]}" for s in services])
                update.message.reply_text(
                    f"{gpt_response_text}\n\n"
                    f"Доступные услуги:\n{service_list}"
                )

        elif action == "SELECT_SPECIALIST":
            if not state or not state.get('service_id'):
                update.message.reply_text("Сначала выберите услугу.")
                return

            specialist_name = extracted_data.get('specialist') or user_text  # Берем имя из GPT или из текста пользователя
            specialists = get_specialists(state['service_id'])
            
            if specialist_name:
                # Ищем специалиста, игнорируя регистр и учитывая частичное совпадение имени
                specialist = next(
                    (s for s in specialists if specialist_name.lower() in s[1].lower() or s[1].lower() in specialist_name.lower()),
                    None
                )
                
                if specialist:
                    available_times = get_available_times(specialist[0], state['service_id'])
                    if available_times:
                        set_user_state(
                            user_id, 
                            "select_time",
                            service_id=state['service_id'],
                            specialist_id=specialist[0]
                        )
                        times_text = "\n".join([f"🕐 {t}" for t in available_times])
                        update.message.reply_text(
                            f"Вы выбрали специалиста: {specialist[1]}\n\n"
                            f"Доступное время:\n{times_text}\n\n"
                            "Пожалуйста, выберите удобное время."
                        )
                    else:
                        # Ищем другого специалиста с доступным временем
                        other_specialists = [s for s in specialists if s[0] != specialist[0]]
                        available_specialist = None
                        available_times = []
                        
                        for other_spec in other_specialists:
                            times = get_available_times(other_spec[0], state['service_id'])
                            if times:
                                available_specialist = other_spec
                                available_times = times
                                break
                        
                        if available_specialist:
                            update.message.reply_text(
                                f"К сожалению, у специалиста {specialist[1]} нет свободного времени.\n"
                                f"Но вы можете записаться к {available_specialist[1]}:\n\n" +
                                "\n".join([f"🕐 {t}" for t in available_times[:5]]) +
                                "\n\nХотите записаться к этому специалисту?"
                            )
                        else:
                            update.message.reply_text(
                                "К сожалению, сейчас нет свободного времени у специалистов. "
                                "Попробуйте позже или выберите другую услугу."
                            )
                else:
                    specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
                    update.message.reply_text(
                        f"Специалист не найден. Выберите из списка:\n\n{specialists_text}"
                    )
            else:
                specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
                update.message.reply_text(
                    f"{gpt_response_text}\n\n"
                    f"Доступные специалисты:\n{specialists_text}"
                )

        elif action == "SELECT_TIME":
            if not state or not all(k in state for k in ['service_id', 'specialist_id']):
                update.message.reply_text("Сначала выберите услугу и специалиста.")
                return

            available_times = get_available_times(state['specialist_id'], state['service_id'])
            
            if not available_times:
                alternative_specialist = find_available_specialist(state['service_id'], state['specialist_id'])
                if alternative_specialist:
                    alt_times = get_available_times(alternative_specialist[0], state['service_id'])
                    update.message.reply_text(
                        f"К сожалению, у выбранного специалиста нет свободного времени.\n"
                        f"Вы можете записаться к {alternative_specialist[1]}:\n\n" +
                        "\n".join([f"🕐 {t}" for t in alt_times])
                    )
                else:
                    update.message.reply_text(
                        "К сожалению, сейчас нет свободного времени для записи.\n"
                        "Попробуйте выбрать другую услугу или свяжитесь с администратором."
                    )
                return

            chosen_time = None
            gpt_time = extracted_data.get('time')
            if gpt_time:
                chosen_time = parse_time_input(gpt_time, available_times)

            if chosen_time:
                set_user_state(
                    user_id,
                    "confirm",
                    service_id=state['service_id'],
                    specialist_id=state['specialist_id'],
                    chosen_time=chosen_time
                )
                service_name = get_service_name(state['service_id'])
                specialist_name = get_specialist_name(state['specialist_id'])
                update.message.reply_text(
                    f"Подтвердите запись:\n\n"
                    f"🎯 Услуга: {service_name}\n"
                    f"👩‍💼 Специалист: {specialist_name}\n"
                    f"📅 Время: {chosen_time}\n\n"
                    "Для подтверждения напишите 'да' или 'нет' для отмены."
                )
            else:
                times_text = "\n".join([f"🕐 {t}" for t in available_times])
                update.message.reply_text(
                    f"Пожалуйста, выберите точное время из списка:\n\n{times_text}"
                )

        elif action == "CONFIRM_BOOKING":
            if not state or not all(k in state for k in ['service_id', 'specialist_id', 'chosen_time']):
                update.message.reply_text("Недостаточно информации для создания записи.")
                return

            if user_text.lower() in ['да', 'yes', 'подтверждаю']:
                success = create_booking(
                    user_id=user_id,
                    serv_id=state['service_id'],
                    spec_id=state['specialist_id'],
                    date_str=state['chosen_time']
                )
                if success:
                    service_name = get_service_name(state['service_id'])
                    specialist_name = get_specialist_name(state['specialist_id'])
                    
                    try:
                        date_time = datetime.datetime.strptime(state['chosen_time'], "%Y-%m-%d %H:%M")
                        formatted_date = date_time.strftime("%d.%m.%Y")
                        formatted_time = date_time.strftime("%H:%M")
                    except ValueError:
                        formatted_date = state['chosen_time'].split()[0]
                        formatted_time = state['chosen_time'].split()[1]
                    
                    confirmation_message = (
                        "✅ Ваша запись успешно подтверждена!\n\n"
                        f"🎯 Услуга: {service_name}\n"
                        f"👩‍💼 Мастер: {specialist_name}\n"
                        f"📅 Дата: {formatted_date}\n"
                        f"⏰ Время: {formatted_time}\n\n"
                        "ℹ️ Если вам потребуется изменить или отменить запись, "
                        "просто напишите об этом в чат.\n\n"
                        "👋 Будем рады видеть вас!"
                    )
                    update.message.reply_text(confirmation_message)
                    
                    if MANAGER_CHAT_ID:
                        manager_message = (
                            "🆕 Новая запись!\n\n"
                            f"🎯 Услуга: {service_name}\n"
                            f"👩‍💼 Мастер: {specialist_name}\n"
                            f"📅 Дата: {formatted_date}\n"
                            f"⏰ Время: {formatted_time}\n"
                            f"👤 Клиент ID: {user_id}"
                        )
                        bot.send_message(MANAGER_CHAT_ID, manager_message)
                else:
                    update.message.reply_text(
                        "❌ Произошла ошибка при создании записи.\n"
                        "Пожалуйста, попробуйте позже или свяжитесь с администратором."
                    )
                delete_user_state(user_id)
            else:
                update.message.reply_text(
                    "❌ Запись отменена.\n"
                    "Если хотите записаться на другое время, напишите 'Записаться'."
                )
                delete_user_state(user_id)

        elif action == "CANCEL_BOOKING":
            delete_user_state(user_id)
            update.message.reply_text(f"{gpt_response_text}")

        else:
            update.message.reply_text(gpt_response_text or "Извините, я не понял ваш запрос.")

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON от GPT для user {user_id}: {e}")
        update.message.reply_text(f"Ответ GPT не разобран:\n{gpt_response}")
    except Exception as e:
        logger.error(f"Ошибка при обработке GPT для user {user_id}: {e}", exc_info=True)
        update.message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте сформулировать ваш запрос иначе или начните сначала."
        )















# Обновляем основной обработчик сообщений
def handle_message(update, context):
    try:
        user_text = update.message.text.strip()
        user_id = update.message.chat_id
        user_name = update.message.chat.first_name or "Unknown"
        
        logger.info(f"Получено сообщение от user_id={user_id}, name={user_name}: {user_text}")

        # Регистрируем пользователя
        register_user(user_id, user_name)
        
         # Получаем текущее состояние
        state = get_user_state(user_id)
        logger.info(f"Текущее состояние для user_id={user_id}: {state}")

        # Определяем намерение пользователя
        intent = determine_intent(user_text)
        logger.info(f"Определено намерение для user_id={user_id}: {intent}")

        # Если пользователь хочет записаться
        if "запис" in user_text.lower() or intent['intent'] == 'BOOKING_INTENT':
            # Проверяем наличие активных записей
            existing_bookings = get_user_bookings(user_id)
            
            if existing_bookings:
                service = find_service_by_name(user_text)
                if service:
                    update.message.reply_text(
                        "У вас уже есть активная запись. Хотите сделать дополнительную запись? (да/нет)"
                    )
                    set_user_state(user_id, "confirm_additional_booking", service_id=service[0])
                    return
            
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Базовые команды отмены
        if user_text.lower() in ['отмена', 'cancel', 'стоп', 'stop']:
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён. Можете начать заново.")
            return
        # Обработка отмены записи
        if "отмен" in user_text.lower() or (user_text.lower() == "да" and state and state.get('cancellation_pending')):
            bookings = get_user_bookings(user_id)
            if bookings:
                success, message = cancel_booking(user_id, bookings[0]['id'])
                if success:
                    update.message.reply_text(message)
                else:
                    update.message.reply_text(
                        "❌ Не удалось отменить запись. Пожалуйста, попробуйте позже или свяжитесь с администратором."
                    )
            else:
                update.message.reply_text("У вас нет активных записей для отмены.")
            delete_user_state(user_id)
            return    

        # Проверяем, является ли текст названием услуги
        service = find_service_by_name(user_text)
        if service:
            update.message.reply_text(f"Вы выбрали услугу: {service[1]}")
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Если пользователь находится в процессе выбора специалиста
        if state and state['step'] == 'select_specialist':
            handle_booking_with_gpt(update, user_id, user_text, state)
            return

        # Анализ намерения пользователя через GPT
        system_prompt = """
        Ты — ассистент салона красоты. Определи намерение пользователя:
        1. GENERAL_QUESTION - общий вопрос о салоне/услугах
        2. BOOKING_INTENT - намерение записаться
        3. CANCEL_INTENT - намерение отменить запись
        4. RESCHEDULE_INTENT - намерение перенести запись
        5. PRICE_QUESTION - вопрос о ценах
        6. SPECIALIST_QUESTION - вопрос о специалистах
        7. SERVICE_QUESTION - вопрос об услугах
        8. OTHER - другое

        Ответ дай в формате JSON:
        {
            "intent": "тип намерения",
            "confidence": float от 0 до 1,
            "extracted_info": {
                "service": "название услуги если есть",
                "specialist": "имя специалиста если есть",
                "date": "дата если есть"
            }
        }
        """

        try:
            intent_response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.3
            )
            
            raw_intent = intent_response.choices[0].message.content
            # == ДОБАВЛЕНО:
            raw_intent = clean_gpt_json(raw_intent)

            intent_data = json.loads(raw_intent)
            logger.info(f"Определено намерение для user_id={user_id}: {intent_data}")

            if intent_data['intent'] == "BOOKING_INTENT":
                handle_booking_with_gpt(update, user_id, user_text, state)
            elif intent_data['intent'] == "CANCEL_INTENT":
                handle_cancellation(update, user_id, intent_data['extracted_info'])
            elif intent_data['intent'] == "RESCHEDULE_INTENT":
                handle_reschedule(update, user_id, intent_data['extracted_info'])
            elif intent_data['intent'] == "PRICE_QUESTION":
                handle_price_question(update, user_id, intent_data['extracted_info'])
            elif intent_data['intent'] == "SPECIALIST_QUESTION":
                handle_specialist_question(update, user_id, intent_data['extracted_info'])
            elif intent_data['intent'] == "SERVICE_QUESTION":
                handle_services_question(update)
            elif intent_data['intent'] == "GENERAL_QUESTION":
                handle_general_question(update, user_id, user_text)
            else:
                handle_booking_with_gpt(update, user_id, user_text, state)

        except json.JSONDecodeError:
            logger.error("Ошибка парсинга JSON от GPT")
            handle_booking_with_gpt(update, user_id, user_text, state)

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}", exc_info=True)
        update.message.reply_text(
            "Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте позже или напишите /start"
        )


def handle_cancellation(update, user_id, extracted_info):
    try:
        bookings = get_user_bookings(user_id)
        if not bookings:
            update.message.reply_text("У вас нет активных записей для отмены.")
            return

        if len(bookings) == 1:
            booking = bookings[0]
            if cancel_booking(user_id, booking['id']):
                update.message.reply_text(
                    f"Ваша запись на {booking['date_time']} "
                    f"к {booking['specialist_name']} была отменена."
                )
            else:
                update.message.reply_text("Произошла ошибка при отмене записи.")
        else:
            bookings_text = "\n".join([
                f"{i+1}. {b['date_time']} - {b['service_name']} у {b['specialist_name']}"
                for i, b in enumerate(bookings)
            ])
            update.message.reply_text(
                "У вас несколько записей. Какую хотите отменить?\n\n"
                f"{bookings_text}\n\n"
                "Укажите номер записи для отмены."
            )
            set_user_state(user_id, "canceling_booking", bookings=bookings)

    except Exception as e:
        logger.error(f"Ошибка при отмене записи: {e}")
        update.message.reply_text("Произошла ошибка при отмене записи.")

def handle_reschedule(update, user_id, extracted_info):
    try:
        bookings = get_user_bookings(user_id)
        if not bookings:
            update.message.reply_text("У вас нет активных записей для переноса.")
            return

        if len(bookings) == 1:
            booking = bookings[0]
            available_times = get_available_times(
                booking['specialist_id'], 
                booking['service_id']
            )
            if available_times:
                times_text = "\n".join([f"- {t}" for t in available_times])
                update.message.reply_text(
                    f"Выберите новое время для записи:\n\n{times_text}"
                )
                set_user_state(
                    user_id, 
                    "rescheduling", 
                    booking_id=booking['id']
                )
            else:
                update.message.reply_text(
                    "К сожалению, нет доступного времени для переноса записи."
                )
        else:
            bookings_text = "\n".join([
                f"{i+1}. {b['date_time']} - {b['service_name']} у {b['specialist_name']}"
                for i, b in enumerate(bookings)
            ])
            update.message.reply_text(
                "У вас несколько записей. Какую хотите перенести?\n\n"
                f"{bookings_text}\n\n"
                "Укажите номер записи для переноса."
            )
            set_user_state(user_id, "selecting_reschedule", bookings=bookings)

    except Exception as e:
        logger.error(f"Ошибка при переносе записи: {e}")
        update.message.reply_text("Произошла ошибка при переносе записи.")

def handle_price_question(update, user_id, extracted_info):
    try:
        if 'service' in extracted_info and extracted_info['service']:
            service_info = get_service_price(extracted_info['service'])
            if service_info:
                update.message.reply_text(
                    f"Стоимость услуги '{service_info['name']}': "
                    f"{service_info['price']} руб."
                )
            else:
                show_price_list(update)
        else:
            show_price_list(update)

    except Exception as e:
        logger.error(f"Ошибка при обработке вопроса о ценах: {e}")
        update.message.reply_text("Произошла ошибка при получении информации о ценах.")

def handle_specialist_question(update, user_id, extracted_info):
    try:
        if 'specialist' in extracted_info and extracted_info['specialist']:
            specialist_info = get_specialist_info(extracted_info['specialist'])
            if specialist_info:
                update.message.reply_text(
                    f"Специалист: {specialist_info['name']}\n"
                    f"Специализация: {specialist_info.get('specialization','')}\n"
                    f"Опыт работы: {specialist_info.get('experience','')}\n"
                    f"Доступные услуги: {specialist_info['services']}"
                )
            else:
                show_all_specialists(update)
        else:
            show_all_specialists(update)

    except Exception as e:
        logger.error(f"Ошибка при обработке вопроса о специалистах: {e}")
        update.message.reply_text("Произошла ошибка при получении информации о специалистах.")

def handle_general_question(update, user_id, question):
    try:
        system_prompt = """
        Ты — дружелюбный ассистент салона красоты. Отвечай на вопросы клиентов.
        Используй вежливый тон и предоставляй полезную информацию.
        Если не знаешь точного ответа, предложи связаться с администратором.
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.7,
            max_tokens=150
        )
        
        answer = response.choices[0].message.content.strip()
        update.message.reply_text(answer)

    except Exception as e:
        logger.error(f"Ошибка при обработке общего вопроса: {e}")
        update.message.reply_text(
            "Извините, я не смог обработать ваш вопрос. "
            "Пожалуйста, попробуйте переформулировать или обратитесь к администратору."
        )

# =============================================================================
# Функция пошаговой логики бронирования
# =============================================================================
def process_booking(update, user_id, user_text, state):
    step = state['step']

    if "хочу" in user_text:
        delete_user_state(user_id)
        found = find_service_by_name(user_text)
        if found:
            s_id, s_title = found
            set_user_state(user_id, "select_specialist", service_id=s_id)
            sp_list = get_specialists(service_id=s_id)
            if not sp_list:
                update.message.reply_text("Нет специалистов, предлагающих эту услугу.")
                delete_user_state(user_id)
                return
            sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in sp_list])
            update.message.reply_text(f"Вы выбрали услугу: {s_title}\nПожалуйста, выберите специалиста:\n{sp_text}")
        else:
            set_user_state(user_id, "select_service")
            all_services = get_services()
            s_list = "\n".join([f"{s[0]}. {s[1]}" for s in all_services])
            update.message.reply_text(f"Доступные услуги:\n{s_list}\nВведите название услуги.")
        return

    if step == "select_service":
        if "повтори" in user_text or "какие услуги" in user_text or "услуги" in user_text:
            services = get_services()
            unique_services = sorted({s[1] for s in services})
            if unique_services:
                service_list = "\n".join([f"- {s}" for s in unique_services])
                update.message.reply_text(f"Доступные услуги:\n{service_list}")
            else:
                update.message.reply_text("На данный момент нет услуг.")
            return

        services = get_services()
        service = next((s for s in services if s[1].lower() == user_text.lower()), None)
        if service:
            set_user_state(user_id, "select_specialist", service_id=service[0])
            sp_list = get_specialists(service_id=service[0])
            if not sp_list:
                update.message.reply_text("Нет специалистов, предлагающих эту услугу.")
                delete_user_state(user_id)
                return
            sp_text = "\n".join([f"{sp[0]}. {sp[1]}" for sp in sp_list])
            update.message.reply_text(f"Вы выбрали услугу: {service[1]}\nПожалуйста, выберите специалиста:\n{sp_text}")
        else:
            system_prompt = (
                "Ты — эксперт в распознавании запросов на повторение списка услуг в контексте бронирования услуг."
            )
            user_prompt = (
                f"Пользователь на этапе выбора услуги ввёл: '{user_text}'. "
                "Определи, что он просит повторить список услуг. Ответь 'да' или 'нет'."
            )
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "system", "content": system_prompt},{"role": "user", "content": user_prompt}],
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
        specs = get_specialists(service_id=state['service_id'])
        specialist = next((sp for sp in specs if sp[1].lower() == user_text.lower()), None)
        if specialist:
            av_times = get_available_times(specialist[0], state['service_id'])
            if av_times:
                set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=specialist[0])
                txt = "\n".join(av_times)
                update.message.reply_text(
                    f"Доступное время:\n{txt}\nВведите удобное время (YYYY-MM-DD HH:MM, или 'HH:MM')."
                )
            else:
                another_spec = find_available_specialist(state['service_id'], exclude_id=specialist[0])
                if another_spec:
                    set_user_state(user_id, "select_specialist", service_id=state['service_id'])
                    update.message.reply_text(
                        f"Нет свободных слотов у {specialist[1]}.\nМожет, подойдет другой специалист:\n{another_spec[0]}. {another_spec[1]}"
                    )
                else:
                    update.message.reply_text("Нет свободных специалистов для этой услуги. Попробуйте позже.")
                    delete_user_state(user_id)
        else:
            sp_id, sp_name = match_specialist_with_gpt(user_text, specs)
            if sp_id:
                av_times = get_available_times(sp_id, state['service_id'])
                if av_times:
                    set_user_state(user_id, "select_time", service_id=state['service_id'], specialist_id=sp_id)
                    txt = "\n".join(av_times)
                    update.message.reply_text(f"Похоже, вы имели в виду: {sp_name}\nДоступное время:\n{txt}\nВведите удобное время.")
                else:
                    another_spec = find_available_specialist(state['service_id'], exclude_id=sp_id)
                    if another_spec:
                        set_user_state(user_id, "select_specialist", service_id=state['service_id'])
                        update.message.reply_text(
                            f"Нет свободных слотов у {sp_name}.\nМожет, подойдет другой специалист:\n{another_spec[0]}. {another_spec[1]}"
                        )
                    else:
                        update.message.reply_text("Нет свободных специалистов для этой услуги. Попробуйте позже.")
                        delete_user_state(user_id)
            else:
                update.message.reply_text("Не нашли такого специалиста. Попробуйте снова.")

    elif step == "select_time":
        if not state or not all(k in state for k in ['service_id', 'specialist_id']):
            update.message.reply_text("Сначала выберите услугу и специалиста.")
            return

        available_times = get_available_times(state['specialist_id'], state['service_id'])
        chosen_time = parse_time_input(user_text, available_times)

        if chosen_time and chosen_time in available_times:
            set_user_state(
                user_id,
                "confirm",
                service_id=state['service_id'],
                specialist_id=state['specialist_id'],
                chosen_time=chosen_time
            )
            srv_name = get_service_name(state['service_id'])
            sp_name = get_specialist_name(state['specialist_id'])
            update.message.reply_text(
                f"Вы выбрали:\nУслуга: {srv_name}\nСпециалист: {sp_name}\nВремя: {chosen_time}\nПодтвердите запись (да/нет)."
            )
        else:
            times_text = "\n".join([f"🕐 {t}" for t in available_times])
            update.message.reply_text(
                f"Пожалуйста, выберите точное время из списка:\n\n{times_text}"
            )

    elif step == "confirm":
        if user_text.lower() in ["да", "да.", "yes", "yes."]:
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
        elif user_text.lower() in ["нет", "нет.", "no", "no."]:
            update.message.reply_text("Запись отменена.")
            delete_user_state(user_id)
        else:
            update.message.reply_text("Пожалуйста, ответьте 'да' или 'нет'.")

def handle_specialist_selection(update, user_id, specialist_name, state):
    specialists = get_specialists(state['service_id'])
    specialist = next(
        (sp for sp in specialists 
         if any(part.lower() in sp[1].lower() for part in specialist_name.split())),
        None
    )
    
    if specialist:
        av_times = get_available_times(specialist[0], state['service_id'])
        if av_times:
            if len(av_times) == 1:
                set_user_state(
                    user_id, 
                    "confirm",
                    service_id=state['service_id'],
                    specialist_id=specialist[0],
                    chosen_time=av_times[0]
                )
                service_name = get_service_name(state['service_id'])
                update.message.reply_text(
                    f"Специалист {specialist[1]} доступен только в следующее время:\n"
                    f"🗓 {av_times[0]}\n\n"
                    "Хотите записаться на это время? (да/нет)"
                )
            else:
                set_user_state(
                    user_id, 
                    "select_time",
                    service_id=state['service_id'],
                    specialist_id=specialist[0]
                )
                times_text = "\n".join([f"🕐 {t}" for t in av_times])
                update.message.reply_text(
                    f"Выберите удобное время для записи к {specialist[1]}:\n\n{times_text}\n\n"
                    "Достаточно указать только время (например, '12:00')"
                )
        else:
            update.message.reply_text(
                f"К сожалению, у специалиста {specialist[1]} нет свободного времени."
            )
    else:
        specialists_text = "\n".join([f"👩‍💼 {s[1]}" for s in specialists])
        update.message.reply_text(
            "Пожалуйста, выберите специалиста из списка:\n\n"
            f"{specialists_text}"
        )

def handle_time_selection(update, user_id, time_text, state):
    available_times = get_available_times(state['specialist_id'], state['service_id'])
    time_part = None
    
    cleaned_time = ''.join(c for c in time_text if c.isdigit() or c == ':')
    
    if ':' in cleaned_time:
        time_part = cleaned_time
    else:
        try:
            hour = int(cleaned_time)
            if 0 <= hour <= 23:
                time_part = f"{hour:02d}:00"
        except ValueError:
            time_part = None

    if time_part:
        chosen_time = next(
            (t for t in available_times if t.endswith(time_part)),
            None
        )
        
        if chosen_time:
            service_name = get_service_name(state['service_id'])
            specialist_name = get_specialist_name(state['specialist_id'])
            
            set_user_state(
                user_id,
                "confirm",
                service_id=state['service_id'],
                specialist_id=state['specialist_id'],
                chosen_time=chosen_time
            )
            
            update.message.reply_text(
                f"Подтвердите запись:\n\n"
                f"🎯 Услуга: {service_name}\n"
                f"👩‍💼 Специалист: {specialist_name}\n"
                f"📅 Дата и время: {chosen_time}\n\n"
                "Для подтверждения напишите 'да' или 'нет' для отмены."
            )
            return

    times_text = "\n".join([f"🕐 {t}" for t in available_times])
    update.message.reply_text(
        f"Пожалуйста, выберите точное время из списка:\n\n{times_text}"
    )

def handle_booking_confirmation(update, user_id, response, state):
    if not state or 'chosen_time' not in state:
        update.message.reply_text(
            "❌ Извините, информация о бронировании была потеряна. "
            "Пожалуйста, начните процесс записи заново."
        )
        delete_user_state(user_id)
        return

    if response.lower() in ['да', 'yes', 'подтверждаю', 'lf', 'конечно', '+']:
        try:
            service_name = get_service_name(state['service_id'])
            specialist_name = get_specialist_name(state['specialist_id'])
            
            available_times = get_available_times(state['specialist_id'], state['service_id'])
            if state['chosen_time'] not in available_times:
                update.message.reply_text(
                    "❌ К сожалению, выбранное время уже занято. "
                    "Пожалуйста, выберите другое время."
                )
                set_user_state(
                    user_id, 
                    "select_time",
                    service_id=state['service_id'],
                    specialist_id=state['specialist_id']
                )
                return

            success = create_booking(
                user_id=user_id,
                serv_id=state['service_id'],
                spec_id=state['specialist_id'],
                date_str=state['chosen_time']
            )
            
            if success:
                try:
                    date_time = datetime.datetime.strptime(state['chosen_time'], "%Y-%m-%d %H:%M")
                    formatted_date = date_time.strftime("%d.%m.%Y")
                    formatted_time = date_time.strftime("%H:%M")
                except ValueError:
                    formatted_date = state['chosen_time'].split()[0]
                    formatted_time = state['chosen_time'].split()[1]

                confirmation_message = (
                    "✅ Ваша запись успешно подтверждена!\n\n"
                    f"🎯 Услуга: {service_name}\n"
                    f"👩‍💼 Мастер: {specialist_name}\n"
                    f"📅 Дата: {formatted_date}\n"
                    f"⏰ Время: {formatted_time}\n\n"
                    "ℹ️ Если вам потребуется изменить или отменить запись, "
                    "просто напишите об этом в чат.\n\n"
                    "👋 Будем рады видеть вас!"
                )
                update.message.reply_text(confirmation_message)
                
                manager_message = (
                    "🆕 Новая запись!\n\n"
                    f"🎯 Услуга: {service_name}\n"
                    f"👩‍💼 Мастер: {specialist_name}\n"
                    f"📅 Дата: {formatted_date}\n"
                    f"⏰ Время: {formatted_time}\n"
                    f"👤 Клиент ID: {user_id}"
                )
                
                notify_managers(manager_message, 'new_booking')
                
                if MANAGER_CHAT_ID:
                    try:
                        bot.send_message(MANAGER_CHAT_ID, manager_message)
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления основному менеджеру: {e}")
                
            else:
                update.message.reply_text(
                    "❌ Произошла ошибка при создании записи.\n"
                    "Пожалуйста, попробуйте позже или свяжитесь с администратором."
                )
                
        except Exception as e:
            logger.error(f"Ошибка при подтверждении записи: {e}", exc_info=True)
            update.message.reply_text(
                "❌ Произошла ошибка при создании записи.\n"
                "Пожалуйста, попробуйте позже или свяжитесь с администратором."
            )
            
        finally:
            delete_user_state(user_id)
            
    elif response.lower() in ['нет', 'no', 'отмена', 'ytn', 'отменить', '-']:
        update.message.reply_text(
            "❌ Запись отменена.\n"
            "Если хотите записаться на другое время, напишите 'Записаться'."
        )
        delete_user_state(user_id)
        
    else:
        update.message.reply_text(
            "Пожалуйста, ответьте 'да' для подтверждения "
            "или 'нет' для отмены записи."
        )


def get_user_bookings(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT b.id, b.service_id, b.specialist_id, b.date_time,
                   s.title as service_name, sp.name as specialist_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN specialists sp ON b.specialist_id = sp.id
            WHERE b.user_id = %s AND b.date_time > NOW()
            ORDER BY b.date_time
        """, (user_id,))
        bookings = []
        for row in cur.fetchall():
            bookings.append({
                'id': row[0],
                'service_id': row[1],
                'specialist_id': row[2],
                'date_time': row[3].strftime("%Y-%m-%d %H:%M"),
                'service_name': row[4],
                'specialist_name': row[5]
            })
        return bookings
    finally:
        cur.close()
        conn.close()

def get_service_price(service_name):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, title, price 
            FROM services 
            WHERE LOWER(title) LIKE LOWER(%s)
        """, (f"%{service_name}%",))
        row = cur.fetchone()
        if row:
            return {
                'id': row[0],
                'name': row[1],
                'price': row[2]
            }
        return None
    finally:
        cur.close()
        conn.close()

def get_specialist_info(specialist_name):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.id, s.name,
                   STRING_AGG(srv.title, ', ') as services
            FROM specialists s
            LEFT JOIN specialist_services ss ON s.id = ss.specialist_id
            LEFT JOIN services srv ON ss.service_id = srv.id
            WHERE LOWER(s.name) LIKE LOWER(%s)
            GROUP BY s.id, s.name
        """, (f"%{specialist_name}%",))
        row = cur.fetchone()
        if row:
            return {
                'id': row[0],
                'name': row[1],
                'services': row[2]
            }
        return None
    finally:
        cur.close()
        conn.close()

def show_price_list(update):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT title, price FROM services ORDER BY title")
        prices = cur.fetchall()
        if prices:
            price_list = "\n".join([f"• {row[0]}: {row[1]} руб." for row in prices])
            update.message.reply_text(f"Прайс-лист:\n\n{price_list}")
        else:
            update.message.reply_text("К сожалению, информация о ценах временно недоступна.")
    finally:
        cur.close()
        conn.close()

def show_all_specialists(update):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.name, s.specialization, STRING_AGG(srv.title, ', ') as services
            FROM specialists s
            LEFT JOIN specialist_services ss ON s.id = ss.specialist_id
            LEFT JOIN services srv ON ss.service_id = srv.id
            GROUP BY s.id, s.name, s.specialization
            ORDER BY s.name
        """)
        specialists = cur.fetchall()
        if specialists:
            spec_list = "\n\n".join([
                f"🎓 {row[0]}\n"
                f"Специализация: {row[1]}\n"
                f"Услуги: {row[2]}"
                for row in specialists
            ])
            update.message.reply_text(f"Наши специалисты:\n\n{spec_list}")
        else:
            update.message.reply_text("К сожалению, информация о специалистах временно недоступна.")
    finally:
        cur.close()
        conn.close()

def handle_services_question(update):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT title 
            FROM services 
            ORDER BY title
        """)
        services = cur.fetchall()
        
        if services:
            services_text = "Наши услуги:\n\n"
            for service in services:
                services_text += f"💠 {service[0]}\n"
            
            services_text += "\nЧтобы записаться на услугу, просто напишите её название."
            
            update.message.reply_text(services_text)
        else:
            update.message.reply_text(
                "К сожалению, список услуг временно недоступен. "
                "Пожалуйста, свяжитесь с администратором."
            )
            
    except Exception as e:
        logger.error(f"Ошибка при получении списка услуг: {e}", exc_info=True)
        update.message.reply_text(
            "Извините, произошла ошибка при получении списка услуг. "
            "Пожалуйста, попробуйте позже."
        )
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

# =============================================================================
# /start команда
# =============================================================================
def start(update, context):
    update.message.reply_text(
        "Привет! Я ваш бот для управления записями. Напишите 'Записаться', чтобы начать запись, или задайте мне любой вопрос!"
    )

def cancel_booking(user_id, booking_id):
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
        booking = cur.fetchone()
        
        if booking:
            service_id, specialist_id, date_time, service_name, specialist_name = booking
            
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

            manager_message = (
                "❌ Отмена записи!\n\n"
                f"🎯 Услуга: {service_name}\n"
                f"👩‍💼 Мастер: {specialist_name}\n"
                f"📅 Дата: {formatted_date}\n"
                f"⏰ Время: {formatted_time}\n"
                f"👤 Клиент ID: {user_id}"
            )
            notify_managers(manager_message, 'cancellation')

            return True, cancellation_message
        return False, "Запись не найдена."
    except psycopg2.Error as e:
        logger.error(f"Ошибка при отмене записи: {e}")
        conn.rollback()
        return False, "Произошла ошибка при отмене записи. Пожалуйста, попробуйте позже."
    finally:
        cur.close()
        conn.close()


def register_manager(chat_id, username=None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM managers WHERE chat_id = %s",
            (chat_id,)
        )
        manager = cur.fetchone()
        
        if not manager:
            cur.execute(
                """
                INSERT INTO managers (chat_id, username)
                VALUES (%s, %s)
                RETURNING id
                """,
                (chat_id, username)
            )
            manager_id = cur.fetchone()[0]
            
            cur.execute(
                """
                INSERT INTO notification_settings (manager_id)
                VALUES (%s)
                """,
                (manager_id,)
            )
            conn.commit()
            return True
        return False
    finally:
        cur.close()
        conn.close()

def get_active_managers():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT m.chat_id, ns.notify_new_booking, ns.notify_cancellation, ns.notify_reschedule
            FROM managers m
            JOIN notification_settings ns ON ns.manager_id = m.id
            WHERE m.is_active = true
            """
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def notify_managers(message, notification_type='new_booking'):
    managers = get_active_managers()
    for manager in managers:
        chat_id, notify_new, notify_cancel, notify_reschedule = manager
        should_notify = (
            (notification_type == 'new_booking' and notify_new) or
            (notification_type == 'cancellation' and notify_cancel) or
            (notification_type == 'reschedule' and notify_reschedule)
        )
        if should_notify:
            try:
                bot.send_message(chat_id, message)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления менеджеру {chat_id}: {e}")

def handle_manager_commands(update, context):
    command = update.message.text
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    
    if command == '/register_manager':
        if register_manager(chat_id, username):
            update.message.reply_text(
                "✅ Вы успешно зарегистрированы как менеджер.\n"
                "Вам будут приходить уведомления о новых записях."
            )
        else:
            update.message.reply_text("Вы уже зарегистрированы как менеджер.")
    
    elif command == '/stop_notifications':
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE managers SET is_active = false WHERE chat_id = %s",
                (chat_id,)
            )
            conn.commit()
            update.message.reply_text("Уведомления отключены.")
        finally:
            cur.close()
            conn.close()

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    upd = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(upd)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

dispatcher = Dispatcher(bot, None, workers=4)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

def set_webhook():
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

if __name__ == "__main__":
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=5000)

###############################################################################
# Конец 1761-й строки
###############################################################################
