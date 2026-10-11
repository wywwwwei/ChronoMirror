"""回归测试：开启并发更新处理之后，存储层的写入仍然自洽。

机器人现在会把多条更新并发处理（见 bot.telegram_bot.MAX_CONCURRENT_UPDATES），
于是多个处理器会同时落到同一批文件上。这里钉住三件曾经会被破坏的事：

  1. 当天首条日志的 frontmatter 只能写一次——`append_log` 靠"文件存不存在"决定
     要不要补 frontmatter，判断和追加若不原子，并发下当天头几条会各写一份；
  2. 同一秒内的两个附件不能互相覆盖——调用方只把文件名精确到秒；
  3. 模块级 storage 单例必须跨事件循环可用——asyncio.Lock 的绑定陷阱。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import aiofiles

from core import storage as storage_module
from core.storage import VaultStorage


@contextlib.asynccontextmanager
async def _widen_write_window():
    """把 aiofiles.open 推迟到让出一次调度之后再真正建文件。

    竞态窗口就在"判断文件/名字是否存在"与"真正落盘"之间，真实情况下只有一个
    await 宽，靠 asyncio.gather 撞不稳——线程池通常抢在下一个任务做判断之前就把
    文件建好了，于是**测试会假绿**（把锁整个删掉也照样通过）。这里人为把窗口放大
    成确定的一轮调度：所有并发任务都能先跑完各自的存在性判断，再去落盘。
    没有锁时必然互踩；有锁时被串行化，窗口自然消失。
    """
    real_open = aiofiles.open

    @contextlib.asynccontextmanager
    async def slow_open(*args, **kwargs):
        await asyncio.sleep(0)
        async with real_open(*args, **kwargs) as handle:
            yield handle

    with mock.patch.object(aiofiles, "open", slow_open):
        yield


class ConcurrentWriteTests(unittest.IsolatedAsyncioTestCase):
    """每个用例独立的 VaultStorage 实例，互不干扰"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.storage = VaultStorage()
        self.storage.users_base_dir = self.root / "users"

    def tearDown(self):
        self._tmp.cleanup()

    async def test_concurrent_appends_share_one_frontmatter(self):
        n = 12
        async with _widen_write_window():
            await asyncio.gather(*(
                self.storage.append_log(user_id=1, content=f"第{i}条", tag="并发")
                for i in range(n)
            ))

        log_dir = self.root / "users" / "1" / "logs"
        files = list(log_dir.glob("*.md"))
        self.assertEqual(len(files), 1, [f.name for f in files])

        text = files[0].read_text(encoding="utf-8")
        # frontmatter 与其后的标题都只能出现一次
        self.assertEqual(text.count("\ntype: daily-log\n"), 1)
        self.assertEqual(text.count("# 📝 时间流日志"), 1)
        self.assertTrue(text.startswith("---\n"), text[:40])
        # 每条都完整落盘，一条不少
        for i in range(n):
            self.assertIn(f"第{i}条", text)
        self.assertEqual(text.count("\n## "), n)

    async def test_same_second_attachments_do_not_overwrite(self):
        """同秒落盘的三个附件必须各自存活，且返回的引用指向自己那份"""
        payloads = {f"payload-{i}".encode() for i in range(3)}
        async with _widen_write_window():
            results = await asyncio.gather(*(
                self.storage.save_attachment(1, payload, "photo_20261012_013225.jpg")
                for payload in payloads
            ))

        targets = [target for target, _ in results]
        self.assertEqual(len(set(targets)), 3, [t.name for t in targets])
        self.assertEqual({t.read_bytes() for t in targets}, payloads)

        # 相对引用是拼进 Markdown 的那份，必须和真实落盘路径对得上
        vault_root = self.root / "users" / "1"
        for target, rel in results:
            self.assertTrue(rel.startswith("attachments/"), rel)
            self.assertEqual(Path(rel).name, target.name)
            self.assertEqual((vault_root / rel).read_bytes(), target.read_bytes())
            # 去重后缀插在扩展名前，日期前缀不能被动到
            self.assertTrue(target.name.startswith("photo_20261012_013225"), target.name)

    async def test_deduped_name_does_not_collide_with_existing(self):
        """先占掉原始名字，再来一个同秒附件，不能覆盖已有的那份"""
        first_path, _ = await self.storage.save_attachment(1, b"first", "voice_20261012_013225.ogg")
        second_path, _ = await self.storage.save_attachment(1, b"second", "voice_20261012_013225.ogg")

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.read_bytes(), b"first")
        self.assertEqual(second_path.read_bytes(), b"second")


class SingletonLockTests(unittest.IsolatedAsyncioTestCase):
    """storage 是模块级单例，而每个测试方法各起一个事件循环。

    asyncio.Lock 一旦被争用就会绑定到当时运行的循环，换循环再 acquire 直接抛
    RuntimeError("... is bound to a different event loop")。锁若在 __init__ 里
    建一次就会踩中这个坑——线上只有一个循环所以看不出来，测试里必炸。
    _write_lock() 因此按循环惰性重建；下面两个方法故意各跑一轮争用。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._original_base = storage_module.storage.users_base_dir
        storage_module.storage.users_base_dir = Path(self._tmp.name).resolve() / "users"

    def tearDown(self):
        storage_module.storage.users_base_dir = self._original_base
        self._tmp.cleanup()

    async def _contend(self):
        await asyncio.gather(*(
            storage_module.storage.append_log(user_id=1, content=f"条目{i}")
            for i in range(8)
        ))

    async def test_a_contend_on_first_loop(self):
        await self._contend()

    async def test_b_contend_on_second_loop(self):
        # 这一轮换到了新的循环。若锁被首次争用绑定后不再重建，这里会抛 RuntimeError。
        await self._contend()


class UpdateConcurrencyWiringTests(unittest.TestCase):
    """并发度必须真的接进 Application，而不只是定义了一个常量"""

    def setUp(self):
        from config.settings import settings
        from bot import telegram_bot as bot_module
        self.bot_module = bot_module
        self.settings = settings
        self._orig_token = settings.TELEGRAM_BOT_TOKEN
        self._orig_proxy = settings.TELEGRAM_PROXY

    def tearDown(self):
        self.settings.TELEGRAM_BOT_TOKEN = self._orig_token
        self.settings.TELEGRAM_PROXY = self._orig_proxy

    def test_builder_gets_bounded_concurrency(self):
        self.settings.TELEGRAM_BOT_TOKEN = "123456:TESTTOKEN"
        # 避免测试环境里的代理配置参与构造成本（构造本身不联网）
        self.settings.TELEGRAM_PROXY = None

        app = self.bot_module.build_telegram_app()
        self.assertEqual(
            app.update_processor.max_concurrent_updates,
            self.bot_module.MAX_CONCURRENT_UPDATES,
        )
        # 有界并发：大于 1（真要并发），但不是 True（PTB 把 True 当无界）。
        # 想改回 True 的话这两条断言会先拦下来。
        self.assertGreater(self.bot_module.MAX_CONCURRENT_UPDATES, 1)
        self.assertIsNot(self.bot_module.MAX_CONCURRENT_UPDATES, True)
