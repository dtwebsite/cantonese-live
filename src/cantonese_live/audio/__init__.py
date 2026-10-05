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
