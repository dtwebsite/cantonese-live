"""打包與直接執行用的進入點。

開發時 src/ 不在 sys.path 上，所以這裡自己加進去；PyInstaller 打包後
模組已經內嵌，就不需要動 sys.path。
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cantonese_live.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
