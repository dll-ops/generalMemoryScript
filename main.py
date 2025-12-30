import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Optional dependency: pandas for reading xlsx/csv/tsv robustly
try:
    import pandas as pd
except Exception as e:
    pd = None


def normalize_text(s: str) -> str:
    """Normalize for answer checking."""
    if s is None:
        return ""
    s = str(s).strip()
    # Collapse internal whitespace
    s = " ".join(s.split())
    return s.lower()


class ABDeck:
    """Holds pairs and supports quiz card sampling."""
    def __init__(self):
        self.pairs = []  # list[tuple[str, str]] (A, B)
        self.filepath = ""
        self.columns = []

    def load_table(self, filepath: str) -> None:
        if pd is None:
            raise RuntimeError("缺少依赖 pandas。请先 pip install pandas openpyxl")

        self.filepath = filepath
        lower = filepath.lower()

        if lower.endswith(".xlsx"):
            df = pd.read_excel(filepath, engine="openpyxl")
        elif lower.endswith(".csv"):
            df = pd.read_csv(filepath)
        elif lower.endswith(".tsv"):
            df = pd.read_csv(filepath, sep="\t")
        else:
            raise ValueError("不支持的文件格式。请使用 .xlsx / .csv / .tsv")

        # Keep original columns order
        self.columns = [str(c) for c in df.columns]

        # Convert to string-ish; keep NaN as None
        df = df.copy()

        # Store df for later selection
        self._df = df

    def build_pairs(self, col_a: str, col_b: str) -> int:
        df = getattr(self, "_df", None)
        if df is None:
            return 0

        if col_a not in df.columns or col_b not in df.columns:
            return 0

        pairs = []
        for _, row in df[[col_a, col_b]].iterrows():
            a = row[col_a]
            b = row[col_b]
            if pd is not None:
                # pd.NA/NaN handling
                if pd.isna(a) or pd.isna(b):
                    continue
            a = str(a).strip()
            b = str(b).strip()
            if not a or not b:
                continue
            pairs.append((a, b))

        self.pairs = pairs
        return len(self.pairs)

    def is_ready(self) -> bool:
        return len(self.pairs) > 0

    def all_As(self):
        return [a for a, _ in self.pairs]

    def all_Bs(self):
        return [b for _, b in self.pairs]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("A-B 对照记忆工具")
        self.geometry("980x620")
        self.minsize(900, 560)

        self.deck = ABDeck()
        self.review_only = False
        self.wrong_set = set()  # store indices of wrong cards

        # Quiz state
        self.current_index = None
        self.current_prompt = ""
        self.current_answer = ""
        self.current_direction = "A->B"
        self.mode = "choice"  # "choice" or "fill"
        self.choice_count = 4
        self.total = 0
        self.correct = 0

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_load = ttk.Frame(nb)
        self.tab_quiz = ttk.Frame(nb)

        nb.add(self.tab_load, text="导入/建立对应")
        nb.add(self.tab_quiz, text="记忆练习")

        self._build_tab_load()
        self._build_tab_quiz()

    # ----------------------
    # Tab 1: Load & mapping
    # ----------------------
    def _build_tab_load(self):
        frm = ttk.Frame(self.tab_load)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        top = ttk.LabelFrame(frm, text="1) 选择文件")
        top.pack(fill="x", padx=8, pady=8)

        self.file_label_var = tk.StringVar(value="未选择文件")
        ttk.Button(top, text="选择表格文件（.xlsx/.csv/.tsv）", command=self.pick_file).pack(
            side="left", padx=8, pady=10
        )
        ttk.Label(top, textvariable=self.file_label_var).pack(side="left", padx=10)

        mid = ttk.LabelFrame(frm, text="2) 选择 A 列（B 列自动 = A 的下一列）")
        mid.pack(fill="x", padx=8, pady=8)

        self.colA_var = tk.StringVar(value="")
        self.colA_combo = ttk.Combobox(mid, textvariable=self.colA_var, state="readonly", width=40)
        self.colA_combo.pack(side="left", padx=8, pady=10)
        self.colA_combo.bind("<<ComboboxSelected>>", lambda e: self._update_colB_label())

        self.colB_label_var = tk.StringVar(value="B 列：-")
        ttk.Label(mid, textvariable=self.colB_label_var).pack(side="left", padx=10)

        self.build_btn = ttk.Button(mid, text="建立 A-B 对应关系", command=self.build_mapping, state="disabled")
        self.build_btn.pack(side="left", padx=8)

        bot = ttk.LabelFrame(frm, text="状态")
        bot.pack(fill="both", expand=True, padx=8, pady=8)

        self.status_var = tk.StringVar(value="请先导入文件。")
        ttk.Label(bot, textvariable=self.status_var).pack(anchor="w", padx=10, pady=10)

        tips = (
            "规则：你只要指定 A 在哪一列，程序自动把它右边那一列当作 B。\n"
            "如果表格只有两列，会自动默认 A=第一列，B=第二列。"
        )
        ttk.Label(bot, text=tips, foreground="#444").pack(anchor="w", padx=10, pady=2)

    def pick_file(self):
        fp = filedialog.askopenfilename(
            title="选择表格文件",
            filetypes=[
                ("Excel", "*.xlsx"),
                ("CSV", "*.csv"),
                ("TSV", "*.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not fp:
            return

        try:
            self.deck.load_table(fp)
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return

        self.file_label_var.set(fp)
        cols = self.deck.columns

        if not cols:
            messagebox.showerror("读取失败", "未检测到列名/列。")
            return

        self.colA_combo["values"] = cols

        # Auto default: if 2 cols, pick first; else pick first column by default
        self.colA_var.set(cols[0])
        self._update_colB_label()

        self.build_btn.config(state="normal")
        self.status_var.set(f"已读取文件，共 {len(cols)} 列。请选择 A 列并建立对应关系。")

    def _update_colB_label(self):
        cols = self.deck.columns
        a = self.colA_var.get()
        if a in cols:
            idx = cols.index(a)
            if idx + 1 < len(cols):
                b = cols[idx + 1]
                self.colB_label_var.set(f"B 列：{b}")
            else:
                self.colB_label_var.set("B 列：不存在（A 已是最后一列）")
        else:
            self.colB_label_var.set("B 列：-")

    def build_mapping(self):
        cols = self.deck.columns
        a = self.colA_var.get()
        if a not in cols:
            messagebox.showerror("错误", "请选择有效的 A 列。")
            return
        idx = cols.index(a)
        if idx + 1 >= len(cols):
            messagebox.showerror("错误", "A 已是最后一列，无法自动取到 B=下一列。")
            return
        b = cols[idx + 1]

        try:
            n = self.deck.build_pairs(a, b)
        except Exception as e:
            messagebox.showerror("建立失败", str(e))
            return

        if n <= 0:
            messagebox.showwarning("无数据", "没有读取到有效的 A-B 行（可能有空值/空白行）。")
            self.status_var.set("建立对应失败：无有效行。")
            return

        # Reset quiz stats
        self.wrong_set.clear()
        self.total = 0
        self.correct = 0

        self.status_var.set(f"✅ 已建立对应：{n} 组（A={a}，B={b}）。现在可以去“记忆练习”页开始。")
        self._refresh_quiz_ui_enabled(True)

    # ----------------------
    # Tab 2: Quiz
    # ----------------------
    def _build_tab_quiz(self):
        frm = ttk.Frame(self.tab_quiz)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        cfg = ttk.LabelFrame(frm, text="练习设置")
        cfg.pack(fill="x", padx=8, pady=8)

        # Mode
        self.mode_var = tk.StringVar(value="choice")
        ttk.Radiobutton(cfg, text="给 x 选 y（选择题）", variable=self.mode_var, value="choice",
                        command=self._apply_settings).grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Radiobutton(cfg, text="给 x 填 y（填空题）", variable=self.mode_var, value="fill",
                        command=self._apply_settings).grid(row=0, column=1, padx=8, pady=8, sticky="w")

        # Direction
        self.dir_var = tk.StringVar(value="A->B")
        ttk.Radiobutton(cfg, text="x=A → y=B", variable=self.dir_var, value="A->B",
                        command=self._apply_settings).grid(row=1, column=0, padx=8, pady=8, sticky="w")
        ttk.Radiobutton(cfg, text="x=B → y=A", variable=self.dir_var, value="B->A",
                        command=self._apply_settings).grid(row=1, column=1, padx=8, pady=8, sticky="w")

        # Choices
        ttk.Label(cfg, text="选项数：").grid(row=0, column=2, padx=8, pady=8, sticky="e")
        self.choice_var = tk.IntVar(value=4)
        self.choice_spin = ttk.Spinbox(cfg, from_=2, to=8, textvariable=self.choice_var, width=5,
                                       command=self._apply_settings)
        self.choice_spin.grid(row=0, column=3, padx=8, pady=8, sticky="w")

        # Review-only
        self.review_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="只练错题", variable=self.review_var, command=self._apply_settings)\
            .grid(row=1, column=2, padx=8, pady=8, sticky="w")

        for i in range(4):
            cfg.grid_columnconfigure(i, weight=0)
        cfg.grid_columnconfigure(4, weight=1)

        quiz = ttk.LabelFrame(frm, text="题目")
        quiz.pack(fill="both", expand=True, padx=8, pady=8)

        self.prompt_var = tk.StringVar(value="（请先在“导入/建立对应”页建立 A-B 数据）")
        self.answer_var = tk.StringVar(value="")

        ttk.Label(quiz, textvariable=self.prompt_var, wraplength=860, font=("Arial", 16))\
            .pack(anchor="w", padx=12, pady=(14, 8))

        self.choice_frame = ttk.Frame(quiz)
        self.choice_frame.pack(fill="x", padx=12, pady=8)

        self.fill_frame = ttk.Frame(quiz)
        self.fill_frame.pack(fill="x", padx=12, pady=8)

        # Fill mode widgets
        ttk.Label(self.fill_frame, text="你的答案：").pack(side="left")
        self.fill_entry = ttk.Entry(self.fill_frame, width=50)
        self.fill_entry.pack(side="left", padx=8)
        self.fill_submit_btn = ttk.Button(self.fill_frame, text="提交", command=self.submit_fill)
        self.fill_submit_btn.pack(side="left", padx=8)

        # Answer display
        self.answer_label = ttk.Label(quiz, textvariable=self.answer_var, wraplength=860, foreground="#333")
        self.answer_label.pack(anchor="w", padx=12, pady=10)

        # Control buttons
        ctrl = ttk.Frame(frm)
        ctrl.pack(fill="x", padx=8, pady=8)

        self.btn_next = ttk.Button(ctrl, text="下一题", command=self.next_question, state="disabled")
        self.btn_show = ttk.Button(ctrl, text="显示答案", command=self.show_answer, state="disabled")
        self.btn_wrong = ttk.Button(ctrl, text="标记为错题", command=self.mark_wrong, state="disabled")
        self.btn_reset_wrong = ttk.Button(ctrl, text="清空错题", command=self.clear_wrong, state="disabled")

        self.btn_next.pack(side="left", padx=6, pady=6)
        self.btn_show.pack(side="left", padx=6, pady=6)
        self.btn_wrong.pack(side="left", padx=6, pady=6)
        self.btn_reset_wrong.pack(side="left", padx=6, pady=6)

        self.score_var = tk.StringVar(value="正确率：-")
        ttk.Label(ctrl, textvariable=self.score_var).pack(side="right", padx=10)

        self._apply_settings()
        self._refresh_quiz_ui_enabled(False)

    def _apply_settings(self):
        self.mode = self.mode_var.get()
        self.current_direction = self.dir_var.get()
        self.choice_count = int(self.choice_var.get())
        self.review_only = bool(self.review_var.get())

        # Toggle mode frames
        if self.mode == "choice":
            self.fill_frame.pack_forget()
            self.choice_frame.pack(fill="x", padx=12, pady=8)
        else:
            self.choice_frame.pack_forget()
            self.fill_frame.pack(fill="x", padx=12, pady=8)

        # If ready, refresh question type UI
        if self.deck.is_ready():
            self.next_question()

    def _refresh_quiz_ui_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_next.config(state=state)
        self.btn_show.config(state=state)
        self.btn_wrong.config(state=state)
        self.btn_reset_wrong.config(state=state)
        self.fill_submit_btn.config(state=state)
        self.choice_spin.config(state=("readonly" if enabled else "disabled"))

        if not enabled:
            # Clear choices/buttons
            for w in self.choice_frame.winfo_children():
                w.destroy()

    def _candidate_indices(self):
        if not self.deck.is_ready():
            return []
        if self.review_only:
            return sorted(list(self.wrong_set))
        return list(range(len(self.deck.pairs)))

    def next_question(self):
        if not self.deck.is_ready():
            return

        candidates = self._candidate_indices()
        if not candidates:
            if self.review_only:
                self.prompt_var.set("✅ 当前没有错题可练。")
            else:
                self.prompt_var.set("没有可用题目。")
            self.answer_var.set("")
            self._clear_choice_buttons()
            return

        self.current_index = random.choice(candidates)
        a, b = self.deck.pairs[self.current_index]

        if self.current_direction == "A->B":
            self.current_prompt = a
            self.current_answer = b
        else:
            self.current_prompt = b
            self.current_answer = a

        self.prompt_var.set(f"x：{self.current_prompt}")
        self.answer_var.set("")
        self._clear_choice_buttons()

        if self.mode == "choice":
            self._render_choices()
        else:
            self.fill_entry.delete(0, tk.END)
            self.fill_entry.focus_set()

    def _clear_choice_buttons(self):
        for w in self.choice_frame.winfo_children():
            w.destroy()

    def _render_choices(self):
        # Build options: correct answer + random distractors from same answer domain
        all_answers = self.deck.all_Bs() if self.current_direction == "A->B" else self.deck.all_As()
        all_answers = list({normalize_text(x): x for x in all_answers}.values())  # unique-ish

        correct = self.current_answer
        options = [correct]

        # Distractors
        pool = [x for x in all_answers if normalize_text(x) != normalize_text(correct)]
        random.shuffle(pool)
        while len(options) < self.choice_count and pool:
            options.append(pool.pop())

        # If dataset too small, shrink
        random.shuffle(options)

        # Render as big clickable buttons
        grid = ttk.Frame(self.choice_frame)
        grid.pack(fill="x")

        cols = 2 if len(options) > 3 else 1
        for i, opt in enumerate(options):
            btn = ttk.Button(grid, text=opt, command=lambda o=opt: self.choose_answer(o))
            r = i // cols
            c = i % cols
            btn.grid(row=r, column=c, sticky="ew", padx=8, pady=8, ipadx=6, ipady=10)
            grid.grid_columnconfigure(c, weight=1)

    def choose_answer(self, chosen: str):
        self.total += 1
        if normalize_text(chosen) == normalize_text(self.current_answer):
            self.correct += 1
            self.answer_var.set("✅ 正确！")
            # If it was wrong before and user got it right, optionally remove from wrong set
            # (We keep it unless user clears; easier & conservative.)
        else:
            self.answer_var.set(f"❌ 错误。\n正确答案：{self.current_answer}")
            self.wrong_set.add(self.current_index)

        self._update_score()

    def submit_fill(self):
        user_ans = self.fill_entry.get()
        self.total += 1
        if normalize_text(user_ans) == normalize_text(self.current_answer):
            self.correct += 1
            self.answer_var.set("✅ 正确！")
        else:
            self.answer_var.set(f"❌ 错误。\n正确答案：{self.current_answer}")
            self.wrong_set.add(self.current_index)
        self._update_score()

    def show_answer(self):
        if not self.deck.is_ready() or self.current_index is None:
            return
        self.answer_var.set(f"答案：{self.current_answer}")

    def mark_wrong(self):
        if self.current_index is None:
            return
        self.wrong_set.add(self.current_index)
        self.answer_var.set("已标记为错题。")

    def clear_wrong(self):
        self.wrong_set.clear()
        self.answer_var.set("已清空错题。")
        self._apply_settings()

    def _update_score(self):
        if self.total <= 0:
            self.score_var.set("正确率：-")
            return
        rate = (self.correct / self.total) * 100.0
        self.score_var.set(f"正确率：{self.correct}/{self.total}（{rate:.1f}%）")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()