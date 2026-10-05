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
