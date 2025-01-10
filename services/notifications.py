from typing import List, Tuple
import telegram
from config.settings import TOKEN
from database.connection import get_db_connection
from utils.logger import logger

bot = telegram.Bot(token=TOKEN)

def get_active_managers() -> List[Tuple]:
    """Получение списка активных менеджеров"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT m.chat_id, ns.notify_new_booking, 
                   ns.notify_cancellation, ns.notify_reschedule
            FROM managers m
            JOIN notification_settings ns ON ns.manager_id = m.id
            WHERE m.is_active = true
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def notify_managers(message: str, notification_type: str = 'new_booking') -> None:
    """Отправка уведомлений менеджерам"""
    managers = get_active_managers()
    for mgr in managers:
        chat_id, notify_new, notify_cancel, notify_reschedule = mgr
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

def register_manager(chat_id: int, username: Optional[str] = None) -> bool:
    """Регистрация нового менеджера"""
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
        
        cur.execute("""
            INSERT INTO notification_settings (manager_id)
            VALUES (%s)
        """, (manager_id,))
        
        conn.commit()
        return True
    finally:
        cur.close()
        conn.close()
