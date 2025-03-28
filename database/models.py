from typing import Dict, Optional, List
import datetime
from database.connection import get_db_connection
from utils.logger import logger

def get_user_state(user_id: int) -> Optional[Dict]:
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
            return {'step': row[0], 'service_id': row[1], 'specialist_id': row[2], 'chosen_time': row[3]}
        return None
    finally:
        cur.close()
        conn.close()

def set_user_state(user_id: int, step: str, service_id: Optional[int] = None, specialist_id: Optional[int] = None, chosen_time: Optional[str] = None) -> None:
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
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM user_state WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def get_user_bookings(user_id: int) -> List[Dict]:
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
