import asyncio
import datetime
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from core.review_engine import review_engine
from core.user_config import user_config_manager

logger = logging.getLogger(__name__)

class ReviewScheduler:
    def __init__(self, bot=None):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

    def set_bot(self, bot):
        self.bot = bot

    async def _send_to_user(self, user_id: int, text: str):
        if not self.bot:
            return
        chunk_size = 4000
        try:
            for i in range(0, len(text), chunk_size):
                await self.bot.send_message(chat_id=user_id, text=text[i:i + chunk_size])
        except Exception as e:
            logger.error(f"向用户 {user_id} 发送定时推送失败: {e}")

    async def scheduled_daily_review(self):
        logger.info("执行定时每日复盘 (多用户)...")
        active_users = user_config_manager.list_active_users()
        logger.info(f"待复盘用户列表: {active_users}")

        for user_id in active_users:
            try:
                success, review_text, path = await review_engine.run_daily_review(user_id=user_id)
                if success:
                    msg = f"🌙 【每晚深度复盘与认知镜像】\n\n{review_text}"
                    await self._send_to_user(user_id, msg)
                else:
                    logger.info(f"用户 {user_id} 每日复盘跳过: {review_text}")
            except Exception as e:
                logger.exception(f"用户 {user_id} 每日复盘异常: {e}")

    async def scheduled_weekly_review(self):
        logger.info("执行定时周度战略复盘 (多用户)...")
        active_users = user_config_manager.list_active_users()

        for user_id in active_users:
            try:
                success, weekly_text, path = await review_engine.run_weekly_review(user_id=user_id)
                if success:
                    msg = f"📊 【周日战略复盘与长期画像更新】\n\n{weekly_text}"
                    await self._send_to_user(user_id, msg)
                else:
                    logger.info(f"用户 {user_id} 周复盘跳过: {weekly_text}")
            except Exception as e:
                logger.exception(f"用户 {user_id} 周复盘异常: {e}")

    def start(self):
        # Daily review trigger
        daily_hour, daily_min = map(int, settings.DAILY_REVIEW_TIME.split(":"))
        self.scheduler.add_job(
            self.scheduled_daily_review,
            CronTrigger(hour=daily_hour, minute=daily_min, timezone=settings.TIMEZONE),
            id="daily_review_job",
            replace_existing=True
        )

        # Weekly review trigger
        weekly_hour, weekly_min = map(int, settings.WEEKLY_REVIEW_TIME.split(":"))
        self.scheduler.add_job(
            self.scheduled_weekly_review,
            CronTrigger(
                day_of_week=settings.WEEKLY_REVIEW_DAY,
                hour=weekly_hour,
                minute=weekly_min,
                timezone=settings.TIMEZONE
            ),
            id="weekly_review_job",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(
            f"定时调度已启动: 每日复盘={settings.DAILY_REVIEW_TIME}, "
            f"周度复盘={settings.WEEKLY_REVIEW_DAY} {settings.WEEKLY_REVIEW_TIME}"
        )

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
