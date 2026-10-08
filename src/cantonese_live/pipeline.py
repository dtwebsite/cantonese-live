"""把擷取 → 辨識 → 翻譯 串起來，跑在背景執行緒上。

執行緒分工：

    PortAudio 回呼   收音、混單聲道、重採樣到 16kHz
    工作執行緒       VAD 斷句 → SenseVoice 辨識 → 翻譯 → 丟結果出來
    主執行緒         顯示（tkinter 必須在主執行緒跑 mainloop）

辨識和翻譯刻意放在同一個工作執行緒，不再細分。因為辨識 RTF 只有 0.03，
翻譯用詞典是微秒級，就算走 Claude API 也只有一兩秒 —— 瓶頸從來不是
算力，而是「等對方講完一句」。多開執行緒只會讓句子亂序。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .asr import AsrError, Recognizer, Utterance
from .audio import AudioError, LoopbackCapture, resolve_device
from .config import Config
from .translate import build_translator
from .translate.base import Translation
from .transcript import TranscriptWriter
from . import jyutping as _jyutping


@dataclass
class Line:
    """一句完成的翻譯，送去顯示與存檔。"""

    utterance: Utterance
    translation: Translation
    latency_s: float   # 從「這句講完」到「翻譯出來」的時間
    jyutping: str = ""  # 粵語原文的粵拼；關閉或套件沒裝時是空字串


@dataclass
class Stats:
    lines: int = 0
    audio_seconds: float = 0.0
    asr_seconds: float = 0.0
    dropped_samples: int = 0
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def summary(self) -> str:
        rtf = (self.asr_seconds / self.audio_seconds
               if self.audio_seconds else 0.0)
        out = (
            f"執行 {self.elapsed / 60:.1f} 分鐘，"
            f"辨識出 {self.lines} 句（共 {self.audio_seconds:.0f} 秒語音），"
            f"辨識耗時 {self.asr_seconds:.1f} 秒（RTF {rtf:.3f}）"
        )
        if self.dropped_samples:
            out += f"\n  注意：因處理不及丟棄了 {self.dropped_samples / 16000:.1f} 秒音訊"
        return out


class Pipeline:
    """整條管線。建構時就會載入模型（約 1.5 秒）。"""

    def __init__(
        self,
        cfg: Config,
        on_line: Callable[[Line], None],
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self._on_line = on_line
        self._on_status = on_status or (lambda msg: None)

        self.device = resolve_device(cfg.audio.device)
        self.recognizer = Recognizer(cfg)
        # 詞典 key 要跟辨識輸出用同一套繁體寫法，否則比對不到
        self.translator = build_translator(
            cfg, on_status=self._on_status,
            normalize=self.recognizer.to_traditional,
        )

        transcript_dir: Path | None = None
        if cfg.transcript.enabled:
            transcript_dir = cfg.path(cfg.transcript.dir)
        self._want_jyutping = bool(cfg.ui.show_jyutping) and _jyutping.available()
        if cfg.ui.show_jyutping and not _jyutping.available():
            self._on_status("沒有安裝 ToJyutping，這次不顯示粵拼（pip install ToJyutping）")
        self.transcript = TranscriptWriter(transcript_dir, self.translator.name,
                                           jyutping=self._want_jyutping)

        self.stats = Stats()
        self._context: list[str] = []
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._capture: LoopbackCapture | None = None
        self._errors: queue.Queue[str] = queue.Queue()

    # -- 生命週期 ---------------------------------------------------------

    def start(self) -> None:
        self._capture = LoopbackCapture(
            device=self.device,
            block_ms=self.cfg.audio.block_ms,
            queue_seconds=self.cfg.audio.queue_seconds,
            on_overflow=self._on_overflow,
        )
        self._capture.start()
        self._worker = threading.Thread(
            target=self._run, name="cantonese-live-worker", daemon=True
        )
        self._worker.start()
        self._on_status(f"收音中：{self.device.name}")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._capture is not None:
            self._capture.stop()
        if self._worker is not None:
            self._worker.join(timeout)
            self._worker = None
        self.transcript.footer(self.final_summary())
        self.transcript.close()
        self.translator.close()

    def __enter__(self) -> "Pipeline":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # -- 狀態查詢（給 UI 用） ---------------------------------------------

    @property
    def listening(self) -> bool:
        return self._capture is not None and self._capture.alive

    @property
    def speech_active(self) -> bool:
        try:
            return self.recognizer.speech_active
        except Exception:
            return False

    def pop_error(self) -> str | None:
        try:
            return self._errors.get_nowait()
        except queue.Empty:
            return None

    def final_summary(self) -> str:
        parts = [self.stats.summary()]
        cost = getattr(self.translator, "cost_summary", None)
        if callable(cost):
            parts.append(cost())
        if self.transcript.path is not None:
            parts.append(f"逐字稿：{self.transcript.path}")
        return "\n".join(parts)

    # -- 內部 -------------------------------------------------------------

    def _on_overflow(self, dropped: int) -> None:
        self.stats.dropped_samples += dropped

    def _run(self) -> None:
        capture = self._capture
        assert capture is not None
        try:
            while not self._stop.is_set():
                block = capture.read(timeout=0.25)
                if block is None:
                    break
                for utt in self.recognizer.feed(block):
                    self._emit(utt)
            for utt in self.recognizer.flush():
                self._emit(utt)
        except (AudioError, AsrError) as exc:
            self._errors.put(str(exc))
            self._on_status(f"錯誤：{exc}")
        except Exception as exc:  # 工作執行緒的例外不能無聲消失
            self._errors.put(f"{type(exc).__name__}: {exc}")
            self._on_status(f"非預期錯誤：{exc}")

    def _emit(self, utt: Utterance) -> None:
        t0 = time.perf_counter()
        translation = self.translator.translate(utt.text, self._context)
        latency = utt.asr_seconds + (time.perf_counter() - t0)

        self.stats.lines += 1
        self.stats.audio_seconds += utt.duration_s
        self.stats.asr_seconds += utt.asr_seconds

        self._context.append(translation.text)
        if len(self._context) > 12:
            del self._context[:-12]

        jp = _jyutping.to_jyutping(utt.text) if self._want_jyutping else ""
        line = Line(utterance=utt, translation=translation, latency_s=latency, jyutping=jp)
        self.transcript.write(utt, translation, jp)
        self._on_line(line)
