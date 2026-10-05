#!/bin/bash
# 啟動粵語即時翻譯。所有參數原樣交給程式：
#
#   ./run.sh                          用 config.toml 的設定啟動（置頂浮動視窗）
#   ./run.sh --list-devices           列出可用的音訊裝置
#   ./run.sh --self-test              檢查模型/裝置/翻譯器是否正常
#   ./run.sh --ui console             只用終端機，不開浮動視窗
#   ./run.sh --engine claude          這次改用 Claude 翻譯
#   ./run.sh --file samples/yue.wav   拿音檔測試，不需要收音
#   ./run.sh --no-transcript          這次不存逐字稿
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "找不到虛擬環境，請先執行： ./setup.sh"; exit 1
fi
if [[ ! -f models/sense-voice/model.int8.onnx ]]; then
  echo "找不到辨識模型，請先執行： ./setup.sh"; exit 1
fi

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$PWD/src"
exec .venv/bin/python -m cantonese_live "$@"
