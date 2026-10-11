"""回归测试：.env 全局 Key 的兜底规则，以及 resolve_config 绝不污染磁盘。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import json
import tempfile
import unittest
from pathlib import Path

from config.settings import Settings
from core import user_config as user_config_module
from core.user_config import UserConfig, UserConfigManager


class EnvKeyFallbackPolicyTests(unittest.TestCase):
    """公开模式绝不能拿部署者的 Key 兜底，否则陌生人白嫖额度"""

    @staticmethod
    def _settings(**kwargs) -> Settings:
        return Settings(_env_file=None, **kwargs)

    def test_env_fallback_disabled_in_public_mode(self):
        s = self._settings(ALLOWED_USER_IDS="", GEMINI_API_KEY="global-key")
        self.assertTrue(s.env_llm_keys_configured)
        self.assertFalse(s.env_key_fallback_enabled)

    def test_env_fallback_disabled_in_explicit_public_mode(self):
        s = self._settings(ALLOWED_USER_IDS="*", GEMINI_API_KEY="global-key")
        self.assertFalse(s.env_key_fallback_enabled)

    def test_env_fallback_enabled_in_private_mode(self):
        s = self._settings(ALLOWED_USER_IDS="111", GEMINI_API_KEY="global-key")
        self.assertTrue(s.env_key_fallback_enabled)

    def test_no_keys_means_no_fallback(self):
        s = self._settings(ALLOWED_USER_IDS="111")
        self.assertFalse(s.env_key_fallback_enabled)

    def test_env_key_lookup_by_provider(self):
        s = self._settings(GEMINI_API_KEY="g", OPENAI_API_KEY="o")
        self.assertEqual(s.env_key_for("gemini"), "g")
        self.assertEqual(s.env_key_for("openai"), "o")
        self.assertIsNone(s.env_key_for("claude"))

    def test_invalid_default_provider_rejected(self):
        with self.assertRaises(Exception):
            self._settings(DEFAULT_LLM_PROVIDER="claude")

    def test_provider_is_normalized(self):
        self.assertEqual(self._settings(DEFAULT_LLM_PROVIDER="  Gemini ").DEFAULT_LLM_PROVIDER, "gemini")


class UserConfigResolutionTests(unittest.TestCase):
    """resolve_config：个人 Key 优先、模型跟随 .env、兜底副本绝不落盘"""

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
        )

    def tearDown(self):
        user_config_module.settings = self._original_settings
        self.manager.base_dir = self._original_base
        self._tmp.cleanup()

    def test_personal_key_takes_precedence(self):
        self.manager.save_user_config(UserConfig(user_id=111, gemini_api_key="personal-key"))
        resolved = self.manager.resolve_config(111)
        self.assertEqual(resolved.gemini_api_key, "personal-key")
        self.assertFalse(resolved.env_key_fallback)

    def test_whitelisted_user_falls_back_to_env_key(self):
        resolved = self.manager.resolve_config(111)
        self.assertTrue(resolved.has_valid_key())
        self.assertTrue(resolved.env_key_fallback)
        self.assertEqual(resolved.gemini_api_key, "global-key")
        self.assertEqual(resolved.key_source_label(), "环境变量兜底")

    def test_non_whitelisted_user_gets_no_fallback(self):
        self.assertFalse(self.manager.resolve_config(222).has_valid_key())

    def test_explicit_opt_in_overrides_policy(self):
        """CLI 本地自用模式显式允许兜底"""
        resolved = self.manager.resolve_config(222, allow_env_fallback=True)
        self.assertTrue(resolved.has_valid_key())

    def test_resolution_never_touches_disk(self):
        self.manager.resolve_config(111)
        self.assertFalse(self.manager._config_path(111).exists())

    def test_env_fallback_flag_is_not_serialized(self):
        resolved = self.manager.resolve_config(111)
        self.assertNotIn("env_key_fallback", resolved.model_dump())
        self.assertNotIn("env_key_fallback", resolved.model_dump_json())

    def test_saving_stored_config_keeps_global_key_out(self):
        """落盘的用户配置里绝不能带上部署者的全局 Key"""
        stored = self.manager.get_user_config(111)
        stored.active_provider = "openai"
        self.manager.save_user_config(stored)

        data = json.loads(self.manager._config_path(111).read_text(encoding="utf-8"))
        self.assertIsNone(data["gemini_api_key"])
        self.assertIsNone(data["openai_api_key"])
        # 模型未被显式指定时留空，表示"跟随 .env"，避免把默认值固化进用户配置
        self.assertIsNone(data["gemini_model"])
        self.assertIsNone(data["gemini_capture_model"])
        self.assertIsNone(data["gemini_review_model"])

    def test_models_follow_env_when_not_pinned(self):
        resolved = self.manager.resolve_config(111)
        self.assertEqual(resolved.gemini_capture_model, "gemini-capture-test")
        self.assertEqual(resolved.gemini_review_model, "gemini-review-test")

        stored = self.manager.get_user_config(111)
        stored.active_provider = "openai"
        self.manager.save_user_config(stored)
        self.assertEqual(self.manager.resolve_config(111).openai_model, "openai-test-model")

    def test_explicit_model_overrides_env(self):
        self.manager.save_user_config(UserConfig(user_id=111, gemini_capture_model="my-pinned-model"))
        self.assertEqual(self.manager.resolve_config(111).gemini_capture_model, "my-pinned-model")

    def test_legacy_single_model_field_maps_to_review_only(self):
        """旧的单档 gemini_model 只喂 review。

        存量用户（含仓库里那份真实 config.json）都钉着这个字段。若让它同时覆盖
        capture，拆档在这些人身上等于没做——capture 会永远停在旧值上。
        """
        self.manager.save_user_config(UserConfig(user_id=111, gemini_model="legacy-model"))
        resolved = self.manager.resolve_config(111)
        self.assertEqual(resolved.gemini_review_model, "legacy-model")
        self.assertEqual(resolved.gemini_capture_model, "gemini-capture-test")

    def test_explicit_review_model_beats_legacy_field(self):
        self.manager.save_user_config(
            UserConfig(user_id=111, gemini_model="legacy-model", gemini_review_model="explicit-model")
        )
        self.assertEqual(self.manager.resolve_config(111).gemini_review_model, "explicit-model")

    def test_resolved_config_never_carries_legacy_field(self):
        """回填后 gemini_model 仍是 None，"用户钉过没有"才判断得出来。

        一旦它被填上默认值，/status 的来源标签会全体显示成"个人设置"。
        """
        stored = self.manager.get_user_config(111)
        self.assertIsNone(stored.gemini_model)
        self.assertIsNone(self.manager.resolve_config(111).gemini_model)

    def test_corrupted_config_does_not_crash(self):
        path = self.manager._config_path(111)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        config = self.manager.get_user_config(111)
        self.assertEqual(config.user_id, 111)
        # 损坏文件不被静默删除，便于人工排查
        self.assertTrue(path.exists())

    def test_save_is_atomic(self):
        self.manager.save_user_config(UserConfig(user_id=111, gemini_api_key="k"))
        self.assertFalse(self.manager._config_path(111).with_name("config.json.tmp").exists())

    def test_list_active_users_includes_whitelisted_fallback_user(self):
        self.assertIn(111, self.manager.list_active_users())


if __name__ == "__main__":
    unittest.main()
