"""浮動視窗的視覺檢查 —— 不收音，灌假資料進去看版面。

    python tools\\test_overlay.py          開著讓你看，按 Esc 關
    python tools\\test_overlay.py 3        3 秒後自動關閉（CI / 冒煙測試用）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from cantonese_live.asr import Utterance  # noqa: E402
from cantonese_live.config import load_config  # noqa: E402
from cantonese_live.overlay import Overlay  # noqa: E402
from cantonese_live.pipeline import Line  # noqa: E402
from cantonese_live.translate.base import Translation  # noqa: E402

SAMPLES = [
    ("呢幾個字都表達唔到我想講嘅意思。", "這幾個字都表達不到我想講的意思。", "lexicon", ""),
    ("我哋聽日落單，你畀個報價我先。", "我們明天下訂單，你先給我報價。", "claude", ""),
    ("而家點算好？客仔仲未覆我。", "現在怎麼辦好？客戶還沒回覆我。", "lexicon", ""),
    ("幾時可以出貨？貨期趕唔趕得切？", "什麼時候可以出貨？交期趕不趕得上？", "lexicon", ""),
    ("平啲得唔得？咁貴我哋做唔到。", "便宜一點行不行？這麼貴我們做不到。",
     "lexicon-fallback", "API 逾時，這句改用詞典"),
    ("收數嘅時候記得睇下條數對唔對。", "收款的時候記得看一下這筆帳對不對。", "lexicon", ""),
]


def main() -> int:
    auto_close = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0

    cfg = load_config()
    overlay = Overlay(cfg.ui, on_close=lambda: print("關閉"))
    overlay.status("示範模式（沒有在收音）")
    overlay.notice("這是版面示範，資料是假的")

    # 錯開時間送進去，模擬真實對話節奏
    for i, (yue, zh, engine, note) in enumerate(SAMPLES):
        def submit(y=yue, z=zh, e=engine, n=note, idx=i) -> None:
            overlay.submit(Line(
                utterance=Utterance(
                    text=y, raw_text=y, start_s=idx * 7.5, duration_s=3.4,
                    language="yue", emotion="NEUTRAL", asr_seconds=0.11,
                ),
                translation=Translation(text=z, engine=e,
                                        changed_ratio=0.4, note=n),
                latency_s=0.3 if e == "lexicon" else 1.4,
            ))
        overlay.root.after(400 + i * 500, submit)

    # 指示燈閃爍，示意「正在收音 / 偵測到說話」
    state = {"on": False}

    def blink() -> None:
        state["on"] = not state["on"]
        overlay.set_indicator(listening=True, speaking=state["on"])
    overlay.every(700, blink)

    if auto_close > 0:
        overlay.root.after(int(auto_close * 1000), overlay.close)
        print(f"{auto_close:.0f} 秒後自動關閉…")
    else:
        print("視窗已開啟。可拖曳頂欄移動、拖右下角縮放、按 Esc 關閉。")

    overlay.run()
    print("視窗已結束，沒有錯誤。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
