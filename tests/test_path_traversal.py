"""回归测试：外部传入的日期参数不能逃出 vault 目录。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import tempfile
import unittest
from pathlib import Path

from core import storage as storage_module
from core.review_engine import ReviewEngine


class DateValidationTests(unittest.TestCase):
    """/review <date> 的入参必须无法逃出 vault 目录"""

    def test_accepts_valid_date(self):
        self.assertEqual(ReviewEngine.normalize_target_date("2026-10-10"), ("2026-10-10", None))
        self.assertEqual(ReviewEngine.normalize_target_date(None), (None, None))
        self.assertEqual(ReviewEngine.normalize_target_date("  "), (None, None))

    def test_rejects_path_traversal(self):
        for payload in (
            "../../../../README",
            "../../1/reviews/daily/2026-10-10",
            "..",
            "/etc/passwd",
            "2026-10-10/../../x",
            "2026-10-10\n..",
        ):
            with self.subTest(payload=payload):
                date_str, error = ReviewEngine.normalize_target_date(payload)
                self.assertIsNone(date_str)
                self.assertIsNotNone(error)

    def test_rejects_malformed_dates(self):
        for payload in ("2026/10/10", "20261010", "2026-10-10-1", "today", "2026-13-45"):
            with self.subTest(payload=payload):
                date_str, error = ReviewEngine.normalize_target_date(payload)
                self.assertIsNone(date_str)
                self.assertIsNotNone(error)


class StorageContainmentTests(unittest.IsolatedAsyncioTestCase):
    """存储层兜底：即使有人绕过日期校验，也不能读写目标目录之外的文件"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self._original_base = storage_module.storage.users_base_dir
        storage_module.storage.users_base_dir = self.root / "users"

        # vault 之外的“敏感文件”，任何越权写入都必须失败
        self.outside = self.root / "README.md"
        self.outside.write_text("SENSITIVE", encoding="utf-8")

    def tearDown(self):
        storage_module.storage.users_base_dir = self._original_base
        self._tmp.cleanup()

    async def test_read_outside_returns_none(self):
        self.assertIsNone(await storage_module.storage.get_daily_log(1, "../../../README"))

    async def test_write_outside_is_rejected(self):
        with self.assertRaises(ValueError):
            await storage_module.storage.save_daily_review(1, "../../../README", "pwned")
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "SENSITIVE")

    async def test_cross_user_write_is_rejected(self):
        victim_dir = self.root / "users" / "2" / "reviews" / "daily"
        victim_dir.mkdir(parents=True)
        victim_file = victim_dir / "2026-10-10.md"
        victim_file.write_text("victim's review", encoding="utf-8")

        with self.assertRaises(ValueError):
            await storage_module.storage.save_daily_review(
                1, "../../2/reviews/daily/2026-10-10", "overwritten"
            )
        self.assertEqual(victim_file.read_text(encoding="utf-8"), "victim's review")

    async def test_normal_paths_still_work(self):
        await storage_module.storage.append_log(user_id=1, content="hello", tag="测试")
        logs = list((self.root / "users" / "1" / "logs").glob("*.md"))
        self.assertEqual(len(logs), 1)
        self.assertIn("hello", logs[0].read_text(encoding="utf-8"))

        await storage_module.storage.save_daily_review(1, "2026-10-10", "review body")
        saved = self.root / "users" / "1" / "reviews" / "daily" / "2026-10-10.md"
        self.assertEqual(saved.read_text(encoding="utf-8"), "review body")
        self.assertEqual(await storage_module.storage.get_daily_review(1, "2026-10-10"), "review body")


if __name__ == "__main__":
    unittest.main()
