from typing import List, Tuple, Optional, Dict
import datetime
import psycopg2

from database.connection import get_db_connection
from utils.logger import logger

def get_services() -> List[Tuple[int, str]]:
    """Возвращает список (id, title) услуг"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, title FROM services ORDER BY id;")
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def find_service_by_name(user_text: str) -> Optional[Tuple[int, str]]:
    """Поиск услуги по названию"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Точное совпадение
        cur.execute(
            "SELECT id, title FROM services WHERE LOWER(title) = LOWER(%s)",
            (user_text,)
        )
        service = cur.fetchone()
        if service:
            return service

        # Частичное совпадение
        cur.execute(
            "SELECT id, title FROM services WHERE LOWER(title) LIKE LOWER(%s)",
            (f"%{user_text}%",)
        )
        matches = cur.fetchall()
        return matches[0] if matches else None
    finally:
        cur.close()
        conn.close()

def get_specialists(service_id: Optional[int] = None) -> List[Tuple[int, str]]:
    """Возвращает список (id, name) специалистов"""
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
    """Возвращает список свободных временных слотов"""
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
    """Создает новую запись"""
    try:
        chosen_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        logger.error(f"Неверный формат даты: {date_str}")
        return False

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Обновляем статус временного слота
        cur.execute("""
            UPDATE booking_times
            SET is_booked = TRUE
            WHERE specialist_id = %s 
              AND service_id = %s 
              AND slot_time = %s
        """, (spec_id, serv_id, chosen_dt))

        # Создаем запись
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
