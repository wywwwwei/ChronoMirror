"""回归测试：异常必须原样冒泡，不能被 raise e 污染 traceback。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import unittest

from core.llm_service import LLMService


class _ExplodingModels:
    async def generate_content(self, **kwargs):
        raise RuntimeError("boom-from-sdk")


class _ExplodingAio:
    models = _ExplodingModels()


class _FakeGeminiClient:
    aio = _ExplodingAio()


def _frames(exc):
    tb, out = exc.__traceback__, []
    while tb is not None:
        out.append(tb.tb_frame.f_code.co_name)
        tb = tb.tb_next
    return out


class TracebackPreservationTests(unittest.IsolatedAsyncioTestCase):
    """`raise e` 会在 traceback 里多插一条指向 raise 语句自身的帧，
    真正的出错位置反而被淹没；裸 `raise` 只保留原始调用链。"""

    async def test_exception_type_and_message_survive(self):
        service = LLMService()
        with self.assertRaises(RuntimeError) as ctx:
            await service._call_gemini_with_retry(
                client=_FakeGeminiClient(), model="m", contents="c", retries=1
            )
        self.assertEqual(str(ctx.exception), "boom-from-sdk")

    async def test_traceback_has_no_duplicate_frame(self):
        service = LLMService()
        try:
            await service._call_gemini_with_retry(
                client=_FakeGeminiClient(), model="m", contents="c", retries=1
            )
        except RuntimeError as exc:
            names = _frames(exc)
        else:
            self.fail("预期抛出 RuntimeError")

        # 原始出错点必须在
        self.assertIn("generate_content", names)
        # 重试函数自身只能出现一次；`raise e` 会让它出现两次
        self.assertEqual(
            names.count("_call_gemini_with_retry"), 1,
            f"traceback 被污染，出现重复帧: {names}",
        )


if __name__ == "__main__":
    unittest.main()
