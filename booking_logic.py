# booking_logic.py
import datetime
import logging
import psycopg2

from db import get_db_connection
from gpt_utils import clean_gpt_booking_response

logger = logging.getLogger(__name__)

def get_available_times(spec_id, serv_id):
    """
    Возвращает список свободных временных слотов (YYYY-MM-DD HH:MM)
    из booking_times, где specialist_id=spec_id, service_id=serv_id, is_booked=FALSE
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

def parse_time_input(user_text, available_times):
    """
    Пытается распознать время из user_text, возвращает 'YYYY-MM-DD HH:MM',
    если совпадает с одним из available_times, иначе None.
    """
    if not available_times:
        return None

    unique_dates = list({ t.split()[0] for t in available_times })
    cleaned = user_text.strip().lower()

    # Если просто число (например, "12"), подставляем :00
    if cleaned.isdigit():
        try:
            hour = int(cleaned)
            if 0 <= hour <= 23:
                time_part = f"{hour:02d}:00"
                if len(unique_dates) == 1:
                    only_date = unique_dates[0]
                    candidate = f"{only_date} {time_part}"
                    if candidate in available_times:
                        return candidate
                return None
        except ValueError:
            return None

    # Если формат "12:00" (и только одна дата)
    if user_text.count(":") == 1 and user_text.count("-") == 0:
        if len(unique_dates) == 1:
            only_date = unique_dates[0]
            candidate = f"{only_date} {user_text}"
            if candidate in available_times:
                return candidate
        return None

    # Если полное совпадение "2025-01-08 12:00"
    if user_text in available_times:
        return user_text

    return None

def create_booking(user_id, serv_id, spec_id, date_str):
    """
    Обновляем booking_times (is_booked=TRUE) и вставляем запись в bookings.
    """
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты: {date_str}")
        return False

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Помечаем слот занятым
        cur.execute("""
            UPDATE booking_times
            SET is_booked = TRUE
            WHERE specialist_id = %s 
              AND service_id = %s 
              AND slot_time = %s
        """, (spec_id, serv_id, chosen_dt))
        # Вставляем запись в bookings
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

def cancel_booking(user_id, booking_id):
    """
    Удаление записи из bookings + освобождение слота в booking_times.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Получаем информацию о записи
        cur.execute("""
            SELECT b.service_id, b.specialist_id, b.date_time
            FROM bookings b
            WHERE b.id = %s AND b.user_id = %s
        """, (booking_id, user_id))
        row = cur.fetchone()
        if row:
            service_id, specialist_id, date_time = row
            # Освобождаем слот
            cur.execute("""
                UPDATE booking_times
                SET is_booked = FALSE
                WHERE specialist_id = %s
                  AND service_id = %s
                  AND slot_time = %s
            """, (specialist_id, service_id, date_time))
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

def get_user_bookings(user_id):
    """
    Возвращает список активных (будущих) записей пользователя
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT b.id, b.service_id, b.specialist_id, b.date_time
            FROM bookings b
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
                'date_time': r[3].strftime("%Y-%m-%d %H:%M")
            })
        return result
    finally:
        cur.close()
        conn.close()
