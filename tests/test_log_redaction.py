"""回归测试：日志里绝不能出现明文令牌。

httpx 把完整请求 URL 打进 INFO 日志，而 Telegram 的 URL 是
`https://api.telegram.org/bot<数字>:<令牌>/getUpdates`。README 教的
`docker compose logs -f` 会把它打出来，容器日志又常被收集器长期留存。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import logging
import sys
import unittest

from core.llm_errors import RedactingFormatter, redact_secrets

# 形状与真实令牌一致（10 位数字 + 35 位字符），但内容完全是假的
FAKE_TOKEN = "1234567890:AAHfakeTokenValueForTestsOnly12345"


class RedactSecretsTests(unittest.TestCase):
    def test_redacts_token_inside_a_url(self):
        """令牌只会以 URL 的形式泄露，所以这条是重点。

        历史坑：这个 pattern 原本带前导 \\b，而 URL 里令牌紧跟在 "bot" 后面
        （"t" 和数字之间没有词边界），导致它在唯一真正会泄露的形态上从来没生效过。
        """
        line = f"POST https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates"
        out = redact_secrets(line)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertIn("[REDACTED]", out)
        # URL 骨架要保留，否则排查问题时看不出打的是哪个接口
        self.assertIn("api.telegram.org", out)
        self.assertIn("getUpdates", out)

    def test_redacts_bare_token(self):
        self.assertNotIn(FAKE_TOKEN, redact_secrets(f"token={FAKE_TOKEN}"))

    def test_redacts_provider_keys(self):
        for payload in (
            "Incorrect API key provided: sk-proj-abcdefghijklmnop",
            "请求失败: https://generativelanguage.googleapis.com/v1?key=AIzaSyDabcdefghijklmn",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9",
        ):
            with self.subTest(payload=payload):
                self.assertIn("[REDACTED]", redact_secrets(payload))

    def test_leaves_ordinary_log_lines_alone(self):
        """别把时间戳、用户 ID 这类正常内容当成令牌抹掉"""
        for line in (
            "[daily-review] user=6068039554 生成完成，用时 12.3s",
            "2026-10-12 01:05:58,151 - core.scheduler - INFO - 定时调度已启动",
            "每日复盘=23:00, 周度复盘=sun 22:00",
            "记录时间 04:34:48",
        ):
            with self.subTest(line=line):
                self.assertEqual(redact_secrets(line), line)

    def test_empty_input(self):
        self.assertEqual(redact_secrets(""), "")


class RedactingFormatterTests(unittest.TestCase):
    """护栏加在 Formatter 层：漏掉任何一个调用点都等于没做"""

    FORMAT = "%(name)s - %(levelname)s - %(message)s"

    def _record(self, msg, args=(), exc_info=None, name="httpx", level=logging.INFO):
        return logging.LogRecord(
            name=name, level=level, pathname=__file__, lineno=1,
            msg=msg, args=args, exc_info=exc_info,
        )

    def test_strips_token_from_message(self):
        out = RedactingFormatter(self.FORMAT).format(
            self._record(f"HTTP Request: POST https://api.telegram.org/bot{FAKE_TOKEN}/getMe")
        )
        self.assertNotIn(FAKE_TOKEN, out)

    def test_strips_token_from_lazy_args(self):
        """logger.info("...%s", url) 的惰性格式化同样要覆盖"""
        out = RedactingFormatter(self.FORMAT).format(
            self._record("HTTP Request: POST %s", (f"https://api.telegram.org/bot{FAKE_TOKEN}/getMe",))
        )
        self.assertNotIn(FAKE_TOKEN, out)

    def test_strips_token_from_traceback(self):
        """TelegramError 的报文里也带着同一个 URL，堆栈会把它渲染出来"""
        try:
            raise RuntimeError(f"Bad Request: https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates")
        except RuntimeError:
            record = self._record(
                "polling failed", exc_info=sys.exc_info(), name="telegram.ext", level=logging.ERROR
            )

        out = RedactingFormatter(self.FORMAT).format(record)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertIn("[REDACTED]", out)


if __name__ == "__main__":
    unittest.main()
