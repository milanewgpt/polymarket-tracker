import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.handlers import register_handlers
from clients.polymarket import PolymarketClient
from clients.xtracker import XtrackerClient
from config.settings import Settings
from db.session import DatabaseManager
from scheduler.jobs import setup_scheduler
from services.monitoring import MonitoringService
from services.notification import NotificationService


async def main() -> None:
    settings = Settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting Polymarket Tweet Tracker")

    db = DatabaseManager(settings.database_url)
    await db.init_db()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    polymarket_client = PolymarketClient(gamma_api_url=settings.polymarket_gamma_api_url)
    xtracker_client = XtrackerClient(base_url=settings.xtracker_base_url)
    notification_service = NotificationService(bot)
    monitoring_service = MonitoringService(
        db, xtracker_client, notification_service, settings
    )

    register_handlers(dp, db, settings, polymarket_client, xtracker_client)

    scheduler = AsyncIOScheduler()
    setup_scheduler(scheduler, monitoring_service, settings.default_check_interval_minutes)
    scheduler.start()

    try:
        logger.info("Bot is polling…")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await polymarket_client.close()
        await xtracker_client.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
