"""回归测试：运行日志要落盘、要轮转、要脱敏，且不能挡住启动。

此前只有 StreamHandler，日志只存在于 stdout。容器里能不能翻到旧日志完全取决于
docker 日志驱动策略，而且 bot/telegram_bot.py 里那些带 update_id 的行如果不落盘，
"哪条消息被吞了"事后依然查不到。这里钉住四件事：目录会自己建、按大小轮转、
脱敏对文件同样生效、目录不可写时降级而不是崩溃。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.settings import settings
from core import runtime_logging

# 形状与真实令牌一致（10 位数字 + 35 位字符），但内容完全是假的
FAKE_TOKEN = "1234567890:AAHfakeTokenValueForTestsOnly12345"


class FileHandlerTests(unittest.TestCase):
    def test_creates_log_dir_and_returns_rotating_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "logs"
            with mock.patch.object(settings, "LOG_DIR", target):
                handler = runtime_logging.file_handler()
            try:
                self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
                self.assertEqual(Path(handler.baseFilename), target / runtime_logging.LOG_FILE_NAME)
                # 目录不存在时得自己建出来，不能要求部署者先 mkdir
                self.assertTrue(target.is_dir())
                # 必须真的轮转：不轮转的话跑久了就是把磁盘写满
                self.assertEqual(handler.maxBytes, runtime_logging.LOG_FILE_MAX_BYTES)
                self.assertGreater(handler.backupCount, 0)
            finally:
                handler.close()

    def test_degrades_instead_of_raising_when_dir_is_not_writable(self):
        """日志不可写是可观测性问题，不该成为启动前提"""
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocker"
            blocker.write_text("我是文件，不是目录", encoding="utf-8")
            with mock.patch.object(settings, "LOG_DIR", blocker / "logs"):
                self.assertIsNone(runtime_logging.file_handler())

    def test_rotates_when_the_size_limit_is_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            with mock.patch.object(settings, "LOG_DIR", log_dir):
                handler = runtime_logging.file_handler()
            # 把上限压到很小，省得真写满 2MB
            handler.maxBytes = 200
            logger = logging.getLogger("runtime-logging-rotation-probe")
            logger.propagate = False
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)
            try:
                for _ in range(50):
                    logger.info("x" * 40)
            finally:
                logger.removeHandler(handler)
                handler.close()

            names = sorted(p.name for p in log_dir.iterdir())
            self.assertIn(runtime_logging.LOG_FILE_NAME, names)
            self.assertIn(f"{runtime_logging.LOG_FILE_NAME}.1", names, names)


class FileRedactionTests(unittest.TestCase):
    """日志文件比 stdout 活得更久，明文令牌留在里面比一闪而过更糟"""

    def test_secrets_are_redacted_in_the_log_file(self):
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_level = root.level
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            with mock.patch.object(settings, "LOG_DIR", log_dir):
                # basicConfig 在 root 已有 handler 时直接返回，所以先摘干净
                root.handlers.clear()
                try:
                    runtime_logging.configure_logging()
                    logging.getLogger("probe").info(
                        f"POST https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"
                    )
                    for handler in root.handlers:
                        handler.flush()
                    text = (log_dir / runtime_logging.LOG_FILE_NAME).read_text(encoding="utf-8")
                finally:
                    for handler in root.handlers:
                        handler.close()
                    root.handlers[:] = saved_handlers
                    root.setLevel(saved_level)

        self.assertNotIn(FAKE_TOKEN, text)
        self.assertIn("[REDACTED]", text)
        # URL 骨架要留着，否则排查时看不出打的是哪个接口
        self.assertIn("api.telegram.org", text)
        self.assertIn("getUpdates", text)

    def test_startup_line_says_where_the_log_goes(self):
        """启动时要有一行明确告知日志落在哪，否则部署者猜不到去翻哪个文件"""
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_level = root.level
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            with mock.patch.object(settings, "LOG_DIR", log_dir):
                root.handlers.clear()
                try:
                    runtime_logging.configure_logging()
                    for handler in root.handlers:
                        handler.flush()
                    text = (log_dir / runtime_logging.LOG_FILE_NAME).read_text(encoding="utf-8")
                finally:
                    for handler in root.handlers:
                        handler.close()
                    root.handlers[:] = saved_handlers
                    root.setLevel(saved_level)

        self.assertIn(str(log_dir / runtime_logging.LOG_FILE_NAME), text)

    def test_startup_does_not_crash_when_the_log_dir_is_unusable(self):
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_level = root.level
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocker"
            blocker.write_text("我是文件，不是目录", encoding="utf-8")
            with mock.patch.object(settings, "LOG_DIR", blocker / "logs"):
                root.handlers.clear()
                try:
                    runtime_logging.configure_logging()
                    # 降级后仍然要有可用的输出通道
                    self.assertTrue(root.handlers)
                finally:
                    for handler in root.handlers:
                        handler.close()
                    root.handlers[:] = saved_handlers
                    root.setLevel(saved_level)


class LogDirPlacementTests(unittest.TestCase):
    """运行日志不能落在 vault/ 里"""

    def test_default_log_dir_is_outside_the_vault(self):
        """vault/logs 是用户的日记流水账（要给人看、被 Obsidian 索引），
        运行日志是给排障看的、会被轮转删掉。混在一起两边都受干扰。"""
        default_log_dir = type(settings).model_fields["LOG_DIR"].default
        self.assertFalse(
            Path(default_log_dir).is_relative_to(settings.VAULT_DIR),
            f"LOG_DIR={default_log_dir} 落在了 vault 里面",
        )
        self.assertEqual(Path(default_log_dir).name, "logs")
