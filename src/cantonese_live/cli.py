"""進入點。

    python -m cantonese_live                  用 config.toml 的設定啟動
    python -m cantonese_live --list-devices   列出可用的 loopback 裝置
    python -m cantonese_live --ui console     只用終端機，不開浮動視窗
    python -m cantonese_live --engine claude  這次改用 Claude 翻譯
    python -m cantonese_live --file a.wav     拿音檔測試，不開收音
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import wave
from pathlib import Path

import numpy as np

from .asr import AsrError, Recognizer
from .audio import AudioError, list_loopback_devices, resolve_device, routing_hint, setup_help
from .config import Config, load_config
from .pipeline import Line, Pipeline
from .translate import ENGINES
from .transcript import TranscriptWriter


def _force_utf8() -> None:
    """Windows 主控台預設是 cp950，不先切成 UTF-8 中文會變亂碼。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="cantonese-live",
        description="把會議中對方的粵語即時翻成普通話（只錄喇叭輸出，不錄你的麥克風）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--config", type=Path, help="指定設定檔（預設 config.toml）")
    p.add_argument("--list-devices", action="store_true",
                   help="列出可用的 loopback 裝置後結束")
    p.add_argument("--device", help="指定裝置（名稱片段或索引），覆蓋設定檔")
    p.add_argument("--engine", choices=ENGINES, help="翻譯引擎，覆蓋設定檔")
    p.add_argument("--ui", choices=("overlay", "console", "both"),
                   help="顯示方式，覆蓋設定檔")
    p.add_argument("--no-transcript", action="store_true", help="這次不存逐字稿")
    p.add_argument("--file", type=Path,
                   help="辨識一個 wav 檔而不收音，並產出逐字稿"
                        "（測試用，也可事後補跑錄音檔）")
    p.add_argument("--self-test", action="store_true",
                   help="檢查模型、音訊裝置、翻譯器是否都正常後結束")
    return p.parse_args(argv)


def _apply_overrides(cfg: Config, args: argparse.Namespace) -> None:
    if args.device is not None:
        cfg.audio.device = args.device
    if args.engine is not None:
        cfg.translate.engine = args.engine
    if args.ui is not None:
        cfg.ui.mode = args.ui
    if args.no_transcript:
        cfg.transcript.enabled = False


# ---------------------------------------------------------------------------
# 子指令
# ---------------------------------------------------------------------------

def _cmd_list_devices() -> int:
    devices = list_loopback_devices()
    if not devices:
        print(setup_help())
        return 1

    print("可用的裝置（錄的是這個裝置的聲音）：\n")
    try:
        default = resolve_device("")
    except AudioError:
        default = None
    for d in devices:
        mark = "  <- 預設" if default and d.index == default.index else ""
        print(f"  {d}{mark}")
    print("\n設定方式：在 config.toml 的 [audio] 填 device = \"名稱片段\" 或索引數字。")
    if sys.platform == "darwin":
        print("留空（device = \"\"）表示自動使用 BlackHole。")
        hint = routing_hint()
        if hint:
            print(f"\n注意：{hint}")
    else:
        print("留空（device = \"\"）表示自動跟著 Windows 的預設輸出裝置走。")
    return 0


def _cmd_self_test(cfg: Config) -> int:
    ok = True

    print("[1/3] 音訊裝置")
    try:
        dev = resolve_device(cfg.audio.device)
        print(f"  OK  {dev}")
        hint = routing_hint()
        if hint:
            print(f"  !!  {hint}")
    except AudioError as exc:
        print(f"  失敗  {exc}")
        ok = False

    print("\n[2/3] 辨識模型")
    try:
        rec = Recognizer(cfg)
        print(f"  OK  載入耗時 {rec.load_seconds:.2f} 秒"
              f"（語言={cfg.asr.language or '自動'}，"
              f"繁體轉換={'開啟' if rec.to_traditional.active else '關閉'}）")
    except AsrError as exc:
        print(f"  失敗  {exc}")
        return 1
    except Exception as exc:
        print(f"  失敗  {type(exc).__name__}: {exc}")
        return 1

    print("\n[3/3] 翻譯器")
    try:
        from .translate import build_translator
        tr = build_translator(cfg, normalize=rec.to_traditional)
        sample = "我哋聽日落單，你畀個報價我先。"
        out = tr.translate(sample, [])
        print(f"  OK  引擎={tr.name}")
        entries = getattr(tr, "entry_count", None)
        if entries is None:
            entries = getattr(getattr(tr, "fallback", None), "entry_count", None)
        if entries is None:
            entries = getattr(getattr(tr, "lexicon", None), "entry_count", None)
        if entries:
            print(f"      詞表 {entries} 條")
        print(f"      粵: {sample}")
        print(f"      普: {out.text}")
        if out.note:
            print(f"      註: {out.note}")
        tr.close()
    except Exception as exc:
        print(f"  失敗  {type(exc).__name__}: {exc}")
        ok = False

    run_cmd = "./run.sh" if sys.platform == "darwin" else "run.ps1"
    print("\n" + (f"全部正常，可以執行 {run_cmd} 開始使用。" if ok
                  else "有項目失敗，請看上面的訊息。"))
    return 0 if ok else 1


def _cmd_file(cfg: Config, path: Path) -> int:
    """辨識一個 wav 檔，並產出逐字稿。

    用途有兩個：測試辨識與翻譯是否正常，以及萬一即時收音當天出問題，
    事後拿錄下來的檔案補跑一份逐字稿。
    """
    if not path.exists():
        print(f"找不到檔案：{path}", file=sys.stderr)
        return 1

    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            print(f"只支援 16-bit PCM wav，這個檔是 "
                  f"{w.getsampwidth() * 8}-bit", file=sys.stderr)
            return 1
        rate, channels = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16_000:
        import soxr
        audio = soxr.resample(audio, rate, 16_000).astype(np.float32)

    print(f"{path.name}：{audio.size / 16_000:.2f} 秒\n")

    rec = Recognizer(cfg)
    from .translate import build_translator
    tr = build_translator(cfg, normalize=rec.to_traditional)

    utterances = list(rec.feed(audio)) + list(rec.flush())
    if not utterances:
        print("VAD 沒有偵測到語音。")
        print("如果這個檔確實有說話聲，可以把 config.toml 的 "
              "[vad] threshold 調低（例如 0.35）。")
        tr.close()
        return 1

    transcript = TranscriptWriter(
        cfg.path(cfg.transcript.dir) if cfg.transcript.enabled else None,
        engine=tr.name,
        source=path.stem,
    )

    context: list[str] = []
    asr_total = 0.0
    try:
        for utt in utterances:
            out = tr.translate(utt.text, context)
            context.append(out.text)
            asr_total += utt.asr_seconds
            transcript.write(utt, out)

            print(f"[{utt.start_s:6.2f}s +{utt.duration_s:4.1f}s  "
                  f"RTF {utt.real_time_factor:.3f}]")
            print(f"  粵: {utt.text}")
            print(f"  普: {out.text}")
            if out.note:
                print(f"  註: {out.note}")
            print()

        summary = (f"{len(utterances)} 句，音訊 {audio.size / 16_000:.1f} 秒，"
                   f"辨識耗時 {asr_total:.1f} 秒")
        cost = getattr(tr, "cost_summary", None)
        if callable(cost):
            summary += "\n" + cost()
        print(summary)
        transcript.footer(summary)
        if transcript.path is not None:
            print(f"逐字稿：{transcript.path}")
    finally:
        transcript.close()
        tr.close()
    return 0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _dim(text: str) -> str:
    """灰字。輸出被重導向到檔案時不加色碼，免得變成一堆 [90m。"""
    if not sys.stdout.isatty():
        return text
    return f"\033[90m{text}\033[0m"


def _run_console(cfg: Config) -> int:
    stop = threading.Event()

    def on_line(line: Line) -> None:
        utt, tr = line.utterance, line.translation
        if cfg.ui.show_original and utt.text != tr.text:
            print(f"  {_dim(utt.text)}")
        print(f"  {tr.text}")
        suffix = f"{_clock(utt.start_s)} · {line.latency_s:.1f}s"
        if tr.note:
            suffix += f" · {tr.note}"
        print(f"  {_dim(suffix)}\n", flush=True)

    def on_status(msg: str) -> None:
        print(f"[狀態] {msg}", flush=True)

    pipeline = Pipeline(cfg, on_line=on_line, on_status=on_status)

    def handle_sigint(_sig, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, handle_sigint)

    print(f"裝置：{pipeline.device}")
    print(f"翻譯：{pipeline.translator.name}")
    if pipeline.transcript.path:
        print(f"逐字稿：{pipeline.transcript.path}")
    hint = routing_hint()
    if hint:
        print(f"[注意] {hint}")
    print("\n開始收音。按 Ctrl+C 結束。\n")

    with pipeline:
        while not stop.wait(0.3):
            err = pipeline.pop_error()
            if err:
                print(f"[錯誤] {err}", file=sys.stderr, flush=True)
                break
            if not pipeline.listening:
                print("[錯誤] 音訊串流已中斷。", file=sys.stderr, flush=True)
                break

    print("\n" + pipeline.final_summary())
    return 0


def _run_overlay(cfg: Config, also_console: bool) -> int:
    from .overlay import Overlay

    pipeline_box: dict[str, Pipeline] = {}

    def on_close() -> None:
        pipeline = pipeline_box.get("p")
        if pipeline is not None:
            pipeline.stop()
            print("\n" + pipeline.final_summary())

    overlay = Overlay(cfg.ui, on_close=on_close)

    def on_line(line: Line) -> None:
        overlay.submit(line)
        if also_console:
            utt, tr = line.utterance, line.translation
            if utt.text != tr.text:
                print(f"  {_dim(utt.text)}")
            print(f"  {tr.text}\n", flush=True)

    def on_status(msg: str) -> None:
        # 多行訊息（例如沒設 API key 的說明）在狀態列只放第一行
        first = msg.splitlines()[0]
        kind = "warn" if ("失敗" in msg or "沒有設定" in msg
                          or "改用詞典" in msg) else "meta"
        overlay.status(first, kind)
        if also_console:
            print(f"[狀態] {msg}", flush=True)

    try:
        pipeline = Pipeline(cfg, on_line=on_line, on_status=on_status)
    except (AudioError, AsrError) as exc:
        overlay.status(str(exc).splitlines()[0], "error")
        overlay.notice(str(exc))
        overlay.run()
        return 1

    pipeline_box["p"] = pipeline
    pipeline.start()

    hint = routing_hint()
    if hint:
        overlay.status(hint.split("。")[0], "warn")
        overlay.notice(hint)

    overlay.notice(f"收音：{pipeline.device.name}")
    overlay.notice(f"翻譯：{pipeline.translator.name}"
                   + (f"　逐字稿：{pipeline.transcript.path.name}"
                      if pipeline.transcript.path else ""))

    def poll() -> None:
        overlay.set_indicator(pipeline.listening, pipeline.speech_active)
        err = pipeline.pop_error()
        if err:
            overlay.status(err.splitlines()[0], "error")
        elif not pipeline.listening:
            overlay.status("音訊串流中斷", "error")

    overlay.every(250, poll)
    overlay.run()
    return 0


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = _parse_args(argv)

    if args.list_devices:
        try:
            return _cmd_list_devices()
        except AudioError as exc:
            print(exc, file=sys.stderr)
            return 1

    cfg = load_config(args.config)
    _apply_overrides(cfg, args)

    if args.self_test:
        return _cmd_self_test(cfg)

    if args.file is not None:
        return _cmd_file(cfg, args.file)

    try:
        mode = cfg.ui.mode.strip().lower()
        if mode == "console":
            return _run_console(cfg)
        if mode in ("overlay", "both"):
            return _run_overlay(cfg, also_console=(mode == "both"))
        print(f"未知的 ui.mode：{cfg.ui.mode!r}（可用 overlay / console / both）",
              file=sys.stderr)
        return 2
    except (AudioError, AsrError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
