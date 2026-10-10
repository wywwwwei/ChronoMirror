import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import aiofiles

from config.settings import settings
from core.prompts import DEFAULT_USER_PROFILE

class VaultStorage:
    def __init__(self):
        self.logs_dir = settings.logs_dir
        self.attachments_dir = settings.attachments_dir
        self.daily_reviews_dir = settings.daily_reviews_dir
        self.weekly_reviews_dir = settings.weekly_reviews_dir
        self.memory_dir = settings.memory_dir
        self.user_profile_path = settings.user_profile_path
        self._ensure_init()

    def _ensure_init(self):
        if not self.user_profile_path.exists():
            self.user_profile_path.write_text(DEFAULT_USER_PROFILE, encoding="utf-8")

    async def get_user_profile(self) -> str:
        if not self.user_profile_path.exists():
            return DEFAULT_USER_PROFILE
        async with aiofiles.open(self.user_profile_path, mode="r", encoding="utf-8") as f:
            return await f.read()

    async def save_user_profile(self, content: str):
        async with aiofiles.open(self.user_profile_path, mode="w", encoding="utf-8") as f:
            await f.write(content)

    async def save_attachment(self, file_bytes: bytes, filename: str) -> Tuple[Path, str]:
        """Saves an attachment into vault/attachments/YYYY-MM/filename"""
        month_str = datetime.datetime.now().strftime("%Y-%m")
        target_dir = self.attachments_dir / month_str
        target_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = target_dir / filename
        async with aiofiles.open(target_path, mode="wb") as f:
            await f.write(file_bytes)
        
        # relative path for Markdown reference
        rel_path = f"attachments/{month_str}/{filename}"
        return target_path, rel_path

    async def append_log(
        self,
        content: str,
        tag: str = "记录",
        dt: Optional[datetime.datetime] = None,
        attachment_rel_path: Optional[str] = None
    ) -> Path:
        """Appends an entry to today's log (vault/logs/YYYY-MM-DD.md)"""
        now = dt or datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        week_str = now.strftime("%Y-W%W")
        
        file_path = self.logs_dir / f"{date_str}.md"
        is_new = not file_path.exists()

        entry_lines = []
        if is_new:
            entry_lines.append("---")
            entry_lines.append(f"date: {date_str}")
            entry_lines.append(f"week: {week_str}")
            entry_lines.append("type: daily-log")
            entry_lines.append("status: recording")
            entry_lines.append("---\n")
            entry_lines.append(f"# 📝 时间流日志 ({date_str})\n")

        entry_lines.append(f"## {time_str} [{tag}]")
        if attachment_rel_path:
            if attachment_rel_path.endswith((".jpg", ".jpeg", ".png", ".webp")):
                entry_lines.append(f"![附件]({attachment_rel_path})")
            else:
                entry_lines.append(f"[音频附件]({attachment_rel_path})")
        entry_lines.append(content.strip())
        entry_lines.append("") # empty line separator

        text_to_append = "\n".join(entry_lines) + "\n"
        async with aiofiles.open(file_path, mode="a", encoding="utf-8") as f:
            await f.write(text_to_append)

        return file_path

    async def get_daily_log(self, date_str: str) -> Optional[str]:
        file_path = self.logs_dir / f"{date_str}.md"
        if not file_path.exists():
            return None
        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            return await f.read()

    async def save_daily_review(self, date_str: str, content: str) -> Path:
        file_path = self.daily_reviews_dir / f"{date_str}.md"
        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        return file_path

    async def get_daily_review(self, date_str: str) -> Optional[str]:
        file_path = self.daily_reviews_dir / f"{date_str}.md"
        if not file_path.exists():
            return None
        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            return await f.read()

    async def get_recent_daily_reviews(self, days: int = 7) -> List[Tuple[str, str]]:
        """Returns list of (date_str, content) for the past N days that exist"""
        today = datetime.date.today()
        reviews = []
        for i in range(days - 1, -1, -1):
            d = today - datetime.timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            content = await self.get_daily_review(d_str)
            if content:
                reviews.append((d_str, content))
        return reviews

    async def save_weekly_review(self, week_label: str, content: str) -> Path:
        file_path = self.weekly_reviews_dir / f"{week_label}.md"
        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        return file_path

storage = VaultStorage()
