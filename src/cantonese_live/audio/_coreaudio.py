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
        # 一定要宣告 argtypes：ctypes 預設把 Python int 當 32 位元傳，
        # 64 位元的 CFStringRef 指標會被截斷而 segfault。
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
