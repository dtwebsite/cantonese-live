"""置頂浮動字幕視窗（tkinter，無額外依賴）。

無邊框 + 永遠置頂 + 可調透明度，疊在 Google Meet / Zoom 視窗旁邊看。
沒有系統標題列，所以自己畫了一條可拖曳的頂欄和右下角的縮放把手。

鍵盤：
    Esc / Ctrl+Q（Mac 也可 ⌘Q）   結束
    Ctrl + / -（Mac 也可 ⌘）       放大 / 縮小字級
    Ctrl + 0                       重設字級
    F                              切換是否顯示粵語原文
    J                              切換是否顯示粵拼
    T                              切換置頂
    空白鍵                         暫停／繼續捲動（想回看前面幾句時用）
"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
from collections import deque
from typing import Callable

from .config import UiConfig
from .pipeline import Line

# 深色底，開會時疊在視窗旁不刺眼
BG = "#14161a"
BG_BAR = "#1e2128"
FG_TRANSLATED = "#f2f4f8"   # 普通話
# 粵語原文：比譯文暗一階以便區分，但仍然要能直接讀 —— 粵語書面文字
# 本身就有七八成看得懂，原文常常比譯文更貼近對方的原意。
FG_ORIGINAL = "#aab4c2"
FG_JYUTPING = "#7f8a9a"     # 粵拼：再暗一階，是原文的附註
FG_META = "#5a616c"
FG_ACCENT = "#5fb3f2"
FG_WARN = "#e8a33d"
FG_ERROR = "#e06c6c"


class Overlay:
    """字幕視窗。必須在主執行緒建立並呼叫 run()。"""

    def __init__(
        self,
        cfg: UiConfig,
        on_close: Callable[[], None] | None = None,
        title: str = "粵語即時翻譯",
    ) -> None:
        self.cfg = cfg
        self._on_close = on_close
        self._queue: queue.Queue[Line] = queue.Queue()
        self._status_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._show_original = cfg.show_original
        self._show_jyutping = cfg.show_jyutping
        self._font_size = cfg.font_size
        self._paused = False
        self._closed = False
        # 每句開頭放一個 tkinter mark，裁掉舊內容時用它定位
        self._marks: deque[str] = deque()
        self._entry_seq = 0

        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.geometry(f"{cfg.width}x{cfg.height}+80+80")
        self._set_topmost(cfg.always_on_top)
        try:
            self.root.attributes("-alpha", max(0.3, min(1.0, cfg.opacity)))
        except tk.TclError:
            pass  # 少數環境不支援半透明，照常顯示

        self._build_bar()
        self._build_text()
        self._build_grip()
        self._bind_keys()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self._drain)

    # -- 版面 -------------------------------------------------------------

    def _build_bar(self) -> None:
        bar = tk.Frame(self.root, bg=BG_BAR, height=28)
        bar.pack(side=tk.TOP, fill=tk.X)
        bar.pack_propagate(False)

        self._dot = tk.Label(bar, text="●", bg=BG_BAR, fg=FG_META,
                             font=("Segoe UI", 10))
        self._dot.pack(side=tk.LEFT, padx=(10, 4))

        self._status = tk.Label(
            bar, text="啟動中…", bg=BG_BAR, fg=FG_META, anchor="w",
            font=(self.cfg.font_family, 9),
        )
        self._status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        for text, cmd in (
            ("A-", lambda: self._bump_font(-1)),
            ("A+", lambda: self._bump_font(+1)),
            ("原", self._toggle_original),
            ("頂", self._toggle_topmost),
            ("✕", self.close),
        ):
            btn = tk.Label(bar, text=text, bg=BG_BAR, fg=FG_META,
                           font=(self.cfg.font_family, 9), cursor="hand2",
                           padx=7)
            btn.pack(side=tk.RIGHT)
            btn.bind("<Button-1>", lambda _e, c=cmd: c())
            btn.bind("<Enter>", lambda e: e.widget.config(fg=FG_TRANSLATED))
            btn.bind("<Leave>", lambda e: e.widget.config(fg=FG_META))

        # 拖曳移動視窗
        for widget in (bar, self._status, self._dot):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
        self._bar = bar

    def _build_text(self) -> None:
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.text = tk.Text(
            wrap, bg=BG, fg=FG_TRANSLATED, bd=0, highlightthickness=0,
            wrap=tk.WORD, padx=14, pady=10, spacing1=2, spacing3=6,
            cursor="arrow", state=tk.DISABLED, takefocus=False,
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bar = tk.Scrollbar(wrap, command=self.text.yview, width=8,
                           bg=BG, troughcolor=BG, bd=0, highlightthickness=0,
                           activebackground=FG_META)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.config(yscrollcommand=bar.set)

        self._apply_fonts()
        self.text.tag_configure("translated", foreground=FG_TRANSLATED)
        self.text.tag_configure("original", foreground=FG_ORIGINAL)
        self.text.tag_configure("jyutping", foreground=FG_JYUTPING)
        self.text.tag_configure("meta", foreground=FG_META)
        self.text.tag_configure("notice", foreground=FG_ACCENT)
        self.text.tag_configure("warn", foreground=FG_WARN)
        self.text.tag_configure("error", foreground=FG_ERROR)

    def _build_grip(self) -> None:
        grip = tk.Label(self.root, text="◢", bg=BG, fg=FG_META,
                        cursor="bottom_right_corner",
                        font=("Segoe UI", 8))
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<Button-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_move)

    def _apply_fonts(self) -> None:
        family = self.cfg.resolved_font_family()
        small = max(8, self._font_size - (self.cfg.font_size
                                          - self.cfg.original_font_size))
        self._font_main = tkfont.Font(family=family, size=self._font_size)
        self._font_small = tkfont.Font(family=family, size=small)
        self._font_meta = tkfont.Font(family=family, size=max(7, small - 2))
        self._font_jyutping = tkfont.Font(family=family, size=max(8, small - 1))
        self.text.config(font=self._font_main)
        for tag, font in (("translated", self._font_main),
                          ("original", self._font_small),
                          ("jyutping", self._font_jyutping),
                          ("meta", self._font_meta),
                          ("notice", self._font_small),
                          ("warn", self._font_small),
                          ("error", self._font_small)):
            self.text.tag_configure(tag, font=font)

    # -- 互動 -------------------------------------------------------------

    def _bind_keys(self) -> None:
        r = self.root
        r.bind("<Escape>", lambda _e: self.close())
        r.bind("<Control-q>", lambda _e: self.close())
        r.bind("<Control-plus>", lambda _e: self._bump_font(+1))
        r.bind("<Control-equal>", lambda _e: self._bump_font(+1))
        r.bind("<Control-minus>", lambda _e: self._bump_font(-1))
        r.bind("<Control-Key-0>", lambda _e: self._reset_font())
        r.bind("<f>", lambda _e: self._toggle_original())
        r.bind("<F>", lambda _e: self._toggle_original())
        r.bind("<j>", lambda _e: self._toggle_jyutping())
        r.bind("<J>", lambda _e: self._toggle_jyutping())
        r.bind("<t>", lambda _e: self._toggle_topmost())
        r.bind("<T>", lambda _e: self._toggle_topmost())
        r.bind("<space>", lambda _e: self._toggle_pause())
        if sys.platform == "darwin":
            r.bind("<Command-q>", lambda _e: self.close())
            r.bind("<Command-plus>", lambda _e: self._bump_font(+1))
            r.bind("<Command-equal>", lambda _e: self._bump_font(+1))
            r.bind("<Command-minus>", lambda _e: self._bump_font(-1))
            r.bind("<Command-Key-0>", lambda _e: self._reset_font())
        r.focus_force()

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_from = (event.x_root - self.root.winfo_x(),
                           event.y_root - self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        dx, dy = self._drag_from
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _resize_start(self, event: tk.Event) -> None:
        self._resize_from = (event.x_root, event.y_root,
                             self.root.winfo_width(), self.root.winfo_height())

    def _resize_move(self, event: tk.Event) -> None:
        x0, y0, w0, h0 = self._resize_from
        w = max(320, w0 + event.x_root - x0)
        h = max(140, h0 + event.y_root - y0)
        self.root.geometry(f"{w}x{h}")

    def _bump_font(self, delta: int) -> None:
        self._font_size = max(9, min(48, self._font_size + delta))
        self._apply_fonts()

    def _reset_font(self) -> None:
        self._font_size = self.cfg.font_size
        self._apply_fonts()

    def _toggle_original(self) -> None:
        self._show_original = not self._show_original
        self.notice("顯示粵語原文" if self._show_original else "只顯示普通話")

    def _toggle_jyutping(self) -> None:
        self._show_jyutping = not self._show_jyutping
        self.notice("顯示粵拼" if self._show_jyutping else "不顯示粵拼")

    def _set_topmost(self, on: bool) -> None:
        self._topmost = on
        try:
            self.root.attributes("-topmost", on)
        except tk.TclError:
            pass

    def _toggle_topmost(self) -> None:
        self._set_topmost(not self._topmost)
        self.notice("已置頂" if self._topmost else "取消置頂")

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.notice("已暫停自動捲動（可往上回看）" if self._paused
                    else "恢復自動捲動")

    # -- 外部 API（可從其他執行緒呼叫） -----------------------------------

    def submit(self, line: Line) -> None:
        """從工作執行緒送一句進來。"""
        self._queue.put(line)

    def status(self, message: str, kind: str = "meta") -> None:
        self._status_queue.put((message, kind))

    def notice(self, message: str) -> None:
        self._append_notice(message, "notice")

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._on_close is not None:
            self._on_close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # -- 輪詢（在主執行緒） ------------------------------------------------

    def _drain(self) -> None:
        if self._closed:
            return

        while True:
            try:
                message, kind = self._status_queue.get_nowait()
            except queue.Empty:
                break
            colour = {"meta": FG_META, "warn": FG_WARN,
                      "error": FG_ERROR, "notice": FG_ACCENT}.get(kind, FG_META)
            self._status.config(text=message, fg=colour)
            if kind in ("warn", "error"):
                self._append_notice(message, kind)

        drained = 0
        while drained < 20:  # 一次最多處理 20 句，別讓 UI 卡住
            try:
                line = self._queue.get_nowait()
            except queue.Empty:
                break
            self._append_line(line)
            drained += 1

        self.root.after(50, self._drain)

    def _append_line(self, line: Line) -> None:
        utt, tr = line.utterance, line.translation
        self.text.config(state=tk.NORMAL)

        # 在這句的開頭放一個 mark，之後裁掉舊內容時用它定位。
        #
        # 兩個細節是實測出來的，寫錯會整個文字區被清空：
        #  1. 必須先用 index() 取出「具體」索引（如 "7.0"）再 mark_set。
        #     直接 mark_set(mark, tk.END) 不行 —— "end" 是動態索引，位置在
        #     自動結尾換行之後，mark 會被後續插入一路推到最尾端。
        #  2. gravity 必須是 LEFT，mark 才會留在新插入文字的前面。
        mark = f"entry{self._entry_seq}"
        self._entry_seq += 1
        self.text.mark_set(mark, self.text.index("end-1c"))
        self.text.mark_gravity(mark, tk.LEFT)
        self._marks.append(mark)

        if self._show_original and utt.text != tr.text:
            self.text.insert(tk.END, f"{utt.text}\n", "original")
        if self._show_original and self._show_jyutping and line.jyutping:
            self.text.insert(tk.END, f"{line.jyutping}\n", "jyutping")
        self.text.insert(tk.END, f"{tr.text}\n", "translated")

        meta = f"{_clock(utt.start_s)} · 處理 {line.latency_s:.1f}s"
        if tr.engine not in ("lexicon", "none"):
            meta += f" · {tr.engine}"
        if tr.note:
            meta += f" · {tr.note}"
        self.text.insert(tk.END, f"{meta}\n\n", "meta")

        self._trim()
        self.text.config(state=tk.DISABLED)
        if not self._paused:
            self.text.see(tk.END)

    def _append_notice(self, message: str, tag: str) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.insert(tk.END, f"— {message} —\n\n", tag)
        self.text.config(state=tk.DISABLED)
        if not self._paused:
            self.text.see(tk.END)

    def _trim(self) -> None:
        """只留最近 max_entries 句，長會議才不會越來越吃記憶體。

        靠 mark 定位而不是算行數 —— 每句佔的行數不固定（原文可能不顯示），
        中間還會插入通知訊息，用行數估算會刪太多或刪太少。
        """
        while len(self._marks) > self.cfg.max_entries:
            oldest = self._marks.popleft()
            # 刪到「下一句的開頭」，剩下的 mark 會自動跟著文字移動
            boundary = self._marks[0] if self._marks else tk.END
            self.text.delete("1.0", boundary)
            self.text.mark_unset(oldest)

    def set_indicator(self, listening: bool, speaking: bool) -> None:
        if self._closed:
            return
        if not listening:
            self._dot.config(fg=FG_ERROR)
        elif speaking:
            self._dot.config(fg=FG_ACCENT)
        else:
            self._dot.config(fg=FG_META)

    def every(self, ms: int, fn: Callable[[], None]) -> None:
        """註冊一個週期性的回呼（在主執行緒跑）。"""
        def tick() -> None:
            if self._closed:
                return
            fn()
            self.root.after(ms, tick)
        self.root.after(ms, tick)


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"
