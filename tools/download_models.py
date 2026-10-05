"""下載離線語音辨識所需的模型檔。

只用標準庫，所以在安裝其他套件之前就能跑。
重複執行是安全的 —— 已經下載好的檔案會跳過。

  python tools/download_models.py
  python tools/download_models.py --full-precision   # 另外抓 fp32 模型（較準、較慢）
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

SENSE_VOICE_ARCHIVE = (
    f"{RELEASE}/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
)
SILERO_VAD = f"{RELEASE}/asr-models/silero_vad.onnx"

# 壓縮檔內的路徑 -> 解壓後要放到 models/ 下的哪裡
SENSE_VOICE_WANTED = {
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx":
        "sense-voice/model.int8.onnx",
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt":
        "sense-voice/tokens.txt",
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/LICENSE":
        "sense-voice/LICENSE",
}
SENSE_VOICE_FP32 = {
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.onnx":
        "sense-voice/model.onnx",
}

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def download(url: str, dest: Path) -> Path:
    """下載 url 到 dest，顯示進度。先寫到 .part 再改名，避免中斷留下半截檔案。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  已存在，跳過: {dest.name} ({_human(dest.stat().st_size)})")
        return dest

    part = dest.with_suffix(dest.suffix + ".part")
    print(f"  下載 {dest.name} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "cantonese-live/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(part, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r    {pct:3d}%  {_human(done)} / {_human(total)}",
                          end="", flush=True)
                else:
                    print(f"\r    {_human(done)}", end="", flush=True)
    print()
    part.replace(dest)
    return dest


def extract_members(archive: Path, wanted: dict[str, str], out_dir: Path) -> None:
    """只從壓縮檔中取出 wanted 指定的檔案，攤平放到 out_dir 下的目標路徑。"""
    with tarfile.open(archive, "r:bz2") as tar:
        for member_name, rel_out in wanted.items():
            target = out_dir / rel_out
            if target.exists() and target.stat().st_size > 0:
                print(f"  已存在，跳過: {rel_out}")
                continue
            try:
                member = tar.getmember(member_name)
            except KeyError:
                print(f"  !! 壓縮檔內找不到 {member_name}", file=sys.stderr)
                continue
            src = tar.extractfile(member)
            if src is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"  解開 {rel_out} ({_human(member.size)})")
            with src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)


def main() -> int:
    ap = argparse.ArgumentParser(description="下載 cantonese-live 需要的模型")
    ap.add_argument("--full-precision", action="store_true",
                    help="同時取出 fp32 模型（約 900MB，較準但 CPU 上較慢）")
    ap.add_argument("--keep-archive", action="store_true",
                    help="保留下載的 tar.bz2（預設解完就刪）")
    args = ap.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"模型目錄: {MODELS_DIR}\n")

    print("[1/2] Silero VAD（語句切分）")
    download(SILERO_VAD, MODELS_DIR / "silero_vad.onnx")

    print("\n[2/2] SenseVoice（粵語/國語/英日韓 辨識）")
    wanted = dict(SENSE_VOICE_WANTED)
    if args.full_precision:
        wanted.update(SENSE_VOICE_FP32)

    if all((MODELS_DIR / rel).exists() for rel in wanted.values()):
        print("  全部已存在，跳過下載壓縮檔")
    else:
        archive_dir = MODELS_DIR if args.keep_archive else Path(tempfile.mkdtemp())
        archive = archive_dir / "sense-voice.tar.bz2"
        try:
            download(SENSE_VOICE_ARCHIVE, archive)
            extract_members(archive, wanted, MODELS_DIR)
        finally:
            if not args.keep_archive:
                shutil.rmtree(archive_dir, ignore_errors=True)

    print("\n完成。models/ 內容：")
    for p in sorted(MODELS_DIR.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(MODELS_DIR).as_posix():40s} {_human(p.stat().st_size)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
