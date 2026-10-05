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
