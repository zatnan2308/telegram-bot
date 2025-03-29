from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

from config.settings import TOKEN, APP_URL
from database.connection import init_db
from handlers.commands import start, help_command, spec_list_command, service_list_command
from handlers.messages import handle_message
from handlers.manager import handle_manager_commands
from handlers.admin_commands import (
    admin_command_add_service,
    admin_command_add_specialist,
    admin_command_add_manager,
    admin_command_set_service_duration
)
from handlers.specialist_commands import (
    specialist_command_free_time,
    specialist_command_appointments,
    specialist_command_cancel_booking,
    specialist_command_add_service
)
from utils.logger import logger
from telegram import BotCommand

app = Flask(__name__)
bot = telegram.Bot(token=TOKEN)

def setup_commands(bot_instance):
    commands = [
        BotCommand("start", "Начать работу"),
        BotCommand("help", "Получить справку"),
        BotCommand("service_list", "Показать список услуг"),
        BotCommand("spec_list", "Показать список специалистов"),
        BotCommand("add_service", "Добавить услугу"),
        BotCommand("add_specialist", "Добавить специалиста"),
        BotCommand("add_manager", "Добавить менеджера"),
        BotCommand("spec_free_time", "Показать свободное время специалиста"),
        BotCommand("spec_appointments", "Показать записи специалиста"),
        BotCommand("spec_cancel_booking", "Отменить запись (по ID)"),
        BotCommand("spec_add_service", "Добавить услугу к специалисту"),
        BotCommand("set_service_duration", "Установить длительность (мин) для услуги"),
        # Новые команды для управления расписанием
        BotCommand("add_freetime", "Добавить свободное время"),
        BotCommand("remove_freetime", "Удалить свободное время"),
        BotCommand("list_freetime", "Просмотреть свободное время"),
    ]
    bot_instance.set_my_commands(commands)


dispatcher = Dispatcher(bot, None, workers=4)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("help", help_command))
dispatcher.add_handler(CommandHandler("register_manager", handle_manager_commands))
dispatcher.add_handler(CommandHandler("stop_notifications", handle_manager_commands))
dispatcher.add_handler(CommandHandler("add_service", admin_command_add_service))
dispatcher.add_handler(CommandHandler("add_specialist", admin_command_add_specialist))
dispatcher.add_handler(CommandHandler("add_manager", admin_command_add_manager))
dispatcher.add_handler(CommandHandler("service_list", service_list_command))
dispatcher.add_handler(CommandHandler("spec_list", spec_list_command))
dispatcher.add_handler(CommandHandler("spec_free_time", specialist_command_free_time))
dispatcher.add_handler(CommandHandler("spec_appointments", specialist_command_appointments))
dispatcher.add_handler(CommandHandler("spec_cancel_booking", specialist_command_cancel_booking))
dispatcher.add_handler(CommandHandler("spec_add_service", specialist_command_add_service))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

def set_webhook():
    url = f"{APP_URL}/{TOKEN}"
    bot.set_webhook(url=url)
    logger.info(f"Webhook установлен: {url}")

if __name__ == "__main__":
    init_db()
    set_webhook()
    setup_commands(bot)
    app.run(host="0.0.0.0", port=5000)
