import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.db.database import AsyncSessionLocal
from app.services.followup_service import run_followup_check

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


def start_scheduler():
    """Start the background scheduler. Called once on app startup."""
    scheduler.add_job(
        _followup_job,
        trigger=IntervalTrigger(hours=1),
        id="followup_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,  # allow up to 5 min late start
    )
    scheduler.start()
    logger.info("APScheduler started — follow-up check runs every hour")


def stop_scheduler():
    """Gracefully shut down the scheduler on app shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


async def _followup_job():
    """The actual job: open DB session, run follow-up check, close session."""
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_followup_check(db)
            logger.info(
                f"Follow-up check complete — "
                f"checked={summary['checked']}, "
                f"notified={summary['notified']}, "
                f"escalated={summary['escalated']}"
            )
    except Exception as e:
        logger.error(f"Follow-up job failed: {e}", exc_info=True)
