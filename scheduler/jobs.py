import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.monitoring import MonitoringService

logger = logging.getLogger(__name__)


def setup_scheduler(
    scheduler: AsyncIOScheduler,
    monitoring_service: MonitoringService,
    interval_minutes: int,
) -> None:
    async def _monitoring_tick() -> None:
        try:
            await monitoring_service.check_and_update()
        except Exception:
            logger.exception("Unhandled error in monitoring job")

    scheduler.add_job(
        _monitoring_tick,
        "interval",
        minutes=interval_minutes,
        id="monitoring_check",
        replace_existing=True,
    )
    logger.info("Scheduled monitoring every %d minutes", interval_minutes)
