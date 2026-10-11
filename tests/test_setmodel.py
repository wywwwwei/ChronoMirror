"""回归测试：/setmodel 的档位模型、模型名校验、以及"只列自己在用的那一家"。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import json
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings
from core import user_config as user_config_module
from core.llm_service import LLMService
from core.user_config import (
    _MODEL_FIELDS,
    MODEL_ROLES,
    UserConfig,
    UserConfigManager,
    apply_role_value,
    available_roles,
    describe_role,
    normalize_model_name,
)


class NormalizeModelNameTests(unittest.TestCase):
    def test_accepts_common_model_names(self):
        for payload in (
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gpt-4o-mini",
            "whisper-1",
            # 中转 / 聚合平台的写法，放行 / : @ 就是为了这些
            "google/gemini-2.5-pro-preview-05-06",
            "us.anthropic.claude-3-5-sonnet-v2:0",
            "vendor/model:free@latest",
        ):
            with self.subTest(payload=payload):
                name, error = normalize_model_name(payload)
                self.assertEqual(name, payload)
                self.assertIsNone(error)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(normalize_model_name("  gpt-4o-mini \n"), ("gpt-4o-mini", None))

    def test_rejects_empty(self):
        for payload in (None, "", "   ", "\n"):
            with self.subTest(payload=payload):
                name, error = normalize_model_name(payload)
                self.assertIsNone(name)
                self.assertIsNotNone(error)

    def test_rejects_over_length(self):
        name, error = normalize_model_name("a" * 65)
        self.assertIsNone(name)
        self.assertIsNotNone(error)
        # 边界值本身要能过
        self.assertEqual(normalize_model_name("a" * 64), ("a" * 64, None))

    def test_rejects_illegal_characters(self):
        """模型名会被拼进 API 请求，字符合集必须收紧"""
        for payload in (
            "gemini model",       # 空格
            "gemini\nmodel",      # 换行
            "model;rm -rf /",     # 命令拼接
            "model$(whoami)",     # 命令替换
            "model`id`",          # 反引号：还会破坏 Telegram Markdown
            "model%20name",
            "model&x=1",
        ):
            with self.subTest(payload=payload):
                name, error = normalize_model_name(payload)
                self.assertIsNone(name)
                self.assertIsNotNone(error)


class RoleScopingTests(unittest.TestCase):
    """档位按 provider 归属：单 Key 的用户永远不该看到另一家的档位"""

    def test_gemini_key_only_sees_gemini_roles(self):
        cfg = UserConfig(user_id=1, gemini_api_key="k")
        self.assertEqual(available_roles(cfg), ["capture", "review"])

    def test_openai_key_only_sees_openai_roles(self):
        cfg = UserConfig(user_id=1, openai_api_key="k")
        self.assertEqual(available_roles(cfg), ["chat", "whisper"])

    def test_no_key_sees_nothing(self):
        self.assertEqual(available_roles(UserConfig(user_id=1)), [])

    def test_both_keys_sees_both_families(self):
        cfg = UserConfig(user_id=1, gemini_api_key="g", openai_api_key="o")
        self.assertEqual(set(available_roles(cfg)), set(MODEL_ROLES))

    def test_no_role_name_collides_with_a_provider_name(self):
        """档位名撞上 provider 名会让 /setmodel openai X 产生歧义"""
        for role, meta in MODEL_ROLES.items():
            with self.subTest(role=role):
                self.assertNotIn(role, meta["provider"])

    def test_chat_role_covers_text_and_vision(self):
        self.assertEqual(MODEL_ROLES["chat"]["fields"], ("openai_model", "openai_vision_model"))
        self.assertIn("openai_vision_model", _MODEL_FIELDS)


class SetModelPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = UserConfigManager()
        self._original_base = self.manager.base_dir
        self.manager.base_dir = Path(self._tmp.name).resolve() / "users"
        self.manager.base_dir.mkdir(parents=True, exist_ok=True)

        self._original_settings = user_config_module.settings
        user_config_module.settings = Settings(
            _env_file=None,
            ALLOWED_USER_IDS="111",
            GEMINI_API_KEY="global-key",
            GEMINI_CAPTURE_MODEL="gemini-capture-test",
            GEMINI_REVIEW_MODEL="gemini-review-test",
            OPENAI_MODEL="openai-test-model",
            OPENAI_VISION_MODEL="openai-vision-test",
            OPENAI_WHISPER_MODEL="whisper-test",
        )

    def tearDown(self):
        user_config_module.settings = self._original_settings
        self.manager.base_dir = self._original_base
        self._tmp.cleanup()

    def _stored(self, **kwargs) -> UserConfig:
        cfg = UserConfig(user_id=111, gemini_api_key="personal-key", **kwargs)
        self.manager.save_user_config(cfg)
        return cfg

    def _on_disk(self) -> dict:
        return json.loads(self.manager._config_path(111).read_text(encoding="utf-8"))

    def test_set_then_resolve_returns_user_value(self):
        stored = self._stored()
        apply_role_value(stored, "capture", "gemini-3.5-flash")
        self.manager.save_user_config(stored)

        resolved = self.manager.resolve_config(111)
        self.assertEqual(resolved.gemini_capture_model, "gemini-3.5-flash")
        # 只动被设置的那一档
        self.assertEqual(resolved.gemini_review_model, "gemini-review-test")

    def test_setting_chat_writes_both_fields(self):
        stored = self._stored()
        apply_role_value(stored, "chat", "gpt-4o")
        self.manager.save_user_config(stored)

        data = self._on_disk()
        self.assertEqual(data["openai_model"], "gpt-4o")
        self.assertEqual(data["openai_vision_model"], "gpt-4o")

    def test_reset_restores_env_default(self):
        stored = self._stored(gemini_capture_model="pinned")
        apply_role_value(stored, "capture", None)
        self.manager.save_user_config(stored)

        self.assertIsNone(self._on_disk()["gemini_capture_model"])
        self.assertEqual(self.manager.resolve_config(111).gemini_capture_model, "gemini-capture-test")

    def test_reset_all_clears_every_model_field(self):
        stored = self._stored(
            gemini_capture_model="a", gemini_review_model="b", gemini_model="legacy",
            openai_model="c", openai_vision_model="d", openai_whisper_model="e",
        )
        for field_name in _MODEL_FIELDS:
            setattr(stored, field_name, None)
        stored.gemini_model = None
        self.manager.save_user_config(stored)

        data = self._on_disk()
        for field_name in list(_MODEL_FIELDS) + ["gemini_model"]:
            with self.subTest(field=field_name):
                self.assertIsNone(data[field_name])

    def test_reset_review_also_clears_legacy_field(self):
        """不连旧字段一起清，review 会被它立刻顶回旧值，看起来像重置失效。"""
        stored = self._stored(gemini_model="legacy-model")
        apply_role_value(stored, "review", None)
        self.manager.save_user_config(stored)

        self.assertIsNone(self._on_disk()["gemini_model"])
        self.assertEqual(self.manager.resolve_config(111).gemini_review_model, "gemini-review-test")

    def test_setting_never_persists_resolved_defaults(self):
        """只写过 capture，其余字段必须仍然是 null —— 否则默认值被固化进用户配置"""
        stored = self._stored()
        apply_role_value(stored, "capture", "gemini-3.5-flash")
        self.manager.save_user_config(stored)

        data = self._on_disk()
        self.assertEqual(data["gemini_capture_model"], "gemini-3.5-flash")
        for field_name in ("gemini_review_model", "openai_model", "openai_vision_model",
                           "openai_whisper_model", "gemini_model"):
            with self.subTest(field=field_name):
                self.assertIsNone(data[field_name])

    def test_setmodel_never_leaks_env_fallback_key(self):
        """写配置必须走存储副本：用 resolve_config 的副本会把部署者的全局 Key 落盘"""
        stored = self._stored()
        stored.gemini_api_key = None  # 让该用户走 .env 兜底
        self.manager.save_user_config(stored)
        self.assertTrue(self.manager.resolve_config(111).env_key_fallback)

        # 模拟 /setmodel 的写法：读存储副本 → 改 → 存
        editing = self.manager.get_user_config(111)
        apply_role_value(editing, "capture", "gemini-3.5-flash")
        self.manager.save_user_config(editing)

        data = self._on_disk()
        self.assertIsNone(data["gemini_api_key"])
        self.assertNotIn("env_key_fallback", data)


class RoleDescriptionTests(unittest.TestCase):
    """来源标签要区分"个人设置"和"跟随 .env"，否则 /setmodel 的输出会骗人"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = UserConfigManager()
        self._original_base = self.manager.base_dir
        self.manager.base_dir = Path(self._tmp.name).resolve() / "users"
        self.manager.base_dir.mkdir(parents=True, exist_ok=True)

        self._original_settings = user_config_module.settings
        user_config_module.settings = Settings(
            _env_file=None, ALLOWED_USER_IDS="111",
            GEMINI_CAPTURE_MODEL="gemini-capture-test",
            GEMINI_REVIEW_MODEL="gemini-review-test",
        )

    def tearDown(self):
        user_config_module.settings = self._original_settings
        self.manager.base_dir = self._original_base
        self._tmp.cleanup()

    def test_labels_follow_env_when_nothing_pinned(self):
        self.manager.save_user_config(UserConfig(user_id=111, gemini_api_key="k"))
        stored = self.manager.get_user_config(111)
        resolved = self.manager.resolve_config(111)

        self.assertFalse(describe_role(stored, resolved, "capture")["pinned"])
        self.assertEqual(describe_role(stored, resolved, "capture")["values"], ["gemini-capture-test"])

    def test_labels_personal_after_setting(self):
        stored = UserConfig(user_id=111, gemini_api_key="k", gemini_capture_model="pinned")
        self.manager.save_user_config(stored)
        resolved = self.manager.resolve_config(111)

        info = describe_role(self.manager.get_user_config(111), resolved, "capture")
        self.assertTrue(info["pinned"])
        self.assertEqual(info["values"], ["pinned"])

    def test_legacy_field_counts_as_personal_for_review(self):
        """存量用户被 gemini_model 钉着 review，标签不能显示成「跟随 .env」"""
        self.manager.save_user_config(
            UserConfig(user_id=111, gemini_api_key="k", gemini_model="gemini-3.8-flash")
        )
        resolved = self.manager.resolve_config(111)

        review = describe_role(self.manager.get_user_config(111), resolved, "review")
        self.assertTrue(review["pinned"])
        self.assertEqual(review["values"], ["gemini-3.8-flash"])

    def test_chat_reports_both_values_when_hand_edited_apart(self):
        self.manager.save_user_config(UserConfig(
            user_id=111, openai_api_key="k",
            openai_model="gpt-4o", openai_vision_model="gpt-4o-mini",
        ))
        resolved = self.manager.resolve_config(111)
        info = describe_role(self.manager.get_user_config(111), resolved, "chat")
        self.assertEqual(info["values"], ["gpt-4o", "gpt-4o-mini"])


class _FakeModels:
    def __init__(self, text="done"):
        self.calls = []
        self._text = text

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)

        class _Resp:
            pass

        resp = _Resp()
        resp.text = self._text
        return resp


class _FakeGeminiClient:
    def __init__(self, models):
        self.aio = type("_Aio", (), {"models": models})()


class ModelWiringTests(unittest.IsolatedAsyncioTestCase):
    """采集走 capture 档、复盘走 review 档，接错线等于拆档没做"""

    def setUp(self):
        self.service = LLMService()
        self.models = _FakeModels()
        self.client = _FakeGeminiClient(self.models)
        self.cfg = UserConfig(
            user_id=1, active_provider="gemini", gemini_api_key="k",
            gemini_capture_model="cap-model", gemini_review_model="rev-model",
        )
        self._original = self.service._get_gemini_client

        async def _fake_client(cfg):
            return self.client

        self.service._get_gemini_client = _fake_client
        self._tmp = tempfile.TemporaryDirectory()
        self.audio = Path(self._tmp.name) / "a.ogg"
        self.audio.write_bytes(b"OggS")

    def tearDown(self):
        self.service._get_gemini_client = self._original
        self._tmp.cleanup()

    async def test_capture_paths_use_capture_model(self):
        await self.service.describe_image(image_bytes=b"\x89PNG", user_config=self.cfg)
        self.assertEqual(self.models.calls[-1]["model"], "cap-model")

        await self.service.transcribe_audio(audio_path=self.audio, user_config=self.cfg)
        self.assertEqual(self.models.calls[-1]["model"], "cap-model")

    async def test_review_paths_use_review_model(self):
        await self.service.generate_daily_review(
            date_str="2026-10-12", log_content="log", profile_content="p", user_config=self.cfg
        )
        self.assertEqual(self.models.calls[-1]["model"], "rev-model")

        await self.service.generate_weekly_review(
            week_label="2026-W41", daily_reviews_summary="s", profile_content="p", user_config=self.cfg
        )
        self.assertEqual(self.models.calls[-1]["model"], "rev-model")

        await self.service.evolve_memory(
            recent_reviews_text="r", current_profile="p", user_config=self.cfg
        )
        self.assertEqual(self.models.calls[-1]["model"], "rev-model")

    async def test_unpinned_config_falls_back_to_settings(self):
        """调用方传未解析的配置时也不能把 None 当模型名发出去"""
        cfg = UserConfig(user_id=1, active_provider="gemini", gemini_api_key="k")
        await self.service.describe_image(image_bytes=b"\x89PNG", user_config=cfg)
        self.assertEqual(self.models.calls[-1]["model"], Settings(_env_file=None).GEMINI_CAPTURE_MODEL)


class SettingsModelSplitTests(unittest.TestCase):
    def test_new_defaults(self):
        s = Settings(_env_file=None)
        self.assertEqual(s.GEMINI_CAPTURE_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(s.GEMINI_REVIEW_MODEL, "gemini-3.8-flash")

    def test_legacy_env_var_maps_to_both(self):
        """extra="ignore" 会静默吞掉旧变量，必须显式接管，否则存量部署无声换模型"""
        s = Settings(_env_file=None, GEMINI_MODEL="legacy-env-model")
        self.assertEqual(s.GEMINI_CAPTURE_MODEL, "legacy-env-model")
        self.assertEqual(s.GEMINI_REVIEW_MODEL, "legacy-env-model")

    def test_explicit_new_var_beats_legacy(self):
        s = Settings(
            _env_file=None, GEMINI_MODEL="legacy-env-model", GEMINI_CAPTURE_MODEL="explicit"
        )
        self.assertEqual(s.GEMINI_CAPTURE_MODEL, "explicit")
        self.assertEqual(s.GEMINI_REVIEW_MODEL, "legacy-env-model")


if __name__ == "__main__":
    unittest.main()
