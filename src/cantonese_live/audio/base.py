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
