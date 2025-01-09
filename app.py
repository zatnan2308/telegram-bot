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

def determine_intent(user_message):
    system_prompt = (
        "Ты — Telegram-бот для управления записями. Определи намерение пользователя и извлеки сущности из его сообщения. "
        "Возможные намерения: LIST_SERVICES, LIST_SPECIALIST_SERVICES, BOOK_SERVICE, UNKNOWN. "
        "Сущности могут включать 'specialist_name'. Отвечай в формате JSON без пояснений."
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":user_message}
            ],
            max_tokens=100,
            temperature=0
        )
        response_content = resp['choices'][0]['message']['content'].strip()
        return json.loads(response_content)
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

def find_service_in_text(user_text):
    services = get_services()
    user_text_lower = user_text.lower()
    logger.info(f"Поиск услуги в тексте: {user_text_lower}")
    for (s_id, s_title) in services:
        logger.info(f"Проверка услуги: {s_title.lower()}")
        if s_title.lower() in user_text_lower:
            logger.info(f"Найдена услуга: {s_title}")
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

def handle_booking_with_gpt(update, user_id, user_text, state=None):
    system_prompt = """
    Ты — ассистент по бронированию услуг в салоне красоты. Твоя задача:
    1. Определить намерение пользователя (запись/отмена/перенос)
    2. Извлечь важную информацию (услуга, специалист, время)
    3. Вести диалог последовательно и вежливо
    4. Предоставлять четкие инструкции

    Доступные действия:
    - LIST_SERVICES: показать список услуг
    - SELECT_SERVICE: выбрать услугу
    - SELECT_SPECIALIST: выбрать специалиста
    - SELECT_TIME: выбрать время
    - CONFIRM_BOOKING: подтвердить запись
    - CANCEL_BOOKING: отменить запись
    - RESCHEDULE: перенести запись
    """

    # Получаем контекст предыдущего состояния
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
        # Запрос к GPT
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Контекст:\n{context}\nСообщение пользователя: {user_text}"}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        # Логируем ответ GPT
        logger.info(f"GPT response for user {user_id}: {response.choices[0].message.content}")
        
        result = json.loads(response.choices[0].message.content)
        action = result.get('action')
        extracted_data = result.get('extracted_data', {})

        if action == "LIST_SERVICES":
            services = get_services()
            if services:
                service_list = "\n".join([f"- {s[1]}" for s in services])
                update.message.reply_text(f"Доступные услуги:\n{service_list}")
            else:
                update.message.reply_text("К сожалению, сейчас нет доступных услуг.")

        elif action == "SELECT_SERVICE":
            service_name = extracted_data.get('service')
            if not service_name:
                services = get_services()
                service_list = "\n".join([f"- {s[1]}" for s in services])
                update.message.reply_text(
                    "Пожалуйста, выберите услугу из списка:\n\n"
                    f"{service_list}"
                )
                return

            services = get_services()
            service = next(
                (s for s in services if s[1].lower() == service_name.lower() or 
                 service_name.lower() in s[1].lower()),
                None
            )
            
            if service:
                specialists = get_specialists(service_id=service[0])
                if specialists:
                    set_user_state(user_id, "select_specialist", service_id=service[0])
                    sp_text = "\n".join([f"- {sp[1]}" for sp in specialists])
                    update.message.reply_text(
                        f"Вы выбрали услугу: {service[1]}\n\n"
                        f"Доступные специалисты:\n{sp_text}"
                    )
                else:
                    update.message.reply_text(
                        "К сожалению, сейчас нет доступных специалистов для этой услуги."
                    )
            else:
                update.message.reply_text(
                    "Извините, такой услуги нет в списке. Пожалуйста, выберите из доступных услуг."
                )

        elif action == "SELECT_SPECIALIST":
            if not state or not state.get('service_id'):
                update.message.reply_text("Сначала выберите услугу.")
                return

            specialist_name = extracted_data.get('specialist')
            if not specialist_name:
                specialists = get_specialists(state['service_id'])
                sp_text = "\n".join([f"- {sp[1]}" for sp in specialists])
                update.message.reply_text(
                    "Пожалуйста, выберите специалиста из списка:\n\n"
                    f"{sp_text}"
                )
                return

            specialists = get_specialists(state['service_id'])
            specialist = next(
                (s for s in specialists if s[1].lower() == specialist_name.lower() or 
                 specialist_name.lower() in s[1].lower()),
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
                    times_text = "\n".join([f"- {t}" for t in available_times])
                    update.message.reply_text(
                        f"Вы выбрали специалиста: {specialist[1]}\n\n"
                        f"Доступное время:\n{times_text}\n\n"
                        "Выберите удобное время из списка."
                    )
                else:
                    update.message.reply_text(
                        f"К сожалению, у специалиста {specialist[1]} нет свободного времени."
                    )
            else:
                specialists_text = "\n".join([f"- {s[1]}" for s in specialists])
                update.message.reply_text(
                    "Специалист не найден. Выберите из списка:\n\n"
                    f"{specialists_text}"
                )

        elif action == "SELECT_TIME":
            if not state or not all(k in state for k in ['service_id', 'specialist_id']):
                update.message.reply_text("Сначала выберите услугу и специалиста.")
                return

            chosen_time = extracted_data.get('time')
            if not chosen_time:
                available_times = get_available_times(state['specialist_id'], state['service_id'])
                times_text = "\n".join([f"- {t}" for t in available_times])
                update.message.reply_text(
                    "Пожалуйста, выберите время из списка:\n\n"
                    f"{times_text}"
                )
                return

            available_times = get_available_times(state['specialist_id'], state['service_id'])
            if chosen_time in available_times:
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
                    f"Услуга: {service_name}\n"
                    f"Специалист: {specialist_name}\n"
                    f"Время: {chosen_time}\n\n"
                    "Для подтверждения напишите 'да' или 'нет' для отмены."
                )
            else:
                update.message.reply_text("Выбранное время недоступно. Пожалуйста, выберите другое время.")

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
                    update.message.reply_text(
                        f"Запись успешно создана!\n\n"
                        f"Услуга: {service_name}\n"
                        f"Специалист: {specialist_name}\n"
                        f"Время: {state['chosen_time']}\n\n"
                        "Будем ждать вас!"
                    )
                    # Отправляем уведомление менеджеру
                    if MANAGER_CHAT_ID:
                        bot.send_message(
                            MANAGER_CHAT_ID,
                            f"Новая запись!\n"
                            f"Услуга: {service_name}\n"
                            f"Специалист: {specialist_name}\n"
                            f"Время: {state['chosen_time']}\n"
                            f"Клиент ID: {user_id}"
                        )
                else:
                    update.message.reply_text("Произошла ошибка при создании записи. Пожалуйста, попробуйте позже.")
                delete_user_state(user_id)
            elif user_text.lower() in ['нет', 'no', 'отмена']:
                update.message.reply_text("Запись отменена.")
                delete_user_state(user_id)

        elif action == "CANCEL_BOOKING":
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён. Можете начать заново.")

        else:
            update.message.reply_text(result.get('response', "Извините, я не понял ваш запрос."))

    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON от GPT для user {user_id}: {e}")
        update.message.reply_text("Произошла ошибка обработки. Попробуйте еще раз.")
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

        # Базовые команды отмены
        if user_text.lower() in ['отмена', 'cancel', 'стоп', 'stop']:
            delete_user_state(user_id)
            update.message.reply_text("Процесс записи отменён. Можете начать заново.")
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
        7. OTHER - другое

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
            
            intent_data = json.loads(intent_response.choices[0].message.content)
            logger.info(f"Определено намерение для user_id={user_id}: {intent_data}")

            # Обработка различных намерений
            if intent_data['intent'] == "BOOKING_INTENT":
                # Передаем в основной обработчик бронирования
                handle_booking_with_gpt(update, user_id, user_text, state)
                
            elif intent_data['intent'] == "CANCEL_INTENT":
                # Обработка отмены записи
                handle_cancellation(update, user_id, intent_data['extracted_info'])
                
            elif intent_data['intent'] == "RESCHEDULE_INTENT":
                # Обработка переноса записи
                handle_reschedule(update, user_id, intent_data['extracted_info'])
                
            elif intent_data['intent'] == "PRICE_QUESTION":
                # Ответ на вопрос о ценах
                handle_price_question(update, user_id, intent_data['extracted_info'])
                
            elif intent_data['intent'] == "SPECIALIST_QUESTION":
                # Информация о специалистах
                handle_specialist_question(update, user_id, intent_data['extracted_info'])
                
            elif intent_data['intent'] == "GENERAL_QUESTION":
                # Обработка общих вопросов через GPT
                handle_general_question(update, user_id, user_text)
                
            else:
                # Общий ответ через GPT
                response = generate_ai_response(user_text)
                update.message.reply_text(response)

        except json.JSONDecodeError:
            logger.error("Ошибка парсинга JSON от GPT")
            handle_booking_with_gpt(update, user_id, user_text, state)

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}", exc_info=True)
        update.message.reply_text(
            "Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте позже или напишите /start"
        )

# Вспомогательные функции для обработки различных намерений
def handle_cancellation(update, user_id, extracted_info):
    try:
        # Получаем активные записи пользователя
        bookings = get_user_bookings(user_id)
        if not bookings:
            update.message.reply_text("У вас нет активных записей для отмены.")
            return

        if len(bookings) == 1:
            # Если только одна запись, отменяем её
            booking = bookings[0]
            if cancel_booking(user_id, booking['id']):
                update.message.reply_text(
                    f"Ваша запись на {booking['date_time']} "
                    f"к {booking['specialist_name']} была отменена."
                )
            else:
                update.message.reply_text("Произошла ошибка при отмене записи.")
        else:
            # Если несколько записей, показываем список
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
            # Получаем цену конкретной услуги
            service_info = get_service_price(extracted_info['service'])
            if service_info:
                update.message.reply_text(
                    f"Стоимость услуги '{service_info['name']}': "
                    f"{service_info['price']} руб."
                )
            else:
                # Показываем все цены
                show_price_list(update)
        else:
            show_price_list(update)

    except Exception as e:
        logger.error(f"Ошибка при обработке вопроса о ценах: {e}")
        update.message.reply_text("Произошла ошибка при получении информации о ценах.")

def handle_specialist_question(update, user_id, extracted_info):
    try:
        if 'specialist' in extracted_info and extracted_info['specialist']:
            # Информация о конкретном специалисте
            specialist_info = get_specialist_info(extracted_info['specialist'])
            if specialist_info:
                update.message.reply_text(
                    f"Специалист: {specialist_info['name']}\n"
                    f"Специализация: {specialist_info['specialization']}\n"
                    f"Опыт работы: {specialist_info['experience']}\n"
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
        found = find_service_in_text(user_text)
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
        service = next((s for s in services if s[1].lower() == user_text), None)
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
        specialist = next((sp for sp in specs if sp[1].lower() == user_text), None)
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
        serv_id = state['service_id']
        spec_id = state['specialist_id']
        av_times = get_available_times(spec_id, serv_id)
        chosen_time = parse_time_input(user_text, av_times)
        if chosen_time and chosen_time in av_times:
            set_user_state(user_id, "confirm", service_id=serv_id, specialist_id=spec_id, chosen_time=chosen_time)
            srv_name = get_service_name(serv_id)
            sp_name = get_specialist_name(spec_id)
            update.message.reply_text(
                f"Вы выбрали:\nУслуга: {srv_name}\nСпециалист: {sp_name}\nВремя: {chosen_time}\nПодтвердите запись (да/нет)."
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















def get_user_bookings(user_id):
    """Получение всех активных записей пользователя"""
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
    """Получение информации о цене услуги"""
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
    """Получение информации о специалисте"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.id, s.name, s.specialization, s.experience,
                   STRING_AGG(srv.title, ', ') as services
            FROM specialists s
            LEFT JOIN specialist_services ss ON s.id = ss.specialist_id
            LEFT JOIN services srv ON ss.service_id = srv.id
            WHERE LOWER(s.name) LIKE LOWER(%s)
            GROUP BY s.id, s.name, s.specialization, s.experience
        """, (f"%{specialist_name}%",))
        row = cur.fetchone()
        if row:
            return {
                'id': row[0],
                'name': row[1],
                'specialization': row[2],
                'experience': row[3],
                'services': row[4]
            }
        return None
    finally:
        cur.close()
        conn.close()

def show_price_list(update):
    """Показать список цен на услуги"""
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
    """Показать список всех специалистов"""
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
```




















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
        
        # Получаем информацию о записи
        cur.execute("""
            SELECT service_id, specialist_id, date_time 
            FROM bookings 
            WHERE id = %s AND user_id = %s
        """, (booking_id, user_id))
        booking = cur.fetchone()
        
        if booking:
            # Освобождаем слот
            cur.execute("""
                UPDATE booking_times 
                SET is_booked = FALSE 
                WHERE specialist_id = %s 
                AND service_id = %s 
                AND slot_time = %s
            """, (booking[1], booking[0], booking[2]))
            
            # Удаляем запись
            cur.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
            conn.commit()
            return True
        return False
    except psycopg2.Error as e:
        logger.error(f"Ошибка при отмене записи: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()





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
