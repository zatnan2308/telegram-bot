import psycopg2
from config.settings import DATABASE_URL
from utils.logger import logger

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
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
