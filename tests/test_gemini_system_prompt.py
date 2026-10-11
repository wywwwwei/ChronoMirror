"""回归测试：Gemini 的 system prompt 必须走 system_instruction，
不能塞进 contents 当普通 user 消息。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import unittest

from core.llm_service import LLMService
from core.user_config import UserConfig


class _FakeModels:
    def __init__(self, text="analysis done"):
        self.calls = []
        self._text = text

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)

        class _Resp:
            pass

        resp = _Resp()
        resp.text = self._text
        return resp


class _FakeAio:
    def __init__(self, models):
        self.models = models


class _FakeGeminiClient:
    def __init__(self, models):
        self.aio = _FakeAio(models)


class GeminiSystemInstructionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = LLMService()
        self.models = _FakeModels()
        self.client = _FakeGeminiClient(self.models)
        self.cfg = UserConfig(user_id=1, active_provider="gemini", gemini_api_key="k")

    async def test_system_prompt_goes_to_config(self):
        await self.service._call_gemini_with_retry(
            client=self.client,
            model="m",
            contents="user body",
            system_instruction="you are a mirror",
        )
        call = self.models.calls[-1]
        self.assertEqual(call["contents"], "user body")
        self.assertIsNotNone(call["config"], "system_instruction 没有通过 config 传递")
        self.assertEqual(call["config"].system_instruction, "you are a mirror")

    async def test_no_system_prompt_means_no_config(self):
        await self.service._call_gemini_with_retry(
            client=self.client, model="m", contents=[b"part", "prompt"]
        )
        self.assertIsNone(self.models.calls[-1]["config"])

    async def test_daily_review_puts_system_prompt_in_config(self):
        import core.llm_service as module

        async def _fake_client(cfg):
            return self.client

        original = self.service._get_gemini_client
        self.service._get_gemini_client = _fake_client
        try:
            await self.service.generate_daily_review(
                date_str="2026-10-12",
                log_content="log",
                profile_content="profile",
                user_config=self.cfg,
            )
        finally:
            self.service._get_gemini_client = original

        call = self.models.calls[-1]
        self.assertNotIsInstance(call["contents"], list, "system prompt 又被塞回 contents 里了")
        self.assertEqual(call["config"].system_instruction, module.DAILY_REVIEW_SYSTEM_PROMPT.format(date="2026-10-12"))

    async def test_memory_update_puts_system_prompt_in_config(self):
        import core.llm_service as module

        async def _fake_client(cfg):
            return self.client

        original = self.service._get_gemini_client
        self.service._get_gemini_client = _fake_client
        try:
            await self.service.evolve_memory(
                recent_reviews_text="reviews",
                current_profile="profile",
                user_config=self.cfg,
            )
        finally:
            self.service._get_gemini_client = original

        self.assertEqual(
            self.models.calls[-1]["config"].system_instruction,
            module.MEMORY_UPDATE_SYSTEM_PROMPT,
        )

    async def test_image_and_audio_paths_stay_on_user_role(self):
        """视觉与转写的提示词是任务说明，不是 system，保持原样"""

        async def _fake_client(cfg):
            return self.client

        original = self.service._get_gemini_client
        self.service._get_gemini_client = _fake_client
        try:
            await self.service.describe_image(
                image_bytes=b"\x89PNG", user_config=self.cfg, mime_type="image/png"
            )
        finally:
            self.service._get_gemini_client = original

        call = self.models.calls[-1]
        self.assertIsNone(call["config"])
        self.assertEqual(len(call["contents"]), 2)


if __name__ == "__main__":
    unittest.main()
