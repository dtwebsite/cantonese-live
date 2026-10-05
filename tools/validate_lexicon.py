"""檢查粵語詞典有沒有會誤傷普通話的規則。

跑法：  python tools\\validate_lexicon.py

檢查項目：

1. 單字規則是否都在白名單內（SAFE_SINGLES 或 GUARDED_SINGLES）
2. GUARDED_SINGLES 宣告的保護詞是否真的都在 GUARDS 裡
3. 有沒有殘留簡體字
4. **誤傷測試**：拿一堆正常的普通話句子餵進翻譯器，結果必須完全不變
5. **回歸測試**：粵語句子要翻出預期結果
6. 自我一致性：每個詞條都必須翻出自己宣告的譯文（抓條目互相遮蔽）
7. 已知限制：詞典做不到、需要 Claude 引擎的句子

第 4 項是最有價值的 —— 詞典翻譯最大的風險不是翻得不好，
而是把本來就正確的普通話改壞。第 5 項則是唯一抓得到「跨詞邊界遮蔽」
的檢查，改完詞表一定要跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from cantonese_live.translate.claude import (  # noqa: E402
    needs_word_order_help,
)
from cantonese_live.translate.lexicon import (  # noqa: E402
    ALLOWED_SINGLES, LexiconTranslator,
)
from cantonese_live.translate.lexicon_data import (  # noqa: E402
    GUARDED_SINGLES, GUARDS, LEXICON, SAFE_SINGLES, build_table,
)

# OpenCC 的 s2tw 會做異體字正規化，這些是我們刻意保留的常見寫法，
# 不是簡體殘留。台/臺、准/準、晒/曬、痴/癡、峰/峯、揾/搵 都屬於這類
# （「揾」是粵語「找」的常見異體寫法，兩種都收以防 OpenCC 沒啟用）。
VARIANT_OK: frozenset[str] = frozenset("台准晒痴峰吃揾")

# 正常的普通話句子 —— 翻譯器碰到這些必須一個字都不改。
# 刻意塞滿了詞典裡會替換的字（係/仲/同/咁/點/幾/好/單/數/平/未/樣/客/入/落/行）。
MANDARIN_CORPUS = (
    "這個專案的進度有點慢，資訊要及時更新。",
    "我們的勞資關係一直很好，沒有發生過爭議。",
    "這個係數要重新計算，不然報表會出錯。",
    "雙方同意提交仲裁，由仲介機構安排。",
    "他的能力在兩人之間，難分伯仲。",
    "同事們同時完成了同樣的工作，進度相同。",
    "這兩個版本不同，請同步一下再上線。",
    "我同學和同行都認同這個共同的方案。",
    "簡單來說，這個單位的訂單數量是一百張。",
    "菜單上的單價寫錯了，請改成正確的金額。",
    "數字和數量都要核對，數據不能有誤差。",
    "水平有限，但平均來說還算公平。",
    "這個平台的介面設計很平實，使用起來很平順。",
    "一點小問題，重點是地點還沒確定。",
    "現在幾點了？我們幾個人要在十點開會。",
    "你好，很好，好的，我覺得這樣很好。",
    "入口和出口都要標示清楚，收入要記錄。",
    "他已經入職三個月了，表現不錯。",
    "落實這個計畫之後，進度明顯落後了。",
    "銀行和行政部門要執行這個行業標準。",
    "整個團隊要整理資料，調整整體架構。",
    "他很固執，但執行力很強，執照也齊全。",
    "這家企業的企劃做得很完整。",
    "未來的事還未必確定，從未有人試過。",
    "這樣的樣子和那個樣品一樣嗎？",
    "客戶和顧客都很客氣，客觀來說服務不錯。",
    "實際上，其實這個事實已經確實被證明了。",
    "首都的都市計畫都要重新檢討。",
    "他理睬了一下，就沒有再回應。",
    "飲食習慣和飲料選擇都會影響健康。",
    "請在表單上填寫姓名、電話和地址。",
    "這批貨物的運費和關稅要分開計算。",
    "我們公司的薪資結構包含底薪和獎金。",
    "最低薪資的設定要符合勞基法規定。",
    "系統測試通過之後就可以上線了。",
    "埋怨沒有用，不如一起把問題解決。",
    "請先確認交貨日期，再安排船期。",
)

# 粵語回歸測試：(輸入, 期望輸出)。
# 這組是會失敗就代表詞典壞了的硬性測試 —— 改詞表之後務必跑過。
CANTONESE_EXPECTED: tuple[tuple[str, str], ...] = (
    ("呢幾個字都表達唔到我想講嘅意思。",
     "這幾個字都表達不到我想講的意思。"),
    ("而家點算好？客仔仲未覆我。",
     "現在怎麼辦好？客戶還沒回覆我。"),
    ("你睇下呢張單係唔係搞錯咗。",
     "你看一下這張訂單是不是弄錯了。"),
    ("唔好意思，我頭先冇留意到。",
     "不好意思，我剛才沒有留意到。"),
    ("幾時可以出貨？貨期趕唔趕得切？",
     "什麼時候可以出貨？交期趕不趕得上？"),
    ("嗰邊嘅同事話要再傾下價。",
     "那邊的同事說要再談一下價。"),
    ("我唔知邊個負責呢件事，你搵佢問下。",
     "我不知道誰負責這件事，你找他問一下。"),
    ("多謝你幫忙，唔使客氣。",
     "謝謝你幫忙，不用客氣。"),
    ("呢排好忙，成日都要加班。",
     "最近很忙，整天都要加班。"),
    ("平啲得唔得？咁貴我哋做唔到。",
     "便宜一點行不行？這麼貴我們做不到。"),
    ("聽朝九點開會，你記得返工啦。",
     "明天早上九點開會，你記得上班啦。"),
    ("佢搞唔掂，所以要搵人幫手喎。",
     "他搞不定，所以要找人幫忙。"),
    ("收數嘅時候記得睇下條數對唔對。",
     "收款的時候記得看一下這筆帳對不對。"),
    ("呢個系統嘅設定我唔識改。",
     "這個系統的設定我不會改。"),
    ("出糧嗰日我會畀返你。",
     "發薪水那天我會還給你。"),
)

# 詞典做不到的句子 —— 都是語序問題，需要 engine = claude 才能翻好。
# 列在這裡是為了把限制寫明，不是為了通過測試。
KNOWN_LIMITS: tuple[tuple[str, str], ...] = (
    ("我哋聽日落單，你畀個報價我先。", "正解應為「你先給我報價」：雙賓語後置 + 句末「先」"),
    ("佢話個價錢太貴，冇辦法做。", "正解應為「他說價錢太貴」：量詞「個」要省略"),
    ("個報表有啲問題，要整返先得。", "正解應為「這份報表」：句首量詞要補指示詞"),
)


def check_single_chars() -> list[str]:
    problems = []
    for src in LEXICON:
        if len(src) == 1 and src not in ALLOWED_SINGLES:
            problems.append(
                f"單字規則 {src!r} → {LEXICON[src]!r} 不在白名單內。"
                f"這個字普通話可能也在用，單獨替換會誤傷 —— "
                f"請改成兩字以上的詞，或把它加進 GUARDED_SINGLES 並列出保護詞。"
            )
    return problems


def check_guard_coverage() -> list[str]:
    """GUARDED_SINGLES 宣告需要哪些保護詞，就必須真的有那些保護詞。"""
    problems = []
    guards = set(GUARDS)
    for char, required in GUARDED_SINGLES.items():
        missing = [w for w in required if w not in guards]
        if missing:
            problems.append(
                f"單字 {char!r} 宣告的保護詞沒進 GUARDS：{missing}"
            )
        for word in required:
            if char not in word:
                problems.append(
                    f"{word!r} 被列為 {char!r} 的保護詞，但裡面沒有這個字"
                )
    overlap = SAFE_SINGLES & GUARDED_SINGLES.keys()
    if overlap:
        problems.append(
            f"這些字同時出現在 SAFE_SINGLES 和 GUARDED_SINGLES：{sorted(overlap)}"
            f" —— 需要保護詞就不該算「安全」，請只留一邊。"
        )
    return problems


def check_traditional() -> list[str]:
    """抓殘留的簡體字。

    用逐字的 s2tw 比對，而不是整詞 —— 整詞比對會把「台灣→臺灣」這種
    異體字正規化誤判成簡體殘留。VARIANT_OK 列出我們刻意保留的寫法。
    """
    try:
        import opencc
    except ImportError:
        return ["（跳過簡體檢查：未安裝 opencc）"]

    s2tw = opencc.OpenCC("s2tw")
    problems = []
    for src, dst in build_table().items():
        for label, value in (("原文", src), ("譯文", dst)):
            for char in value:
                if char in VARIANT_OK:
                    continue
                converted = s2tw.convert(char)
                if converted != char:
                    problems.append(
                        f"{label} {value!r} 裡的 {char!r} 是簡體，"
                        f"應寫成 {converted!r}（條目 {src!r} → {dst!r}）"
                    )
    return problems


def check_no_false_positives(tr: LexiconTranslator) -> list[str]:
    problems = []
    for sentence in MANDARIN_CORPUS:
        out = tr.translate(sentence).text
        if out != sentence:
            diff = _first_diff(sentence, out)
            problems.append(f"普通話句子被改壞了：\n    原: {sentence}\n"
                            f"    變: {out}\n    {diff}")
    return problems


def check_self_consistency(tr: LexiconTranslator) -> list[str]:
    """每個詞條單獨餵進翻譯器，必須翻出它自己宣告的譯文。

    抓的是「條目互相遮蔽」：替換是由左而右掃一趟，最長優先只在同一個
    位置成立，所以某個條目有可能永遠匹配不到。例如詞表裡若同時有
    `收數`→`收款` 和 `數對`→`帳對`，`數對` 就永遠輪不到。

    這個檢查零誤報（比對的是詞表自己的宣告），但也只抓得到「在條目本身
    的字面範圍內」發生的遮蔽。跨詞邊界的遮蔽（`再傾` 擋住 `傾下` 那種）
    只有第 5 項的整句回歸測試抓得到 —— 所以兩項都要留。
    """
    table = build_table()
    problems = []
    for src, expected in table.items():
        got = tr.translate(src).text
        # 句末語氣詞會被刪掉，所以譯文本身就是語氣詞的條目要跳過
        if expected != src and not got:
            continue
        if got != expected:
            problems.append(
                f"詞條 {src!r} 應該翻成 {expected!r}，實際卻得到 {got!r}"
                f" —— 有別的條目把它遮蔽了"
            )
    return problems


def check_regressions(tr: LexiconTranslator) -> list[str]:
    problems = []
    for src, expected in CANTONESE_EXPECTED:
        got = tr.translate(src).text
        if got != expected:
            problems.append(
                f"翻譯結果與預期不符：\n    粵  : {src}\n"
                f"    預期: {expected}\n    實得: {got}\n"
                f"    {_first_diff(expected, got)}"
            )
    return problems


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            lo = max(0, i - 4)
            return f"↑ 第 {i + 1} 字起：{a[lo:i + 6]!r} → {b[lo:i + 6]!r}"
    return f"↑ 長度不同：{len(a)} → {len(b)}"


def main() -> int:
    tr = LexiconTranslator()
    print(f"詞表條目：{tr.entry_count}（含 {len(GUARDS)} 個保護詞）")
    print(f"安全單字：{len(SAFE_SINGLES)} 個\n")

    failed = 0

    for title, problems in (
        ("1. 單字白名單", check_single_chars()),
        ("2. 保護詞覆蓋", check_guard_coverage()),
        ("3. 簡體殘留檢查", check_traditional()),
        ("4. 普通話誤傷測試", check_no_false_positives(tr)),
        ("5. 粵語翻譯回歸測試", check_regressions(tr)),
        ("6. 詞條自我一致性", check_self_consistency(tr)),
    ):
        real = [p for p in problems if not p.startswith("（")]
        status = "OK" if not real else f"{len(real)} 個問題"
        print(f"=== {title}：{status} ===")
        for p in problems[:30]:
            print(f"  {p}")
        if len(problems) > 30:
            print(f"  ...另外還有 {len(problems) - 30} 筆")
        if not problems:
            print("  通過")
        print()
        failed += len(real)

    print("=== 7. 已知限制（需要 engine = claude 才翻得好）===")
    for src, why in KNOWN_LIMITS:
        print(f"  粵  : {src}")
        print(f"  詞典: {tr.translate(src).text}")
        print(f"  說明: {why}")
    print()

    print("=== 8. 混合模式會把哪些句子送去 API ===")
    corpus = ([s for s, _ in CANTONESE_EXPECTED]
              + [s for s, _ in KNOWN_LIMITS]
              + list(MANDARIN_CORPUS)
              + ["可以", "明白", "好啊", "冇問題", "多謝"])
    escalated = 0
    for src in corpus:
        out = tr.translate(src).text
        reason = needs_word_order_help(src, out)
        if reason:
            escalated += 1
            print(f"  送 API（{reason}）: {out}")
    rate = escalated / len(corpus) * 100
    print(f"\n  {len(corpus)} 句中有 {escalated} 句會送 API（{rate:.0f}%）")
    print(f"  詞典擋下 {len(corpus) - escalated} 句，不花錢")
    print()

    if failed:
        print(f"!! 共 {failed} 個問題需要修正")
        return 1
    print("全部檢查通過。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
