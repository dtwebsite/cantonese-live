"""粵語原文標註粵拼（Jyutping）。

用 ToJyutping 套件：純 Python、無相依、懂多字詞的變讀（「唔到」→ m4 dou2，
「聽日」→ ting1 jat6）。沒裝套件時所有函式都安靜退化成空字串，不影響主功能。
"""

from __future__ import annotations

try:
    import ToJyutping as _default_impl
except ImportError:  # 套件沒裝
    _default_impl = None

_MISSING = object()

# 全形標點換成半形，跟拼音的拉丁字母比較搭
_PUNCT = {"，": ",", "。": ".", "？": "?", "！": "!", "；": ";", "：": ":",
          "、": ",", "「": '"', "」": '"'}


def available() -> bool:
    return _default_impl is not None


def to_jyutping(text: str, impl=_MISSING) -> str:
    """整句轉成粵拼，一字一音節以空白分隔，標點與非漢字原樣保留。

    impl 參數只給測試注入用；傳 None 模擬套件沒裝的情況。
    """
    backend = _default_impl if impl is _MISSING else impl
    if backend is None or not text:
        return ""
    try:
        pairs = backend.get_jyutping_list(text)
    except Exception:
        return ""
    # 自己拼接而不用 get_jyutping_text()：那個會把數字/英文換成「[…]」，
    # 但辨識結果常有「300」「OK」這種東西，要原樣留著。
    out: list[str] = []
    prev_alnum = False
    for ch, syllable in pairs:
        if syllable:
            out.append((" " if out else "") + syllable)
            prev_alnum = False
        elif ch.isspace():
            if out and not out[-1].endswith(" "):
                out.append(" ")
            prev_alnum = False
        elif ch.isalnum():
            need_space = bool(out) and not prev_alnum and not out[-1].endswith(" ")
            out.append((" " if need_space else "") + ch)
            prev_alnum = True
        else:
            out.append(_PUNCT.get(ch, ch))
            prev_alnum = False
    return "".join(out).strip()
