"""翻譯層的共用介面。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Translation:
    text: str              # 普通話結果
    engine: str            # 實際用了哪個引擎（lexicon / claude / none / lexicon-fallback）
    changed_ratio: float   # 相對原文改動了多少（0.0 = 完全沒動）
    note: str = ""         # 失敗原因之類的附註，會顯示在 UI 狀態列

    @property
    def changed(self) -> bool:
        return self.changed_ratio > 0.0


@runtime_checkable
class Translator(Protocol):
    name: str

    def translate(self, text: str, context: list[str]) -> Translation:
        """把一句粵語（繁體）翻成普通話。

        context 是前幾句的「普通話結果」，給需要上下文的引擎參考；
        不需要的引擎可以忽略。這個方法不該丟例外 —— 內部失敗要自己
        降級並在 note 說明，因為它跑在即時管線上。
        """
        ...

    def close(self) -> None:
        ...
