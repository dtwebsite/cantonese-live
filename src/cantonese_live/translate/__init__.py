"""翻譯引擎。

engine 設定值：

    lexicon         只用詞典 —— 免費、離線、不到 1ms
    claude          每句都送 Claude API —— 最準，約 $0.18 美元/小時
    lexicon+claude  詞典先擋，粵語味重的句子才送 API —— 省六到八成成本
    none            不翻譯，只看辨識原文
"""

from __future__ import annotations

from typing import Callable

from ..config import Config
from .base import Translation, Translator
from .claude import ClaudeTranslator, HybridTranslator, NullTranslator
from .lexicon import LexiconTranslator

__all__ = [
    "Translation", "Translator", "LexiconTranslator", "ClaudeTranslator",
    "HybridTranslator", "NullTranslator", "build_translator", "ENGINES",
]

ENGINES = ("lexicon", "claude", "lexicon+claude", "none")


def build_translator(
    cfg: Config,
    on_status: Callable[[str], None] | None = None,
    normalize: Callable[[str], str] | None = None,
) -> Translator:
    """依設定建立翻譯器。

    normalize 要傳入 Recognizer.to_traditional，詞典 key 才會跟辨識結果
    用同一套繁體寫法。
    """
    tc = cfg.translate
    engine = tc.engine.strip().lower()

    if engine == "none":
        return NullTranslator()

    lexicon = LexiconTranslator(
        user_lexicon_path=cfg.path(tc.user_lexicon) if tc.user_lexicon else None,
        normalize=normalize,
    )
    if engine == "lexicon":
        return lexicon

    if engine not in ("claude", "lexicon+claude"):
        raise ValueError(
            f"未知的翻譯引擎 {tc.engine!r}，可用的是：{', '.join(ENGINES)}"
        )

    claude = ClaudeTranslator(
        model=tc.model,
        fallback=lexicon,
        api_key_env=tc.api_key_env,
        context_lines=tc.context_lines,
        timeout_s=tc.timeout_s,
        on_status=on_status,
    )
    if engine == "claude":
        return claude
    return HybridTranslator(lexicon, claude)
