"""測試套件。把 src/ 加進 sys.path，這樣不設 PYTHONPATH 也能跑。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
