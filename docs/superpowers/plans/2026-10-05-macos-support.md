# macOS 支援 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 cantonese-live 在 macOS 上透過 BlackHole 虛擬裝置收音並正常運作，Windows 行為不變。

**Architecture:** `audio.py` 拆成 `audio/` 套件：`base.py` 放兩平台共用的緩衝與重採樣邏輯，`windows.py` 原封搬入 WASAPI 程式碼，`macos.py` 用 sounddevice 從 BlackHole 錄音並以 ctypes 讀 CoreAudio 做收音路徑健檢。對外介面（`LoopbackCapture`、`resolve_device`、`list_loopback_devices`、`Device`、`AudioError`）不變，pipeline 不動。另加 `setup.sh` / `run.sh`、字型與快捷鍵的平台適配、README。

**Tech Stack:** Python 3.12、sounddevice 0.5.6（內含 PortAudio）、ctypes + CoreAudio.framework、tkinter、標準庫 unittest、Homebrew、BlackHole 2ch。

**Spec:** `docs/superpowers/specs/2026-10-05-macos-support-design.md`

## Global Constraints

- 對外介面不變：`from cantonese_live.audio import Device, AudioError, TARGET_RATE, LoopbackCapture, list_loopback_devices, resolve_device` 全部仍可用，`LoopbackCapture(device=..., device_spec="", block_ms=64, queue_seconds=30.0, on_overflow=None)` 呼叫方式不變。
- `pipeline.py`、`asr.py`、`translate/`、`transcript.py`、所有 `.ps1` 不修改。
- Mac 上不得 import `pyaudiowpatch`；Windows 上不得 import `sounddevice`（延遲載入後端）。
- 非 Windows / macOS 平台：`AudioError("目前只支援 Windows 與 macOS")`。
- 健檢 `routing_hint()` 任何例外都回 `None`，絕不影響主功能。
- 測試只用標準庫 `unittest`，不新增測試相依。執行方式：`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`。
- Python 固定 3.12（Homebrew `python@3.12` + `python-tk@3.12`）。
- 所有使用者可見文字為繁體中文，風格與現有訊息一致（簡短、說原因、給下一步）。
- 不做 Mac 免安裝打包、不自動建多重輸出裝置、不支援 Linux。
- Commit 訊息結尾加 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`。

## Review Focus

1. 同時裝了 BlackHole 2ch 與 16ch 時，device 留空應選 2ch（聲道最少者），不是隨機一個。→ Task 4 測試 `test_blank_prefers_fewest_channels`。
2. 使用者在 Mac 上把 device 填成喇叭名稱（只有輸出聲道）時，應得到「不能當輸入」的明確錯誤而不是開串流失敗。→ Task 4 測試 `test_text_matching_output_only_device_errors`。
3. BlackHole 預設 44.1kHz 或 48kHz 都要正確重採樣成 16kHz，且 2-D (frames, ch) 輸入與 1-D 交錯輸入結果一致。→ Task 2 測試 `test_2d_and_interleaved_agree`、`test_resample_44100`。
4. 健檢時某個子裝置名稱讀取失敗（CFString 回傳空）不能讓整個健檢崩潰，應視為「不是 BlackHole」。→ Task 5 測試 `test_sub_device_name_failure_is_tolerated`。
5. 系統輸出本身就是 BlackHole（使用者自己聽不到）要給專屬訊息，而不是籠統的「沒經過 BlackHole」。→ Task 5 測試 `test_output_is_blackhole_itself`。

---

### Task 1: requirements 平台標記 + Mac 開發環境

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: 一個可跑測試的 `.venv`（Python 3.12，含 numpy、soxr、sounddevice、tkinter）。後續所有任務的測試指令都依賴它。

- [ ] **Step 1: 改 requirements.txt 用環境標記**

把這兩行：
```
PyAudioWPatch==0.2.12.8   # WASAPI loopback 擷取（PyAudio 的 Windows 分支）
```
改成：
```
PyAudioWPatch==0.2.12.8; sys_platform == "win32"    # WASAPI loopback 擷取（只有 Windows）
sounddevice==0.5.6;      sys_platform == "darwin"   # 從 BlackHole 錄音（只有 macOS，內含 PortAudio）
```
其餘行不動。

- [ ] **Step 2: 裝 Homebrew Python 3.12 與 Tk，建 venv**

```bash
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list python-tk@3.12 >/dev/null 2>&1 || brew install python-tk@3.12
cd /Users/dennis/html/cantonese-live
"$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
.venv/bin/python -c "import numpy, soxr, sounddevice, tkinter, sherpa_onnx, opencc; print('ok')"
```
Expected: 印出 `ok`，且 `pip list` 內沒有 PyAudioWPatch。

- [ ] **Step 3: 建 tests 套件並把 src 加進路徑**

`tests/__init__.py`：
```python
"""測試套件。把 src/ 加進 sys.path，這樣不設 PYTHONPATH 也能跑。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
```

- [ ] **Step 4: 確認測試框架能跑（零測試）**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: `Ran 0 tests` `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/__init__.py
git commit -m "requirements：依平台安裝 PyAudioWPatch / sounddevice；建立 tests 套件

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: audio/base.py — 兩平台共用的擷取基底

**Files:**
- Create: `src/cantonese_live/audio/base.py`
- Test: `tests/test_audio_base.py`

說明：這一步只新增檔案，不動舊的 `audio.py`，所以程式照常可用。`CaptureBase` 的邏輯是從 `audio.py` 的 `LoopbackCapture` 搬出來的，差別只有兩點：音訊進來的入口改成 `_ingest(samples)` 接 ndarray（1-D 交錯或 2-D (frames, ch) 都收），以及開關串流交給子類別的 `start()` / `_close_stream()` / `_stream_active()`。

**Interfaces:**
- Produces:
  ```python
  TARGET_RATE: int = 16_000
  class AudioError(RuntimeError)
  @dataclass(frozen=True) class Device: index: int; name: str; rate: int; channels: int
  class CaptureBase:
      def __init__(self, device: Device, block_ms: int = 64, queue_seconds: float = 30.0,
                   on_overflow: Callable[[int], None] | None = None)
      frames_per_block: int            # 屬性
      def start(self) -> None          # 子類別實作
      def stop(self) -> None           # 通用，最後呼叫 self._close_stream()
      def _close_stream(self) -> None  # 子類別實作
      def _stream_active(self) -> bool # 子類別實作
      alive: bool                      # 屬性 = not stopped and _stream_active()
      def _ingest(self, samples: np.ndarray) -> None   # 回呼執行緒呼叫
      def _fail(self, exc: BaseException) -> None      # 回呼出錯時呼叫
      def read(self, timeout: float = 0.5) -> np.ndarray | None
      def blocks(self, timeout: float = 0.5) -> Iterator[np.ndarray]
      dropped_samples: int
      __enter__ / __exit__
  ```

- [ ] **Step 1: 寫失敗的測試**

`tests/test_audio_base.py`：
```python
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


class ToMono16kTests(unittest.TestCase):
    def test_resample_48000_stereo_interleaved(self):
        cap = FakeCapture(Device(0, "x", 48000, 2))
        cap._ingest(sine(48000, 1.0, channels=2, interleaved=True))
        got = np.concatenate([b for b in iter(lambda: cap.read(0.01), None)
                              if b.size] or [np.empty(0)])
        self.assertTrue(15000 <= got.size <= 16000, got.size)

    def test_resample_44100(self):
        cap = FakeCapture(Device(0, "x", 44100, 1))
        cap._ingest(sine(44100, 1.0))
        total = sum(b.size for b in self._drain(cap))
        self.assertTrue(15000 <= total <= 16000, total)

    def test_2d_and_interleaved_agree(self):
        a = FakeCapture(Device(0, "x", 48000, 2))
        b = FakeCapture(Device(0, "x", 48000, 2))
        a._ingest(sine(48000, 0.5, channels=2, interleaved=True))
        b._ingest(sine(48000, 0.5, channels=2, interleaved=False))
        xa = np.concatenate(self._drain(a))
        xb = np.concatenate(self._drain(b))
        np.testing.assert_allclose(xa, xb, atol=1e-6)

    def test_16k_mono_passthrough(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 1))
        x = sine(TARGET_RATE, 0.2)
        cap._ingest(x)
        got = np.concatenate(self._drain(cap))
        np.testing.assert_array_equal(got, x)

    def test_odd_tail_sample_is_dropped_not_crashed(self):
        cap = FakeCapture(Device(0, "x", TARGET_RATE, 2))
        cap._ingest(np.zeros(7, dtype=np.float32))   # 7 不是 2 的倍數
        got = np.concatenate(self._drain(cap))
        self.assertEqual(got.size, 3)

    def _drain(self, cap):
        out = []
        while True:
            b = cap.read(0.01)
            if b is None or b.size == 0:
                return out or [np.empty(0, dtype=np.float32)]
            out.append(b)


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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m unittest tests.test_audio_base -v`
Expected: `ModuleNotFoundError: No module named 'cantonese_live.audio.base'`（`audio` 目前是模組不是套件）

- [ ] **Step 3: 寫 base.py**

`src/cantonese_live/audio/base.py`：
```python
"""兩個平台共用的擷取基底：混單聲道、重採樣到 16kHz、環形緩衝。

子類別只負責「開一條音訊串流，把每個回呼的樣本交給 _ingest()」。
輸出一律是 16kHz 單聲道 float32，這是 Silero VAD 和 SenseVoice 要的格式。
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
import soxr

TARGET_RATE = 16_000


class AudioError(RuntimeError):
    """找不到裝置、或音訊串流開不起來。"""


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    rate: int
    channels: int

    def __str__(self) -> str:
        return f"[{self.index}] {self.name} ({self.rate} Hz, {self.channels} ch)"


class CaptureBase:
    """背景擷取音訊，轉成 16kHz 單聲道。

    用法（透過 audio.LoopbackCapture 建立實例）：

        with LoopbackCapture() as cap:
            for block in cap.blocks():
                ...  # block 是 float32 ndarray

    音訊是在音訊回呼執行緒裡收的，混音與重採樣也在那裡做完
    （soxr 處理一個 64ms 區塊只要幾十微秒，不會拖慢回呼）。
    消費端跟不上時會丟掉最舊的資料而不是無限長大 —— 開會時寧可漏掉
    幾百毫秒，也不要讓程式吃爆記憶體。
    """

    def __init__(
        self,
        device: Device,
        block_ms: int = 64,
        queue_seconds: float = 30.0,
        on_overflow: Callable[[int], None] | None = None,
    ) -> None:
        self.device = device
        self.block_ms = max(16, int(block_ms))
        self._on_overflow = on_overflow

        self.frames_per_block = max(64, int(device.rate * self.block_ms / 1000))
        self._resampler = (
            soxr.ResampleStream(device.rate, TARGET_RATE, 1, dtype="float32")
            if device.rate != TARGET_RATE
            else None
        )

        self._max_samples = int(TARGET_RATE * queue_seconds)
        self._buffer: deque[np.ndarray] = deque()
        self._buffered = 0
        self._dropped = 0
        self._lock = threading.Lock()
        self._data_ready = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._error: BaseException | None = None

    # -- 子類別要實作的 -----------------------------------------------------

    def start(self) -> None:
        raise NotImplementedError

    def _close_stream(self) -> None:
        raise NotImplementedError

    def _stream_active(self) -> bool:
        raise NotImplementedError

    # -- 生命週期 ---------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        with self._data_ready:
            self._data_ready.notify_all()
        self._close_stream()

    def __enter__(self) -> "CaptureBase":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    @property
    def alive(self) -> bool:
        return not self._stop.is_set() and self._stream_active()

    # -- 回呼執行緒呼叫 ---------------------------------------------------

    def _ingest(self, samples: np.ndarray) -> None:
        """收一塊原始樣本。1-D 視為交錯多聲道，2-D 視為 (frames, channels)。"""
        try:
            mono = self._to_mono_16k(samples)
            if mono.size:
                self._push(mono)
        except BaseException as exc:  # 回呼裡不能讓例外逃出去
            self._fail(exc)

    def _fail(self, exc: BaseException) -> None:
        self._error = exc
        self._stop.set()
        with self._data_ready:
            self._data_ready.notify_all()

    def _to_mono_16k(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if x.ndim == 2:
            x = x.mean(axis=1) if x.shape[1] > 1 else np.array(x[:, 0])
        elif self.device.channels > 1:
            # 丟掉不完整的尾巴，再把各聲道平均成單聲道
            usable = (x.size // self.device.channels) * self.device.channels
            x = x[:usable].reshape(-1, self.device.channels).mean(axis=1)
        if self._resampler is not None:
            # ResampleStream 會視內部濾波器狀態回傳 0 到數百個樣本，
            # 空陣列是正常的，不是錯誤。
            x = self._resampler.resample_chunk(np.ascontiguousarray(x))
        return np.asarray(x, dtype=np.float32)

    def _push(self, block: np.ndarray) -> None:
        with self._data_ready:
            self._buffer.append(block)
            self._buffered += block.size
            dropped_now = 0
            while self._buffered > self._max_samples and self._buffer:
                old = self._buffer.popleft()
                self._buffered -= old.size
                dropped_now += old.size
            if dropped_now:
                self._dropped += dropped_now
                if self._on_overflow is not None:
                    self._on_overflow(dropped_now)
            self._data_ready.notify()

    # -- 消費端 -----------------------------------------------------------

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        """取出一塊音訊。沒資料就等到 timeout，串流結束時回傳 None。"""
        with self._data_ready:
            while not self._buffer and not self._stop.is_set():
                if not self._data_ready.wait(timeout):
                    return np.empty(0, dtype=np.float32)
            if self._error is not None:
                err, self._error = self._error, None
                raise AudioError(f"音訊擷取中斷：{err}") from err
            if not self._buffer:
                return None
            block = self._buffer.popleft()
            self._buffered -= block.size
            return block

    def blocks(self, timeout: float = 0.5) -> Iterator[np.ndarray]:
        """持續產出音訊塊，直到 stop() 被呼叫。"""
        while True:
            block = self.read(timeout)
            if block is None:
                return
            if block.size:
                yield block

    @property
    def dropped_samples(self) -> int:
        return self._dropped
```

注意：這一步 `audio.py` 與 `audio/` 目錄同時存在，Python 會優先載入套件 `audio/`，但套件還沒有 `__init__.py` 導出介面，所以 **在 Task 3 完成前 `python -m cantonese_live` 會壞**。Task 2 與 Task 3 要連續做完。

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m unittest tests.test_audio_base -v`
Expected: 11 tests `OK`

- [ ] **Step 5: Commit**

```bash
git add src/cantonese_live/audio/base.py tests/test_audio_base.py
git commit -m "audio：抽出平台共用的 CaptureBase（混音、重採樣、緩衝）

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: audio/windows.py 搬移 + audio/__init__.py 門面 + 刪除 audio.py

**Files:**
- Create: `src/cantonese_live/audio/windows.py`
- Create: `src/cantonese_live/audio/__init__.py`
- Create: `src/cantonese_live/audio/__main__.py`
- Delete: `src/cantonese_live/audio.py`
- Test: `tests/test_audio_facade.py`

**Interfaces:**
- Consumes: `base.CaptureBase`, `base.Device`, `base.AudioError`, `base.TARGET_RATE`
- Produces（`cantonese_live.audio` 對外）:
  ```python
  Device, AudioError, TARGET_RATE, CaptureBase
  def list_loopback_devices() -> list[Device]
  def resolve_device(spec: str = "") -> Device
  def LoopbackCapture(device: Device | None = None, device_spec: str = "", block_ms: int = 64,
                      queue_seconds: float = 30.0, on_overflow=None) -> CaptureBase   # 工廠函式
  def routing_hint() -> str | None
  def setup_help() -> str
  ```
- 每個後端模組必須提供：`list_devices()`, `resolve_device(spec)`, `open_capture(device, block_ms, queue_seconds, on_overflow)`, `routing_hint()`, `SETUP_HELP: str`

- [ ] **Step 1: 寫失敗的門面測試**

`tests/test_audio_facade.py`：
```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m unittest tests.test_audio_facade -v`
Expected: `ImportError`（`audio/__init__.py` 不存在）或 `AttributeError: _BACKEND`

- [ ] **Step 3: 寫 windows.py（從 audio.py 搬）**

`src/cantonese_live/audio/windows.py`：
```python
"""Windows 後端：WASAPI loopback，錄「電腦播出去的聲音」。

你自己的麥克風完全不會被錄到，因為我們根本沒有開啟任何輸入裝置。
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio

from .base import AudioError, CaptureBase, Device

SETUP_HELP = (
    "找不到任何 WASAPI loopback 裝置。\n"
    "請確認 Windows 音效設定裡至少有一個啟用的播放裝置。"
)


def _dev(info: dict) -> Device:
    return Device(
        index=int(info["index"]),
        name=str(info["name"]),
        rate=int(info["defaultSampleRate"]),
        channels=int(info["maxInputChannels"]),
    )


def list_devices() -> list[Device]:
    """列出所有可用的 loopback 裝置（每個喇叭/耳機各一個）。"""
    pa = pyaudio.PyAudio()
    try:
        return [_dev(d) for d in pa.get_loopback_device_info_generator()]
    except OSError as exc:
        raise AudioError(f"無法列舉 WASAPI 裝置：{exc}") from exc
    finally:
        pa.terminate()


def resolve_device(spec: str = "") -> Device:
    """把設定檔裡的 device 字串解析成實際裝置。

    spec 為空        -> 目前「預設輸出裝置」的 loopback（跟著系統設定走）
    spec 是數字      -> 直接當裝置索引
    spec 是文字      -> 比對裝置名稱（不分大小寫的子字串比對）
    """
    pa = pyaudio.PyAudio()
    try:
        spec = spec.strip()

        if not spec:
            try:
                return _dev(pa.get_default_wasapi_loopback())
            except OSError as exc:
                raise AudioError(
                    f"WASAPI 驅動不可用：{exc}\n"
                    "這個工具需要 Windows Vista 以後的 WASAPI 支援。"
                ) from exc
            except LookupError as exc:
                raise AudioError(
                    "找不到預設輸出裝置的 loopback。\n"
                    "請確認 Windows 音效設定裡有啟用的播放裝置，"
                    "然後用 --list-devices 看看有哪些可選。"
                ) from exc

        if spec.isdigit():
            idx = int(spec)
            try:
                info = pa.get_device_info_by_index(idx)
            except OSError as exc:
                raise AudioError(f"裝置索引 {idx} 不存在：{exc}") from exc
            if int(info["maxInputChannels"]) < 1:
                raise AudioError(
                    f"裝置 [{idx}] {info['name']} 不能當輸入用。\n"
                    "你要的應該是名稱帶 [Loopback] 的那一個，"
                    "用 --list-devices 查看。"
                )
            return _dev(info)

        needle = spec.casefold()
        matches = [d for d in (_dev(x) for x in pa.get_loopback_device_info_generator())
                   if needle in d.name.casefold()]
        if not matches:
            available = "\n".join(f"  {d}" for d in list_devices())
            raise AudioError(
                f"沒有 loopback 裝置的名稱包含 {spec!r}。\n可選的有：\n{available}"
            )
        return matches[0]
    finally:
        pa.terminate()


class WasapiCapture(CaptureBase):
    def __init__(self, device: Device, **kw) -> None:
        super().__init__(device, **kw)
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None

    def start(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self.device.channels,
                rate=self.device.rate,
                input=True,
                input_device_index=self.device.index,
                frames_per_buffer=self.frames_per_block,
                stream_callback=self._callback,
            )
        except OSError as exc:
            self._pa.terminate()
            self._pa = None
            raise AudioError(
                f"無法開啟 {self.device}：{exc}\n"
                "常見原因：裝置被其他程式獨佔、或該裝置已被停用。"
            ) from exc
        self._stream.start_stream()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def _stream_active(self) -> bool:
        return self._stream is not None and self._stream.is_active()

    def _callback(self, in_data, frame_count, time_info, status):  # noqa: ARG002
        if self._stop.is_set():
            return (None, pyaudio.paComplete)
        self._ingest(np.frombuffer(in_data, dtype=np.float32))
        if self._stop.is_set():          # _ingest 內部出錯會 set
            return (None, pyaudio.paAbort)
        return (None, pyaudio.paContinue)


def open_capture(
    device: Device,
    block_ms: int,
    queue_seconds: float,
    on_overflow: Callable[[int], None] | None,
) -> CaptureBase:
    return WasapiCapture(device, block_ms=block_ms, queue_seconds=queue_seconds,
                         on_overflow=on_overflow)


def routing_hint() -> str | None:
    """Windows 直接錄喇叭輸出，沒有路徑設定問題。"""
    return None
```

- [ ] **Step 4: 寫 __init__.py 門面**

`src/cantonese_live/audio/__init__.py`：
```python
"""音訊擷取：錄「電腦播出去的聲音」，也就是會議中對方的聲音。

    Windows  WASAPI loopback，直接錄喇叭輸出（windows.py）
    macOS    從 BlackHole 虛擬裝置錄音，使用者需把系統輸出設成
             含 BlackHole 的多重輸出裝置（macos.py）

輸出一律是 16kHz 單聲道 float32。後端依 sys.platform 延遲載入，
所以 Mac 上不會 import PyAudioWPatch，Windows 上不會 import sounddevice。
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Callable

from .base import TARGET_RATE, AudioError, CaptureBase, Device

__all__ = [
    "AudioError", "CaptureBase", "Device", "TARGET_RATE",
    "LoopbackCapture", "list_loopback_devices", "resolve_device",
    "routing_hint", "setup_help",
]

_BACKEND: ModuleType | None = None


def _backend() -> ModuleType:
    global _BACKEND
    if _BACKEND is None:
        if sys.platform == "win32":
            from . import windows as mod
        elif sys.platform == "darwin":
            from . import macos as mod
        else:
            raise AudioError("目前只支援 Windows 與 macOS")
        _BACKEND = mod
    return _BACKEND


def list_loopback_devices() -> list[Device]:
    """列出所有可以拿來錄「播出去的聲音」的裝置。"""
    return _backend().list_devices()


def resolve_device(spec: str = "") -> Device:
    """把設定檔裡的 device 字串解析成實際裝置。語意見各後端說明。"""
    return _backend().resolve_device(spec)


def LoopbackCapture(  # noqa: N802  保留舊名字，呼叫端程式碼不用改
    device: Device | None = None,
    device_spec: str = "",
    block_ms: int = 64,
    queue_seconds: float = 30.0,
    on_overflow: Callable[[int], None] | None = None,
) -> CaptureBase:
    """建立目前平台的擷取器。用法：

        with LoopbackCapture() as cap:
            for block in cap.blocks():
                ...
    """
    backend = _backend()
    dev = device or backend.resolve_device(device_spec)
    return backend.open_capture(dev, block_ms, queue_seconds, on_overflow)


def routing_hint() -> str | None:
    """收音路徑有疑慮時回傳一段給使用者看的說明，正常回 None。

    任何內部錯誤都吞掉回 None —— 這只是提示，不能影響主功能。
    """
    try:
        return _backend().routing_hint()
    except Exception:
        return None


def setup_help() -> str:
    """找不到裝置時，印給使用者的平台專屬指引。"""
    return _backend().SETUP_HELP
```

- [ ] **Step 5: 寫 __main__.py（原 audio.py 的 _main）**

`src/cantonese_live/audio/__main__.py`：
```python
"""python -m cantonese_live.audio —— 列出裝置並做 3 秒擷取測試。"""

from __future__ import annotations

import sys
import time

import numpy as np

from . import TARGET_RATE, LoopbackCapture, list_loopback_devices, resolve_device, routing_hint


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("可用的裝置：")
    for d in list_loopback_devices():
        print(f"  {d}")

    dev = resolve_device()
    print(f"\n預設裝置：{dev}")
    hint = routing_hint()
    if hint:
        print(f"\n注意：{hint}\n")
    print("擷取 3 秒（請確保電腦正在播放聲音）...")

    with LoopbackCapture(device=dev) as cap:
        chunks, deadline = [], time.monotonic() + 3.0
        while time.monotonic() < deadline:
            block = cap.read(0.2)
            if block is None:
                break
            if block.size:
                chunks.append(block)

    if not chunks:
        print("沒有收到任何音訊。")
        return 1
    audio = np.concatenate(chunks)
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio ** 2)))
    print(f"收到 {audio.size} 個樣本 = {audio.size / TARGET_RATE:.2f} 秒 "
          f"@ {TARGET_RATE} Hz")
    print(f"峰值 {peak:.4f}  RMS {rms:.4f}")
    print("靜音（電腦當時沒出聲？）" if peak < 1e-4 else "有收到聲音。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 先放一個最小的 macos.py 佈樁，讓門面在 Mac 上可 import**

`src/cantonese_live/audio/macos.py`（Task 4 會整個改寫）：
```python
"""macOS 後端（Task 4 實作）。"""

from __future__ import annotations

from .base import AudioError, Device

SETUP_HELP = "macOS 後端尚未實作。"


def list_devices() -> list[Device]:
    raise AudioError(SETUP_HELP)


def resolve_device(spec: str = "") -> Device:
    raise AudioError(SETUP_HELP)


def open_capture(device, block_ms, queue_seconds, on_overflow):
    raise AudioError(SETUP_HELP)


def routing_hint() -> str | None:
    return None
```

- [ ] **Step 7: 刪除舊的 audio.py**

```bash
git rm -q src/cantonese_live/audio.py
```

- [ ] **Step 8: 跑測試確認通過**

Run: `.venv/bin/python -m unittest tests.test_audio_facade tests.test_audio_base -v`
Expected: 全部 `OK`

另外確認 pipeline 與 cli 還能 import：
Run: `PYTHONPATH=src .venv/bin/python -c "import cantonese_live.cli, cantonese_live.pipeline; print('ok')"`
Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add src/cantonese_live/audio/ tests/test_audio_facade.py
git commit -m "audio：拆成套件，Windows WASAPI 後端原封搬入，依平台延遲載入後端

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: audio/macos.py — 裝置列舉、解析與 sounddevice 擷取

**Files:**
- Modify: `src/cantonese_live/audio/macos.py`（整個改寫）
- Test: `tests/test_audio_macos.py`

**Interfaces:**
- Consumes: `base.CaptureBase`, `base.Device`, `base.AudioError`
- Produces:
  ```python
  SETUP_HELP: str
  def list_devices(query=None) -> list[Device]      # query: () -> list[dict]，測試注入用
  def resolve_device(spec: str = "", query=None) -> Device
  class SoundDeviceCapture(CaptureBase)
  def open_capture(device, block_ms, queue_seconds, on_overflow, stream_cls=None) -> CaptureBase
  def routing_hint(route_fn=None) -> str | None     # Task 5 實作，本任務先回 None
  ```
  `query()` 回傳的 dict 與 `sounddevice.query_devices()` 每一項相同：`name`, `max_input_channels`, `max_output_channels`, `default_samplerate`，以清單位置當 index。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_audio_macos.py`：
```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m unittest tests.test_audio_macos -v`
Expected: 多數 FAIL / ERROR（佈樁的函式都丟 `AudioError("macOS 後端尚未實作。")`，`open_capture` 不接受 `stream_cls`）

- [ ] **Step 3: 改寫 macos.py**

`src/cantonese_live/audio/macos.py`：
```python
"""macOS 後端：從 BlackHole 虛擬裝置錄音。

macOS 沒有像 WASAPI loopback 那樣直接錄「喇叭輸出」的開放介面，所以借道
BlackHole：使用者把系統輸出設成「多重輸出裝置」（喇叭或 AirPods + BlackHole），
系統聲音就會同時送到喇叭和 BlackHole，我們再把 BlackHole 當輸入裝置錄下來。

    brew install --cask blackhole-2ch
    音訊 MIDI 設定 → ＋ → 建立多重輸出裝置 → 勾喇叭（或 AirPods）和 BlackHole 2ch
    選單列音量圖示 → 選那個多重輸出裝置

device 設定的語意：
    ""      名稱含 BlackHole 的輸入裝置（有多個時取聲道最少的，通常是 2ch）
    數字    sounddevice 的裝置索引，必須有輸入聲道
    文字    輸入裝置名稱的子字串（不分大小寫），所以其他虛擬裝置也能用
"""

from __future__ import annotations

from typing import Callable

import sounddevice as sd

from .base import AudioError, CaptureBase, Device

BLACKHOLE = "blackhole"

SETUP_HELP = (
    "找不到可以收音的裝置。\n"
    "macOS 需要 BlackHole 虛擬裝置才能錄到系統聲音：\n"
    "  brew install --cask blackhole-2ch\n"
    "裝好後在「音訊 MIDI 設定」建一個多重輸出裝置（喇叭 + BlackHole 2ch），\n"
    "並在選單列音量圖示選它。詳見 README 的 macOS 章節。"
)

_MULTI_OUTPUT_STEPS = (
    "請在「音訊 MIDI 設定」建一個多重輸出裝置（喇叭或 AirPods + BlackHole 2ch），"
    "並在選單列音量圖示選它。"
)


def _query_devices() -> list[dict]:
    return [dict(d) for d in sd.query_devices()]


def _dev(index: int, info: dict) -> Device:
    return Device(
        index=index,
        name=str(info["name"]),
        rate=int(round(float(info["default_samplerate"]))),
        channels=int(info["max_input_channels"]),
    )


def _is_blackhole(name: str) -> bool:
    return BLACKHOLE in name.casefold()


def _inputs(query: Callable[[], list[dict]]) -> list[Device]:
    try:
        raw = query()
    except Exception as exc:
        raise AudioError(f"無法列舉音訊裝置：{exc}") from exc
    return [_dev(i, d) for i, d in enumerate(raw) if int(d["max_input_channels"]) > 0]


def list_devices(query: Callable[[], list[dict]] | None = None) -> list[Device]:
    """列出所有有輸入聲道的裝置，BlackHole 排最前（聲道少的優先）。"""
    devs = _inputs(query or _query_devices)
    return sorted(devs, key=lambda d: (not _is_blackhole(d.name), d.channels, d.index))


def resolve_device(spec: str = "", query: Callable[[], list[dict]] | None = None) -> Device:
    query = query or _query_devices
    spec = spec.strip()

    if not spec:
        candidates = [d for d in list_devices(query) if _is_blackhole(d.name)]
        if not candidates:
            raise AudioError(
                "找不到 BlackHole 裝置。\n"
                "macOS 需要它才能錄到系統聲音：\n"
                "  brew install --cask blackhole-2ch\n"
                "裝好後重新執行。如果你用的是別的虛擬音訊裝置，"
                "請在 config.toml 的 [audio] device 填它的名稱，"
                "用 --list-devices 查看有哪些。"
            )
        return candidates[0]

    if spec.isdigit():
        idx = int(spec)
        try:
            raw = query()
        except Exception as exc:
            raise AudioError(f"無法列舉音訊裝置：{exc}") from exc
        if idx >= len(raw):
            raise AudioError(f"裝置索引 {idx} 不存在，用 --list-devices 查看。")
        info = raw[idx]
        if int(info["max_input_channels"]) < 1:
            raise AudioError(
                f"裝置 [{idx}] {info['name']} 不能當輸入用。\n"
                "在 macOS 上要錄的是 BlackHole（或其他虛擬輸入裝置），"
                "用 --list-devices 查看。"
            )
        return _dev(idx, info)

    needle = spec.casefold()
    try:
        raw = query()
    except Exception as exc:
        raise AudioError(f"無法列舉音訊裝置：{exc}") from exc
    named = [(i, d) for i, d in enumerate(raw) if needle in str(d["name"]).casefold()]
    if not named:
        available = "\n".join(f"  {d}" for d in list_devices(query))
        raise AudioError(
            f"沒有裝置的名稱包含 {spec!r}。\n可選的有：\n{available}"
        )
    usable = [(i, d) for i, d in named if int(d["max_input_channels"]) > 0]
    if not usable:
        i, d = named[0]
        raise AudioError(
            f"裝置 [{i}] {d['name']} 不能當輸入用。\n"
            "在 macOS 上要錄的是 BlackHole（或其他虛擬輸入裝置），"
            "用 --list-devices 查看。"
        )
    usable.sort(key=lambda pair: (int(pair[1]["max_input_channels"]), pair[0]))
    return _dev(*usable[0])


class SoundDeviceCapture(CaptureBase):
    def __init__(self, device: Device, stream_cls=None, **kw) -> None:
        super().__init__(device, **kw)
        self._stream_cls = stream_cls or sd.InputStream
        self._stream = None

    def start(self) -> None:
        try:
            self._stream = self._stream_cls(
                device=self.device.index,
                channels=self.device.channels,
                samplerate=self.device.rate,
                dtype="float32",
                blocksize=self.frames_per_block,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioError(
                f"無法開啟 {self.device}：{exc}\n"
                "常見原因：裝置被拔掉、BlackHole 剛安裝還沒生效（登出再登入）、"
                "或系統設定 → 隱私權與安全性 → 麥克風 沒有允許終端機。"
            ) from exc

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _stream_active(self) -> bool:
        return self._stream is not None and bool(getattr(self._stream, "active", True))

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if self._stop.is_set():
            return
        # indata 是 (frames, channels) 的 float32，PortAudio 會重用這塊記憶體，
        # _to_mono_16k 的 mean/copy 會產生新陣列，所以這裡不用再 copy。
        self._ingest(indata)


def open_capture(
    device: Device,
    block_ms: int,
    queue_seconds: float,
    on_overflow: Callable[[int], None] | None,
    stream_cls=None,
) -> CaptureBase:
    return SoundDeviceCapture(device, stream_cls=stream_cls, block_ms=block_ms,
                              queue_seconds=queue_seconds, on_overflow=on_overflow)


def routing_hint(route_fn=None) -> str | None:
    """Task 5 實作。"""
    return None
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/python -m unittest tests.test_audio_macos -v`
Expected: 13 tests `OK`

- [ ] **Step 5: 在真實裝置上列一次**

Run: `PYTHONPATH=src .venv/bin/python -m cantonese_live --list-devices`
Expected（BlackHole 尚未安裝時）: 列出麥克風，然後 `resolve_device("")` 的 `AudioError` 被 cli 接住印出 brew 指令，exit 1。不崩潰即可。

- [ ] **Step 6: Commit**

```bash
git add src/cantonese_live/audio/macos.py tests/test_audio_macos.py
git commit -m "audio：macOS 後端 —— 列舉/解析 BlackHole 裝置，sounddevice 擷取

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 收音路徑健檢 — _coreaudio.py 與 routing_hint()

**Files:**
- Create: `src/cantonese_live/audio/_coreaudio.py`
- Modify: `src/cantonese_live/audio/macos.py`（`routing_hint`）
- Test: `tests/test_audio_macos.py`（新增 `RoutingHintTests`）

**Interfaces:**
- Produces:
  ```python
  # _coreaudio.py
  @dataclass(frozen=True) class OutputRoute: name: str; is_aggregate: bool; sub_names: tuple[str, ...]
  def default_output_route() -> OutputRoute      # 任何失敗丟 OSError
  # macos.py
  def routing_hint(route_fn: Callable[[], OutputRoute] | None = None) -> str | None
  ```

已在本機驗證過的 ctypes 事實：CoreAudio 位於 `/System/Library/Frameworks/CoreAudio.framework/CoreAudio`；`kAudioObjectSystemObject = 1`；屬性選擇子用 FourCC（`'dOut'` 預設輸出、`'tran'` 傳輸類型、`'grup'` 聚合裝置、`'agrp'` 聚合裝置的子裝置 ID 陣列、`'lnam'` 名稱 CFString）；**必須設 argtypes**，否則 64 位元指標會被截成 int 而 segfault。

- [ ] **Step 1: 寫失敗的測試（加到 tests/test_audio_macos.py 末尾、`if __name__` 之前）**

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m unittest tests.test_audio_macos.RoutingHintTests -v`
Expected: `ImportError`（`_coreaudio` 不存在）

- [ ] **Step 3: 寫 _coreaudio.py**

`src/cantonese_live/audio/_coreaudio.py`：
```python
"""用 ctypes 直接問 CoreAudio：目前的預設輸出裝置是誰、是不是多重輸出裝置、
裡面有哪些子裝置。只給 macos.routing_hint() 做收音路徑健檢用。

任何失敗一律丟 OSError，由呼叫端決定要不要忽略。
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

_CA_PATH = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
_CF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

_SYSTEM_OBJECT = 1
_CF_UTF8 = 0x08000100


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


SEL_DEFAULT_OUTPUT = _fourcc("dOut")
SEL_TRANSPORT_TYPE = _fourcc("tran")
SEL_DEVICE_NAME = _fourcc("lnam")
SEL_AGGREGATE_SUBDEVICES = _fourcc("agrp")
SCOPE_GLOBAL = _fourcc("glob")
TRANSPORT_AGGREGATE = _fourcc("grup")


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class OutputRoute:
    name: str
    is_aggregate: bool
    sub_names: tuple[str, ...]


_libs: tuple[ctypes.CDLL, ctypes.CDLL] | None = None


def _load() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    global _libs
    if _libs is None:
        ca = ctypes.CDLL(_CA_PATH)
        cf = ctypes.CDLL(_CF_PATH)
        ca.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(_PropertyAddress), ctypes.c_uint32,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ]
        ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        ca.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(_PropertyAddress), ctypes.c_uint32,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
        ]
        ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFRelease.restype = None
        _libs = (ca, cf)
    return _libs


def _get_scalar(obj: int, selector: int, ctype):
    ca, _ = _load()
    addr = _PropertyAddress(selector, SCOPE_GLOBAL, 0)
    size = ctypes.c_uint32(ctypes.sizeof(ctype))
    out = ctype()
    status = ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None,
                                           ctypes.byref(size), ctypes.byref(out))
    if status != 0:
        raise OSError(status, f"AudioObjectGetPropertyData({selector:#x}) 失敗")
    return out.value


def _get_u32_array(obj: int, selector: int) -> list[int]:
    ca, _ = _load()
    addr = _PropertyAddress(selector, SCOPE_GLOBAL, 0)
    size = ctypes.c_uint32()
    status = ca.AudioObjectGetPropertyDataSize(obj, ctypes.byref(addr), 0, None,
                                               ctypes.byref(size))
    if status != 0:
        raise OSError(status, "AudioObjectGetPropertyDataSize 失敗")
    count = size.value // ctypes.sizeof(ctypes.c_uint32)
    if count == 0:
        return []
    arr = (ctypes.c_uint32 * count)()
    status = ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None,
                                           ctypes.byref(size), arr)
    if status != 0:
        raise OSError(status, "AudioObjectGetPropertyData(array) 失敗")
    return list(arr)


def _device_name(device_id: int) -> str:
    """讀不到名稱時回空字串，不丟例外 —— 一個子裝置壞掉不該讓整個健檢失敗。"""
    _, cf = _load()
    try:
        ref = _get_scalar(device_id, SEL_DEVICE_NAME, ctypes.c_void_p)
    except OSError:
        return ""
    if not ref:
        return ""
    try:
        buf = ctypes.create_string_buffer(512)
        ok = cf.CFStringGetCString(ref, buf, len(buf), _CF_UTF8)
        return buf.value.decode("utf-8", errors="replace") if ok else ""
    finally:
        cf.CFRelease(ref)


def default_output_route() -> OutputRoute:
    device_id = _get_scalar(_SYSTEM_OBJECT, SEL_DEFAULT_OUTPUT, ctypes.c_uint32)
    if device_id == 0:
        raise OSError(0, "沒有預設輸出裝置")
    name = _device_name(device_id)
    transport = _get_scalar(device_id, SEL_TRANSPORT_TYPE, ctypes.c_uint32)
    if transport != TRANSPORT_AGGREGATE:
        return OutputRoute(name, False, ())
    subs = tuple(_device_name(sub) for sub in _get_u32_array(device_id, SEL_AGGREGATE_SUBDEVICES))
    return OutputRoute(name, True, subs)


if __name__ == "__main__":
    print(default_output_route())
```

- [ ] **Step 4: 實作 macos.routing_hint**

把 `macos.py` 末尾的 `routing_hint` 替換成：
```python
def routing_hint(route_fn=None) -> str | None:
    """系統輸出有沒有經過 BlackHole？有疑慮就回一段說明，正常回 None。

    這是 Mac 上最常見的失敗方式：BlackHole 裝了，但系統輸出沒選到含它的
    多重輸出裝置，程式就只會收到一片靜音。健檢本身任何失敗都回 None。
    """
    try:
        from . import _coreaudio
        route = (route_fn or _coreaudio.default_output_route)()
    except Exception:
        return None

    if _is_blackhole(route.name):
        return ("目前系統聲音只送到 BlackHole，你自己會聽不到對方說話。"
                + _MULTI_OUTPUT_STEPS)
    if route.is_aggregate and any(_is_blackhole(n) for n in route.sub_names):
        return None
    return (f"目前系統輸出是「{route.name or '未知裝置'}」，聲音沒有經過 BlackHole，"
            f"程式會收到靜音。" + _MULTI_OUTPUT_STEPS)
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/python -m unittest tests.test_audio_macos -v`
Expected: 19 tests `OK`

- [ ] **Step 6: 對真機跑一次探測**

Run: `PYTHONPATH=src .venv/bin/python -m cantonese_live.audio._coreaudio`
Expected: 類似 `OutputRoute(name='MacBook Pro的揚聲器', is_aggregate=False, sub_names=())`，不崩潰。

- [ ] **Step 7: Commit**

```bash
git add src/cantonese_live/audio/_coreaudio.py src/cantonese_live/audio/macos.py tests/test_audio_macos.py
git commit -m "audio：macOS 收音路徑健檢 —— 用 CoreAudio 判斷系統輸出是否經過 BlackHole

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: cli.py 平台中性化 + 健檢接線

**Files:**
- Modify: `src/cantonese_live/cli.py`

**Interfaces:**
- Consumes: `audio.setup_help()`, `audio.routing_hint()`

沒有自動化測試（cli 直接碰硬體與 Tk）；用 `--list-devices` 與 `--self-test` 手動驗證。

- [ ] **Step 1: 改 import**

把
```python
from .audio import AudioError, list_loopback_devices, resolve_device
```
改成
```python
from .audio import AudioError, list_loopback_devices, resolve_device, routing_hint, setup_help
```

- [ ] **Step 2: 改 `_cmd_list_devices`**

整個函式替換為：
```python
def _cmd_list_devices() -> int:
    devices = list_loopback_devices()
    if not devices:
        print(setup_help())
        return 1

    print("可用的裝置（錄的是這個裝置的聲音）：\n")
    try:
        default = resolve_device("")
    except AudioError:
        default = None
    for d in devices:
        mark = "  <- 預設" if default and d.index == default.index else ""
        print(f"  {d}{mark}")
    print("\n設定方式：在 config.toml 的 [audio] 填 device = \"名稱片段\" 或索引數字。")
    if sys.platform == "darwin":
        print("留空（device = \"\"）表示自動使用 BlackHole。")
        hint = routing_hint()
        if hint:
            print(f"\n注意：{hint}")
    else:
        print("留空（device = \"\"）表示自動跟著 Windows 的預設輸出裝置走。")
    return 0
```

- [ ] **Step 3: 自我檢查加健檢**

在 `_cmd_self_test` 的 `[1/3] 音訊裝置` 區塊，`print(f"  OK  {dev}")` 之後加：
```python
        hint = routing_hint()
        if hint:
            print(f"  !!  {hint}")
```
（縮排與 `print(f"  OK  {dev}")` 同層，在 `try` 內。）

結尾訊息改成平台中性：
```python
    run_cmd = "./run.sh" if sys.platform == "darwin" else "run.ps1"
    print("\n" + (f"全部正常，可以執行 {run_cmd} 開始使用。" if ok
                  else "有項目失敗，請看上面的訊息。"))
```

- [ ] **Step 4: 兩個 `_run_*` 啟動後加健檢**

`_run_console`：在 `print("\n開始收音。按 Ctrl+C 結束。\n")` 之前加：
```python
    hint = routing_hint()
    if hint:
        print(f"[注意] {hint}")
```

`_run_overlay`：在 `pipeline.start()` 之後、`overlay.notice(f"收音：...")` 之前加：
```python
    hint = routing_hint()
    if hint:
        overlay.status(hint.split("。")[0], "warn")
        overlay.notice(hint)
```

- [ ] **Step 5: 手動驗證**

```bash
PYTHONPATH=src .venv/bin/python -m cantonese_live --list-devices; echo "exit=$?"
PYTHONPATH=src .venv/bin/python -m cantonese_live --self-test; echo "exit=$?"
```
Expected（BlackHole 未裝）：list-devices 列出麥克風、無「<- 預設」標記、exit 0；self-test 第 1 步 `失敗  找不到 BlackHole 裝置...brew install --cask blackhole-2ch`，第 2 步模型若未下載則失敗（Task 10 的 setup.sh 會下載）。訊息內不得出現「WASAPI」。

- [ ] **Step 6: Commit**

```bash
git add src/cantonese_live/cli.py
git commit -m "cli：裝置訊息改由後端提供，啟動與自我檢查時顯示收音路徑健檢

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: 字型自動選擇 + macOS Command 快捷鍵

**Files:**
- Modify: `src/cantonese_live/config.py`（`UiConfig.font_family` 預設、新增 `default_font_family`）
- Modify: `src/cantonese_live/overlay.py`（`_apply_fonts`、`_bind_keys`、模組 docstring）
- Modify: `config.toml`（`[ui] font_family`）
- Test: `tests/test_config_font.py`

**Interfaces:**
- Produces: `config.default_font_family(platform: str | None = None) -> str`

- [ ] **Step 1: 寫失敗的測試**

`tests/test_config_font.py`：
```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/python -m unittest tests.test_config_font -v`
Expected: `ImportError: cannot import name 'default_font_family'`

- [ ] **Step 3: 改 config.py**

在 `UiConfig` 之前加函式：
```python
def default_font_family(platform: str | None = None) -> str:
    """各平台內建的繁體中文 UI 字型。"""
    platform = platform or sys.platform
    if platform == "win32":
        return "Microsoft JhengHei UI"
    if platform == "darwin":
        return "PingFang TC"
    return "TkDefaultFont"
```

`UiConfig` 的 `font_family` 改成：
```python
    # 空字串 = 自動：Windows 用 Microsoft JhengHei UI，macOS 用 PingFang TC。
    font_family: str = ""
```
並在 `UiConfig` 內加方法：
```python
    def resolved_font_family(self, platform: str | None = None) -> str:
        return self.font_family.strip() or default_font_family(platform)
```

- [ ] **Step 4: 改 overlay.py**

`_apply_fonts` 第一行 `family = self.cfg.font_family` 改成 `family = self.cfg.resolved_font_family()`。

`_bind_keys` 在 `r.bind("<space>", ...)` 之後、`r.focus_force()` 之前加：
```python
        if sys.platform == "darwin":
            r.bind("<Command-q>", lambda _e: self.close())
            r.bind("<Command-plus>", lambda _e: self._bump_font(+1))
            r.bind("<Command-equal>", lambda _e: self._bump_font(+1))
            r.bind("<Command-minus>", lambda _e: self._bump_font(-1))
            r.bind("<Command-Key-0>", lambda _e: self._reset_font())
```
檔頭 import 區加 `import sys`。模組 docstring 的鍵盤段落改成：
```
鍵盤：
    Esc / Ctrl+Q（Mac 也可 ⌘Q）   結束
    Ctrl + / -（Mac 也可 ⌘）       放大 / 縮小字級
    Ctrl + 0                       重設字級
    F                              切換是否顯示粵語原文
    T                              切換置頂
    空白鍵                         暫停／繼續捲動（想回看前面幾句時用）
```

- [ ] **Step 5: 改 config.toml**

`font_family = "Microsoft JhengHei UI"` 改成：
```toml
# 字型。留空 = 自動（Windows 用 Microsoft JhengHei UI，macOS 用 PingFang TC）。
font_family = ""
```

- [ ] **Step 6: 跑測試確認通過**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: 全部 `OK`

- [ ] **Step 7: Commit**

```bash
git add src/cantonese_live/config.py src/cantonese_live/overlay.py config.toml tests/test_config_font.py
git commit -m "ui：字型依平台自動選擇，macOS 加 Command 快捷鍵

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: tools/test_live_capture.py 平台播放

**Files:**
- Modify: `tools/test_live_capture.py`

- [ ] **Step 1: 改 play()**

把 `play` 函式替換為：
```python
def play(path: Path, done: threading.Event) -> None:
    """把檔案播到系統預設輸出裝置。Windows 用 winsound，macOS 用內建的 afplay。

    在 macOS 上這會經過多重輸出裝置到 BlackHole，所以這個測試驗證的
    就是完整的收音路徑。
    """
    try:
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["afplay", str(path)], check=True)
        else:
            print("[播放] 這個平台沒有內建播放器，請自行播放該檔案。", file=sys.stderr)
    except Exception as exc:
        print(f"[播放] 失敗：{exc}", file=sys.stderr)
    finally:
        done.set()
```

- [ ] **Step 2: 失敗訊息平台化**

把末尾 `if peak < 1e-4:` 區塊替換為：
```python
    if peak < 1e-4:
        print("\n失敗：收到的是靜音。")
        if sys.platform == "darwin":
            print("  1. 確認系統輸出選的是含 BlackHole 的多重輸出裝置（選單列音量圖示）")
            print("  2. 確認 BlackHole 已安裝：brew install --cask blackhole-2ch")
            print("  3. 用 ./run.sh --list-devices 看看是不是該指定別的裝置")
        else:
            print("  1. 確認喇叭/耳機沒有靜音，音量不是 0")
            print("  2. 確認 Windows 的預設輸出裝置就是你實際在用的那個")
            print("  3. 用 run.ps1 -List 看看是不是該指定別的裝置")
        return 1
```
並把 `print("\n注意：這台電腦的喇叭/耳機音量不能是靜音，否則 loopback 收不到訊號。\n")` 改成：
```python
    if sys.platform == "darwin":
        print("\n注意：系統輸出必須是含 BlackHole 的多重輸出裝置，否則收不到訊號。\n")
    else:
        print("\n注意：這台電腦的喇叭/耳機音量不能是靜音，否則 loopback 收不到訊號。\n")
```
檔頭 docstring 的指令範例加一行 `python tools/test_live_capture.py   # macOS 也一樣`。

- [ ] **Step 3: 確認可 import（不實跑，模型未必已下載）**

Run: `.venv/bin/python -c "import ast,sys; ast.parse(open('tools/test_live_capture.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 4: Commit**

```bash
git add tools/test_live_capture.py
git commit -m "tools：收音測試在 macOS 用 afplay 播放，失敗提示依平台

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: setup.sh 與 run.sh

**Files:**
- Create: `setup.sh`
- Create: `run.sh`

- [ ] **Step 1: 寫 setup.sh**

```bash
#!/bin/bash
# 在這台 Mac 上安裝粵語即時翻譯（裝 Python、BlackHole、建虛擬環境、下載模型）。
#
#   ./setup.sh                 一般安裝
#   ./setup.sh --with-claude   同時安裝 anthropic（要用 Claude 翻譯才需要）
#
# 重複執行是安全的 —— 已完成的步驤會跳過。
# 需要 Homebrew；安裝 BlackHole 那一步會要求輸入 macOS 密碼。
set -euo pipefail
cd "$(dirname "$0")"

WITH_CLAUDE=0
for arg in "$@"; do
  case "$arg" in
    --with-claude) WITH_CLAUDE=1 ;;
    *) echo "未知參數：$arg"; exit 2 ;;
  esac
done

step() { printf '\n\033[36m[%s] %s\033[0m\n' "$1" "$2"; }
ok()   { printf '  \033[32mOK\033[0m  %s\n' "$1"; }
warn() { printf '  \033[33m!!\033[0m  %s\n' "$1"; }

if [[ "$(uname)" != "Darwin" ]]; then
  echo "這個腳本只給 macOS 用。Windows 請執行 setup.ps1。"; exit 1
fi

step 1 "檢查 Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "  找不到 Homebrew。請先到 https://brew.sh 依指示安裝，再重新執行這個腳本。"
  exit 1
fi
ok "$(brew --version | head -1)"

step 2 "Python 3.12 與 Tk"
for formula in python@3.12 python-tk@3.12; do
  if brew list --versions "$formula" >/dev/null 2>&1; then
    ok "$formula 已安裝"
  else
    brew install "$formula"
  fi
done
PY="$(brew --prefix python@3.12)/bin/python3.12"
"$PY" -c "import tkinter" || { echo "  Tk 載入失敗，請重跑 brew install python-tk@3.12"; exit 1; }
ok "$("$PY" --version)"

step 3 "BlackHole 虛擬音訊裝置（錄系統聲音用）"
if brew list --cask --versions blackhole-2ch >/dev/null 2>&1; then
  ok "blackhole-2ch 已安裝"
else
  echo "  安裝時會要求輸入 macOS 密碼（驅動要放進 /Library/Audio）。"
  brew install --cask blackhole-2ch
  warn "BlackHole 剛裝好。如果稍後找不到裝置，登出再登入一次即可。"
fi

step 4 "建立虛擬環境 .venv 並安裝套件"
if [[ ! -x .venv/bin/python ]]; then
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
if [[ $WITH_CLAUDE -eq 1 ]]; then
  .venv/bin/python -m pip install --upgrade anthropic --quiet
  ok "anthropic 已安裝"
fi
ok "套件安裝完成"

step 5 "下載辨識模型（約 230MB，只需一次）"
.venv/bin/python tools/download_models.py

step 6 "自我檢查"
set +e
PYTHONPATH=src .venv/bin/python -m cantonese_live --self-test
SELF=$?
set -e

cat <<'EOF'

────────────────────────────────────────────────────────────
接下來只剩一步要手動做（macOS 沒有命令列方式）：

  1. 打開「音訊 MIDI 設定」（Spotlight 搜尋 Audio MIDI Setup）
  2. 左下角 ＋ → 「建立多重輸出裝置」
  3. 右側勾選：你的喇叭（MacBook Pro的揚聲器）和 BlackHole 2ch
     ↳ 用 AirPods 開會的話，再建一個：AirPods ＋ BlackHole 2ch
  4. 可以把它改名成「會議（喇叭）」「會議（AirPods）」方便辨認
  5. 開會前：選單列音量圖示 → 選對應的多重輸出裝置
     Zoom 裡的喇叭請選「與系統相同」

  注意：選了多重輸出裝置後，鍵盤音量鍵會失效（macOS 限制），
  請事先在「音訊 MIDI 設定」把音量調好，或用 AirPods 本身調。

然後執行：  ./run.sh
────────────────────────────────────────────────────────────
EOF
exit $SELF
```

- [ ] **Step 2: 寫 run.sh**

```bash
#!/bin/bash
# 啟動粵語即時翻譯。所有參數原樣交給程式：
#
#   ./run.sh                          用 config.toml 的設定啟動（置頂浮動視窗）
#   ./run.sh --list-devices           列出可用的音訊裝置
#   ./run.sh --self-test              檢查模型/裝置/翻譯器是否正常
#   ./run.sh --ui console             只用終端機，不開浮動視窗
#   ./run.sh --engine claude          這次改用 Claude 翻譯
#   ./run.sh --file samples/yue.wav   拿音檔測試，不需要收音
#   ./run.sh --no-transcript          這次不存逐字稿
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "找不到虛擬環境，請先執行： ./setup.sh"; exit 1
fi
if [[ ! -f models/sense-voice/model.int8.onnx ]]; then
  echo "找不到辨識模型，請先執行： ./setup.sh"; exit 1
fi

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$PWD/src"
exec .venv/bin/python -m cantonese_live "$@"
```

- [ ] **Step 3: 設執行權限並檢查語法**

```bash
chmod +x setup.sh run.sh
bash -n setup.sh && bash -n run.sh && echo "syntax ok"
./run.sh --help | head -3
```
Expected: `syntax ok`，然後 `--help` 印出 `usage: cantonese-live`（模型未下載時 run.sh 會先擋下，這時先跑 `.venv/bin/python tools/download_models.py` 再試）。

- [ ] **Step 4: Commit**

```bash
git add setup.sh run.sh
git commit -m "macOS 安裝與啟動腳本 setup.sh / run.sh

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 開頭段落**

把第一個條列的第一點
```
- **只錄電腦播出去的聲音**（WASAPI loopback）—— 你自己的麥克風完全不會被錄到，
  程式根本沒開啟任何輸入裝置
```
改成
```
- **只錄電腦播出去的聲音** —— Windows 用 WASAPI loopback，macOS 透過 BlackHole
  虛擬裝置。你自己的麥克風完全不會被錄到
```
並在「整個資料夾可複製到其他電腦使用」後加一點：
```
- **Windows 與 macOS 都能用**（macOS 需要一次性的 BlackHole 設定，見下）
```

- [ ] **Step 2: 安裝章節**

把 `## 安裝` 改名為 `## 安裝（Windows）`，內容不動。緊接著在 `## 使用` 之前加：

````markdown
## 安裝（macOS）

需要 [Homebrew](https://brew.sh)。

```bash
cd cantonese-live
./setup.sh                  # 裝 Python 3.12 + Tk、BlackHole、套件、模型，然後自我檢查
./setup.sh --with-claude    # 同時裝 Claude 翻譯的相依套件
```

安裝 BlackHole 時會要求輸入 macOS 密碼。

### 為什麼 Mac 需要 BlackHole

macOS 沒有提供「錄下喇叭正在播的聲音」的介面，所以借道
[BlackHole](https://github.com/ExistentialAudio/BlackHole) 這個免費的虛擬音訊裝置：
把系統輸出設成「多重輸出裝置」（喇叭 + BlackHole），系統聲音就同時送到喇叭和
BlackHole，程式再從 BlackHole 錄音。

`setup.sh` 跑完後要手動做一次（macOS 沒有命令列方式）：

1. 打開「音訊 MIDI 設定」（Spotlight 搜 Audio MIDI Setup）
2. 左下角 ＋ →「建立多重輸出裝置」
3. 勾選你的喇叭（MacBook Pro的揚聲器）和 BlackHole 2ch
4. 用 AirPods 開會的話，再建一個：AirPods + BlackHole 2ch（AirPods 要先連上）
5. 改名成「會議（喇叭）」「會議（AirPods）」方便辨認

開會前在選單列的音量圖示選對應的多重輸出裝置。Zoom 裡的喇叭選「與系統相同」；
Google Meet 在瀏覽器裡跟系統走，不用另外設。

程式啟動時會檢查系統輸出有沒有經過 BlackHole，沒有就在狀態列警告，
不會默默顯示一片空白。

**已知限制**

- 選了多重輸出裝置後，鍵盤音量鍵會失效。先在「音訊 MIDI 設定」把音量調好，或用 AirPods 本身調。
- AirPods 同時當麥克風時，藍牙會壓低對方聲音的取樣率；辨識仍可用，但比喇叭情境略差。
- macOS 沒有免安裝打包版，用「複製資料夾 + `./setup.sh`」。
````

- [ ] **Step 3: 使用章節**

在 `## 使用` 的 PowerShell 區塊後面加：

````markdown
macOS 對應指令（參數直接交給程式）：

```bash
./run.sh                           # 開始（置頂浮動視窗）
./run.sh --list-devices            # 列出可用的裝置
./run.sh --self-test               # 檢查模型/裝置/翻譯器
./run.sh --ui console              # 只用終端機文字
./run.sh --file 會議錄音.wav        # 辨識錄音檔並產出逐字稿
./run.sh --no-transcript           # 不留逐字稿
```
````

`第一次在一台新電腦上用，建議先跑這個確認收音路徑正常：` 的程式區塊改成兩行：
```
.\.venv\Scripts\python.exe tools\test_live_capture.py    # Windows
.venv/bin/python tools/test_live_capture.py              # macOS
```
其後那句「**喇叭或耳機不能靜音**」改成「Windows 上**喇叭或耳機不能靜音**，macOS 上**系統輸出必須是含 BlackHole 的多重輸出裝置**，否則收到的是無聲。」

視窗操作表格的 `Esc` / `Ctrl+Q` 列改成 `Esc` / `Ctrl+Q` / `⌘Q`；`Ctrl` `+` / `-` / `0` 列備註「Mac 也可用 ⌘」。

- [ ] **Step 4: 調校表格**

「換耳機後收不到聲音」那列的調整欄改成：`Windows：[audio] device 留空會自動跟著系統預設裝置。macOS：在選單列音量圖示改選含 BlackHole 的多重輸出裝置`。

- [ ] **Step 5: 複製到其他電腦**

方法一的文字後面加一句：`macOS 執行 ./setup.sh。` 方法二標題加「（僅 Windows）」。

- [ ] **Step 6: 專案結構**

把
```
  setup.ps1              安裝（找/裝 Python、建環境、下載模型）
  run.ps1                啟動
```
改成
```
  setup.ps1 / setup.sh   安裝（Windows / macOS）
  run.ps1 / run.sh       啟動（Windows / macOS）
```
把
```
    audio.py             WASAPI loopback 擷取
```
改成
```
    audio/
      base.py            共用：混單聲道、重採樣、緩衝
      windows.py         WASAPI loopback 擷取
      macos.py           從 BlackHole 錄音 + 收音路徑健檢
      _coreaudio.py      ctypes 問 CoreAudio 目前輸出裝置
```
並在 `tools/` 之前加
```
  tests/                 單元測試（python -m unittest discover -s tests）
```

- [ ] **Step 7: 用到的東西表格**

在 PyAudioWPatch 那列後加：
```
| [sounddevice](https://python-sounddevice.readthedocs.io) | macOS 從 BlackHole 錄音（PortAudio） |
| [BlackHole](https://github.com/ExistentialAudio/BlackHole) | macOS 虛擬音訊裝置，把系統聲音分一路給程式 |
```

- [ ] **Step 8: Commit**

```bash
git add README.md
git commit -m "README：macOS 安裝、BlackHole 多重輸出設定、對應指令與限制

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: 這台 Mac 的端對端驗證（含無邊框視窗決策）

**Files:**
- 可能修改: `src/cantonese_live/overlay.py`（只在 Step 4 驗證失敗時）

這個任務需要使用者在旁邊：Step 1 會要密碼，Step 2 要在圖形介面操作。

- [ ] **Step 1: 跑 setup.sh**

Run: `./setup.sh`
Expected: 六步全過；自我檢查第 1 步可能是 `失敗 找不到 BlackHole`（若剛裝好需登出登入）或 `OK BlackHole 2ch` 加 `!! 目前系統輸出是「MacBook Pro的揚聲器」...`；第 2、3 步 OK。

- [ ] **Step 2: 建多重輸出裝置並確認健檢兩種狀態**

請使用者依 setup.sh 印出的步驟建「會議（喇叭）」。然後：
```bash
./run.sh --self-test          # 系統輸出仍是喇叭 → 第 1 步應有 !! 警告
# 使用者在選單列切到「會議（喇叭）」
./run.sh --self-test          # 第 1 步應只有 OK，沒有 !!
PYTHONPATH=src .venv/bin/python -m cantonese_live.audio._coreaudio
```
Expected 最後一行：`OutputRoute(name='會議（喇叭）', is_aggregate=True, sub_names=('MacBook Pro的揚聲器', 'BlackHole 2ch'))`

- [ ] **Step 3: 收音路徵端對端**

Run: `.venv/bin/python tools/test_live_capture.py`
Expected: 聽到 `samples/yue.wav` 從喇叭播出，終端印出粵/普句子，最後 `成功：擷取路徑正常，辨識出 N 句。`

- [ ] **Step 4: 浮動視窗鍵盤驗證（決定 overrideredirect）**

Run: `./run.sh`
逐一按：`Esc`（應關閉；重開）、`⌘Q`、`Ctrl+=`、`⌘-`、`Ctrl+0`、`F`、`T`、空白鍵、拖曳頂欄、拖右下角 ◢。

若鍵盤全部有效 → 不改 overlay.py，跳到 Step 5。

若鍵盤無效（macOS 無邊框視窗收不到焦點）→ 依規格改用原生標題列：在 `overlay.py` 的 `__init__` 把
```python
        self.root.overrideredirect(True)
```
改成
```python
        if sys.platform != "darwin":
            # macOS 的無邊框視窗收不到鍵盤事件，改用原生標題列（拖曳與縮放交給系統）
            self.root.overrideredirect(True)
```
並在 `_build_grip` 開頭加 `if sys.platform == "darwin": return`（原生視窗已有縮放角）。重跑 `./run.sh` 確認鍵盤有效、拖標題列可移動。然後 commit：
```bash
git add src/cantonese_live/overlay.py
git commit -m "overlay：macOS 改用原生標題列視窗以接收鍵盤事件

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 5: 「輸出切到 BlackHole 本身」的警告**

使用者在選單列把輸出切到「BlackHole 2ch」本身，重跑 `./run.sh`。
Expected: 狀態列橘字「目前系統聲音只送到 BlackHole，你自己會聽不到對方說話」。切回「會議（喇叭）」。

- [ ] **Step 6: 全部自動化測試**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: 全部 `OK`

- [ ] **Step 7: 若有 AirPods，驗證第二個多重輸出裝置**

建「會議（AirPods）」並選用，重跑 Step 3。Expected 同 Step 3。沒有 AirPods 就在完成報告寫明未驗證。

- [ ] **Step 8: 完成報告必須包含**

- Windows 端尚未回歸：需在 Windows 機器上執行 `.\run.ps1 -SelfTest` 與 `.\.venv\Scripts\python.exe tools\test_live_capture.py`。`windows.py` 是原封搬移加 `_callback` 微調（改呼叫 `_ingest`），風險點就在這個回呼。
- Step 4 的 overrideredirect 決策結果。
- Step 7 是否驗證。
