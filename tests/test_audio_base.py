import unittest

import numpy as np

from cantonese_live.audio.base import TARGET_RATE, AudioError, CaptureBase, Device


class FakeCapture(CaptureBase):
    """不碰硬體的子類別，直接用 _ingest 餵資料。"""

    def __init__(self, device, **kw):
        super().__init__(device, **kw)
        self.started = False

    def start(self):
        self.started = True

    def _close_stream(self):
        self.started = False

    def _stream_active(self):
        return self.started


def sine(rate: int, seconds: float, channels: int = 1, interleaved: bool = True):
    t = np.arange(int(rate * seconds)) / rate
    mono = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    if channels == 1:
        return mono
    multi = np.stack([mono] * channels, axis=1)          # (frames, ch)
    return multi.reshape(-1) if interleaved else multi


def drain(cap):
    out = []
    while True:
        b = cap.read(0.01)
        if b is None or b.size == 0:
            return out or [np.empty(0, dtype=np.float32)]
        out.append(b)


class ToMono16kTests(unittest.TestCase):
    def test_resample_48000_stereo_interleaved(self):
        cap = FakeCapture(Device(0, "x", 48000, 2))
        cap._ingest(sine(48000, 1.0, channels=2, interleaved=True))
        total = sum(b.size for b in drain(cap))
        self.assertTrue(15000 <= total <= 16000, total)

    def test_resample_44100(self):
        cap = FakeCapture(Device(0, "x", 44100, 1))
        cap._ingest(sine(44100, 1.0))
        total = sum(b.size for b in drain(cap))
        self.assertTrue(15000 <= total <= 16000, total)

    def test_2d_and_interleaved_agree(self):
        a = FakeCapture(Device(0, "x", 48000, 2))
        b = FakeCapture(Device(0, "x", 48000, 2))
        a._ingest(sine(48000, 0.5, channels=2, interleaved=True))
        b._ingest(sine(48000, 0.5, channels=2, interleaved=False))
        xa = np.concatenate(drain(a))
        xb = np.concatenate(drain(b))
        np.testing.assert_allclose(xa, xb, atol=1e-6)

    def test_16k_mono_passthrough(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1))
        x = sine(TARGET_RATE, 0.2)
        cap._ingest(x)
        got = np.concatenate(drain(cap))
        np.testing.assert_array_equal(got, x)

    def test_odd_tail_sample_is_dropped_not_crashed(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 2))
        cap._ingest(np.zeros(7, dtype=np.float32))   # 7 不是 2 的倍數
        got = np.concatenate(drain(cap))
        self.assertEqual(got.size, 3)


class BufferTests(unittest.TestCase):
    def test_overflow_drops_oldest_and_reports(self):
        dropped = []
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1),
                          queue_seconds=0.01,  # 160 樣本
                          on_overflow=dropped.append)
        first = np.full(100, 1.0, dtype=np.float32)
        second = np.full(100, 2.0, dtype=np.float32)
        cap._ingest(first)
        cap._ingest(second)
        got = cap.read(0.01)
        self.assertEqual(float(got[0]), 2.0)          # 最舊的被丟掉
        self.assertEqual(cap.dropped_samples, 100)
        self.assertEqual(dropped, [100])

    def test_read_times_out_with_empty_array(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1))
        got = cap.read(0.01)
        self.assertEqual(got.size, 0)

    def test_read_returns_none_after_stop(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1))
        cap.start()
        cap.stop()
        self.assertIsNone(cap.read(0.01))
        self.assertFalse(cap.alive)

    def test_fail_surfaces_as_audio_error_on_read(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1))
        cap._fail(RuntimeError("boom"))
        with self.assertRaises(AudioError):
            cap.read(0.01)

    def test_context_manager_starts_and_stops(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1))
        with cap as c:
            self.assertTrue(c.alive)
        self.assertFalse(cap.alive)

    def test_frames_per_block_follows_device_rate(self):
        cap = FakeCapture(Device(0, "x", 48000, 2), block_ms=64)
        self.assertEqual(cap.frames_per_block, 3072)


if __name__ == "__main__":
    unittest.main()
