"""回归测试：给用户看的错误提示不能包含供应商原文，更不能带出 API Key。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import re
import unittest

from core.llm_errors import describe_llm_error, redact_secrets

OPENAI_BAD_KEY = (
    "Error code: 401 - {'error': {'message': 'Incorrect API key provided: "
    "sk-proj-AbCdEf1234567890. You can find your API key at https://platform.openai.com/account/api-keys.',"
    " 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}"
)
GEMINI_BAD_KEY = (
    "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid. "
    "Please pass a valid API key.', 'status': 'INVALID_ARGUMENT'}}"
)
GEMINI_KEY_IN_URL = (
    "ClientError: 400 Bad Request for url: "
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key=AIzaSyD-EXAMPLEKEY1234567890"
)


class _StatusError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class DescribeErrorTests(unittest.TestCase):
    """无论哪种异常，输出都必须不含密钥、不含供应商原文"""

    CASES = (
        (Exception(OPENAI_BAD_KEY), "重新绑定"),
        (Exception(GEMINI_BAD_KEY), "重新绑定"),
        (Exception(GEMINI_KEY_IN_URL), "重新绑定"),
    )

    def test_never_leaks_key_material(self):
        for err, _ in self.CASES:
            with self.subTest(err=str(err)[:40]):
                message = describe_llm_error(err)
                self.assertNotIn("sk-", message)
                self.assertNotIn("AIza", message)
                self.assertNotIn("api_key", message.lower().replace("/setkey", ""))

    def test_never_echoes_provider_text(self):
        for err, _ in self.CASES:
            with self.subTest(err=str(err)[:40]):
                message = describe_llm_error(err)
                for fragment in ("Incorrect API key provided", "INVALID_ARGUMENT", "generativelanguage.googleapis.com"):
                    self.assertNotIn(fragment, message)

    def test_messages_are_actionable(self):
        for err, expectation in self.CASES:
            self.assertIn(expectation, describe_llm_error(err))

    def test_status_code_rules(self):
        self.assertIn("额度", describe_llm_error(_StatusError("x", status_code=402)))
        self.assertIn("模型名", describe_llm_error(_StatusError("x", status_code=404)))
        self.assertIn("频繁", describe_llm_error(_StatusError("x", status_code=429)))
        self.assertIn("临时故障", describe_llm_error(_StatusError("x", status_code=503)))
        self.assertIn("Key", describe_llm_error(_StatusError("x", status_code=401)))

    def test_text_rules(self):
        self.assertIn("模型名", describe_llm_error(Exception("The model `gpt-4o` does not exist")))
        self.assertIn("额度", describe_llm_error(Exception("You exceeded your current quota")))
        self.assertIn("安全策略", describe_llm_error(Exception("Blocked by safety settings")))
        self.assertIn("连接", describe_llm_error(Exception("Request timed out.")))

    def test_unknown_error_is_generic(self):
        message = describe_llm_error(Exception("kaboom"))
        self.assertIn("失败", message)
        self.assertNotIn("kaboom", message)


class RedactSecretsTests(unittest.TestCase):
    def test_redacts_known_key_shapes(self):
        cases = (
            ("key is sk-proj-AbCdEf1234567890", "sk-proj"),
            ("AIzaSyD-EXAMPLEKEY1234567890", "AIza"),
            ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc", "eyJhbGci"),
            ('{"api_key": "abcdef1234567890"}', "abcdef1234567890"),
            ("?key=AIzaSyD-EXAMPLEKEY1234567890", "AIzaSyD-EX"),
            ("token 1234567890:AAF-abcdefghijklmnopqrstuvwxyz12345", "AAF-abc"),
        )
        for raw, secret in cases:
            with self.subTest(raw=raw[:30]):
                cleaned = redact_secrets(raw)
                self.assertNotIn(secret, cleaned)
                self.assertIn("[REDACTED]", cleaned)

    def test_keeps_harmless_text(self):
        text = "model gpt-4o-mini returned 429 after 3 attempts"
        self.assertEqual(redact_secrets(text), text)

    def test_handles_empty(self):
        self.assertEqual(redact_secrets(""), "")


class NoRawErrorEchoTests(unittest.TestCase):
    """静态护栏：不许再把 {str(e)} / {e} 直接拼进用户可见的字符串"""

    PATTERN = re.compile(r"(?:edit_text|reply_text|send_message)\(")

    def test_no_dynamic_exception_interpolation_in_user_facing_calls(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        offenders = []
        for folder in ("config", "core", "bot"):
            for py in (root / folder).rglob("*.py"):
                for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if re.search(r"\{str\(e\)\}|\{e\}|\{exc\}", line) and "logger" not in line \
                            and "redact_secrets" not in line and "describe_llm_error" not in line:
                        rel = f"{py.relative_to(root)}:{lineno}"
                        if py.name == "llm_errors.py":
                            continue
                        offenders.append(f"{rel}: {stripped[:80]}")
        self.assertEqual(offenders, [], f"这些位置仍在回吐异常原文: {offenders}")


class _FailingGemini:
    """让 generate_daily_review 抛出带 Key 的鉴权错误"""

    async def generate_daily_review(self, **kwargs):
        raise _StatusError(OPENAI_BAD_KEY, status_code=401)


class ReviewEngineErrorTests(unittest.IsolatedAsyncioTestCase):
    """端到端：复盘失败时返回给用户的文本里不能有 Key"""

    async def test_daily_review_failure_message_is_sanitized(self):
        import core.review_engine as module
        from core.review_engine import ReviewEngine
        from core.user_config import UserConfig

        class _Storage:
            async def get_daily_log(self, user_id, date_str):
                return "今天发生了很多事情"

            async def get_user_profile(self, user_id):
                return "profile"

        class _Manager:
            @staticmethod
            def resolve_config(user_id):
                return UserConfig(user_id=user_id, active_provider="openai", openai_api_key="sk-user")

        originals = (module.llm, module.storage, module.user_config_manager)
        module.llm, module.storage, module.user_config_manager = _FailingGemini(), _Storage(), _Manager
        try:
            success, message, path = await ReviewEngine().run_daily_review(1, "2026-10-12")
        finally:
            module.llm, module.storage, module.user_config_manager = originals

        self.assertFalse(success)
        self.assertIsNone(path)
        self.assertNotIn("sk-", message)
        self.assertNotIn("Incorrect API key", message)
        self.assertIn("重新绑定", message)


if __name__ == "__main__":
    unittest.main()
