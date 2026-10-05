"""設定載入。

config.toml 是給使用者編輯的，所有欄位都可省略 —— 省略就用這裡的預設值。
路徑一律相對於專案根目錄解析，所以整個資料夾複製到別台電腦也不會壞。
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints


def project_root() -> Path:
    """專案根目錄。PyInstaller 打包後是 exe 所在目錄，開發時是 repo 根目錄。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # .../src/cantonese_live/config.py -> 上溯三層
    return Path(__file__).resolve().parents[2]


@dataclass
class AudioConfig:
    # 空字串 = 自動使用「目前預設輸出裝置」的 loopback。
    # 也可以填裝置名稱的一部分（例如 "BenQ"）或裝置索引數字字串（例如 "12"）。
    device: str = ""
    block_ms: int = 64          # 每次從音效卡取多少毫秒
    queue_seconds: float = 30.0  # 內部緩衝上限，超過就丟最舊的（防記憶體爆掉）


@dataclass
class VadConfig:
    threshold: float = 0.5
    min_silence_ms: int = 450    # 靜音多久算一句講完（越小越即時、越容易切斷）
    min_speech_ms: int = 250     # 短於這個就當雜音丟掉
    max_speech_s: float = 18.0   # 一句最長切多久（講不停時強制切斷）


@dataclass
class AsrConfig:
    model: str = "models/sense-voice/model.int8.onnx"
    tokens: str = "models/sense-voice/tokens.txt"
    vad_model: str = "models/silero_vad.onnx"
    language: str = "yue"        # yue=粵語 zh=國語 en ja ko，空字串=自動判斷
    num_threads: int = 4
    use_itn: bool = True         # 數字/標點正規化（「三百」→「300」）
    min_chars: int = 1           # 辨識結果短於這個字數就丟掉
    # SenseVoice 輸出簡體字，這裡轉成繁體。空字串 = 不轉換。
    #   s2twp = 簡體→台灣正體，並轉換用詞（項目→專案、信息→資訊）← 預設
    #   s2tw  = 簡體→台灣正體，只轉字不轉用詞
    #   s2t   = 簡體→傳統繁體（香港/通用）
    traditional: str = "s2twp"


@dataclass
class TranslateConfig:
    # lexicon        = 只用詞典（免費、離線、即時）
    # claude         = 每句都送 Claude API
    # lexicon+claude = 詞典先過，粵語特徵重的句子才送 API（省錢）
    # none           = 不翻譯，只顯示辨識原文
    engine: str = "lexicon"
    model: str = "claude-haiku-4-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    context_lines: int = 3       # 送給 API 的前文行數（讓代名詞/主題連貫）
    timeout_s: float = 12.0
    user_lexicon: str = "lexicon_user.txt"  # 使用者自訂詞表（可選）


@dataclass
class UiConfig:
    mode: str = "overlay"        # overlay | console | both
    font_family: str = "Microsoft JhengHei UI"
    font_size: int = 17
    # 粵語原文的字級。粵語書面文字大多看得懂，所以只比譯文小一點，
    # 不是壓到最小當註腳。設成跟 font_size 一樣就是兩行等重。
    original_font_size: int = 15
    opacity: float = 0.90
    width: int = 780
    height: int = 320
    max_entries: int = 40        # 視窗內保留幾句
    show_original: bool = True
    always_on_top: bool = True


@dataclass
class TranscriptConfig:
    enabled: bool = True
    dir: str = "transcripts"


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    translate: TranslateConfig = field(default_factory=TranslateConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    transcript: TranscriptConfig = field(default_factory=TranscriptConfig)

    root: Path = field(default_factory=project_root)

    def path(self, value: str) -> Path:
        """把設定裡的相對路徑轉成絕對路徑。"""
        p = Path(value)
        return p if p.is_absolute() else (self.root / p)


def _build(cls: type, data: dict[str, Any], where: str) -> Any:
    """用 dict 填一個 dataclass，忽略未知欄位但會警告，型別不符時轉換。

    型別必須用 get_type_hints() 取，不能用 field.type —— 這個模組有
    `from __future__ import annotations`，所以 field.type 是字串 "int"
    而不是型別 int，直接比對會全部落到 str 分支，讓 num_threads 變成 "4"
    之類的字串再傳進 C++ 綁定爆掉。
    """
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    kwargs: dict[str, Any] = {}

    for key, raw in data.items():
        if key not in known:
            print(f"[設定] 忽略未知欄位 {where}.{key}", file=sys.stderr)
            continue
        target = hints.get(key, str)
        if is_dataclass(target):
            continue
        try:
            if target is bool:
                kwargs[key] = _to_bool(raw)
            elif target is int:
                kwargs[key] = int(raw)
            elif target is float:
                kwargs[key] = float(raw)
            else:
                kwargs[key] = str(raw)
        except (TypeError, ValueError):
            print(f"[設定] {where}.{key} 的值 {raw!r} 不是合法的 "
                  f"{getattr(target, '__name__', target)}，改用預設值",
                  file=sys.stderr)
    return cls(**kwargs)


def _to_bool(raw: Any) -> bool:
    """TOML 的 true/false 已經是 bool，但手改成 "true" 字串也要能用。"""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().casefold()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0"):
            return False
        raise ValueError(raw)
    return bool(raw)


def load_config(path: Path | None = None) -> Config:
    """載入 config.toml。檔案不存在就全用預設值。"""
    root = project_root()
    cfg_path = path or (root / "config.toml")
    cfg = Config(root=root)

    if not cfg_path.exists():
        return cfg

    with open(cfg_path, "rb") as fh:
        data = tomllib.load(fh)

    section_types = {
        "audio": AudioConfig, "vad": VadConfig, "asr": AsrConfig,
        "translate": TranslateConfig, "ui": UiConfig,
        "transcript": TranscriptConfig,
    }
    for name, cls in section_types.items():
        if name in data:
            if not isinstance(data[name], dict):
                print(f"[設定] [{name}] 不是一個區段，略過", file=sys.stderr)
                continue
            setattr(cfg, name, _build(cls, data[name], name))
    for unknown in set(data) - set(section_types):
        print(f"[設定] 忽略未知區段 [{unknown}]", file=sys.stderr)

    return cfg
