"""從 Windows 喇叭輸出擷取音訊（WASAPI loopback）。

只錄「電腦播出去的聲音」—— 也就是會議中對方的聲音。你自己的麥克風
完全不會被錄到，因為我們根本沒有開啟任何輸入裝置。

輸出一律是 16kHz 單聲道 float32，這是 Silero VAD 和 SenseVoice 要的格式。
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
import pyaudiowpatch as pyaudio
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


def _dev(info: dict) -> Device:
    return Device(
        index=int(info["index"]),
        name=str(info["name"]),
        rate=int(info["defaultSampleRate"]),
        channels=int(info["maxInputChannels"]),
    )


def list_loopback_devices() -> list[Device]:
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
            available = "\n".join(f"  {d}" for d in list_loopback_devices())
            raise AudioError(
                f"沒有 loopback 裝置的名稱包含 {spec!r}。\n可選的有：\n{available}"
            )
        return matches[0]
    finally:
        pa.terminate()


class LoopbackCapture:
    """背景擷取喇叭輸出，轉成 16kHz 單聲道。

    用法：

        with LoopbackCapture() as cap:
            for block in cap.blocks():
                ...  # block 是 float32 ndarray

    音訊是在 PortAudio 的回呼執行緒裡收的，混音與重採樣也在那裡做完
    （soxr 處理一個 64ms 區塊只要幾十微秒，不會拖慢回呼）。
    消費端跟不上時會丟掉最舊的資料而不是無限長大 —— 開會時寧可漏掉
    幾百毫秒，也不要讓程式吃爆記憶體。
    """

    def __init__(
        self,
        device: Device | None = None,
        device_spec: str = "",
        block_ms: int = 64,
        queue_seconds: float = 30.0,
        on_overflow: Callable[[int], None] | None = None,
    ) -> None:
        self.device = device or resolve_device(device_spec)
        self.block_ms = max(16, int(block_ms))
        self._on_overflow = on_overflow

        self._frames_per_block = max(
            64, int(self.device.rate * self.block_ms / 1000)
        )
        self._resampler = (
            soxr.ResampleStream(self.device.rate, TARGET_RATE, 1, dtype="float32")
            if self.device.rate != TARGET_RATE
            else None
        )

        self._max_samples = int(TARGET_RATE * queue_seconds)
        self._buffer: deque[np.ndarray] = deque()
        self._buffered = 0
        self._dropped = 0
        self._lock = threading.Lock()
        self._data_ready = threading.Condition(self._lock)
        self._stop = threading.Event()

        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self._error: BaseException | None = None

    # -- 生命週期 ---------------------------------------------------------

    def start(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self.device.channels,
                rate=self.device.rate,
                input=True,
                input_device_index=self.device.index,
                frames_per_buffer=self._frames_per_block,
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

    def stop(self) -> None:
        self._stop.set()
        with self._data_ready:
            self._data_ready.notify_all()
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

    def __enter__(self) -> "LoopbackCapture":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # -- PortAudio 回呼 ---------------------------------------------------

    def _callback(self, in_data, frame_count, time_info, status):  # noqa: ARG002
        if self._stop.is_set():
            return (None, pyaudio.paComplete)
        try:
            mono = self._to_mono_16k(in_data)
            if mono.size:
                self._push(mono)
        except BaseException as exc:  # 回呼裡不能讓例外逃出去
            self._error = exc
            self._stop.set()
            with self._data_ready:
                self._data_ready.notify_all()
            return (None, pyaudio.paAbort)
        return (None, pyaudio.paContinue)

    def _to_mono_16k(self, in_data: bytes) -> np.ndarray:
        x = np.frombuffer(in_data, dtype=np.float32)
        if self.device.channels > 1:
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

    @property
    def alive(self) -> bool:
        return (
            self._stream is not None
            and not self._stop.is_set()
            and self._stream.is_active()
        )


def _main() -> int:
    """python -m cantonese_live.audio —— 列出裝置並做 3 秒擷取測試。"""
    sys.stdout.reconfigure(encoding="utf-8")
    print("可用的 loopback 裝置：")
    for d in list_loopback_devices():
        print(f"  {d}")

    dev = resolve_device()
    print(f"\n預設裝置：{dev}")
    print("擷取 3 秒（請確保電腦正在播放聲音）...")

    import time
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
    raise SystemExit(_main())
