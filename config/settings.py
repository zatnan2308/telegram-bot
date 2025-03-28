import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
APP_URL = os.getenv("APP_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-3.5-turbo")

_MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")
try:
    MANAGER_CHAT_ID = int(_MANAGER_CHAT_ID) if _MANAGER_CHAT_ID is not None else None
except ValueError:
    MANAGER_CHAT_ID = None

ADMIN_ID = 561102768

REQUIRED_ENV_VARS = {
    "TOKEN": TOKEN,
    "DATABASE_URL": DATABASE_URL,
    "APP_URL": APP_URL,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "MANAGER_CHAT_ID": MANAGER_CHAT_ID
}

missing_vars = [var_name for var_name, var_value in REQUIRED_ENV_VARS.items() if not var_value]
if missing_vars:
    raise Exception(f"Отсутствуют необходимые переменные окружения: {', '.join(missing_vars)}")
