"""回归测试：消息处理的每一环都要在服务端日志里留痕。

起因是"感觉有时候会吞消息"，但翻日志什么也看不出来——bot/telegram_bot.py
原先 600 多行里只有 3 处 logger 调用，消息收到没有、归档成没成功，一概不可见。
现在入口和归档成功处各留一行、都带 update_id，失败路径也带同一个编号，于是
"吞"在哪一环可以直接判定：两行都有 = 正常；只有入口那行 = 卡在处理中；
两行都没有 = 更新压根没到机器人手里。

同时守住一条隐私底线：日志里只能出现编号和长度，绝不能出现日记正文。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bot import telegram_bot as bot_module
from core.user_config import UserConfig

SECRET_TEXT = "今天跟心理医生聊了复诊的事，加了药"


class _Message:
    def __init__(self, text=None, caption=None, voice=None, photo=None):
        self.text = text
        self.caption = caption
        self.voice = voice
        self.photo = photo
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return self

    async def edit_text(self, text, **kwargs):
        self.replies.append(text)
        return self


def _make_update(update_id=1001, user_id=6068039554, **message_kwargs):
    return SimpleNamespace(
        update_id=update_id,
        effective_user=SimpleNamespace(id=user_id),
        effective_message=_Message(**message_kwargs),
    )


class _RecordingStorage:
    def __init__(self):
        self.appends = []

    async def append_log(self, **kwargs):
        self.appends.append(kwargs)

    async def save_attachment(self, user_id, file_bytes, filename):
        return Path("/dev/null") / filename, f"attachments/2026-10/{filename}"


class _Manager:
    """resolve_config 的替身：key=None 用来模拟"还没 /setkey"的用户"""

    def __init__(self, key="sk-test-key"):
        self._key = key

    def resolve_config(self, user_id):
        if self._key is None:
            return UserConfig(user_id=user_id, active_provider="openai")
        return UserConfig(user_id=user_id, active_provider="openai", openai_api_key=self._key)


class _Voice:
    async def get_file(self):
        return SimpleNamespace(download_as_bytearray=lambda: _abytes())


class _Photo:
    async def get_file(self):
        return SimpleNamespace(download_as_bytearray=lambda: _abytes())


async def _abytes():
    return bytearray(b"fake-bytes")


class _OKLlm:
    async def transcribe_audio(self, **kwargs):
        return "转写出来的内容"

    async def describe_image(self, **kwargs):
        return "照片描述"


class _BoomLlm:
    async def transcribe_audio(self, **kwargs):
        raise RuntimeError("boom sk-live-ABCDEFGHIJKLMNOPQRSTUV")


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from config.settings import settings
        self.settings = settings
        self._orig_allowed = settings.ALLOWED_USER_IDS
        settings.ALLOWED_USER_IDS = "*"

        self._orig = (bot_module.storage, bot_module.llm, bot_module.user_config_manager)
        self.storage = _RecordingStorage()
        bot_module.storage = self.storage
        bot_module.llm = _OKLlm()
        bot_module.user_config_manager = _Manager()

    def tearDown(self):
        bot_module.storage, bot_module.llm, bot_module.user_config_manager = self._orig
        self.settings.ALLOWED_USER_IDS = self._orig_allowed

    def _logs(self):
        return "\n".join(self._cm.output)

    # ── 正常路径：入口和归档成功各一行，都带 update_id ──

    async def test_text_arrival_and_archive_are_both_logged(self):
        with self.assertLogs(level="INFO") as self._cm:
            await bot_module.handle_text(_make_update(update_id=1001, text="随手记一笔"), None)

        logs = self._logs()
        self.assertIn("update=1001 user=6068039554", logs)
        self.assertIn("收到文字", logs)
        self.assertIn("文字已归档", logs)
        self.assertEqual(len(self.storage.appends), 1)

    async def test_voice_arrival_and_archive_are_both_logged(self):
        update = _make_update(update_id=2002, voice=_Voice())
        with self.assertLogs(level="INFO") as self._cm:
            await bot_module.handle_voice(update, None)

        logs = self._logs()
        self.assertIn("update=2002", logs)
        self.assertIn("收到语音", logs)
        self.assertIn("语音已归档", logs)
        # 归档行要带附件路径，方便核对"日志说存了"和"文件真的在"
        self.assertIn("attachments/", logs)
        self.assertEqual(len(self.storage.appends), 1)

    async def test_photo_arrival_and_archive_are_both_logged(self):
        update = _make_update(update_id=3003, photo=[_Photo()])
        with self.assertLogs(level="INFO") as self._cm:
            await bot_module.handle_photo(update, None)

        logs = self._logs()
        self.assertIn("update=3003", logs)
        self.assertIn("收到照片", logs)
        self.assertIn("照片已归档", logs)
        self.assertEqual(len(self.storage.appends), 1)

    # ── 隐私底线：正文不进日志 ──

    async def test_journal_content_never_reaches_the_log(self):
        with self.assertLogs(level="INFO") as self._cm:
            await bot_module.handle_text(_make_update(text=SECRET_TEXT), None)

        logs = self._logs()
        self.assertNotIn(SECRET_TEXT, logs)
        self.assertNotIn("心理医生", logs)
        # 但长度要在，否则仍然分不清"收到的是不是空消息"
        self.assertIn(f"({len(SECRET_TEXT)} 字)", logs)
        # 正文本身当然要照常写进日记
        self.assertEqual(self.storage.appends[0]["content"], SECRET_TEXT)

    # ── 被跳过的消息必须在日志里说得清"被谁跳过了、为什么" ──

    async def test_message_without_a_key_is_logged_as_skipped(self):
        bot_module.user_config_manager = _Manager(key=None)
        with self.assertLogs(level="INFO") as self._cm:
            await bot_module.handle_text(_make_update(update_id=4004, text="记一笔"), None)

        logs = self._logs()
        self.assertIn("update=4004", logs)
        self.assertIn("未绑定有效 Key", logs)
        self.assertIn("跳过", logs)
        # 跳过的消息不能悄悄写进日记
        self.assertEqual(self.storage.appends, [])

    async def test_unauthorized_message_is_logged_at_warning(self):
        self.settings.ALLOWED_USER_IDS = "12345"
        with self.assertLogs(level="WARNING") as self._cm:
            await bot_module.handle_text(_make_update(update_id=5005, user_id=999, text="喂"), None)

        logs = self._logs()
        self.assertIn("update=5005", logs)
        self.assertIn("不在白名单", logs)
        self.assertEqual(self.storage.appends, [])

    # ── 失败路径带同一个 update_id，才好和"收到"那行对上 ──

    async def test_failure_log_carries_the_same_update_id(self):
        bot_module.llm = _BoomLlm()
        update = _make_update(update_id=6006, voice=_Voice())
        with self.assertLogs(level="ERROR") as self._cm:
            await bot_module.handle_voice(update, None)

        logs = self._logs()
        self.assertIn("update=6006", logs)
        self.assertIn("RuntimeError", logs)
        # 失败路径仍然是脱敏过的，不能因为加了字段就漏出去
        self.assertNotIn("sk-live-", logs)
        self.assertEqual(self.storage.appends, [])


class UpdateReferenceFormatTests(unittest.TestCase):
    """_update_ref 是上面所有断言的公共依赖，单独立几条边界"""

    def test_includes_update_id_and_user_id(self):
        self.assertEqual(
            bot_module._update_ref(_make_update(update_id=77, user_id=42)),
            "update=77 user=42",
        )

    def test_survives_missing_effective_user(self):
        """频道帖之类的更新没有 effective_user，不能让日志本身把处理器炸掉"""
        update = SimpleNamespace(update_id=88, effective_user=None, effective_message=_Message())
        self.assertEqual(bot_module._update_ref(update), "update=88 user=未知")
