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
    conn = get_db_connection()
    cur = conn.cursor()
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
    
    Отвечай в формате JSON:
    {
        "action": "действие",
        "response": "ответ пользователю",
        "extracted_data": {
            "service": "название услуги",
            "specialist": "имя специалиста",
            "time": "время"
        }
    }
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
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Контекст:\n{context}\nСообщение пользователя: {user_text}"}
            ],
            temperature=0.7
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Обработка действий на основе ответа GPT
        action = result.get('action')
        if action == "LIST_SERVICES":
            services = get_services()
            service_list = "\n".join([f"- {s[1]}" for s in services])
            update.message.reply_text(f"{result['response']}\n\nДоступные услуги:\n{service_list}")
            
        elif action == "SELECT_SERVICE":
            service_name = result['extracted_data'].get('service')
            if service_name:
                services = get_services()
                service = next((s for s in services if s[1].lower() == service_name.lower()), None)
                if service:
                    set_user_state(user_id, "select_specialist", service_id=service[0])
                    specialists = get_specialists(service_id=service[0])
                    sp_text = "\n".join([f"- {sp[1]}" for sp in specialists])
                    update.message.reply_text(f"{result['response']}\n\nДоступные специалисты:\n{sp_text}")
                else:
                    update.message.reply_text("Извините, такой услуги нет в списке. Попробуйте еще раз.")
            else:
                update.message.reply_text(result['response'])

        elif action == "SELECT_SPECIALIST":
            if state and state.get('service_id'):
                specialist_name = result['extracted_data'].get('specialist')
                specialists = get_specialists(state['service_id'])
                specialist = next((s for s in specialists if s[1].lower() == specialist_name.lower()), None)
                
                if specialist:
                    available_times = get_available_times(specialist[0], state['service_id'])
                    if available_times:
                        set_user_state(user_id, "select_time", 
                                     service_id=state['service_id'],
                                     specialist_id=specialist[0])
                        times_text = "\n".join([f"- {t}" for t in available_times])
                        update.message.reply_text(f"{result['response']}\n\nДоступное время:\n{times_text}")
                    else:
                        update.message.reply_text("К сожалению, у этого специалиста нет свободного времени.")
                else:
                    update.message.reply_text("Специалист не найден. Попробуйте еще раз.")

        elif action == "CONFIRM_BOOKING":
            if state and all(k in state for k in ['service_id', 'specialist_id', 'chosen_time']):
                success = create_booking(
                    user_id=user_id,
                    serv_id=state['service_id'],
                    spec_id=state['specialist_id'],
                    date_str=state['chosen_time']
                )
                if success:
                    update.message.reply_text(result['response'])
                    delete_user_state(user_id)
                else:
                    update.message.reply_text("Произошла ошибка при создании записи. Попробуйте позже.")
            else:
                update.message.reply_text("Недостаточно информации для создания записи.")

        elif action == "CANCEL_BOOKING":
            # Добавить логику отмены записи
            delete_user_state(user_id)
            update.message.reply_text(result['response'])

        else:
            update.message.reply_text(result['response'])

    except Exception as e:
        logger.error(f"Ошибка при обработке GPT: {e}")
        update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

# Обновляем основной обработчик сообщений
def handle_message(update, context):
    user_text = update.message.text.strip()
    user_id = update.message.chat_id
    user_name = update.message.chat.first_name or "Unknown"

    register_user(user_id, user_name)
    state = get_user_state(user_id)
    
    # Передаем обработку GPT
    handle_booking_with_gpt(update, user_id, user_text, state)

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
