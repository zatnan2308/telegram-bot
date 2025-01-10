from typing import Optional, Dict
import telegram
from telegram.ext import CallbackContext

from config.settings import MANAGER_CHAT_ID
from database.queries import get_user_bookings
from utils.logger import logger

def is_manager(chat_id: int) -> bool:
    """Проверяет, является ли пользователь менеджером"""
    return str(chat_id) == str(MANAGER_CHAT_ID)

def handle_manager_commands(update: telegram.Update, context: CallbackContext) -> None:
    """Обработчик команд менеджера"""
    chat_id = update.effective_chat.id
    
    if not is_manager(chat_id):
        update.message.reply_text("У вас нет доступа к командам менеджера.")
        return

    command = update.message.text.lower()
    
    try:
        if command == '/bookings':
            # Получаем все активные записи
            bookings = get_all_bookings()
            if bookings:
                message = "Активные записи:\n\n"
                for booking in bookings:
                    message += (
                        f"📅 {booking['date_time']}\n"
                        f"👤 Клиент: {booking['user_id']}\n"
                        f"🎯 Услуга: {booking['service_name']}\n"
                        f"👩‍💼 Специалист: {booking['specialist_name']}\n"
                        "-------------------\n"
                    )
                update.message.reply_text(message)
            else:
                update.message.reply_text("Нет активных записей.")
                
        elif command == '/stats':
            # Статистика по записям
            stats = get_booking_stats()
            message = (
                f"📊 Статистика:\n\n"
                f"Всего записей: {stats['total']}\n"
                f"Активных записей: {stats['active']}\n"
                f"Отмененных записей: {stats['cancelled']}\n"
                f"Записей на сегодня: {stats['today']}"
            )
            update.message.reply_text(message)
            
        else:
            update.message.reply_text(
                "Доступные команды:\n"
                "/bookings - показать все активные записи\n"
                "/stats - показать статистику"
            )
            
    except Exception as e:
        logger.error(f"Ошибка в обработке команды менеджера: {e}", exc_info=True)
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def get_all_bookings() -> List[Dict]:
    """Получает все активные записи"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT b.id, b.user_id, b.date_time,
                   s.title as service_name, sp.name as specialist_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN specialists sp ON b.specialist_id = sp.id
            WHERE b.date_time > NOW()
              AND b.status = 'active'
            ORDER BY b.date_time
        """)
        rows = cur.fetchall()
        return [{
            'id': r[0],
            'user_id': r[1],
            'date_time': r[2].strftime("%Y-%m-%d %H:%M"),
            'service_name': r[3],
            'specialist_name': r[4]
        } for r in rows]
    finally:
        cur.close()
        conn.close()

def get_booking_stats() -> Dict:
    """Получает статистику по записям"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Общее количество записей
        cur.execute("SELECT COUNT(*) FROM bookings")
        total = cur.fetchone()[0]
        
        # Активные записи
        cur.execute("""
            SELECT COUNT(*) FROM bookings 
            WHERE status = 'active' AND date_time > NOW()
        """)
        active = cur.fetchone()[0]
        
        # Отмененные записи
        cur.execute("SELECT COUNT(*) FROM bookings WHERE status = 'cancelled'")
        cancelled = cur.fetchone()[0]
        
        # Записи на сегодня
        cur.execute("""
            SELECT COUNT(*) FROM bookings 
            WHERE status = 'active' 
              AND date_time::date = CURRENT_DATE
        """)
        today = cur.fetchone()[0]
        
        return {
            'total': total,
            'active': active,
            'cancelled': cancelled,
            'today': today
        }
    finally:
        cur.close()
        conn.close()
