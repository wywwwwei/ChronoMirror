import asyncio
import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import aiofiles

from config.settings import settings
from core.prompts import DEFAULT_USER_PROFILE

class VaultStorage:
    def __init__(self):
        self.users_base_dir = settings.VAULT_DIR / "users"
        self.users_base_dir.mkdir(parents=True, exist_ok=True)
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None

    def _write_lock(self) -> asyncio.Lock:
        """写锁：串行化本类的所有写操作。

        机器人开了并发处理（见 bot.telegram_bot.MAX_CONCURRENT_UPDATES），多个处理器
        会同时落到同一批文件上，而这里的写入要么是"先判断再写"（append_log 靠
        file_path.exists() 决定要不要补 frontmatter），要么是"整体重写"
        （save_* 用 mode="w"）——两者都不是并发安全的。锁的粒度是整个 VaultStorage：
        单次写入只有几百字节，串行化的代价可以忽略，换来的是不必逐个路径推敲。

        锁按事件循环惰性重建，不在 __init__ 里建一次：storage 是模块级单例
        （文件末尾），而 asyncio.Lock 一旦被某个循环争用就会绑定到它，换一个循环再
        acquire 会直接抛 "bound to a different event loop"。线上只有一个循环，
        但测试里每个 IsolatedAsyncioTestCase 方法各起一个循环，所以必须重新建。
        """
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    @staticmethod
    def _safe_file_path(directory: Path, name: str, suffix: str) -> Path:
        """把外部来源的 name 拼成文件名时的兜底防线。

        name 可能来自 Telegram 指令（如 /review 2026-10-10），其中可能包含
        "../" 或绝对路径。上游已经做了格式校验，这里再做一次物理包含性检查：
        解析后的真实路径必须仍在目标目录内，否则拒绝。
        """
        base = directory.resolve()
        candidate = (base / f"{name}{suffix}").resolve()
        if not candidate.is_relative_to(base):
            raise ValueError(f"非法的文件名参数: {name!r}")
        return candidate

    def get_user_dir(self, user_id: int) -> Path:
        d = self.users_base_dir / str(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_logs_dir(self, user_id: int) -> Path:
        d = self.get_user_dir(user_id) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_attachments_dir(self, user_id: int) -> Path:
        d = self.get_user_dir(user_id) / "attachments"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_daily_reviews_dir(self, user_id: int) -> Path:
        d = self.get_user_dir(user_id) / "reviews" / "daily"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_weekly_reviews_dir(self, user_id: int) -> Path:
        d = self.get_user_dir(user_id) / "reviews" / "weekly"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_profile_path(self, user_id: int) -> Path:
        d = self.get_user_dir(user_id) / "memory"
        d.mkdir(parents=True, exist_ok=True)
        return d / "user_profile.md"

    async def get_user_profile(self, user_id: int) -> str:
        profile_path = self.get_user_profile_path(user_id)
        if not profile_path.exists():
            profile_path.write_text(DEFAULT_USER_PROFILE, encoding="utf-8")
            return DEFAULT_USER_PROFILE
        async with aiofiles.open(profile_path, mode="r", encoding="utf-8") as f:
            return await f.read()

    async def save_user_profile(self, user_id: int, content: str):
        profile_path = self.get_user_profile_path(user_id)
        async with self._write_lock():
            async with aiofiles.open(profile_path, mode="w", encoding="utf-8") as f:
                await f.write(content)

    @staticmethod
    def _dedupe(directory: Path, filename: str) -> Tuple[Path, str]:
        """给 filename 找一个当前不存在的名字，重名时在扩展名前插 _1、_2 …

        调用方只把文件名精确到秒（voice_20261012_013225.ogg），同一秒内来的两个
        附件会算出同一个名字。开启并发处理后"一口气发两张图"完全可能落在同一秒，
        后写的会把先写的覆盖掉——用户看到的就是照片凭空少了一张。这里做一次去重。
        """
        stem, suffix = Path(filename).stem, Path(filename).suffix
        candidate = filename
        index = 0
        while (directory / candidate).exists():
            index += 1
            candidate = f"{stem}_{index}{suffix}"
        return directory / candidate, candidate

    async def save_attachment(self, user_id: int, file_bytes: bytes, filename: str) -> Tuple[Path, str]:
        """Saves an attachment into vault/users/<user_id>/attachments/YYYY-MM/filename"""
        month_str = settings.now().strftime("%Y-%m")
        target_dir = self.get_user_attachments_dir(user_id) / month_str
        target_dir.mkdir(parents=True, exist_ok=True)

        # 去重和写入必须在同一个临界区里，否则两个并发任务可以同时判定"这个名字没被占用"
        async with self._write_lock():
            target_path, filename = self._dedupe(target_dir, filename)
            async with aiofiles.open(target_path, mode="wb") as f:
                await f.write(file_bytes)

        # 返回去重后的名字：调用方拿它拼 Markdown 引用，用原名字会指向错的附件
        rel_path = f"attachments/{month_str}/{filename}"
        return target_path, rel_path

    async def append_log(
        self,
        user_id: int,
        content: str,
        tag: str = "记录",
        dt: Optional[datetime.datetime] = None,
        attachment_rel_path: Optional[str] = None
    ) -> Path:
        """Appends an entry to today's log (vault/users/<user_id>/logs/YYYY-MM-DD.md)"""
        now = dt or settings.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        week_str = now.strftime("%Y-W%W")

        logs_dir = self.get_user_logs_dir(user_id)
        file_path = self._safe_file_path(logs_dir, date_str, ".md")

        # "文件还不存在"决定要不要补 frontmatter，这是典型的读-改-写：判断和追加
        # 必须在同一个临界区里，否则并发下当天头两条会同时认定自己是首条，
        # 各写一份 frontmatter 和一级标题。
        async with self._write_lock():
            is_new = not file_path.exists()

            entry_lines = []
            if is_new:
                entry_lines.append("---")
                entry_lines.append(f"user_id: {user_id}")
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
            entry_lines.append("")

            text_to_append = "\n".join(entry_lines) + "\n"
            async with aiofiles.open(file_path, mode="a", encoding="utf-8") as f:
                await f.write(text_to_append)

        return file_path

    async def get_daily_log(self, user_id: int, date_str: str) -> Optional[str]:
        try:
            file_path = self._safe_file_path(self.get_user_logs_dir(user_id), date_str, ".md")
        except ValueError:
            return None
        if not file_path.exists():
            return None
        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            return await f.read()

    async def save_daily_review(self, user_id: int, date_str: str, content: str) -> Path:
        file_path = self._safe_file_path(self.get_user_daily_reviews_dir(user_id), date_str, ".md")
        async with self._write_lock():
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(content)
        return file_path

    async def get_daily_review(self, user_id: int, date_str: str) -> Optional[str]:
        try:
            file_path = self._safe_file_path(self.get_user_daily_reviews_dir(user_id), date_str, ".md")
        except ValueError:
            return None
        if not file_path.exists():
            return None
        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            return await f.read()

    async def get_recent_daily_reviews(self, user_id: int, days: int = 7) -> List[Tuple[str, str]]:
        today = settings.today()
        reviews = []
        for i in range(days - 1, -1, -1):
            d = today - datetime.timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            content = await self.get_daily_review(user_id, d_str)
            if content:
                reviews.append((d_str, content))
        return reviews

    async def save_weekly_review(self, user_id: int, week_label: str, content: str) -> Path:
        file_path = self._safe_file_path(self.get_user_weekly_reviews_dir(user_id), week_label, ".md")
        async with self._write_lock():
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(content)
        return file_path

storage = VaultStorage()
