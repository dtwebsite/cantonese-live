import sys
import unittest

import numpy as np

if sys.platform != "darwin":
    raise unittest.SkipTest("macOS 後端只在 macOS 測")

from cantonese_live.audio import macos  # noqa: E402
from cantonese_live.audio.base import AudioError, Device  # noqa: E402

FAKE_DEVICES = [
    {"name": "MacBook Pro的麥克風", "max_input_channels": 1, "max_output_channels": 0,
     "default_samplerate": 48000.0},
    {"name": "MacBook Pro的揚聲器", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000.0},
    {"name": "BlackHole 16ch", "max_input_channels": 16, "max_output_channels": 16,
     "default_samplerate": 44100.0},
    {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2,
     "default_samplerate": 44100.0},
]


def fake_query():
    return [dict(d) for d in FAKE_DEVICES]


class ListDevicesTests(unittest.TestCase):
    def test_only_input_capable_devices_blackhole_first(self):
        devs = macos.list_devices(query=fake_query)
        names = [d.name for d in devs]
        self.assertEqual(names, ["BlackHole 2ch", "BlackHole 16ch", "MacBook Pro的麥克風"])
        self.assertEqual(devs[0].index, 3)
        self.assertEqual(devs[0].rate, 44100)
        self.assertEqual(devs[0].channels, 2)


class ResolveDeviceTests(unittest.TestCase):
    def test_blank_prefers_fewest_channels(self):
        dev = macos.resolve_device("", query=fake_query)
        self.assertEqual(dev.name, "BlackHole 2ch")

    def test_blank_without_blackhole_gives_install_help(self):
        no_bh = lambda: [d for d in fake_query() if "BlackHole" not in d["name"]]
        with self.assertRaises(AudioError) as ctx:
            macos.resolve_device("", query=no_bh)
        msg = str(ctx.exception)
        self.assertIn("brew install --cask blackhole-2ch", msg)
        self.assertIn("--list-devices", msg)

    def test_numeric_index(self):
        dev = macos.resolve_device("2", query=fake_query)
        self.assertEqual(dev.name, "BlackHole 16ch")

    def test_numeric_index_out_of_range(self):
        with self.assertRaises(AudioError) as ctx:
            macos.resolve_device("9", query=fake_query)
        self.assertIn("不存在", str(ctx.exception))

    def test_numeric_index_output_only_errors(self):
        with self.assertRaises(AudioError) as ctx:
            macos.resolve_device("1", query=fake_query)
        self.assertIn("不能當輸入", str(ctx.exception))

    def test_text_match_case_insensitive(self):
        dev = macos.resolve_device("blackhole 16", query=fake_query)
        self.assertEqual(dev.name, "BlackHole 16ch")

    def test_text_matching_output_only_device_errors(self):
        with self.assertRaises(AudioError) as ctx:
            macos.resolve_device("揚聲器", query=fake_query)
        self.assertIn("不能當輸入", str(ctx.exception))

    def test_text_no_match_lists_available(self):
        with self.assertRaises(AudioError) as ctx:
            macos.resolve_device("Loopback Audio", query=fake_query)
        msg = str(ctx.exception)
        self.assertIn("BlackHole 2ch", msg)
        self.assertIn("可選的有", msg)


class FakeStream:
    """模擬 sounddevice.InputStream：記錄參數，提供手動觸發回呼。"""

    instances: list["FakeStream"] = []
    fail_on_open = False

    def __init__(self, **kw):
        if FakeStream.fail_on_open:
            raise RuntimeError("Error opening InputStream: Invalid device")
        self.kw = kw
        self.active = False
        FakeStream.instances.append(self)

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.active = False

    def feed(self, frames: int):
        data = np.zeros((frames, self.kw["channels"]), dtype=np.float32) + 0.25
        self.kw["callback"](data, frames, None, None)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        FakeStream.instances.clear()
        FakeStream.fail_on_open = False
        self.dev = Device(3, "BlackHole 2ch", 48000, 2)

    def test_open_uses_device_parameters(self):
        cap = macos.open_capture(self.dev, 64, 30.0, None, stream_cls=FakeStream)
        cap.start()
        kw = FakeStream.instances[0].kw
        self.assertEqual(kw["device"], 3)
        self.assertEqual(kw["channels"], 2)
        self.assertEqual(kw["samplerate"], 48000)
        self.assertEqual(kw["dtype"], "float32")
        self.assertEqual(kw["blocksize"], cap.frames_per_block)
        self.assertTrue(cap.alive)
        cap.stop()
        self.assertFalse(cap.alive)

    def test_callback_data_reaches_reader(self):
        cap = macos.open_capture(self.dev, 64, 30.0, None, stream_cls=FakeStream)
        cap.start()
        FakeStream.instances[0].feed(48000)
        got = cap.read(0.1)
        self.assertGreater(got.size, 0)
        self.assertAlmostEqual(float(got[-1]), 0.25, places=2)
        cap.stop()

    def test_open_failure_becomes_audio_error(self):
        FakeStream.fail_on_open = True
        cap = macos.open_capture(self.dev, 64, 30.0, None, stream_cls=FakeStream)
        with self.assertRaises(AudioError) as ctx:
            cap.start()
        self.assertIn("BlackHole 2ch", str(ctx.exception))


from cantonese_live.audio._coreaudio import OutputRoute  # noqa: E402


class RoutingHintTests(unittest.TestCase):
    def test_speakers_only_warns_with_device_name(self):
        route = lambda: OutputRoute("MacBook Pro的揚聲器", False, ())
        hint = macos.routing_hint(route_fn=route)
        self.assertIn("MacBook Pro的揚聲器", hint)
        self.assertIn("沒有經過 BlackHole", hint)

    def test_aggregate_with_blackhole_is_fine(self):
        route = lambda: OutputRoute("會議（喇叭）", True, ("MacBook Pro的揚聲器", "BlackHole 2ch"))
        self.assertIsNone(macos.routing_hint(route_fn=route))

    def test_aggregate_without_blackhole_warns(self):
        route = lambda: OutputRoute("會議（喇叭）", True, ("MacBook Pro的揚聲器", "AirPods"))
        hint = macos.routing_hint(route_fn=route)
        self.assertIn("會議（喇叭）", hint)
        self.assertIn("沒有經過 BlackHole", hint)

    def test_output_is_blackhole_itself(self):
        route = lambda: OutputRoute("BlackHole 2ch", False, ())
        hint = macos.routing_hint(route_fn=route)
        self.assertIn("你自己會聽不到", hint)

    def test_sub_device_name_failure_is_tolerated(self):
        # 其中一個子裝置名字讀不到（空字串），另一個是 BlackHole → 正常
        route = lambda: OutputRoute("會議", True, ("", "BlackHole 2ch"))
        self.assertIsNone(macos.routing_hint(route_fn=route))
        # 名字全讀不到 → 當作沒有 BlackHole，警告
        route2 = lambda: OutputRoute("會議", True, ("", ""))
        self.assertIsNotNone(macos.routing_hint(route_fn=route2))

    def test_probe_exception_is_silenced(self):
        def boom():
            raise OSError(-50)
        self.assertIsNone(macos.routing_hint(route_fn=boom))


if __name__ == "__main__":
    unittest.main()
