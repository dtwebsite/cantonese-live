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
