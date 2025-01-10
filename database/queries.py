from typing import List, Tuple, Optional, Dict
import datetime
import psycopg2

from database.connection import get_db_connection
from utils.logger import logger


def get_user_state(user_id: int) -> Optional[Dict]:
    """
    Получение состояния пользователя (этап диалога), хранящегося в таблице user_state.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT step, service_id, specialist_id, chosen_time
            FROM user_state
            WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        if row:
            return {
                'step': row[0],
                'service_id': row[1],
                'specialist_id': row[2],
                'chosen_time': row[3]
            }
        return None
    finally:
        cur.close()
        conn.close()


def get_user_bookings(user_id: int) -> List[Dict]:
    """
    Получение всех активных (будущих) записей пользователя из таблицы bookings.
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
        return [{
            'id': r[0],
            'service_id': r[1],
            'specialist_id': r[2],
            'date_time': r[3].strftime("%Y-%m-%d %H:%M"),
            'service_name': r[4],
            'specialist_name': r[5]
        } for r in rows]
    finally:
        cur.close()
        conn.close()


def get_services() -> List[Tuple[int, str]]:
    """
    Возвращает список (id, title) всех услуг из таблицы services.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, title FROM services ORDER BY id;")
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def find_service_by_name(user_text: str) -> Optional[Tuple[int, str]]:
    """
    Поиск услуги по названию (точное или частичное совпадение) среди services.
    Возвращает кортеж (id, title) или None, если не найдено.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Сначала ищем точное совпадение
        cur.execute(
            "SELECT id, title FROM services WHERE LOWER(title) = LOWER(%s)",
            (user_text,)
        )
        service = cur.fetchone()
        if service:
            return service

        # Если точного совпадения нет, ищем частичное
        cur.execute(
            "SELECT id, title FROM services WHERE LOWER(title) LIKE LOWER(%s)",
            (f"%{user_text}%",)
        )
        matches = cur.fetchall()
        if matches:
            return matches[0]  # Возвращаем первую найденную
        return None
    finally:
        cur.close()
        conn.close()


def get_specialists(service_id: Optional[int] = None) -> List[Tuple[int, str]]:
    """
    Возвращает список (id, name) специалистов.
    Если service_id передан, то только тех, кто привязан к этой услуге.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
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
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def get_available_times(spec_id: int, serv_id: int) -> List[str]:
    """
    Возвращает список свободных слотов (YYYY-MM-DD HH:MM) для пары (spec_id, serv_id)
    из таблицы booking_times, где is_booked=FALSE.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT slot_time
            FROM booking_times
            WHERE specialist_id = %s
              AND service_id = %s
              AND is_booked = FALSE
            ORDER BY slot_time
        """, (spec_id, serv_id))
        rows = cur.fetchall()
        return [r[0].strftime("%Y-%m-%d %H:%M") for r in rows]
    finally:
        cur.close()
        conn.close()


def create_booking(user_id: int, serv_id: int, spec_id: int, date_str: str) -> bool:
    """
    Создаёт новую запись (booking) для user_id, serv_id, spec_id на date_str.
    Помечает слот is_booked = TRUE в booking_times.
    """
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты: {date_str}")
        return False

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Помечаем слот как занятый
        cur.execute("""
            UPDATE booking_times
            SET is_booked = TRUE
            WHERE specialist_id = %s 
              AND service_id = %s 
              AND slot_time = %s
        """, (spec_id, serv_id, chosen_dt))

        # Добавляем в bookings
        cur.execute("""
            INSERT INTO bookings (user_id, service_id, specialist_id, date_time)
            VALUES (%s, %s, %s, %s)
        """, (user_id, serv_id, spec_id, chosen_dt))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error in create_booking: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def get_service_name(service_id: int) -> Optional[str]:
    """
    По id услуги возвращает её название (title) или None, если нет.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT title FROM services WHERE id = %s", (service_id,))
        result = cur.fetchone()
        return result[0] if result else None
    finally:
        cur.close()
        conn.close()


def get_specialist_name(specialist_id: int) -> Optional[str]:
    """
    По id специалиста возвращает его имя (name) или None, если нет.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM specialists WHERE id = %s", (specialist_id,))
        result = cur.fetchone()
        return result[0] if result else None
    finally:
        cur.close()
        conn.close()


def find_available_specialist(service_id: int, exclude_specialist_id: int) -> Optional[Tuple[int, str]]:
    """
    Находит *другого* специалиста (id, name), у которого есть свободное время,
    исключая exclude_specialist_id.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT s.id, s.name
            FROM specialists s
            JOIN specialist_services ss ON s.id = ss.specialist_id
            JOIN booking_times bt ON s.id = bt.specialist_id
            WHERE ss.service_id = %s
              AND s.id != %s
              AND bt.is_booked = FALSE
            LIMIT 1
        """, (service_id, exclude_specialist_id))
        result = cur.fetchone()
        return result if result else None
    finally:
        cur.close()
        conn.close()


def set_user_state(
    user_id: int,
    step: str,
    service_id: Optional[int] = None,
    specialist_id: Optional[int] = None,
    chosen_time: Optional[str] = None
) -> None:
    """
    Сохраняет (или обновляет) состояние пользователя в таблице user_state.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()


def delete_user_state(user_id: int) -> None:
    """
    Удаляет состояние пользователя из таблицы user_state.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM user_state WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()


def create_service(service_name: str, price: float) -> bool:
    """
    Создаёт новую услугу в таблице services (title, price).
    Если такая услуга уже существует, возвращает False.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверим, нет ли дубликата
        cur.execute("SELECT id FROM services WHERE LOWER(title) = LOWER(%s)", (service_name,))
        row = cur.fetchone()
        if row:
            # Уже есть такая услуга
            return False
        
        cur.execute("""
            INSERT INTO services (title, price)
            VALUES (%s, %s)
        """, (service_name, price))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка в create_service: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def create_specialist(specialist_name: str) -> bool:
    """
    Создаёт нового специалиста (name) в таблице specialists.
    Если уже есть с таким же именем (case-insensitive), возвращает False.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM specialists WHERE LOWER(name) = LOWER(%s)", (specialist_name,))
        row = cur.fetchone()
        if row:
            return False
        
        cur.execute("INSERT INTO specialists (name) VALUES (%s)", (specialist_name,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка в create_specialist: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def create_manager_in_db(chat_id: int, username: Optional[str]) -> bool:
    """
    Создаёт нового менеджера по chat_id (и необязательному username) в таблице managers.
    Параллельно добавляет запись в notification_settings.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM managers WHERE chat_id = %s", (chat_id,))
        if cur.fetchone():
            return False
        
        cur.execute("""
            INSERT INTO managers (chat_id, username)
            VALUES (%s, %s)
            RETURNING id
        """, (chat_id, username))
        manager_id = cur.fetchone()[0]

        # Запись в notification_settings
        cur.execute("""
            INSERT INTO notification_settings (manager_id)
            VALUES (%s)
        """, (manager_id,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка в create_manager_in_db: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def add_service_to_specialist(spec_id: int, serv_id: int) -> str:
    """
    Добавляет услугу (service_id) к специалисту (specialist_id) в таблицу specialist_services.
    Если уже есть — сообщает об этом, иначе создаёт новую связку.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверяем, есть ли уже такая связка:
        cur.execute("""
            SELECT 1
            FROM specialist_services
            WHERE specialist_id = %s AND service_id = %s
        """, (spec_id, serv_id))
        row = cur.fetchone()
        if row:
            return f"У специалиста (id={spec_id}) уже есть услуга (id={serv_id})."
        
        # Если нет — добавляем
        cur.execute("""
            INSERT INTO specialist_services (specialist_id, service_id)
            VALUES (%s, %s)
        """, (spec_id, serv_id))
        conn.commit()
        return f"Услуга (id={serv_id}) добавлена к специалисту (id={spec_id})!"
    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка при добавлении услуги {serv_id} к специалисту {spec_id}: {e}")
        return f"Ошибка: {e}"
    finally:
        cur.close()
        conn.close()

def get_bookings_for_specialist(specialist_id: int) -> List[Dict]:
    """
    Возвращает список активных (будущих) записей для конкретного специалиста (по specialist_id).
    Например, формат возвращаемых объектов:
    [
      {
        "id": 10,
        "date_time": "2025-01-15 14:00",
        "service_name": "Чистка лица",
        "user_name": "Олег",
      },
      ...
    ]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                b.id,
                b.date_time,
                s.title as service_name,
                u.name as user_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN users u ON b.user_id = u.id
            WHERE b.specialist_id = %s
              AND b.date_time > NOW()
            ORDER BY b.date_time
        """, (specialist_id,))
        
        rows = cur.fetchall()
        # Для удобства создаём словари
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "date_time": row[1].strftime("%Y-%m-%d %H:%M"),
                "service_name": row[2],
                "user_name": row[3],
            })
        return result

    finally:
        cur.close()
        conn.close()

def cancel_booking_by_id(booking_id: int) -> Tuple[bool, str]:
    """
    Отменяет запись с указанным booking_id. Возвращает кортеж (успех, сообщение).
    Если запись успешно отменена, (True, "Запись ... успешно отменена").
    Если произошла ошибка или запись не найдена, (False, "текст ошибки").
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Сначала проверяем, существует ли запись
        cur.execute("""
            SELECT specialist_id, service_id, date_time 
            FROM bookings
            WHERE id = %s
        """, (booking_id,))
        row = cur.fetchone()
        if not row:
            return (False, f"Запись с ID {booking_id} не найдена")

        specialist_id, service_id, date_time = row

        # Освобождаем слот
        cur.execute("""
            UPDATE booking_times
            SET is_booked = FALSE
            WHERE specialist_id = %s
              AND service_id = %s
              AND slot_time = %s
        """, (specialist_id, service_id, date_time))

        # Удаляем саму запись
        cur.execute("""
            DELETE FROM bookings
            WHERE id = %s
        """, (booking_id,))

        conn.commit()
        return (True, f"Запись с ID {booking_id} успешно отменена.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка при отмене записи {booking_id}: {e}")
        return (False, f"Произошла ошибка при отмене записи: {e}")
    finally:
        cur.close()
        conn.close()
