import unittest


class OverlayImportTests(unittest.TestCase):
    def test_overlay_module_imports(self):
        """overlay 只有實際開視窗時才會被載入，單元測試至少要確保它能被 import。"""
        import cantonese_live.overlay as overlay
        self.assertTrue(hasattr(overlay, "Overlay"))
        self.assertTrue(hasattr(overlay, "FG_JYUTPING"))


if __name__ == "__main__":
    unittest.main()
