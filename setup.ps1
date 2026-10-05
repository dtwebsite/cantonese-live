<#
.SYNOPSIS
  在這台電腦上安裝粵語即時翻譯（建虛擬環境、裝套件、下載模型）。

.DESCRIPTION
  不需要管理員權限。如果這台還沒有 Python，會自動下載官方安裝檔做
  使用者層級安裝（裝在 %LOCALAPPDATA%\Programs\Python，可從
  「應用程式與功能」移除）。

  重複執行是安全的 —— 已完成的步驟會跳過。

.EXAMPLE
  .\setup.ps1
  .\setup.ps1 -WithClaude     同時安裝 anthropic（要用 Claude 翻譯才需要）
#>
[CmdletBinding()]
param(
  [switch]$WithClaude,
  [switch]$WithPyInstaller
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$PyVersion = '3.12.10'

function Write-Step { param($n, $msg) Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  !!  $msg" -ForegroundColor Yellow }

function Test-NativeOk {
  <#
    執行一個原生程式，只回傳「成功了沒」。

    需要這個包裝是因為 Windows PowerShell 5.1 的兩個行為：原生程式只要寫
    stderr 就會被包成 NativeCommandError，而 $ErrorActionPreference = 'Stop'
    會把它當成終止錯誤 —— 於是「檢查某個東西有沒有裝」這種無害的探測
    反而會讓整個腳本掛掉。
  #>
  param([string]$Exe, [string[]]$Arguments)
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & $Exe @Arguments 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  } finally {
    $ErrorActionPreference = $prev
  }
}

# --- 1. 找 Python ----------------------------------------------------------
Write-Step 1 ' 尋找 Python 3.10 - 3.13'

function Find-Python {
  $candidates = @()
  foreach ($cmd in @('python', 'python3')) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) { $candidates += $found.Source }
  }
  $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  $candidates += "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
  $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
  $candidates += "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"

  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    foreach ($exe in ($candidates | Select-Object -Unique)) {
      if (-not (Test-Path $exe)) { continue }
      try {
        # sherpa-onnx 的 wheel 只到 3.13，低於 3.10 也不支援
        $probe = & $exe -c "import sys;v=sys.version_info;print(1 if (3,10)<=(v.major,v.minor)<=(3,13) else 0, f'{v.major}.{v.minor}.{v.micro}')"
        if ($LASTEXITCODE -ne 0) { continue }
        $parts = "$probe".Trim() -split ' '
        if ($parts[0] -eq '1') {
          return [pscustomobject]@{ Exe = $exe; Version = $parts[1] }
        }
      } catch { continue }
    }
  } finally {
    $ErrorActionPreference = $prev
  }
  return $null
}

$python = Find-Python

if (-not $python) {
  Write-Warn "沒有找到合用的 Python，開始下載 $PyVersion（約 26MB）"
  $installer = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
  $url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"
  $pb = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
  Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -TimeoutSec 600
  $ProgressPreference = $pb

  $target = "$env:LOCALAPPDATA\Programs\Python\Python312"
  Write-Host "  安裝到 $target（使用者層級，不需要管理員權限）"
  $proc = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
    '/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'AssociateFiles=0',
    'Include_tcltk=1', 'Include_pip=1', 'Include_test=0', 'Include_doc=0',
    'Shortcuts=0', "TargetDir=$target"
  )
  Remove-Item $installer -ErrorAction SilentlyContinue
  if ($proc.ExitCode -ne 0) {
    Write-Host "  Python 安裝失敗（代碼 $($proc.ExitCode)）。" -ForegroundColor Red
    Write-Host "  請到 https://www.python.org/downloads/ 手動安裝 3.12，再重跑這個腳本。"
    exit 1
  }
  $python = Find-Python
  if (-not $python) {
    Write-Host "  安裝完成但仍找不到 Python，請重開 PowerShell 再試。" -ForegroundColor Red
    exit 1
  }
}
Write-Ok "Python $($python.Version)  ($($python.Exe))"

# tkinter 是浮動視窗的前提，先確認
if (-not (Test-NativeOk $python.Exe @('-c', 'import tkinter'))) {
  Write-Warn '這個 Python 沒有 tkinter —— 浮動視窗不能用，但 -Console 模式還可以。'
}

# --- 2. 虛擬環境 -----------------------------------------------------------
Write-Step 2 ' 建立虛擬環境 .venv'
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path $venvPy) {
  Write-Ok '已存在，跳過'
} else {
  & $python.Exe -m venv (Join-Path $root '.venv')
  if (-not (Test-Path $venvPy)) {
    Write-Host '  虛擬環境建立失敗。' -ForegroundColor Red
    exit 1
  }
  Write-Ok '建立完成'
}

# --- 3. 套件 ---------------------------------------------------------------
Write-Step 3 ' 安裝 Python 套件'
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $root 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) {
  Write-Host '  套件安裝失敗，請看上面的錯誤訊息。' -ForegroundColor Red
  exit 1
}
Write-Ok 'sherpa-onnx / PyAudioWPatch / soxr / numpy / opencc'

if ($WithClaude) {
  & $venvPy -m pip install --upgrade anthropic --quiet
  Write-Ok 'anthropic（Claude 翻譯）'
}
if ($WithPyInstaller) {
  & $venvPy -m pip install --upgrade pyinstaller --quiet
  Write-Ok 'pyinstaller（打包用）'
}

# --- 4. 模型 ---------------------------------------------------------------
Write-Step 4 ' 下載辨識模型（約 230MB，只需一次）'
& $venvPy (Join-Path $root 'tools\download_models.py')
if ($LASTEXITCODE -ne 0) {
  Write-Host '  模型下載失敗。確認網路後重跑這個腳本即可（已下載的部分會跳過）。' -ForegroundColor Red
  exit 1
}

# --- 5. 自我檢查 -----------------------------------------------------------
Write-Step 5 ' 自我檢查'
$env:PYTHONPATH = Join-Path $root 'src'
& $venvPy -m cantonese_live --self-test

Write-Host "`n完成。開始使用：" -ForegroundColor Green
Write-Host "  .\run.ps1              開始即時翻譯" -ForegroundColor Green
Write-Host "  .\run.ps1 -List        看有哪些音訊裝置" -ForegroundColor Green
Write-Host "  .\run.ps1 -File samples\yue.wav   拿範例音檔試一下" -ForegroundColor Green
