"""回归测试：TIMEZONE 必须是全项目唯一的时间来源。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import datetime
import re
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import Settings
from core import storage as storage_module
from core.review_engine import ReviewEngine
from core.scheduler import ReviewScheduler


class TimezoneSourceTests(unittest.TestCase):
    def test_now_and_today_use_configured_timezone(self):
        s = Settings(_env_file=None, TIMEZONE="Asia/Shanghai")
        now = s.now()
        self.assertEqual(now.tzinfo, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(s.today(), now.date())

    def test_utc_and_shanghai_can_differ(self):
        shanghai = Settings(_env_file=None, TIMEZONE="Asia/Shanghai")
        utc = Settings(_env_file=None, TIMEZONE="UTC")
        self.assertEqual(
            (shanghai.now().utcoffset() - utc.now().utcoffset()),
            datetime.timedelta(hours=8),
        )

    def test_invalid_timezone_falls_back_instead_of_crashing(self):
        s = Settings(_env_file=None, TIMEZONE="Mars/Olympus")
        self.assertEqual(s.tzinfo, ZoneInfo("Asia/Shanghai"))

    def test_scheduler_uses_the_same_tzinfo(self):
        scheduler = ReviewScheduler()
        self.assertEqual(scheduler.scheduler.timezone, ZoneInfo("Asia/Shanghai"))


class TimezonePropagationTests(unittest.IsolatedAsyncioTestCase):
    """日期必须由 settings 决定，不能悄悄退回宿主机本地时间"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self._original_base = storage_module.storage.users_base_dir
        storage_module.storage.users_base_dir = self.root / "users"

    def tearDown(self):
        storage_module.storage.users_base_dir = self._original_base
        self._tmp.cleanup()

    async def test_log_filename_matches_configured_timezone(self):
        fixed = datetime.datetime(2026, 10, 12, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        path = await storage_module.storage.append_log(user_id=1, content="x", dt=fixed)
        self.assertEqual(path.name, "2026-10-12.md")
        # 时区必须体现在写入的时间戳里，而不是被抹成 naive
        self.assertIn("23:30:00", path.read_text(encoding="utf-8"))

    async def test_attachment_month_matches_configured_timezone(self):
        _, rel = await storage_module.storage.save_attachment(1, b"data", "a.jpg")
        month = Settings(_env_file=None).now().strftime("%Y-%m")
        self.assertTrue(rel.startswith(f"attachments/{month}/"), rel)


class NoNaiveDatetimeTests(unittest.TestCase):
    """静态护栏：源码里不允许再出现裸的 datetime.now()/date.today()"""

    PATTERN = re.compile(r"datetime\.datetime\.now\(\)|datetime\.date\.today\(\)")

    def test_no_naive_datetime_calls_outside_tests(self):
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for folder in ("config", "core", "bot"):
            for py in (root / folder).rglob("*.py"):
                for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                    if self.PATTERN.search(line):
                        offenders.append(f"{py.relative_to(root)}:{lineno}")
        for py in (root / "main.py",):
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if self.PATTERN.search(line):
                    offenders.append(f"main.py:{lineno}")
        self.assertEqual(offenders, [], f"这些位置仍在使用宿主机本地时间: {offenders}")


if __name__ == "__main__":
    unittest.main()
