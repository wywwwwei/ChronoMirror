"""回归测试：白名单 / 公开模式的语义。

运行方式（无需额外依赖）：
    python -m unittest discover -s tests -t .
"""
import unittest

from config.settings import Settings


class SettingsSemanticsTests(unittest.TestCase):
    """白名单 / 公开模式的判定必须只有一个来源"""

    @staticmethod
    def _settings(**kwargs) -> Settings:
        return Settings(_env_file=None, **kwargs)

    def test_whitelist_parsing_and_authorization(self):
        s = self._settings(ALLOWED_USER_IDS="111, 222")
        self.assertEqual(s.allowed_user_ids_list, [111, 222])
        self.assertFalse(s.is_public_mode)
        self.assertTrue(s.is_user_allowed(111))
        self.assertFalse(s.is_user_allowed(333))

    def test_star_means_explicit_public_mode(self):
        s = self._settings(ALLOWED_USER_IDS="*")
        self.assertTrue(s.is_public_mode)
        self.assertTrue(s.has_explicit_public_mode)
        self.assertTrue(s.is_user_allowed(999))

    def test_empty_whitelist_is_public_but_not_explicit(self):
        s = self._settings(ALLOWED_USER_IDS="")
        self.assertTrue(s.is_public_mode)
        self.assertFalse(s.has_explicit_public_mode)

    def test_bot_authorization_delegates_to_settings(self):
        """bot 层与 settings 层不能各写一份白名单逻辑"""
        from bot import telegram_bot

        original = telegram_bot.settings
        try:
            telegram_bot.settings = self._settings(ALLOWED_USER_IDS="111,222")
            self.assertTrue(telegram_bot.is_authorized(111))
            self.assertFalse(telegram_bot.is_authorized(333))

            telegram_bot.settings = self._settings(ALLOWED_USER_IDS="*")
            self.assertTrue(telegram_bot.is_authorized(333))
        finally:
            telegram_bot.settings = original


if __name__ == "__main__":
    unittest.main()
