# main.py
import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
)

from handlers_user import user_router
from handlers_group import group_router
from storage import init_db

# Временный роутер, чтобы быстро узнать chat_id (удали потом)
tmp_router = Router()

@tmp_router.message()
async def show_chat_id(m):
    print("CHAT ID:", m.chat.id)


def on_startup():
    init_db()


async def main():
    load_dotenv()

    bot = Bot(
        os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(group_router)
    dp.include_router(tmp_router)  # когда chat_id узнаешь — можешь убрать

    # Команды для ЛС (жители)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="stop",  description="Остановить диалог"),
            BotCommand(command="mine",  description="Мои заявки"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )

    # Команды для групп (исполнители)
    await bot.set_my_commands(
    [
        BotCommand(command="active", description="Заявки в работе"),
        BotCommand(command="free",   description="Свободные заявки"),
        BotCommand(command="my",     description="Мои активные"),
        BotCommand(command="done",   description="Выполненные (последние)"),
    ],
    scope=BotCommandScopeAllGroupChats(),
)

    on_startup()
    print("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
from handlers_group import group_router
dp.include_router(group_router)
