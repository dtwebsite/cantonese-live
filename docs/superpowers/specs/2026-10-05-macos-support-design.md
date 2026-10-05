# macOS 支援設計

日期：2026-10-05
狀態：待審閱

## 目標

讓 cantonese-live 在 macOS 上也能用，Windows 現有行為完全不變。
同一個資料夾複製到 Mac 或 Windows，各跑各的安裝腳本就能開會用。

成功的定義：

- 在 Mac 上開 Google Meet / Zoom，對方講粵語，浮動視窗出現粵語原文與普通話譯文。
- 用 Mac 內建喇叭或 AirPods 都收得到聲音（透過各自的多重輸出裝置）。
- 聲音沒有經過 BlackHole 時，程式明確告訴使用者，而不是默默顯示一片空白。
- Windows 上 `setup.ps1` / `run.ps1` / `build_portable.ps1` 行為與輸出和改動前一致。

## 不做的事

- 不做 macOS 免安裝打包（PyInstaller .app 需要簽章與公證，成本高）。Mac 用「複製資料夾 + `setup.sh`」。
- 不做 Core Audio Process Tap 原生擷取（方案 B）。已與使用者確認採 BlackHole。
- 不支援 Linux。音訊後端的結構讓它日後容易加，但這次不實作、不宣稱。
- 不自動建立多重輸出裝置。macOS 沒有簡單的命令列方式，由使用者在「音訊 MIDI 設定」手動建一次，程式負責偵測與指引。

## 現況分析

跑過 PyPI 檢查：sherpa-onnx、soxr、opencc、numpy、sounddevice 都有 macOS wheel（含 Python 3.12 到 3.14）。
純 Python 的 pipeline、translate、transcript、config 無平台相依。tkinter 跨平台。

唯一的硬阻礙是 `src/cantonese_live/audio.py`：用 PyAudioWPatch 的 WASAPI loopback 錄喇叭輸出，該套件只有 Windows 版，macOS 的 CoreAudio 也沒有對應的 loopback 介面。

其他需要配合的地方：

- `tools/test_live_capture.py` 用 `winsound` 播放測試音檔。
- `UiConfig.font_family` 預設 `Microsoft JhengHei UI`，Mac 上沒有這個字型。
- 快捷鍵只綁 `Control`，Mac 使用者習慣 `Command`。
- `cli.py` 的錯誤訊息寫死「WASAPI」「Windows 音效設定」。
- `requirements.txt` 裡的 PyAudioWPatch 在 Mac 上 pip 會直接失敗。
- 啟動與安裝腳本只有 PowerShell 版。

## 方案：BlackHole 虛擬裝置 + 平台後端

### 使用者側的 macOS 收音路徑

```
對方說話 → Meet/Zoom 播放 → 系統輸出 = 多重輸出裝置（喇叭或 AirPods + BlackHole）
        → 程式從 BlackHole 這個「輸入裝置」錄音 → 之後與 Windows 相同
```

使用者一次性設定：

1. `setup.sh` 執行 `brew install blackhole-2ch`。
2. 在「音訊 MIDI 設定」建多重輸出裝置「會議（喇叭）」= MacBook 喇叭 + BlackHole 2ch。
3. 若用 AirPods，再建一個「會議（AirPods）」= AirPods + BlackHole 2ch。
4. 開會前在選單列音量圖示選對應的多重輸出裝置。Zoom 內的喇叭選「與系統相同」。

已知限制（寫進 README）：選了多重輸出裝置後鍵盤音量鍵失效；AirPods 要先連上才能加進去；AirPods 同時當麥克風時對方聲音取樣率會降，辨識略受影響。

### 程式架構：audio 模組拆成套件

`audio.py` 改成 `audio/` 套件，對外介面不變，所以 `pipeline.py`、`cli.py`、`tools/` 的 import 路徑與呼叫方式都不用改：

```
src/cantonese_live/audio/
  __init__.py      對外介面：Device, AudioError, TARGET_RATE, LoopbackCapture,
                   list_loopback_devices(), resolve_device(), setup_help()
                   依 sys.platform 延遲載入後端（Mac 上不會 import PyAudioWPatch）
  __main__.py      python -m cantonese_live.audio：列裝置 + 3 秒擷取測試（原 _main）
  base.py          CaptureBase：混單聲道、重採樣到 16kHz、環形緩衝、丟棄策略、
                   read()/blocks()/dropped_samples。這段邏輯兩個平台完全相同，
                   從現有 LoopbackCapture 原封搬過來。
  windows.py       WASAPI 後端。現有 audio.py 的裝置列舉、resolve、PyAudio 串流
                   開關搬過來，繼承 CaptureBase。行為零改動。
  macos.py         sounddevice 後端。繼承 CaptureBase，實作 start/stop/alive、
                   裝置列舉、resolve、routing_hint()。
  _coreaudio.py    ctypes 包 CoreAudio：取預設輸出裝置、判斷是否為聚合裝置、
                   列出其子裝置 UID。只給 macos.routing_hint() 用，純盡力而為。
```

後端選擇：`sys.platform == "win32"` 用 windows，`"darwin"` 用 macos，其他平台 `AudioError("目前只支援 Windows 與 macOS")`。

### 每個後端要提供的介面

```python
class Backend(Protocol):
    def list_devices() -> list[Device]
    def resolve_device(spec: str) -> Device
    def open_capture(device, block_ms, queue_seconds, on_overflow) -> CaptureBase
    def routing_hint() -> str | None     # 收音路徑有疑慮時回傳一段說明，否則 None
    SETUP_HELP: str                      # 找不到裝置時印給使用者的平台專屬指引
```

Windows 的 `routing_hint()` 永遠回 `None`，`SETUP_HELP` 就是現在 cli 裡那兩行文字。

### macOS 後端的裝置語意

`config.toml` 的 `[audio] device` 三種寫法在 Mac 上的意思：

| 寫法 | Windows（不變） | macOS |
|---|---|---|
| `""` | 預設輸出裝置的 loopback | 名稱含 `BlackHole` 的第一個輸入裝置；找不到就 `AudioError` 並附安裝指引 |
| 數字 | PyAudio 裝置索引 | sounddevice 裝置索引，必須有輸入聲道 |
| 文字 | loopback 裝置名稱子字串 | 輸入裝置名稱子字串（所以 Rogue Amoeba Loopback 之類的也能用） |

`list_loopback_devices()` 在 Mac 上列出所有有輸入聲道的裝置，BlackHole 排最前並標示「建議」。

### 收音路徑健檢 `routing_hint()`

這是 Mac 上最常見的失敗模式：BlackHole 裝了，但系統輸出沒選到含它的多重輸出裝置，結果程式收到一片靜音。

`macos.routing_hint()` 用 `_coreaudio.py` 做三件事：取預設輸出裝置；若它是聚合（aggregate）裝置，列出子裝置 UID；檢查是否有 BlackHole。回傳：

- 預設輸出就是 BlackHole 本身：「目前系統聲音只送到 BlackHole，你自己會聽不到。請改選含喇叭的多重輸出裝置。」
- 預設輸出不是聚合裝置，或聚合裝置內沒有 BlackHole：「目前系統輸出是 X，聲音沒有經過 BlackHole。請在音量選單改選多重輸出裝置。」
- 正常：`None`。
- ctypes 任何例外：`None`（不要因為健檢失敗而影響主功能）。

呼叫點：

- `cli._cmd_self_test` 第 1 步印出裝置後，若有 hint 就印成 `!!` 警告，但不算失敗（使用者可能只是還沒切輸出）。
- `cli._run_overlay` / `_run_console` 在 `pipeline.start()` 之後呼叫一次，有 hint 就以 warn 等級送到狀態列與 notice。不做持續輪詢，使用者開會中切裝置是正常操作。

### requirements.txt

用環境標記，一個檔案兩個平台：

```
PyAudioWPatch==0.2.12.8; sys_platform == "win32"
sounddevice==0.5.6;      sys_platform == "darwin"
```

其餘不動。`sounddevice` 的 macOS wheel 內含 PortAudio，不用另外 brew 裝。

### setup.sh

對應 `setup.ps1` 的流程再加上 BlackHole 與手動設定指引，用 `#!/bin/bash`，可重複執行：

1. 檢查 Homebrew。沒有就印安裝網址後結束，不代為安裝。
2. 確保 `python@3.12` 與 `python-tk@3.12` 已裝（與 Windows 同版本，sherpa-onnx、numpy 2.5.3 都有 cp312 wheel，Homebrew 的 Python 沒帶 Tk 所以要另裝）。
3. `brew install --cask blackhole-2ch`（已裝就跳過；可能要輸入密碼）。
4. 建 `.venv`、`pip install -r requirements.txt`；`--with-claude` 加裝 anthropic。
5. `tools/download_models.py`，然後 `python -m cantonese_live --self-test`。
6. 最後印出多重輸出裝置的設定步驟（上面「使用者側」的 2 到 4），因為這步只能手動。

### run.sh

把所有參數原樣轉給 `python -m cantonese_live "$@"`，不重做 `run.ps1` 的旗標對照（CLI 本來就有 `--list-devices`、`--self-test`、`--ui console`、`--engine`、`--device`、`--file`、`--no-transcript`）。檢查 `.venv` 與模型存在，設 `PYTHONPATH=src`、`PYTHONUTF8=1`。

### 浮動視窗（overlay.py）

- **字型**：`UiConfig.font_family` 預設改為 `""` 表示自動：Windows 用 `Microsoft JhengHei UI`，macOS 用 `PingFang TC`。`config.toml` 同步改並加註解。使用者填了不存在的字型，Tk 會自己退回預設字型，不會壞。
- **快捷鍵**：現有 `Control-*` 全部保留，macOS 再加綁 `Command-q`、`Command-plus`、`Command-equal`、`Command-minus`、`Command-Key-0`。
- **無邊框視窗**：`overrideredirect(True)` 在 macOS 上有「收不到鍵盤事件」的已知風險。實作第一步就在這台 Mac 驗證。驗證通過就維持現狀；收不到就在 macOS 改用原生標題列視窗（不呼叫 overrideredirect），自訂頂欄保留狀態燈與按鈕，但拖曳與縮放交給系統。這是實作時依驗證結果二選一的規則，不是待決事項。
- `-alpha`、`-topmost`、`after()` 在 macOS Tk 都支援，不動。

### tools/test_live_capture.py

播放函式依平台分流：Windows 維持 `winsound`，macOS 用 `subprocess.run(["afplay", path])`（系統內建）。afplay 播到系統預設輸出，所以會經過多重輸出裝置到 BlackHole，這個測試在 Mac 上就是完整收音路徑的驗證。

### cli.py

- `_cmd_list_devices` 找不到裝置時印 `audio.setup_help()`，不再寫死 WASAPI 文字。
- 「留空表示自動跟著 Windows 的預設輸出裝置走」這句改成平台中性，或由後端提供。
- `_cmd_self_test` 與兩個 `_run_*` 加入 `routing_hint()` 呼叫（見上）。
- `_force_utf8` 在 Mac 上無害，不動。

### README.md

- 開頭說明 Windows 直接錄喇叭輸出，macOS 透過 BlackHole。
- 新增「macOS 安裝」章節：`./setup.sh`、多重輸出裝置建立步驟（含 AirPods 情境建兩個）、Zoom 選「與系統相同」、已知限制。
- 「使用」章節補 `./run.sh` 對照指令。
- 專案結構段落更新 audio/ 套件與新腳本。
- 「複製到其他電腦」註明 Mac 無免安裝版。

## 錯誤處理

| 情境 | 行為 |
|---|---|
| Mac 上沒裝 BlackHole，device 留空 | `resolve_device` 丟 `AudioError`，訊息含 `brew install --cask blackhole-2ch` 與 `--list-devices` 提示 |
| 系統輸出沒經過 BlackHole | 啟動後狀態列 warn，自我檢查印 `!!`，程式照常跑 |
| 多重輸出裝置內 AirPods 斷線 | macOS 自己處理，程式只看 BlackHole，串流不中斷 |
| sounddevice 串流開失敗 | `AudioError`，訊息與 Windows 版格式一致（裝置名、原因、常見原因） |
| `_coreaudio.py` 任何例外 | `routing_hint()` 回 `None`，靜默略過 |
| 非 Windows / macOS 平台 | import 時 `AudioError("目前只支援 Windows 與 macOS")` |

## 測試

目前專案沒有自動化測試目錄，這次新增 `tests/`，用標準庫 `unittest`（不新增相依），`python -m unittest` 執行。

自動化（不需要音訊硬體）：

- `tests/test_audio_base.py`：`CaptureBase` 的混單聲道、重採樣、緩衝溢位丟最舊、`read()` 逾時與結束語意。用假資料直接餵 `_push` / `_to_mono_16k`。
- `tests/test_audio_macos.py`：`resolve_device` 三種寫法，對 sounddevice 的裝置列舉注入假清單；`routing_hint` 對 `_coreaudio` 注入假回傳，驗證三種訊息分支與例外靜默。只在 darwin 跑，Windows 上 skip。
- `tests/test_audio_facade.py`：在各平台下 `from cantonese_live.audio import ...` 不會 import 到另一平台的套件（mock `sys.platform`）。
- `tests/test_overlay_font.py`：`""` 字型在兩平台解析到正確預設值。

手動（這台 Mac）：

1. `./setup.sh` 從零跑完，含 BlackHole 安裝（需使用者輸入密碼）。
2. 建多重輸出裝置，`./run.sh --self-test` 三項 OK，routing_hint 在「沒切輸出」與「切了輸出」兩種狀態下訊息正確。
3. `python tools/test_live_capture.py` 播 `samples/yue.wav` 能辨識出文字。
4. `./run.sh` 開浮動視窗，驗證拖曳、縮放、全部快捷鍵（含 Command 系列）、半透明、置頂。
5. 把系統輸出切到 BlackHole 本身，確認狀態列出現對應警告。

Windows 回歸：這台 Mac 無法執行，`windows.py` 是原封搬移，由自動化 facade 測試確保 import 正確。實作完成時會明確標示「Windows 端需在 Windows 機器上跑 `.\run.ps1 -SelfTest` 與 `tools\test_live_capture.py` 確認」。

## 改動檔案清單

新增：`src/cantonese_live/audio/{__init__,__main__,base,windows,macos,_coreaudio}.py`、`setup.sh`、`run.sh`、`tests/*.py`
刪除：`src/cantonese_live/audio.py`（內容搬進套件）
修改：`requirements.txt`、`config.toml`、`src/cantonese_live/{cli,config,overlay}.py`、`tools/test_live_capture.py`、`README.md`
不動：`pipeline.py`、`asr.py`、`translate/`、`transcript.py`、所有 `.ps1`
