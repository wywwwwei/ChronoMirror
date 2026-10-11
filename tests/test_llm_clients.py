"""回归测试：LLM 客户端必须按 Key 复用，且在停机时被关闭。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import unittest

from core.llm_service import LLMService
from core.user_config import UserConfig


class _FakeAsyncClient:
    """冒充 AsyncOpenAI：记录自身是否被关闭"""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        _FakeAsyncClient.instances.append(self)

    async def close(self):
        self.closed = True


class ClientReuseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _FakeAsyncClient.instances = []
        self.service = LLMService()

    def _cfg(self, **kwargs) -> UserConfig:
        return UserConfig(user_id=1, **kwargs)

    async def _openai_client(self, cfg):
        """绕开真实 SDK：直接调用内部工厂并注入假实现"""
        import openai

        original = openai.AsyncOpenAI
        openai.AsyncOpenAI = _FakeAsyncClient
        try:
            return await self.service._get_openai_client(cfg)
        finally:
            openai.AsyncOpenAI = original

    async def test_same_key_reuses_one_client(self):
        cfg = self._cfg(active_provider="openai", openai_api_key="sk-a")
        first = await self._openai_client(cfg)
        second = await self._openai_client(cfg)
        self.assertIs(first, second)
        self.assertEqual(len(_FakeAsyncClient.instances), 1)

    async def test_different_keys_get_different_clients(self):
        a = await self._openai_client(self._cfg(active_provider="openai", openai_api_key="sk-a"))
        b = await self._openai_client(self._cfg(active_provider="openai", openai_api_key="sk-b"))
        self.assertIsNot(a, b)
        self.assertEqual(len(_FakeAsyncClient.instances), 2)

    async def test_different_base_urls_get_different_clients(self):
        a = await self._openai_client(
            self._cfg(active_provider="openai", openai_api_key="sk-a", openai_base_url="https://a/v1")
        )
        b = await self._openai_client(
            self._cfg(active_provider="openai", openai_api_key="sk-a", openai_base_url="https://b/v1")
        )
        self.assertIsNot(a, b)

    async def test_aclose_closes_everything_and_clears_cache(self):
        cfg = self._cfg(active_provider="openai", openai_api_key="sk-a")
        client = await self._openai_client(cfg)
        await self.service.aclose()

        self.assertTrue(client.closed)
        self.assertEqual(self.service._openai_clients, {})
        # 关闭后再次请求应当重新建立，而不是拿到已关闭的客户端
        again = await self._openai_client(cfg)
        self.assertIsNot(again, client)

    async def test_missing_key_raises(self):
        with self.assertRaises(ValueError):
            await self.service._get_openai_client(self._cfg(active_provider="openai"))
        with self.assertRaises(ValueError):
            await self.service._get_gemini_client(self._cfg(active_provider="gemini"))

    async def test_cache_is_bounded(self):
        import core.llm_service as module

        previous = module.MAX_CACHED_CLIENTS
        module.MAX_CACHED_CLIENTS = 3
        try:
            for i in range(5):
                await self._openai_client(
                    self._cfg(active_provider="openai", openai_api_key=f"sk-{i}")
                )
            self.assertEqual(len(self.service._openai_clients), 3)
            # 被淘汰的必须真的关掉，不能只是从字典里删掉
            evicted = _FakeAsyncClient.instances[:2]
            self.assertTrue(all(c.closed for c in evicted), "被淘汰的客户端没有被关闭")
        finally:
            module.MAX_CACHED_CLIENTS = previous


if __name__ == "__main__":
    unittest.main()
