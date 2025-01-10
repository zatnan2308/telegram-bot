# db.py
import os
import logging
import psycopg2

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """
    Возвращает connection к базе данных PostgreSQL, основываясь на DATABASE_URL.
    """
    if not DATABASE_URL:
        raise ValueError("Не установлена переменная окружения DATABASE_URL")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """
    Проверяет подключение к БД, делая простой SELECT 1.
    Выбрасывает исключение, если подключение не удалось.
    """
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

def init_db_docstring_expanded():
    """
    ДОПОЛНИТЕЛЬНАЯ ФУНКЦИЯ (пустышка, повтор лога) для демонстрации.
    Псевдо-тест второго подключения к базе данных (искусственный).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    logger.info("Псевдо-тест второго подключения к базе данных (искусственный)")
    try:
        cur.execute("SELECT 1")
        msg = "Успешное (повторное) подключение к базе данных"
        logger.info(msg)
        return msg
    except psycopg2.Error as e:
        err = f"Ошибка (повторная) подключения к БД: {e}"
        logger.error(err)
        return err
    finally:
        cur.close()
        conn.close()
