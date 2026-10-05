<#
.SYNOPSIS
  打包成免安裝資料夾，複製到其他電腦就能用（不需要那台有 Python）。

.DESCRIPTION
  產出 dist\cantonese-live\ 整個資料夾，約 500MB（含 230MB 模型）。
  把它複製到隨身碟或網路磁碟，在別台電腦上直接跑 cantonese-live.exe。

  要在別台電腦改設定，直接編輯那台的 config.toml 和 lexicon_user.txt
  即可 —— 它們是放在 exe 旁邊的純文字檔，沒有被包進執行檔裡。

.EXAMPLE
  .\build_portable.ps1
  .\build_portable.ps1 -WithClaude    把 anthropic 一起包進去
#>
[CmdletBinding()]
param(
  [switch]$WithClaude,
  [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
  Write-Host '找不到虛擬環境，請先執行 .\setup.ps1' -ForegroundColor Yellow
  exit 1
}

$modelFile = Join-Path $root 'models\sense-voice\model.int8.onnx'
if (-not (Test-Path $modelFile)) {
  Write-Host '找不到模型，請先執行 .\setup.ps1' -ForegroundColor Yellow
  exit 1
}

Write-Host "`n[1/4] 確認 PyInstaller" -ForegroundColor Cyan
# 不先檢查有沒有裝，直接裝 —— pip 本身就是 idempotent 的，而且
# 「先用 2>$null 檢查再決定」在 PowerShell 5.1 會踩到 NativeCommandError：
# 原生程式一寫 stderr，配上 ErrorActionPreference='Stop' 就會直接中止。
& $venvPy -m pip install --upgrade pyinstaller --quiet
if ($LASTEXITCODE -ne 0) {
  Write-Host '  pyinstaller 安裝失敗' -ForegroundColor Red
  exit 1
}
if ($WithClaude) {
  & $venvPy -m pip install --upgrade anthropic --quiet
  if ($LASTEXITCODE -ne 0) {
    Write-Host '  anthropic 安裝失敗' -ForegroundColor Red
    exit 1
  }
}
Write-Host '  OK' -ForegroundColor Green

if ($Clean) {
  Write-Host "`n[清理] 移除舊的 build/ 與 dist/" -ForegroundColor Cyan
  Remove-Item (Join-Path $root 'build') -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item (Join-Path $root 'dist')  -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "`n[2/4] 打包（需要幾分鐘）" -ForegroundColor Cyan

# --collect-all 是必要的：這幾個套件都帶了原生 .pyd/.dll 或資料檔，
# PyInstaller 的靜態分析抓不到。opencc 的簡繁字典（.ocd2）就屬於後者。
$pyiArgs = @(
  '-m', 'PyInstaller',
  '--noconfirm',
  '--onedir',                      # 不用 --onefile：228MB 模型每次解壓會慢到不能用
  '--console',                      # 保留主控台，出問題時看得到訊息
  '--name', 'cantonese-live',
  '--paths', 'src',
  '--collect-all', 'sherpa_onnx',
  '--collect-all', 'sherpa_onnx_core',
  '--collect-all', 'opencc',
  '--collect-all', 'pyaudiowpatch',
  '--collect-all', 'soxr',
  '--hidden-import', 'tkinter',
  '--hidden-import', 'tkinter.font'
)
if ($WithClaude) { $pyiArgs += @('--collect-all', 'anthropic') }
$pyiArgs += 'app.py'

Push-Location $root
try {
  & $venvPy @pyiArgs
  if ($LASTEXITCODE -ne 0) {
    Write-Host '  打包失敗，請看上面的訊息。' -ForegroundColor Red
    exit 1
  }
} finally {
  Pop-Location
}

$dist = Join-Path $root 'dist\cantonese-live'
if (-not (Test-Path (Join-Path $dist 'cantonese-live.exe'))) {
  Write-Host '  找不到產出的 exe。' -ForegroundColor Red
  exit 1
}
Write-Host '  OK' -ForegroundColor Green

Write-Host "`n[3/4] 複製模型與設定檔到 dist" -ForegroundColor Cyan
# 模型刻意放在 exe 旁邊而不是包進去：換模型不用重新打包，
# 而且 config.py 的 project_root() 在 frozen 模式會回傳 exe 所在目錄。
Copy-Item (Join-Path $root 'models') $dist -Recurse -Force
Copy-Item (Join-Path $root 'config.toml') $dist -Force
Copy-Item (Join-Path $root 'lexicon_user.txt') $dist -Force
if (Test-Path (Join-Path $root 'samples')) {
  Copy-Item (Join-Path $root 'samples') $dist -Recurse -Force
}
New-Item -ItemType Directory -Force (Join-Path $dist 'transcripts') | Out-Null

@'
粵語即時翻譯 —— 免安裝版
=========================

直接執行 cantonese-live.exe 即可，這台電腦不需要安裝 Python。

第一次使用建議先確認收音正常：

  cantonese-live.exe --self-test      檢查模型與音訊裝置
  cantonese-live.exe --list-devices   列出可用的播放裝置
  cantonese-live.exe --file samples\yue.wav   用範例音檔測試辨識

常用：

  cantonese-live.exe                  開始即時翻譯（置頂浮動視窗）
  cantonese-live.exe --ui console      只用終端機文字
  cantonese-live.exe --engine claude   改用 Claude 翻譯（需設 API key）

設定檔是 config.toml，自訂詞表是 lexicon_user.txt，
兩個都是純文字檔，用記事本改完重新啟動就生效。
逐字稿會存在 transcripts\ 資料夾。

視窗操作：拖曳頂欄移動、拖右下角縮放、Esc 關閉、
         Ctrl +/- 調字級、F 切換粵語原文、空白鍵暫停捲動。
'@ | Set-Content (Join-Path $dist '使用說明.txt') -Encoding UTF8

Write-Host '  OK' -ForegroundColor Green

Write-Host "`n[4/4] 驗證打包結果" -ForegroundColor Cyan
Push-Location $dist
try {
  & '.\cantonese-live.exe' '--self-test'
  $testExit = $LASTEXITCODE
} finally {
  Pop-Location
}

$size = (Get-ChildItem $dist -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1GB
Write-Host ("`n完成。dist\cantonese-live\ 共 {0:N2} GB" -f $size) -ForegroundColor Green
if ($testExit -eq 0) {
  Write-Host '自我檢查通過 —— 可以把整個 dist\cantonese-live 資料夾複製到其他電腦。' -ForegroundColor Green
} else {
  Write-Host '自我檢查沒通過，先解決上面的問題再分發。' -ForegroundColor Yellow
  exit 1
}
