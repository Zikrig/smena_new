import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# Запуск из каталога guard_bot: python main.py
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import BOT_TOKEN
from db.database import Database
from handlers import accounted, admin_ui, group_admin, private_guard
from middlewares.db_inject import DbInjectMiddleware
from middlewares.scenario_timeout import ScenarioTimeoutMiddleware

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Задайте BOT_TOKEN в .env")

    from config import DATABASE_PATH

    db = Database(DATABASE_PATH)
    await db.connect()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    _db_mw = DbInjectMiddleware(db)
    dp.message.middleware(_db_mw)
    dp.callback_query.middleware(_db_mw)

    _to = ScenarioTimeoutMiddleware()
    dp.message.middleware(_to)
    dp.callback_query.middleware(_to)

    dp.include_router(group_admin.router)
    dp.include_router(accounted.router)
    dp.include_router(admin_ui.router)
    dp.include_router(private_guard.router)

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
