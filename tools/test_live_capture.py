"""端對端測試：播放一個音檔，同時從喇叭輸出 loopback 收音辨識。

這是唯一能驗證「擷取路徑」真的通的測試 —— --file 模式繞過了音效卡。
在別台電腦上第一次安裝完，跑這個就知道收音正不正常。

    python tools\\test_live_capture.py
    python tools\\test_live_capture.py samples\\zh.wav
"""

from __future__ import annotations

import sys
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from cantonese_live.asr import Recognizer  # noqa: E402
from cantonese_live.audio import LoopbackCapture, resolve_device  # noqa: E402
from cantonese_live.config import load_config  # noqa: E402
from cantonese_live.translate import build_translator  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def play(path: Path, done: threading.Event) -> None:
    """用 Windows 內建的播放器把檔案播到預設輸出裝置。"""
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    except Exception as exc:
        print(f"[播放] 失敗：{exc}", file=sys.stderr)
    finally:
        done.set()


def main() -> int:
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "yue.wav"
    if not wav.exists():
        print(f"找不到 {wav}")
        return 1

    with wave.open(str(wav), "rb") as w:
        duration = w.getnframes() / w.getframerate()

    cfg = load_config()
    device = resolve_device(cfg.audio.device)
    print(f"收音裝置：{device}")
    print(f"播放檔案：{wav.name}（{duration:.1f} 秒）")
    print("\n注意：這台電腦的喇叭/耳機音量不能是靜音，否則 loopback 收不到訊號。\n")

    recognizer = Recognizer(cfg)
    translator = build_translator(cfg, normalize=recognizer.to_traditional)

    results: list[tuple[str, str]] = []
    peak = 0.0
    total_samples = 0

    done = threading.Event()
    with LoopbackCapture(device=device, block_ms=cfg.audio.block_ms) as cap:
        # 先開始收音再播放，避免漏掉開頭
        time.sleep(0.3)
        threading.Thread(target=play, args=(wav, done), daemon=True).start()

        deadline = time.monotonic() + duration + 3.0
        while time.monotonic() < deadline:
            block = cap.read(0.2)
            if block is None:
                break
            if block.size:
                total_samples += block.size
                peak = max(peak, float(np.abs(block).max()))
                for utt in recognizer.feed(block):
                    out = translator.translate(utt.text, [])
                    results.append((utt.text, out.text))
                    print(f"  粵: {utt.text}")
                    print(f"  普: {out.text}\n")
            if done.is_set() and time.monotonic() > deadline - 2.0:
                break

        for utt in recognizer.flush():
            out = translator.translate(utt.text, [])
            results.append((utt.text, out.text))
            print(f"  粵: {utt.text}")
            print(f"  普: {out.text}\n")

    print(f"收到 {total_samples / 16000:.1f} 秒音訊，峰值 {peak:.4f}")
    translator.close()

    if peak < 1e-4:
        print("\n失敗：loopback 收到的是靜音。")
        print("  1. 確認喇叭/耳機沒有靜音，音量不是 0")
        print("  2. 確認 Windows 的預設輸出裝置就是你實際在用的那個")
        print("  3. 用 run.ps1 -List 看看是不是該指定別的裝置")
        return 1
    if not results:
        print("\n失敗：收到聲音但沒辨識出任何句子。")
        print("  可以把 config.toml 的 [vad] threshold 調低（例如 0.35）再試。")
        return 1

    print(f"\n成功：擷取路徑正常，辨識出 {len(results)} 句。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
