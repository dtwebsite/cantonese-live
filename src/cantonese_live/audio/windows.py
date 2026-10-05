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
