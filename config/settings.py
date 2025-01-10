import os
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# Основные настройки бота
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
APP_URL = os.getenv("APP_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")
ADMIN_ID = 561102768
# Проверка наличия всех необходимых переменных окружения
REQUIRED_ENV_VARS = {
    "TOKEN": TOKEN,
    "DATABASE_URL": DATABASE_URL,
    "APP_URL": APP_URL,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "MANAGER_CHAT_ID": MANAGER_CHAT_ID
}

# Проверяем, что все необходимые переменные установлены
missing_vars = [var_name for var_name, var_value in REQUIRED_ENV_VARS.items() if not var_value]
if missing_vars:
    raise ValueError(f"Не установлены следующие переменные окружения: {', '.join(missing_vars)}")

# Настройки OpenAI
GPT_MODEL = "gpt-3.5-turbo"
GPT_TEMPERATURE = 0.7
GPT_MAX_TOKENS = 200

# Настройки базы данных
DB_CONNECTION_TIMEOUT = 30  # секунды

# Настройки логирования
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "INFO"

# Настройки Flask
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
