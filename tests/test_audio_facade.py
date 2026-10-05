import sys
import unittest
from unittest import mock

import cantonese_live.audio as audio


class BackendSelectionTests(unittest.TestCase):
    def setUp(self):
        audio._BACKEND = None

    def tearDown(self):
        audio._BACKEND = None

    def test_unsupported_platform_raises(self):
        with mock.patch.object(sys, "platform", "linux"):
            with self.assertRaises(audio.AudioError) as ctx:
                audio._backend()
        self.assertIn("只支援 Windows 與 macOS", str(ctx.exception))

    @unittest.skipUnless(sys.platform == "darwin", "只在 macOS 驗證")
    def test_darwin_uses_macos_backend_without_pyaudiowpatch(self):
        backend = audio._backend()
        self.assertEqual(backend.__name__, "cantonese_live.audio.macos")
        self.assertNotIn("pyaudiowpatch", sys.modules)

    def test_public_names_exist(self):
        for name in ("Device", "AudioError", "TARGET_RATE", "CaptureBase",
                     "LoopbackCapture", "list_loopback_devices", "resolve_device",
                     "routing_hint", "setup_help"):
            self.assertTrue(hasattr(audio, name), name)

    def test_backends_expose_required_interface(self):
        import importlib
        for modname in ("cantonese_live.audio.windows", "cantonese_live.audio.macos"):
            try:
                mod = importlib.import_module(modname)
            except ImportError:
                continue  # 另一平台的相依沒裝是正常的
            for attr in ("list_devices", "resolve_device", "open_capture",
                         "routing_hint", "SETUP_HELP"):
                self.assertTrue(hasattr(mod, attr), f"{modname}.{attr}")


if __name__ == "__main__":
    unittest.main()
