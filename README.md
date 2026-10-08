# 粵語即時翻譯

開會時把對方說的**粵語**即時轉成文字並翻成**普通話**，疊在 Google Meet /
Zoom 旁邊的置頂小視窗上看。

- **只錄電腦播出去的聲音** —— Windows 用 WASAPI loopback，macOS 透過 BlackHole
  虛擬裝置。你自己的麥克風完全不會被錄到
- **純 CPU**，不需要顯示卡。在 i5-9400 上辨識速度是即時的 30 倍以上
- **預設完全離線免費**，一句話也不會離開這台電腦
- 整個資料夾可複製到其他電腦使用
- **Windows 與 macOS 都能用**（macOS 需要一次性的 BlackHole 設定，見下）

```
對方說話 → 喇叭輸出 → loopback 擷取 → VAD 斷句
        → SenseVoice 辨識(粵語) → OpenCC 簡轉繁 → 翻譯 → 置頂視窗 + 逐字稿
```

延遲約 **1.5 ～ 3 秒**（從對方講完一句算起）。不是同步口譯，但看字幕開會夠用。

---

## 安裝（Windows）

```powershell
cd cantonese-live
.\setup.ps1
```

會自動完成：找（或安裝）Python 3.12 → 建虛擬環境 → 裝套件 → 下載模型（約 230MB）
→ 自我檢查。**不需要管理員權限**，重複執行是安全的。

要同時裝 Claude 翻譯的相依套件：`.\setup.ps1 -WithClaude`

## 安裝（macOS）

```bash
cd cantonese-live
./setup.sh                  # 裝 Python 3.12（透過 uv）、BlackHole、套件、模型，然後自我檢查
./setup.sh --with-claude    # 同時裝 Claude 翻譯的相依套件
```

Python 由 [uv](https://docs.astral.sh/uv/) 下載獨立版（含 Tk，不需 sudo，Intel 與 Apple
Silicon 都支援）。BlackHole 從官方網址下載安裝檔並驗證 sha256 後安裝，那一步會要求輸入
macOS 密碼。不需要 Homebrew，也不需要 Command Line Tools。

### 為什麼 Mac 需要 BlackHole

macOS 沒有提供「錄下喇叭正在播的聲音」的介面，所以借道
[BlackHole](https://github.com/ExistentialAudio/BlackHole) 這個免費的虛擬音訊裝置：
把系統輸出設成「多重輸出裝置」（喇叭 + BlackHole），系統聲音就同時送到喇叭和
BlackHole，程式再從 BlackHole 錄音。

`setup.sh` 跑完後要手動做一次（macOS 沒有命令列方式）：

1. 打開「音訊 MIDI 設定」（Spotlight 搜 Audio MIDI Setup）
2. 左下角 ＋ →「建立多重輸出裝置」
3. 勾選你的喇叭（MacBook Pro的揚聲器）和 BlackHole 2ch
4. 用 AirPods 開會的話，再建一個：AirPods + BlackHole 2ch（AirPods 要先連上）
5. 改名成「會議（喇叭）」「會議（AirPods）」方便辨認

開會前在選單列的音量圖示選對應的多重輸出裝置。Zoom 裡的喇叭選「與系統相同」；
Google Meet 在瀏覽器裡跟系統走，不用另外設。

程式啟動時會檢查系統輸出有沒有經過 BlackHole，沒有就在狀態列警告，
不會默默顯示一片空白。

**已知限制**

- 選了多重輸出裝置後，鍵盤音量鍵會失效。先在「音訊 MIDI 設定」把音量調好，或用 AirPods 本身調。
- AirPods 同時當麥克風時，藍牙會壓低對方聲音的取樣率；辨識仍可用，但比喇叭情境略差。
- macOS 沒有免安裝打包版，用「複製資料夾 + `./setup.sh`」。

## 使用

```powershell
.\run.ps1                         # 開始（置頂浮動視窗）
.\run.ps1 -List                   # 列出可用的播放裝置
.\run.ps1 -SelfTest               # 檢查模型/裝置/翻譯器
.\run.ps1 -Console                # 只用終端機文字
.\run.ps1 -File 會議錄音.wav       # 辨識錄音檔並產出逐字稿
```

macOS 上最簡單的開法：在 Finder 雙擊 `粵語翻譯.command`（第一次可能要在「系統設定 →
隱私權與安全性」允許）。或在終端機用指令（參數直接交給程式）：

```bash
./run.sh                           # 開始（置頂浮動視窗）
./run.sh --list-devices            # 列出可用的裝置
./run.sh --self-test               # 檢查模型/裝置/翻譯器
./run.sh --ui console              # 只用終端機文字
./run.sh --file 會議錄音.wav        # 辨識錄音檔並產出逐字稿
./run.sh --no-transcript           # 不留逐字稿
```

`-File` 吃的是 16-bit PCM wav。它一樣會寫逐字稿，所以如果哪天即時收音出問題，
可以事後拿錄下來的檔案補跑一份（錄影檔先用 ffmpeg 轉成 wav：
`ffmpeg -i 錄影.mp4 -ac 1 -ar 16000 會議錄音.wav`）。

第一次在一台新電腦上用，建議先跑這個確認收音路徑正常：

```
.\.venv\Scripts\python.exe tools\test_live_capture.py    # Windows
.venv/bin/python tools/test_live_capture.py              # macOS
```

它會一邊播放範例音檔、一邊收音辨識。Windows 上**喇叭或耳機不能靜音**，macOS 上
**系統輸出必須是含 BlackHole 的多重輸出裝置**，否則收到的是無聲。

### 視窗操作

| 按鍵 | 作用 |
|---|---|
| 拖曳頂欄 | 移動視窗 |
| 拖右下角 `◢` | 縮放 |
| `Esc` / `Ctrl+Q` / `⌘Q` | 結束 |
| `Ctrl` `+` / `-` / `0` | 字級放大 / 縮小 / 重設（Mac 也可用 `⌘`） |
| `F` | 切換是否顯示粵語原文 |
| `J` | 切換是否顯示粵拼 |
| `T` | 切換置頂 |
| 空白鍵 | 暫停自動捲動（想往上回看時用） |

頂欄左邊的圓點是狀態燈：灰＝待機、藍＝偵測到說話、紅＝音訊中斷。

視窗上每句顯示三行：粵語原文、粵拼（Jyutping，灰色小字）、普通話。粵拼用
[ToJyutping](https://github.com/CanCLID/ToJyutping) 標註，懂多字詞的變讀；不想看就把
`config.toml` 的 `show_jyutping` 設成 `false`，或開著時按 `J`。逐字稿也會多一欄粵拼。原文刻意只比譯文小一號
（15pt vs 17pt）而不是壓成註腳 —— 粵語書面文字本來就有七八成看得懂，而且
**原文永遠比譯文貼近對方的原意**，詞典翻錯時你一眼就看得出來。想要兩行等重
就把 `config.toml` 的 `original_font_size` 設成和 `font_size` 一樣。

---

## 翻譯引擎

在 `config.toml` 的 `[translate] engine` 切換：

| 引擎 | 成本 | 延遲 | 說明 |
|---|---|---|---|
| `lexicon` | 免費 | < 1ms | **預設**。557 條詞表，離線。換詞很準，但改不了語序 |
| `lexicon+claude` | 看實際送出比例 | 詞典句即時<br>API 句約 1-2 秒 | 詞典先處理，只有搞不定的句子才送 API |
| `claude` | 約 $0.18/小時 | 1-2 秒 | 每句都送 API，語序也能處理好 |
| `none` | 免費 | — | 不翻譯，只看辨識原文 |

（詞表是 557 條人工條目；啟用簡繁轉換後會自動補上正規化後的寫法，
所以程式顯示的是 561 條。）

`claude` 的 $0.18/小時 是這樣估的：客戶實際講話約 30 分鐘 ≈ 7,000 字 ≈ 350 句，
每句輸入約 330 token、輸出約 35 token，以 Haiku 4.5 的 $1 / $5 每百萬 token 計算。

`lexicon+claude` 的成本取決於有多少句需要送出。判斷方式不是看「改動了多少字」
（實測真實粵語句子的改動比例全都在 19% 以上，用比例當門檻等於每句都送），
而是看兩個直接訊號：詞典有沒有留下看不懂的粵語字，以及輸出是否命中已知的
語序結構。在專案內建的 60 句測試語料上是 3 句送出（5%），但那組語料偏向
詞典處理得好的句子 —— **真實會議的比例會更高**。程式每場結束時會印出實際
送了幾句、用掉多少 token、估算多少錢，不用等帳單。

### 詞典能做到和做不到什麼

做得到（換詞）：

```
我哋聽日落單     → 我們明天下訂單
而家點算好       → 現在怎麼辦好
貨期趕唔趕得切   → 交期趕不趕得上
收數嘅時候睇下條數 → 收款的時候看一下這筆帳
```

做不到（語序）：

```
你畀個報價我先   → 詞典：你給個報價我先    正解：你先給我報價
佢話個價錢太貴   → 詞典：他說個價錢太貴    正解：他說價錢太貴
```

粵語的雙賓語後置、句末「先」、句首量詞這些結構需要真的理解句子，
只有 `claude` 引擎處理得了。如果你發現這類句子影響理解，就切到
`lexicon+claude`。

### 啟用 Claude 翻譯

1. 到 [console.anthropic.com](https://console.anthropic.com) 申請 API key 並儲值
   （最低 $5 美元，可設月支出上限）
2. 設定環境變數：

```powershell
# 這次 PowerShell 有效
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# 永久設定（不需要管理員權限）
[Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'sk-ant-...', 'User')
```

3. 把 `config.toml` 的 `engine` 改成 `lexicon+claude`

**Claude Code 的訂閱不能用在這裡** —— 那是兩套獨立的計費系統，自己寫的程式
必須用 API key 走 pay-as-you-go。

沒設 key、斷網、逾時、額度用完 —— 全部會自動降級回詞典並在狀態列說明，
不會讓會議中斷。結束時會印出這場會議實際用掉多少 token 與估算金額。

---

## 自訂詞表

開會時發現翻錯的詞，加到 `lexicon_user.txt`，下次啟動生效：

```
落定	付訂金
蛇王	偷懶
紅大	宏達
```

格式是 `粵語<TAB>普通話`（中間用 **Tab** 鍵，不是空白）。這裡的條目優先於
內建詞表，所以也能用來修正內建翻譯，或修正語音辨識常聽錯的專有名詞。

**不接受單字規則**（粵語專用字除外）。因為單字替換很容易誤傷普通話 ——
`平`→`便宜` 會把「水平」變成「水便宜」，`數`→`帳` 會把「數量」變成「帳量」。
要翻單字請寫成兩字以上的詞。程式會拒絕不安全的單字規則並在終端機說明。

改完詞表後請跑一次驗證：

```powershell
.\.venv\Scripts\python.exe tools\validate_lexicon.py
```

會檢查：單字白名單、保護詞覆蓋、簡體殘留、**普通話誤傷測試**（拿 37 句
正常普通話餵進去，一個字都不能被改掉）、粵語回歸測試、詞條自我一致性。

---

## 調校

常用的幾個旋鈕都在 `config.toml`，每個欄位旁邊都有說明。最常要動的是：

| 症狀 | 調整 |
|---|---|
| 一句話被切成兩三段 | `[vad] min_silence_ms` 調大（450 → 700） |
| 出字太慢 | `[vad] min_silence_ms` 調小（450 → 350） |
| 對方聲音很小，抓不到 | `[vad] threshold` 調低（0.5 → 0.35） |
| 會議提示音被當成說話 | `[vad] min_speech_ms` 調大（250 → 400） |
| 換耳機後收不到聲音 | Windows：`[audio] device` 留空白，會自動跟著系統預設裝置。macOS：在選單列音量圖示改選含 BlackHole 的多重輸出裝置 |
| 想要香港寫法而非台灣用詞 | `[asr] traditional` 改成 `"s2t"` |
| 開會時 CPU 吃太兇 | `[asr] num_threads` 調小（4 → 2） |
| 想把粵語原文讀得更清楚 | `[ui] original_font_size` 設成和 `font_size` 一樣 |
| 只想看普通話，不要原文 | `[ui] show_original = false`（或開著時按 `F` 切換） |

---

## 複製到其他電腦

**方法一：整個資料夾複製 + 跑 setup**

複製專案資料夾（可以不含 `.venv`），在新電腦上執行 `.\setup.ps1`（Windows）或
`./setup.sh`（macOS）。需要網路下載套件與模型，約 5 分鐘。

**方法二：打包成免安裝版（僅 Windows，新電腦不需要 Python）**

```powershell
.\build_portable.ps1 -WithClaude
```

產出 `dist\cantonese-live\`（約 500MB，含模型）。整個資料夾複製到隨身碟或
網路磁碟，在別台電腦直接執行 `cantonese-live.exe`。

打包後 `config.toml` 和 `lexicon_user.txt` 是放在 exe 旁邊的純文字檔，
每台電腦可以有自己的設定，不用重新打包。

---

## 錄音的合法性

你是通話的當事人之一，在台灣錄下自己參與的對話通常不違法。但如果要把錄音或
逐字稿提供給第三方、或用在商業用途，建議先告知對方。這個工具預設把逐字稿存在
本機 `transcripts\`，不會上傳任何地方（除非你啟用 Claude 翻譯，那時只有
**辨識出來的文字**會送出去，語音本身永遠不離開這台電腦）。

不想留逐字稿就用 `.\run.ps1 -NoTranscript`，或把 `config.toml` 的
`[transcript] enabled` 設成 `false`。

---

## 專案結構

```
cantonese-live/
  setup.ps1 / setup.sh   安裝（Windows / macOS）
  run.ps1 / run.sh       啟動（Windows / macOS）
  build_portable.ps1     打包成免安裝版
  config.toml            設定（每個欄位都有註解）
  lexicon_user.txt       你的自訂詞表
  app.py                 打包用進入點
  models/                下載的模型（SenseVoice 228MB + Silero VAD 629KB）
  samples/               官方測試音檔
  transcripts/           逐字稿輸出
  tests/                 單元測試（python -m unittest discover -s tests -t .）
  tools/
    download_models.py   下載模型
    validate_lexicon.py  詞表驗證（改詞表後必跑）
    test_live_capture.py 收音路徑端對端測試
    test_overlay.py      視窗版面檢查
  src/cantonese_live/
    config.py            設定載入
    audio/
      base.py            共用：混單聲道、重採樣、緩衝
      windows.py         WASAPI loopback 擷取
      macos.py           從 BlackHole 錄音 + 收音路徑健檢
      _coreaudio.py      ctypes 問 CoreAudio 目前輸出裝置
    asr.py               VAD 斷句 + SenseVoice 辨識 + 簡轉繁
    translate/
      lexicon_data.py    粵→普詞表（改這裡之前請先讀檔頭的規則）
      lexicon.py         詞典翻譯
      claude.py          Claude 翻譯 + 混合模式 + 成本統計
    pipeline.py          串接與執行緒
    overlay.py           置頂浮動視窗
    transcript.py        逐字稿輸出
    cli.py               命令列進入點
```

## 用到的東西

| 元件 | 用途 |
|---|---|
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | ONNX 推論執行環境 |
| [SenseVoice-Small](https://github.com/FunAudioLLM/SenseVoice) | 粵語/國語/英日韓 辨識（int8 量化，228MB） |
| [Silero VAD](https://github.com/snakers4/silero-vad) | 語句切分 |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) | WASAPI loopback 擷取 |
| [sounddevice](https://python-sounddevice.readthedocs.io) | macOS 從 BlackHole 錄音（PortAudio） |
| [BlackHole](https://github.com/ExistentialAudio/BlackHole) | macOS 虛擬音訊裝置，把系統聲音分一路給程式 |
| [OpenCC](https://github.com/BYVoid/OpenCC) | 簡體轉繁體（台灣用詞） |
| [soxr](https://github.com/dofuuz/python-soxr) | 48kHz → 16kHz 重採樣 |
