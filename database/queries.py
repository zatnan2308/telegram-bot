from typing import List, Tuple, Optional, Dict
import datetime
import psycopg2

from database.connection import get_db_connection
from utils.logger import logger

def get_user_state(user_id: int) -> Optional[Dict]:
    """Получение состояния пользователя"""
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

def get_service_name(service_id: int) -> Optional[str]:
    """Получает название услуги по id"""
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
    """Получает имя специалиста по id"""
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
    """Находит другого доступного специалиста"""
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
    """Установка состояния пользователя"""
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
    """Удаление состояния пользователя"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM user_state WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def create_service(service_name: str, price: float) -> bool:
    """Создаёт новую услугу (service_name, price) в таблице services."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверяем, нет ли уже такой услуги:
        cur.execute("SELECT id FROM services WHERE LOWER(title) = LOWER(%s)", (service_name,))
        row = cur.fetchone()
        if row:
            # уже есть
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
    """Создаёт нового специалиста (specialist_name) в таблице specialists."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Аналогично проверяем:
        cur.execute("SELECT id FROM specialists WHERE LOWER(name) = LOWER(%s)", (specialist_name,))
        row = cur.fetchone()
        if row:
            return False
        
        cur.execute("""
            INSERT INTO specialists (name)
            VALUES (%s)
        """, (specialist_name,))
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
    """Создаёт нового менеджера по chat_id (и необязательному username)."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверяем, нет ли уже такого chat_id
        cur.execute("SELECT id FROM managers WHERE chat_id = %s", (chat_id,))
        if cur.fetchone():
            return False
        
        cur.execute("""
            INSERT INTO managers (chat_id, username)
            VALUES (%s, %s)
            RETURNING id
        """, (chat_id, username))
        manager_id = cur.fetchone()[0]

        # Также добавим запись в notification_settings
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


        """, (spec_id, serv_id, date_time))

        # Удаляем саму запись
        cur.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
        
        conn.commit()
        return (True, f"Запись с ID {booking_id} успешно отменена.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка при отмене записи {booking_id}: {e}")
        return (False, "Произошла ошибка при отмене записи.")
    finally:
        cur.close()
        conn.close()


def add_service_to_specialist(spec_id: int, serv_id: int) -> str:
    """
    Добавляет услугу (service_id) к специалисту (specialist_id) в таблицу 
    specialist_services. Если уже есть — игнорируем, 
    иначе создаём запись.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверяем, есть ли уже такая связка
        cur.execute("""
            SELECT 1 
            FROM specialist_services
            WHERE specialist_id = %s AND service_id = %s
        """, (spec_id, serv_id))
        row = cur.fetchone()
        if row:
            return f"У специалиста (id={spec_id}) уже есть услуга (id={serv_id})."

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

