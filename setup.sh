#!/bin/bash
# 在這台 Mac 上安裝粵語即時翻譯（裝 Python、BlackHole、建虛擬環境、下載模型）。
#
#   ./setup.sh                 一般安裝
#   ./setup.sh --with-claude   同時安裝 anthropic（要用 Claude 翻譯才需要）
#
# 重複執行是安全的 —— 已完成的步驟會跳過。
# Python 由 uv 管理（獨立版 3.12，內含 Tk，Intel 與 Apple Silicon 都有，不需 sudo）。
# BlackHole 直接從官方網址下載安裝檔並驗證 sha256，安裝那一步會要求輸入 macOS 密碼。
# 不需要 Homebrew，也不需要 Command Line Tools。
set -euo pipefail
cd "$(dirname "$0")"

WITH_CLAUDE=0
for arg in "$@"; do
  case "$arg" in
    --with-claude) WITH_CLAUDE=1 ;;
    *) echo "未知參數：$arg"; exit 2 ;;
  esac
done

step() { printf '\n\033[36m[%s] %s\033[0m\n' "$1" "$2"; }
ok()   { printf '  \033[32mOK\033[0m  %s\n' "$1"; }
warn() { printf '  \033[33m!!\033[0m  %s\n' "$1"; }

if [[ "$(uname)" != "Darwin" ]]; then
  echo "這個腳本只給 macOS 用。Windows 請執行 setup.ps1。"; exit 1
fi

step 1 "Python 3.12（透過 uv）"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "  安裝 uv（單一執行檔，放在 ~/.local/bin）..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
ok "$(uv --version)"
uv python install 3.12 --quiet
PY="$(uv python find 3.12)"
"$PY" -c "import tkinter" || { echo "  這版 Python 沒有 Tk，請回報。"; exit 1; }
ok "$("$PY" --version)（含 Tk）"

step 2 "BlackHole 虛擬音訊裝置（錄系統聲音用）"
BH_VERSION="0.7.1"
BH_URL="https://existential.audio/downloads/BlackHole2ch-${BH_VERSION}.pkg"
BH_SHA256="57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf"
if [[ -d /Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver ]]; then
  ok "BlackHole 2ch 已安裝"
else
  BH_PKG="$(mktemp -d)/BlackHole2ch-${BH_VERSION}.pkg"
  echo "  下載 ${BH_URL}"
  curl -fsSL -o "$BH_PKG" "$BH_URL"
  echo "${BH_SHA256}  ${BH_PKG}" | shasum -a 256 -c --status \
    || { echo "  下載的安裝檔 sha256 不符，為安全起見中止。請稍後再試或改手動安裝。"; exit 1; }
  echo "  安裝時會要求輸入 macOS 密碼（驅動要放進 /Library/Audio）。"
  sudo installer -pkg "$BH_PKG" -target /
  rm -f "$BH_PKG"
  warn "BlackHole 剛裝好。如果稍後找不到裝置，登出再登入一次即可。"
fi

step 3 "建立虛擬環境 .venv 並安裝套件"
if [[ ! -x .venv/bin/python ]]; then
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
if [[ $WITH_CLAUDE -eq 1 ]]; then
  .venv/bin/python -m pip install --upgrade anthropic --quiet
  ok "anthropic 已安裝"
fi
ok "套件安裝完成"

step 4 "下載辨識模型（約 230MB，只需一次）"
.venv/bin/python tools/download_models.py

step 5 "自我檢查"
set +e
PYTHONPATH=src .venv/bin/python -m cantonese_live --self-test
SELF=$?
set -e

cat <<'GUIDE'

────────────────────────────────────────────────────────────
接下來只剩一步要手動做（macOS 沒有命令列方式）：

  1. 打開「音訊 MIDI 設定」（Spotlight 搜尋 Audio MIDI Setup）
  2. 左下角 ＋ → 「建立多重輸出裝置」
  3. 右側勾選：你的喇叭（MacBook Pro的揚聲器）和 BlackHole 2ch
     ↳ 用 AirPods 開會的話，再建一個：AirPods ＋ BlackHole 2ch
  4. 可以把它改名成「會議（喇叭）」「會議（AirPods）」方便辨認
  5. 開會前：選單列音量圖示 → 選對應的多重輸出裝置
     Zoom 裡的喇叭請選「與系統相同」

  注意：選了多重輸出裝置後，鍵盤音量鍵會失效（macOS 限制），
  請事先在「音訊 MIDI 設定」把音量調好，或用 AirPods 本身調。

然後執行：  ./run.sh
────────────────────────────────────────────────────────────
GUIDE
exit $SELF
