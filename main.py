import asyncio
import logging
import sys
from pathlib import Path

from maxapi import Bot, Dispatcher

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DATABASE_PATH, MAX_BOT_TOKEN
from db.database import Database
from handlers import accounted, admin_ui, group_admin, private_guard
from middlewares.db_inject import DbInjectMiddleware
from middlewares.max_logging import MaxUpdateLogMiddleware, register_max_api_response_logging
from middlewares.scenario_timeout import ScenarioTimeoutMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("max_api").setLevel(logging.DEBUG)


async def main() -> None:
    if not MAX_BOT_TOKEN:
        raise SystemExit("Задайте MAX_BOT_TOKEN (или BOT_TOKEN) в .env")

    db = Database(DATABASE_PATH)
    await db.connect()

    bot = Bot(token=MAX_BOT_TOKEN)
    dp = Dispatcher()

    register_max_api_response_logging(dp)
    dp.outer_middleware(MaxUpdateLogMiddleware())
    dp.outer_middleware(DbInjectMiddleware(db))
    dp.outer_middleware(ScenarioTimeoutMiddleware())

    dp.include_routers(
        group_admin.router,
        accounted.router,
        admin_ui.router,
        private_guard.router,
    )

    try:
        await dp.start_polling(bot)
    finally:
        await bot.close_session()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
