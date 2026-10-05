"""詞典式粵語 → 普通話翻譯。

免費、離線、每句不到一毫秒。做法是「最長詞優先」的一次掃描替換：
把所有詞按長度從長到短排進一個 regex 交替式，regex 引擎在每個位置會
依序嘗試，所以 `係咪` 一定排在 `係` 前面、`關係` 一定排在 `係` 前面。

這招的好處是只掃一遍、不會把替換後的結果再拿去替換（避免
「唔」→「不」之後又被其他規則動到），缺點是沒辦法調語序。
長句的語序問題交給 Claude 引擎處理。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

from .base import Translation
from .lexicon_data import (
    FINAL_PARTICLES, GUARDED_SINGLES, SAFE_SINGLES, build_table,
)

#: 可以單獨替換的字 = 安全字 + 有保護詞卡位的字
ALLOWED_SINGLES = SAFE_SINGLES | GUARDED_SINGLES.keys()


def _compile(table: dict[str, str]) -> re.Pattern[str]:
    # 長的排前面 = 最長優先匹配；同長度用字典序，純粹為了結果穩定可重現
    keys = sorted(table, key=lambda k: (-len(k), k))
    return re.compile("|".join(re.escape(k) for k in keys))


def _compile_particles(particles: tuple[str, ...]) -> re.Pattern[str]:
    """只刪句尾或標點前的語氣詞，不動詞中間的字。"""
    alt = "|".join(re.escape(p) for p in particles)
    return re.compile(f"(?:{alt})+(?=[，。！？；、,.!?;\\s]|$)")


def load_user_lexicon(path: Path) -> dict[str, str]:
    """讀使用者自訂詞表。一行一條，格式是「粵語<TAB>普通話」，# 開頭是註解。

    用 TAB 而不是空白分隔，因為中文詞彙本身不含 TAB，而空白容易打錯。
    """
    if not path.exists():
        return {}

    entries: dict[str, str] = {}
    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split(None, 1)
        if len(parts) != 2:
            print(f"[詞典] {path.name}:{lineno} 格式不對（需要「粵語<TAB>普通話」）"
                  f"，略過：{line}", file=sys.stderr)
            continue
        src, dst = parts[0].strip(), parts[1].strip()
        if not src or not dst:
            continue
        if len(src) == 1 and src not in ALLOWED_SINGLES:
            print(f"[詞典] {path.name}:{lineno} 拒絕單字規則 {src!r} —— "
                  f"單字替換很容易誤傷普通話詞彙（例如「平」→「便宜」會把"
                  f"「水平」變成「水便宜」），請改成兩字以上的詞。",
                  file=sys.stderr)
            continue
        entries[src] = dst
    return entries


def _changed_ratio(before: str, after: str) -> float:
    """粗略估算改動幅度，用來決定要不要把這句送去 Claude。

    用「不同字元數 / 原文長度」而不是編輯距離，因為這裡只需要一個
    便宜的訊號，而且每句都要算。
    """
    if not before:
        return 0.0
    if before == after:
        return 0.0
    same = sum(1 for a, b in zip(before, after) if a == b)
    return 1.0 - same / max(len(before), len(after))


class LexiconTranslator:
    """詞典翻譯器。

    normalize 應該傳入「跟 ASR 輸出用的同一套 OpenCC 轉換」。原因是
    OpenCC 的 s2tw 會做異體字正規化（`唔准` → `唔準`、`嗰日` 的 `台` → `臺`），
    如果詞典 key 沒跟著轉，就會比對不到。只轉 key 不轉譯文 ——
    譯文是人工寫定的，`不准`（不允許）被轉成「不準」會是錯的。
    """

    name = "lexicon"

    def __init__(
        self,
        user_lexicon_path: Path | None = None,
        normalize: Callable[[str], str] | None = None,
    ) -> None:
        table = build_table()
        self.user_entries = 0
        if user_lexicon_path is not None:
            user = load_user_lexicon(user_lexicon_path)
            # 使用者詞表優先，可以覆蓋內建條目
            table.update(user)
            self.user_entries = len(user)

        self.normalized_keys = 0
        if normalize is not None:
            table = self._normalize_keys(table, normalize)

        self._table = table
        self._pattern = _compile(table)
        self._particles = _compile_particles(FINAL_PARTICLES)

    def _normalize_keys(
        self, table: dict[str, str], normalize: Callable[[str], str]
    ) -> dict[str, str]:
        """把 key 轉成跟辨識結果同一種寫法。原本的寫法也保留，兩種都能比對。"""
        out: dict[str, str] = {}
        for src, dst in table.items():
            out[src] = dst
            norm = normalize(src)
            if norm != src:
                self.normalized_keys += 1
                out.setdefault(norm, dst)
        return out

    @property
    def entry_count(self) -> int:
        return len(self._table)

    def translate(self, text: str, context: list[str] | None = None) -> Translation:
        del context  # 詞典不需要上下文
        if not text:
            return Translation(text="", engine=self.name, changed_ratio=0.0)

        out = self._pattern.sub(lambda m: self._table[m.group(0)], text)
        out = self._particles.sub("", out)
        out = re.sub(r"\s{2,}", " ", out).strip()

        return Translation(
            text=out,
            engine=self.name,
            changed_ratio=_changed_ratio(text, out),
        )

    def close(self) -> None:
        pass
