"""把會議逐字稿寫成 Markdown 檔。

每句立刻 flush 到磁碟 —— 如果程式當掉或電腦重開，已經講過的內容不會不見。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TextIO

from .asr import Utterance
from .translate.base import Translation


class TranscriptWriter:
    """逐字稿輸出。沒啟用時所有方法都是空動作，呼叫端不用特別判斷。"""

    def __init__(
        self,
        directory: Path | None,
        engine: str = "",
        source: str = "",
    ) -> None:
        """source 非空時會寫進標題並加到檔名裡（用於事後處理錄音檔）。"""
        self._fh: TextIO | None = None
        self.path: Path | None = None
        self.lines = 0

        if directory is None:
            return

        directory.mkdir(parents=True, exist_ok=True)
        started = dt.datetime.now()
        suffix = f"_{_slug(source)}" if source else ""
        self.path = directory / f"{started:%Y-%m-%d_%H%M%S}{suffix}.md"
        self._fh = open(self.path, "w", encoding="utf-8", newline="\n")

        title = f"錄音逐字稿：{source}" if source else "會議逐字稿"
        self._fh.write(
            f"# {title}\n\n"
            f"- 時間：{started:%Y-%m-%d %H:%M}\n"
            f"- 辨識：SenseVoice（粵語）\n"
            f"- 翻譯：{engine or '未設定'}\n\n"
            f"| 時間 | 粵語原文 | 普通話 |\n|---|---|---|\n"
        )
        self._fh.flush()

    def write(self, utt: Utterance, translation: Translation) -> None:
        if self._fh is None:
            return
        stamp = _clock(utt.start_s)
        # 原文和譯文可能含有 | ，不轉義會把 Markdown 表格撐壞
        original = _escape_cell(utt.text)
        translated = _escape_cell(translation.text)
        self._fh.write(f"| {stamp} | {original} | {translated} |\n")
        self._fh.flush()
        self.lines += 1

    def footer(self, summary: str) -> None:
        if self._fh is None:
            return
        self._fh.write(f"\n---\n\n{summary}\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "TranscriptWriter":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _slug(name: str) -> str:
    """把來源檔名變成安全的檔名片段。"""
    keep = [c for c in name if c.isalnum() or c in "-_"]
    return "".join(keep)[:40] or "audio"
