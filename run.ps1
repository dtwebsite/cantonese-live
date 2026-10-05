<#
.SYNOPSIS
  啟動粵語即時翻譯。

.EXAMPLE
  .\run.ps1                       用 config.toml 的設定啟動
  .\run.ps1 -List                 列出可用的音訊裝置
  .\run.ps1 -SelfTest             檢查模型/裝置/翻譯器是否正常
  .\run.ps1 -Console              只用終端機，不開浮動視窗
  .\run.ps1 -Engine claude        這次改用 Claude 翻譯
  .\run.ps1 -File samples\yue.wav 拿音檔測試，不需要喇叭有聲音
#>
[CmdletBinding()]
param(
  [switch]$List,
  [switch]$SelfTest,
  [switch]$Console,
  [ValidateSet('lexicon', 'claude', 'lexicon+claude', 'none')]
  [string]$Engine,
  [string]$Device,
  [string]$File,
  [switch]$NoTranscript
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# 中文顯示的前提：主控台要用 UTF-8，不然 cp950 會把字變亂碼
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  Write-Host "找不到虛擬環境，請先執行： .\setup.ps1" -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path (Join-Path $root 'models\sense-voice\model.int8.onnx'))) {
  Write-Host "找不到辨識模型，請先執行： .\setup.ps1" -ForegroundColor Yellow
  exit 1
}

$env:PYTHONPATH = Join-Path $root 'src'

$cliArgs = @()
if ($List)         { $cliArgs += '--list-devices' }
if ($SelfTest)     { $cliArgs += '--self-test' }
if ($Console)      { $cliArgs += @('--ui', 'console') }
if ($Engine)       { $cliArgs += @('--engine', $Engine) }
if ($Device)       { $cliArgs += @('--device', $Device) }
if ($File)         { $cliArgs += @('--file', $File) }
if ($NoTranscript) { $cliArgs += '--no-transcript' }

& $py '-m' 'cantonese_live' @cliArgs
exit $LASTEXITCODE
