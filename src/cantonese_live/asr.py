"""語音辨識：用 VAD 把連續音訊切成句子，再交給 SenseVoice 辨識。

流程是「先斷句、再辨識」而不是串流辨識，原因是 SenseVoice 是非自回歸模型，
整句一次送進去又快又準（在 i5-9400 上 RTF 約 0.03，比即時快三十倍）。
代價是必須等對方講完一句才出字 —— 開會看字幕夠用，但不是同步口譯。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sherpa_onnx as so

from .config import AsrConfig, Config, VadConfig

SAMPLE_RATE = 16_000
VAD_WINDOW = 512          # Silero VAD 在 16kHz 下的固定窗長
VAD_BUFFER_SECONDS = 90.0  # VAD 內部環形緩衝，要大於 max_speech_s


class AsrError(RuntimeError):
    """模型載入失敗或缺檔。"""


@dataclass
class Utterance:
    """一句辨識結果。"""

    text: str            # 繁體化之後的粵語原文（還沒翻譯）
    raw_text: str        # SenseVoice 的原始輸出（簡體）
    start_s: float       # 相對於開始擷取的時間
    duration_s: float    # 這句話的長度
    language: str        # SenseVoice 回報的語言標記
    emotion: str
    asr_seconds: float   # 辨識本身花的時間，用來看效能

    @property
    def real_time_factor(self) -> float:
        return self.asr_seconds / self.duration_s if self.duration_s > 0 else 0.0


def _require(path: Path, what: str) -> str:
    if not path.exists():
        raise AsrError(
            f"找不到{what}：{path}\n"
            "請先執行：python tools\\download_models.py"
        )
    if path.stat().st_size == 0:
        raise AsrError(f"{what} 是空檔案（下載中斷？）：{path}\n"
                       "請刪掉它再重新執行 tools\\download_models.py")
    return str(path)


def _build_vad(cfg: VadConfig, model: str, num_threads: int) -> so.VoiceActivityDetector:
    silero = so.SileroVadModelConfig(
        model=model,
        threshold=cfg.threshold,
        min_silence_duration=cfg.min_silence_ms / 1000.0,
        min_speech_duration=cfg.min_speech_ms / 1000.0,
        window_size=VAD_WINDOW,
        max_speech_duration=cfg.max_speech_s,
    )
    vad_cfg = so.VadModelConfig(
        silero_vad=silero,
        sample_rate=SAMPLE_RATE,
        num_threads=max(1, min(2, num_threads)),  # VAD 很輕，給太多執行緒反而更慢
        provider="cpu",
    )
    if not vad_cfg.validate():
        raise AsrError("VAD 設定無效，請檢查 config.toml 的 [vad] 區段")
    return so.VoiceActivityDetector(
        vad_cfg, buffer_size_in_seconds=VAD_BUFFER_SECONDS
    )


class TraditionalConverter:
    """簡體 → 繁體。SenseVoice 輸出簡體字，但粵語詞典與顯示都用繁體。

    這個物件也會交給詞典翻譯器，讓詞典的 key 跟辨識結果用同一套寫法 ——
    否則 OpenCC 把 `唔准` 正規化成 `唔準` 之後，詞典就比對不到了。
    設定為空字串時會變成「原樣回傳」，呼叫端不用特別處理。
    """

    def __init__(self, config: str) -> None:
        self._cc = None
        if not config:
            return
        try:
            import opencc
            self._cc = opencc.OpenCC(config)
        except ImportError:
            print("[ASR] 未安裝 opencc，輸出會是簡體字。"
                  "執行 pip install opencc 可修正。", file=sys.stderr)
        except Exception as exc:
            print(f"[ASR] OpenCC 設定 {config!r} 載入失敗（{exc}），改為不轉換。",
                  file=sys.stderr)

    def __call__(self, text: str) -> str:
        if self._cc is None or not text:
            return text
        return self._cc.convert(text)

    @property
    def active(self) -> bool:
        return self._cc is not None


class Recognizer:
    """把音訊餵進來，吐出完整的句子。

        rec = Recognizer(cfg)
        for utt in rec.feed(block):
            print(utt.text)
    """

    def __init__(self, cfg: Config) -> None:
        asr: AsrConfig = cfg.asr
        model = _require(cfg.path(asr.model), "SenseVoice 模型")
        tokens = _require(cfg.path(asr.tokens), "SenseVoice tokens.txt")
        vad_model = _require(cfg.path(asr.vad_model), "Silero VAD 模型")

        self._min_chars = max(0, asr.min_chars)
        #: 公開給翻譯層共用，確保詞典 key 與辨識結果同一種寫法
        self.to_traditional = TraditionalConverter(asr.traditional)

        t0 = time.perf_counter()
        try:
            self._recognizer = so.OfflineRecognizer.from_sense_voice(
                model=model,
                tokens=tokens,
                num_threads=max(1, asr.num_threads),
                use_itn=asr.use_itn,
                language=asr.language,
                provider="cpu",
            )
        except Exception as exc:
            raise AsrError(f"SenseVoice 模型載入失敗：{exc}") from exc
        self._vad = _build_vad(cfg.vad, vad_model, asr.num_threads)
        self.load_seconds = time.perf_counter() - t0

        # VAD 只吃剛好 VAD_WINDOW 個樣本的區塊，而音效卡給的區塊大小不固定
        # （重採樣後更不固定），所以這裡自己補一個碎片緩衝。
        self._pending = np.empty(0, dtype=np.float32)

    # -- 餵音訊 -----------------------------------------------------------

    def feed(self, samples: np.ndarray) -> list[Utterance]:
        """餵一塊 16kHz 單聲道音訊，回傳這次餵完後「已講完」的句子。"""
        if samples.size:
            buf = (samples if self._pending.size == 0
                   else np.concatenate([self._pending, samples]))
            usable = (buf.size // VAD_WINDOW) * VAD_WINDOW
            for i in range(0, usable, VAD_WINDOW):
                self._vad.accept_waveform(buf[i:i + VAD_WINDOW])
            self._pending = buf[usable:].copy()
        return self._drain()

    def flush(self) -> list[Utterance]:
        """收尾：把還沒講完的最後一段也辨識出來。"""
        if self._pending.size:
            pad = np.zeros(VAD_WINDOW - self._pending.size, dtype=np.float32)
            self._vad.accept_waveform(np.concatenate([self._pending, pad]))
            self._pending = np.empty(0, dtype=np.float32)
        self._vad.flush()
        return self._drain()

    def reset(self) -> None:
        self._vad.reset()
        self._pending = np.empty(0, dtype=np.float32)

    @property
    def speech_active(self) -> bool:
        """目前是否偵測到有人在講話（用來做 UI 的收音指示燈）。"""
        return self._vad.is_speech_detected()

    # -- 內部 -------------------------------------------------------------

    def _drain(self) -> list[Utterance]:
        out: list[Utterance] = []
        while not self._vad.empty():
            # front 回傳的是佇列內部元素的參照，pop() 會讓它失效 ——
            # 一定要先把樣本複製出來再 pop，否則拿到的是空陣列。
            segment = self._vad.front
            samples = np.array(segment.samples, dtype=np.float32, copy=True)
            start_sample = segment.start
            self._vad.pop()

            utt = self._recognize(samples, start_sample)
            if utt is not None:
                out.append(utt)
        return out

    def _recognize(self, samples: np.ndarray, start_sample: int) -> Utterance | None:
        if samples.size == 0:
            return None

        t0 = time.perf_counter()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        self._recognizer.decode_stream(stream)
        result = stream.result
        asr_seconds = time.perf_counter() - t0

        raw = (result.text or "").strip()
        if len(raw) < self._min_chars:
            return None

        return Utterance(
            text=self.to_traditional(raw),
            raw_text=raw,
            start_s=start_sample / SAMPLE_RATE,
            duration_s=samples.size / SAMPLE_RATE,
            language=_strip_tag(getattr(result, "lang", "")),
            emotion=_strip_tag(getattr(result, "emotion", "")),
            asr_seconds=asr_seconds,
        )


def _strip_tag(tag: str) -> str:
    """把 SenseVoice 的 '<|yue|>' 變成 'yue'。"""
    return (tag or "").strip().strip("<|>").strip()
