import psycopg2
from config.settings import DATABASE_URL
from utils.logger import logger

def get_db_connection():
    """Возвращает connection к базе данных PostgreSQL"""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Проверяет подключение к БД"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1")
        logger.info("Успешное подключение к базе данных")
    except psycopg2.Error as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        raise
    finally:
        cur.close()
        conn.close()

def create_tables():
    """Создает необходимые таблицы в БД"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Таблица услуг с корректным именем столбца для длительности
        cur.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id SERIAL PRIMARY KEY,
                title VARCHAR(100) NOT NULL,
                description TEXT,
                price DECIMAL(10, 2),
                duration_minutes INTEGER  -- длительность в минутах
            )
        """)

        # Таблица специалистов с добавлением рабочих часов
        cur.execute("""
            CREATE TABLE IF NOT EXISTS specialists (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                is_active BOOLEAN DEFAULT true,
                work_start_time TIME,
                work_end_time TIME
            )
        """)

        # Таблица пользователей (используется telegram_id как первичный ключ)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                name VARCHAR(100)
            )
        """)

        # Таблица связи специалистов и услуг
        cur.execute("""
            CREATE TABLE IF NOT EXISTS specialist_services (
                specialist_id INTEGER REFERENCES specialists(id),
                service_id INTEGER REFERENCES services(id),
                PRIMARY KEY (specialist_id, service_id)
            )
        """)

        # Таблица временных слотов
        cur.execute("""
            CREATE TABLE IF NOT EXISTS booking_times (
                id SERIAL PRIMARY KEY,
                specialist_id INTEGER REFERENCES specialists(id),
                service_id INTEGER REFERENCES services(id),
                slot_time TIMESTAMP NOT NULL,
                is_booked BOOLEAN DEFAULT false,
                UNIQUE (specialist_id, service_id, slot_time)
            )
        """)

        # Таблица записей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                service_id INTEGER REFERENCES services(id),
                specialist_id INTEGER REFERENCES specialists(id),
                date_time TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) DEFAULT 'active'
            )
        """)

        # Таблица состояний пользователей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id BIGINT PRIMARY KEY,
                step VARCHAR(50),
                service_id INTEGER REFERENCES services(id),
                specialist_id INTEGER REFERENCES specialists(id),
                chosen_time TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица менеджеров
        cur.execute("""
            CREATE TABLE IF NOT EXISTS managers (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(100),
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица настроек уведомлений для менеджеров
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_settings (
                id SERIAL PRIMARY KEY,
                manager_id INTEGER REFERENCES managers(id),
                notify_new_booking BOOLEAN DEFAULT true,
                notify_cancellation BOOLEAN DEFAULT true,
                notify_reschedule BOOLEAN DEFAULT true
            )
        """)

        conn.commit()
        logger.info("Таблицы успешно созданы")
    except psycopg2.Error as e:
        logger.error(f"Ошибка создания таблиц: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
