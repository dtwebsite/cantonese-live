import unittest

from cantonese_live.config import UiConfig, default_font_family


class DefaultFontTests(unittest.TestCase):
    def test_windows(self):
        self.assertEqual(default_font_family("win32"), "Microsoft JhengHei UI")

    def test_macos(self):
        self.assertEqual(default_font_family("darwin"), "PingFang TC")

    def test_other_platform_falls_back_to_tk_default(self):
        self.assertEqual(default_font_family("linux"), "TkDefaultFont")

    def test_ui_config_default_is_blank_meaning_auto(self):
        self.assertEqual(UiConfig().font_family, "")

    def test_resolved_font_family_uses_override_when_set(self):
        self.assertEqual(UiConfig(font_family="Noto Sans TC").resolved_font_family("darwin"),
                         "Noto Sans TC")
        self.assertEqual(UiConfig().resolved_font_family("darwin"), "PingFang TC")


if __name__ == "__main__":
    unittest.main()
