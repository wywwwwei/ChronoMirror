"""回归测试：重试策略必须对 Gemini 与 OpenAI 对称。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import asyncio
import unittest

import core.llm_service as llm_module
from core.llm_service import LLMService, is_retryable_error


class _StatusError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class RetryClassificationTests(unittest.TestCase):
    def test_transient_status_codes_are_retryable(self):
        for code in (408, 409, 425, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.assertTrue(is_retryable_error(_StatusError("x", status_code=code)))

    def test_client_errors_are_not_retryable(self):
        for code in (400, 401, 403, 404, 422):
            with self.subTest(code=code):
                self.assertFalse(is_retryable_error(_StatusError("x", status_code=code)))

    def test_status_found_on_nested_response(self):
        class _Resp:
            status_code = 503

        err = Exception("x")
        err.response = _Resp()
        self.assertTrue(is_retryable_error(err))

    def test_text_fallback_covers_both_sdks(self):
        # Gemini 风格
        self.assertTrue(is_retryable_error(Exception("503 UNAVAILABLE. overloaded")))
        self.assertTrue(is_retryable_error(Exception("429 RESOURCE_EXHAUSTED")))
        # OpenAI 风格
        self.assertTrue(is_retryable_error(Exception("Rate limit reached for gpt-4o-mini")))
        self.assertTrue(is_retryable_error(Exception("Request timed out.")))
        self.assertTrue(is_retryable_error(Exception("Connection error.")))

    def test_bad_key_is_never_retryable(self):
        self.assertFalse(is_retryable_error(Exception("Incorrect API key provided: sk-xxx")))
        self.assertFalse(is_retryable_error(Exception("Model Not Exist")))


class _FlakyClient:
    """前 N 次抛可重试错误，之后成功"""

    def __init__(self, failures, error):
        self.failures = failures
        self.error = error
        self.calls = 0

    async def call(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return f"ok-after-{self.calls}"


class RetryBehaviourTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = LLMService()
        self._original_backoff = llm_module.BASE_BACKOFF_SECONDS
        llm_module.BASE_BACKOFF_SECONDS = 0.0  # 测试不要真的等
        self._original_retries = llm_module.MAX_RETRIES

    def tearDown(self):
        llm_module.BASE_BACKOFF_SECONDS = self._original_backoff
        llm_module.MAX_RETRIES = self._original_retries

    async def test_retries_transient_failure_then_succeeds(self):
        client = _FlakyClient(failures=2, error=_StatusError("503", status_code=503))
        result = await self.service._with_retry("test", client.call)
        self.assertEqual(result, "ok-after-3")
        self.assertEqual(client.calls, 3)

    async def test_gives_up_after_max_retries(self):
        client = _FlakyClient(failures=99, error=_StatusError("503", status_code=503))
        with self.assertRaises(_StatusError):
            await self.service._with_retry("test", client.call)
        self.assertEqual(client.calls, llm_module.MAX_RETRIES)

    async def test_non_retryable_fails_fast(self):
        client = _FlakyClient(failures=99, error=_StatusError("401", status_code=401))
        with self.assertRaises(_StatusError):
            await self.service._with_retry("test", client.call)
        self.assertEqual(client.calls, 1, "不可恢复的错误不该重试")

    async def test_openai_completion_path_is_retried(self):
        """这是本次修复的核心：OpenAI 分支之前完全没有重试"""
        calls = {"n": 0}

        class _Completions:
            async def create(self, **kwargs):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise _StatusError("429 rate limit", status_code=429)

                class _Msg:
                    content = "done"

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()
            audio = None

        result = await self.service._with_retry(
            "OpenAI/test",
            lambda: self.service._openai_complete(
                _Client(), model="m", messages=[{"role": "user", "content": "hi"}]
            ),
        )
        self.assertEqual(result, "done")
        self.assertEqual(calls["n"], 3)

    async def test_backoff_grows_exponentially(self):
        delays = []
        original_sleep = asyncio.sleep

        async def _fake_sleep(seconds):
            delays.append(seconds)
            await original_sleep(0)

        llm_module.asyncio.sleep = _fake_sleep
        llm_module.BASE_BACKOFF_SECONDS = 1.0
        try:
            client = _FlakyClient(failures=99, error=_StatusError("503", status_code=503))
            with self.assertRaises(_StatusError):
                await self.service._with_retry("test", client.call, retries=4)
        finally:
            llm_module.asyncio.sleep = original_sleep

        self.assertEqual(delays, [1.0, 2.0, 4.0])


if __name__ == "__main__":
    unittest.main()
