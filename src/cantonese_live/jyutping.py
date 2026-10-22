"""Convert Cantonese text to Jyutping while preserving non-Chinese content."""

from __future__ import annotations

try:
    import ToJyutping as _default_impl
except ImportError:
    _default_impl = None

_MISSING = object()
_PUNCT = {"，": ",", "。": ".", "？": "?", "！": "!", "；": ";",
          "：": ":", "、": ",", "「": '"', "」": '"'}


def available() -> bool:
    return _default_impl is not None


def to_jyutping(text: str, impl=_MISSING) -> str:
    """Return a space-separated Jyutping rendering of the input text."""
    backend = _default_impl if impl is _MISSING else impl
    if backend is None or not text:
        return ""
    try:
        pairs = backend.get_jyutping_list(text)
    except Exception:
        return ""

    out: list[str] = []
    prev_alnum = False
    for char, syllable in pairs:
        if syllable:
            out.append((" " if out else "") + syllable)
            prev_alnum = False
        elif char.isspace():
            if out and not out[-1].endswith(" "):
                out.append(" ")
            prev_alnum = False
        elif char.isalnum():
            need_space = bool(out) and not prev_alnum and not out[-1].endswith(" ")
            out.append((" " if need_space else "") + char)
            prev_alnum = True
        else:
            out.append(_PUNCT.get(char, char))
            prev_alnum = False
    return "".join(out).strip()