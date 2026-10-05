"""用 Claude API 做粵語 → 普通話翻譯（選配）。

詞典只能換詞，換不了語序。粵語長句（「畀個報價我先」這種雙賓語後置）
需要真的理解句子才能翻好，這就是這個引擎存在的理由。

兩個設計重點：

* **絕不讓會議中斷。** API 超時、沒網路、額度用完、key 沒設 —— 全部
  自動降級回詞典並在狀態列說明。translate() 不會往外丟例外。
* **成本看得見。** 每次呼叫都累計 token 數與估算金額，結束時印出來，
  不用等帳單才知道花了多少。
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable

from .base import Translation
from .lexicon import LexiconTranslator, _changed_ratio

SYSTEM_PROMPT = """\
你是粵語口語翻譯員，服務台灣使用者與香港客戶的即時會議。

輸入是語音辨識出來的粵語口語，可能帶有辨識錯誤、沒有標點、或中英夾雜。
請把它翻成自然的台灣繁體中文書面語。

規則：
- 只輸出翻譯結果本身，不要加任何說明、引號或前綴。
- 用繁體字與台灣用詞（專案、資訊、軟體、設定）。
- 數字、金額、日期、產品型號、英文專有名詞一律照原樣保留。
- 保留原本的語氣（疑問句還是疑問句，命令句還是命令句）。
- 如果輸入已經是普通話，原樣輸出即可。
- 如果某段明顯是辨識雜訊而無法理解，就把能理解的部分翻出來，不要自行編造。
"""

# 每百萬 token 的美元單價。只用於畫面上的成本估算，
# 實際帳單以 console.anthropic.com 為準。
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}


class ClaudeTranslator:
    """送 Claude API 翻譯，失敗時退回詞典。"""

    name = "claude"

    def __init__(
        self,
        model: str,
        fallback: LexiconTranslator,
        api_key_env: str = "ANTHROPIC_API_KEY",
        context_lines: int = 3,
        timeout_s: float = 12.0,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.model = model
        self.fallback = fallback
        self.context_lines = max(0, context_lines)
        self._on_status = on_status

        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self.failures = 0

        self._client = None
        self._errors = None
        self._disabled_reason = ""

        api_key = os.environ.get(api_key_env, "").strip()
        if not api_key:
            self._disable(
                f"環境變數 {api_key_env} 沒有設定，改用詞典翻譯。\n"
                f"  設定方式（PowerShell）：$env:{api_key_env} = 'sk-ant-...'\n"
                f"  API key 從 https://console.anthropic.com 取得"
            )
            return

        try:
            import anthropic
        except ImportError:
            self._disable("未安裝 anthropic 套件，改用詞典翻譯。"
                          "執行 pip install anthropic 可啟用。")
            return

        try:
            self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s)
            self._errors = anthropic
        except Exception as exc:
            self._disable(f"Claude 用戶端建立失敗（{exc}），改用詞典翻譯。")

    # -- 狀態 -------------------------------------------------------------

    def _disable(self, reason: str) -> None:
        self._disabled_reason = reason
        self._client = None
        print(f"[Claude] {reason}", file=sys.stderr)
        if self._on_status is not None:
            self._on_status(reason)

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def estimated_cost_usd(self) -> float:
        in_rate, out_rate = PRICING.get(self.model, (1.00, 5.00))
        return (self.input_tokens / 1e6 * in_rate
                + self.output_tokens / 1e6 * out_rate)

    def cost_summary(self) -> str:
        if not self.calls:
            return "Claude 翻譯：未使用"
        return (
            f"Claude 翻譯：{self.calls} 次呼叫"
            f"（失敗 {self.failures}）  "
            f"輸入 {self.input_tokens:,} / 輸出 {self.output_tokens:,} token  "
            f"估算 ${self.estimated_cost_usd:.4f} 美元"
        )

    # -- 翻譯 -------------------------------------------------------------

    def translate(self, text: str, context: list[str] | None = None) -> Translation:
        if not text:
            return Translation(text="", engine=self.name, changed_ratio=0.0)
        if self._client is None:
            result = self.fallback.translate(text)
            result.engine = "lexicon-fallback"
            result.note = self._disabled_reason.splitlines()[0]
            return result

        prompt = self._build_prompt(text, context or [])
        try:
            # 不開 thinking：這是低延遲的短翻譯，思考只會拖慢又變貴。
            # Haiku 4.5 預設就不思考，省略參數即可。
            message = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            return self._failed(text, self._describe(exc))

        self.calls += 1
        usage = getattr(message, "usage", None)
        if usage is not None:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0

        if getattr(message, "stop_reason", None) == "refusal":
            return self._failed(text, "Claude 拒絕處理這段內容")

        out = "".join(
            block.text for block in message.content
            if getattr(block, "type", "") == "text"
        ).strip()
        if not out:
            return self._failed(text, "Claude 回傳空白結果")

        return Translation(
            text=out,
            engine=self.name,
            changed_ratio=_changed_ratio(text, out),
        )

    def _build_prompt(self, text: str, context: list[str]) -> str:
        if not self.context_lines or not context:
            return text
        recent = context[-self.context_lines:]
        before = "\n".join(recent)
        return (
            f"<前文>\n{before}\n</前文>\n\n"
            f"請翻譯下面這一句（只輸出譯文）：\n{text}"
        )

    def _failed(self, text: str, note: str) -> Translation:
        self.failures += 1
        result = self.fallback.translate(text)
        result.engine = "lexicon-fallback"
        result.note = note
        return result

    def _describe(self, exc: BaseException) -> str:
        """把 SDK 例外翻成使用者看得懂的一句話。

        分開處理是因為「重試有用」和「重試沒用」要給不同建議：
        429 / 連線錯誤等一下會好，401 / 400 不會。
        """
        a = self._errors
        if a is not None:
            if isinstance(exc, a.AuthenticationError):
                return "API key 無效或已撤銷，改用詞典"
            if isinstance(exc, a.PermissionDeniedError):
                return "API key 沒有權限使用這個模型，改用詞典"
            if isinstance(exc, a.NotFoundError):
                return f"找不到模型 {self.model}，改用詞典"
            if isinstance(exc, a.RateLimitError):
                return "超過速率限制，這句改用詞典"
            if isinstance(exc, a.APITimeoutError):
                return "API 逾時，這句改用詞典"
            if isinstance(exc, a.APIConnectionError):
                return "連不上 API（網路斷線？），改用詞典"
            if isinstance(exc, a.APIStatusError):
                return f"API 回傳 {exc.status_code}，這句改用詞典"
        return f"{type(exc).__name__}: {exc}"

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass


# 詞典翻完之後還留著的粵語專用字 —— 表示詞典沒看懂這句
RESIDUAL_CHARS = frozenset("唔冇嘅咗佢哋嘢啲睇攞搵揾畀喺嚟嗰咁噉乜咩")

# 詞典改不了的語序結構。這些是實測出來的三種，不是憑空猜的：
#   「你畀個報價我先」 雙賓語後置 + 句末「先」 -> 正解「你先給我報價」
#   「佢話個價錢太貴」 動詞後的裸量詞         -> 正解「他說價錢太貴」
#   「個報表有啲問題」 句首裸量詞             -> 正解「這份報表有些問題」
PRONOUNS = "我|你|他|她|我們|你們|他們"

WORD_ORDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 句末的「先」（粵語後置，普通話要移到動詞前）
    re.compile(rf"(?:{PRONOUNS})?先[。！？\s]*$"),
    # 「給 + 量詞/名詞 + 代詞」的雙賓語後置（粵語「畀個報價我」）。
    # negative lookahead 很關鍵：普通話是「給我報價」，代詞緊跟在「給」
    # 後面就是正確語序，不該送 API。另外刻意不收「還」——「還沒／還有／
    # 還要」在普通話太常見，收了會讓大量正常句子誤送 API。
    re.compile(rf"給(?!{PRONOUNS}).{{1,6}}(?:{PRONOUNS})[。！？\s]*$"),
    # 句首裸量詞，普通話需要補「這／那」。只收「個」「隻」——「張」會
    # 誤傷姓氏（張經理）、「條」會誤傷「條款／條件」、「批」會誤傷
    # 「批准」、「部」會誤傷「部門」。
    re.compile(r"^[個隻][一-鿿]"),
    # 「說／覺得」後面緊接裸量詞（「他說個價錢太貴」）
    re.compile(r"(?:說|覺得|認為)[個隻][一-鿿]"),
)

# 這個長度以下的句子詞典幾乎不會出錯（「可以」「明白」「好啊」「冇問題」）
TRIVIAL_LENGTH = 6


def needs_word_order_help(original: str, translated: str) -> str:
    """判斷這句該不該送 Claude。回傳原因字串，不需要就回傳空字串。

    刻意不用「詞典改動了多少字」當指標 —— 實測發現真實粵語句子的改動
    比例全都在 19% 以上，用比例當門檻等於每句都送 API，省不到錢。而且
    語序有問題的句子（「你給個報價我先」）字全都換對了，比例反而偏高。
    所以這裡改看兩個直接的訊號：詞典有沒有留下看不懂的粵語字，
    以及輸出有沒有命中已知的語序結構。

    判斷標準刻意偏向「寧可多送」：誤送一句的代價是幾分之一美分，而且
    結果通常更好；漏送一句的代價是會議中看到一句看不懂的字幕。
    """
    stripped = translated.rstrip("。！？，、 \t")
    if len(stripped) <= TRIVIAL_LENGTH:
        return ""

    leftover = RESIDUAL_CHARS.intersection(translated)
    if leftover:
        return f"詞典未解：{''.join(sorted(leftover))}"

    for pattern in WORD_ORDER_PATTERNS:
        if pattern.search(translated):
            return "語序結構"

    del original
    return ""


class HybridTranslator:
    """詞典先過一遍，只有詞典搞不定的句子才送 Claude。

    判斷標準見 needs_word_order_help()：看詞典有沒有留下粵語字，
    以及輸出是否命中已知的語序結構。其餘句子直接用詞典結果，
    省下一次 API 呼叫。

    實際擋下的比例取決於對方的說話風格，結束時會印出這場會議的真實數字。
    """

    name = "lexicon+claude"

    def __init__(
        self,
        lexicon: LexiconTranslator,
        claude: ClaudeTranslator,
    ) -> None:
        self.lexicon = lexicon
        self.claude = claude
        self.escalated = 0
        self.total = 0

    def translate(self, text: str, context: list[str] | None = None) -> Translation:
        self.total += 1
        first = self.lexicon.translate(text)
        if not self.claude.available:
            return first

        reason = needs_word_order_help(text, first.text)
        if not reason:
            return first

        self.escalated += 1
        result = self.claude.translate(text, context)
        if not result.note:
            result.note = reason
        return result

    def cost_summary(self) -> str:
        kept = self.total - self.escalated
        pct = (self.escalated / self.total * 100) if self.total else 0.0
        return (f"混合模式：{self.total} 句中 {kept} 句由詞典處理、"
                f"{self.escalated} 句送 API（{pct:.0f}%）\n  "
                f"{self.claude.cost_summary()}")

    def close(self) -> None:
        self.claude.close()
        self.lexicon.close()


class NullTranslator:
    """不翻譯，只顯示辨識原文。"""

    name = "none"

    def translate(self, text: str, context: list[str] | None = None) -> Translation:
        del context
        return Translation(text=text, engine=self.name, changed_ratio=0.0)

    def close(self) -> None:
        pass
