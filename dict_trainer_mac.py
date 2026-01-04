#mac适配-通用记忆程序
# -*- coding: utf-8 -*-
"""Dictionary Trainer (Terminal, curses UI)

从“相邻两列”的表格加载 A-B 对照关系，并提供对照记忆训练：
- 记忆卡（双面浏览）
- 选择题（给 x 选 y）
- 填空题（给 x 填 y）
- 判断题（Q=正确 / E=错误）
- 错题本（权重强化判断）

支持文件：
- .xlsx / .xlsm（需要 openpyxl）
- .csv / .tsv / .txt
- .json（形如 [[A,B], ...] 或 [{"A":...,"B":...}, ...]）

Windows：需要 pip install windows-curses

用法示例：
  python dict_trainer.py /path/to/dict.xlsx
  python dict_trainer.py /path/to/dict.xlsx --col 3   # 用第3列和第4列作为 A/B（1-based）
  python dict_trainer.py /path/to/dict.csv --sep '\t'
"""

from __future__ import annotations

import argparse
import csv
import curses
import json
import locale
import os
import unicodedata
import random
import re
import time
import uuid
import difflib
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

locale.setlocale(locale.LC_ALL, "")

# --------------------------- Utilities ---------------------------

SEPS_PATTERN = re.compile(r"[,\s，、;；|/]+")
ALTS_PATTERN = re.compile(r"\s*(?:\||；|;|/|、)\s*")
import unicodedata
import locale

_PUNCT_RE = re.compile(r"[，。！？；：、,.!?;:\-—()\[\]{}\"'“”‘’·…]+")
_WS_RE = re.compile(r"\s+")

def _norm(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("　", " ")              # 全角空格
    s = _PUNCT_RE.sub("", s)              # 去标点
    s = _WS_RE.sub(" ", s)                # 合并空白
    return s.strip()

def _short_suffix_collapse(s: str) -> str:
    # 只对极短答案做“是/是的”这种容忍
    # 你可以按自己的习惯继续加
    mapping = {
        "是的": "是",
        "对的": "对",
        "好的": "好",
        "可以的": "可以",
        "不是的": "不是",
        "不对的": "不对",
    }
    return mapping.get(s, s)

def word_count(s: str) -> int:
    # 用 norm_text 统一清洗，再按空格分词
    t = norm_text(s)
    if not t:
        return 0
    return len([w for w in t.split(" ") if w])

def is_correct_fuzzy(user: str, correct: str, *, threshold: float = 0.80, min_len_for_fuzzy: int = 4) -> bool:
    u = _norm(user)
    c = _norm(correct)

    # 先处理“是/是的”这类短后缀
    u2 = _short_suffix_collapse(u)
    c2 = _short_suffix_collapse(c)

    # 先给一个“宽松的完全匹配”
    if u2 == c2:
        return True

    # 太短就别模糊（避免把“是”随便判对）
    if len(c2) < min_len_for_fuzzy:
        return False

    # 相似度（SequenceMatcher 基于编辑/块匹配，够用且无依赖）
    ratio = difflib.SequenceMatcher(None, u2, c2).ratio()
    return ratio >= threshold

import os, json

def _pref_path() -> str:
    # 放在项目同目录（最符合你“可复用、可携带”的诉求）
    # 如果你更想全局记忆，也可以换成 os.path.expanduser("~/.generalMemoryScript.json")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, ".gms_prefs.json")

def load_prefs() -> dict:
    p = _pref_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_prefs(d: dict) -> None:
    p = _pref_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_last_deck_path() -> str | None:
    path, _, _ = get_last_deck_info()
    return path

def get_last_deck_info() -> tuple[str | None, int, str | None]:
    d = load_prefs()
    path = d.get("last_deck_path")
    if path and os.path.isfile(path):
        col = d.get("last_deck_col", 1)
        sep = d.get("last_deck_sep")
        try:
            col = int(col)
        except Exception:
            col = 1
        return path, max(1, col), sep
    return None, 1, None

def set_last_deck_path(path: str) -> None:
    d = load_prefs()
    d["last_deck_path"] = path
    save_prefs(d)

def set_last_deck_info(path: str, col: int, sep: str | None) -> None:
    d = load_prefs()
    d["last_deck_path"] = path
    d["last_deck_col"] = int(col)
    d["last_deck_sep"] = sep
    save_prefs(d)

def ensure_deck_ready(stdscr, state) -> bool:
    """
    若当前仍是内置默认词典（2条 bonjour/merci）且存在上次词典，
    则提示是否应用上次词典。用户选择否，则继续使用当前词典。
    返回 True 表示可以继续进入训练模式；False 表示用户取消返回菜单。
    """
    last_path, last_col, last_sep = get_last_deck_info()
    if not last_path:
        return True

    # 你现在的“默认词典”识别方式：按你描述就是两条 bonjour/merci
    # 用更稳妥的方法：deck_path 是 "<内置示例>" 或 len(deck)==2 且内容匹配
    try:
        is_default = (
            getattr(state, "deck_path", "") == "<内置示例>" or
            (len(state.deck) == 2 and
             norm_text(state.deck[0].get("A","")) == "bonjour" and
             norm_text(state.deck[1].get("A","")) == "merci")
        )
    except Exception:
        is_default = False

    if not is_default:
        return True

    # 弹窗询问（你项目里如果已有 yes/no 弹窗函数就用你的）
    draw_header(stdscr, "检测到上次词典")
    center_text(stdscr, 6, "当前未导入词典。是否应用上次使用的词典？")
    safe_addstr(stdscr, 8, 4, f"上次词典：{last_path}")
    safe_addstr(stdscr, 10, 4, "按 y 应用；按 n 继续使用当前默认词典；按 Esc 返回")
    stdscr.refresh()

    k = wait_key(stdscr)
    if k == "esc":
        return False
    if k in ("y", "Y"):
        # 复用你现有的“加载词典”底层函数
        # 你代码里大概率有类似：load_deck_from_path(path) 或 read_pairs(path)
        try:
            new_state = load_deck_into_state(state, last_path, last_col, last_sep)
            if new_state is None:
                raise RuntimeError("读取上次词典失败")
            # 如果你 load 函数返回 new_state
            state.deck = new_state.deck
            state.deck_path = new_state.deck_path
            state.deck_id = new_state.deck_id
            state.wrong_path = new_state.wrong_path
            state.wrong_db = new_state.wrong_db
            return True
        except Exception as e:
            draw_header(stdscr, "应用失败")
            center_text(stdscr, 6, "❌ 读取上次词典失败，已继续使用默认词典。")
            safe_addstr(stdscr, 8, 4, str(e)[:200])
            stdscr.refresh()
            wait_key(stdscr)
            return True
    return True


def file_sha1(path: str, max_bytes: int = 2_000_000) -> str:
    """取文件前 max_bytes 做 sha1（够稳定且快）"""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(max_bytes))
    return h.hexdigest()[:12]

def wrongbook_path_for_deck(deck_path: str) -> str:
    """
    为某个词典生成稳定的错题本路径：
    .wrongbooks/<词典文件名>.<hash>.wrong.json
    """
    here = os.path.dirname(os.path.abspath(__file__))
    wb_dir = os.path.join(here, ".wrongbooks")
    os.makedirs(wb_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(deck_path))[0]
    sig = file_sha1(deck_path)
    return os.path.join(wb_dir, f"{base}.{sig}.wrong.json")

def _init_locale():
    # macOS Terminal / iTerm2 通常是 UTF-8；显式设置可减少 curses 乱码/宽字符异常
    try:
        locale.setlocale(locale.LC_ALL, "")
    except Exception:
        pass


def load_deck_into_state(state: "State", path: str, col: int, sep: str | None) -> Optional["State"]:
    try:
        new_deck = load_deck(path, start_col_1based=col, sep=sep)
    except Exception:
        return None
    if len(new_deck) < 1:
        return None
    new_id = deck_id_from_path(path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    wrong_path = os.path.join(script_dir, f"wrong_book_{new_id}.json")
    wrong_db = load_wrong_db(wrong_path)
    return State(deck=new_deck, deck_path=path, deck_id=new_id, wrong_path=wrong_path, wrong_db=wrong_db)

def display_width(s: str) -> int:
    """粗略计算终端显示宽度（处理 CJK 宽字符）。"""
    w = 0
    for ch in s:
        if ch == "\n" or ch == "\r":
            continue
        # 控制字符
        if ord(ch) < 32:
            continue
        ea = unicodedata.east_asian_width(ch)
        w += 2 if ea in ("W", "F") else 1
    return w

def truncate_to_width(s: str, max_w: int) -> str:
    if max_w <= 0:
        return ""
    out = []
    w = 0
    for ch in s:
        if ch in ("\n", "\r"):
            break
        if ord(ch) < 32:
            continue
        ea = unicodedata.east_asian_width(ch)
        cw = 2 if ea in ("W", "F") else 1
        if w + cw > max_w:
            break
        out.append(ch)
        w += cw
    return "".join(out)

def safe_addstr(stdscr, y: int, x: int, s: str, attr: int = 0):
    """在 macOS 上更稳的 addstr：自动裁剪 + 吞掉 curses.error。"""
    try:
        h, w = stdscr.getmaxyx()
        max_w = max(0, w - x - 1)
        s2 = truncate_to_width(str(s), max_w)
        if attr:
            stdscr.addstr(y, x, s2, attr)
        else:
            stdscr.addstr(y, x, s2)
    except Exception:
        return


def safe_str(x) -> str:
    if x is None:
        return ""
    return str(x).strip()


def parse_tokens(s: str) -> List[str]:
    s = safe_str(s)
    if not s:
        return []
    s = SEPS_PATTERN.sub(" ", s)
    return [t for t in s.split(" ") if t.strip()]


def split_alternatives(cell: str) -> List[str]:
    """一个单元格里可用 | ; ； / 、 分隔多个可接受答案。"""
    cell = safe_str(cell)
    if not cell:
        return []
    parts = [p.strip() for p in ALTS_PATTERN.split(cell) if p.strip()]
    return parts or [cell]


def norm_text(s: str) -> str:
    """宽松归一：去首尾空白 + Unicode casefold（对中日韩基本无影响）。"""
    return strip_accents(safe_str(s)).casefold()

def strip_accents(s: str) -> str:
    """
    去除拉丁字母的重音符号：
    é è ê ë → e
    不影响中文
    """
    if not s:
        return s
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )

def choose_delimiter(first_line: str, forced: Optional[str]) -> str:
    if forced:
        return forced
    # 简单猜测：优先 \t，其次逗号
    return "\t" if ("\t" in first_line and first_line.count("\t") >= first_line.count(",")) else ","


def deck_id_from_path(path: str) -> str:
    # 用文件绝对路径生成稳定 ID（避免不同词典共用错题本）
    # 注意：内置 hash() 在不同进程会变化，因此用 sha1 做稳定哈希
    ap = os.path.abspath(path)
    return hashlib.sha1(ap.encode("utf-8")).hexdigest()[:12]


# --------------------------- Loaders ---------------------------

def load_deck_from_csv(path: str, start_col_1based: int = 1, sep: Optional[str] = None) -> List[Dict[str, str]]:
    start = max(1, int(start_col_1based))
    idx_a = start - 1
    idx_b = start

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        # 先读一行猜分隔符
        pos = f.tell()
        first = f.readline()
        f.seek(pos)
        delimiter = choose_delimiter(first, sep)
        reader = csv.reader(f, delimiter=delimiter)
        deck: List[Dict[str, str]] = []
        for row in reader:
            if not row:
                continue
            # 补齐
            if len(row) <= idx_b:
                continue
            a = safe_str(row[idx_a])
            b = safe_str(row[idx_b])
            if not a or not b:
                continue
            deck.append({"A": a, "B": b})
        return deck


def load_deck_from_xlsx(path: str, start_col_1based: int = 1) -> List[Dict[str, str]]:
    try:
        import openpyxl  # type: ignore
    except Exception as e:
        raise RuntimeError("读取 .xlsx 需要 openpyxl：pip install openpyxl") from e

    start = max(1, int(start_col_1based))
    col_a = start
    col_b = start + 1

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    deck: List[Dict[str, str]] = []
    for row in ws.iter_rows(values_only=True):
        if row is None:
            continue
        if len(row) < col_b:
            continue
        a = safe_str(row[col_a - 1])
        b = safe_str(row[col_b - 1])
        if not a or not b:
            continue
        deck.append({"A": a, "B": b})
    return deck


def load_deck_from_json(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    deck: List[Dict[str, str]] = []
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                a = safe_str(it.get("A") or it.get("a") or it.get("front") or it.get("left") or it.get("x"))
                b = safe_str(it.get("B") or it.get("b") or it.get("back") or it.get("right") or it.get("y"))
            elif isinstance(it, (list, tuple)) and len(it) >= 2:
                a = safe_str(it[0])
                b = safe_str(it[1])
            else:
                continue
            if a and b:
                deck.append({"A": a, "B": b})
    return deck


def load_deck(path: str, start_col_1based: int = 1, sep: Optional[str] = None) -> List[Dict[str, str]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv", ".txt"):
        return load_deck_from_csv(path, start_col_1based=start_col_1based, sep=sep)
    if ext in (".xlsx", ".xlsm"):
        return load_deck_from_xlsx(path, start_col_1based=start_col_1based)
    if ext in (".json",):
        return load_deck_from_json(path)
    raise RuntimeError(f"不支持的文件类型：{ext}")


# --------------------------- Persistence (wrong book) ---------------------------

def save_wrong_db(path: str, db: List[Dict]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_wrong_db(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            for it in data:
                it.setdefault("weight", 1)
                it.setdefault("last_seen", 0.0)
            return dedup_wrong_db(data, path)
    except Exception:
        return []


def _norm_user_wrong_for_key(a_field: str, user_wrong: str) -> str:
    if user_wrong is None:
        return ""
    uw = safe_str(user_wrong)
    if uw.lower() in ("q", "e"):
        return uw.lower()
    return norm_text(uw)


def dedup_wrong_db(db: List[Dict], path: str) -> List[Dict]:
    """同 (deck_id, item_index, question_field, answer_field, user_wrong_norm) 合并。"""
    merged = {}
    for e in db:
        key = (
            e.get("deck_id"),
            e.get("item_index"),
            e.get("question_field"),
            e.get("answer_field"),
            _norm_user_wrong_for_key(e.get("answer_field", ""), e.get("user_wrong", "")),
        )
        if key not in merged:
            merged[key] = e.copy()
        else:
            m = merged[key]
            m["weight"] = m.get("weight", 1) + e.get("weight", 1)
            m["last_seen"] = max(m.get("last_seen", 0.0), e.get("last_seen", 0.0))
            m["correct_value"] = e.get("correct_value", m.get("correct_value"))
            m["question_value"] = e.get("question_value", m.get("question_value"))
    result = list(merged.values())
    if len(result) != len(db):
        db[:] = result
        save_wrong_db(path, db)
    return db


def weighted_pick_wrong(db: List[Dict], exclude_id: Optional[str] = None) -> Optional[Dict]:
    candidates = [e for e in db if e.get("weight", 1) > 0]
    if not candidates:
        return None
    pool: List[Dict] = []
    for e in candidates:
        times = max(1, int(e.get("weight", 1)))
        pool.extend([e] * times)
    if exclude_id and len({e.get("id") for e in pool}) > 1:
        pool2 = [e for e in pool if e.get("id") != exclude_id]
        pool = pool2 or pool
    choice = random.choice(pool)
    choice["last_seen"] = time.time()
    return choice


# --------------------------- App State ---------------------------

@dataclass
class State:
    deck: List[Dict[str, str]]
    deck_path: str
    deck_id: str
    wrong_path: str
    wrong_db: List[Dict]


def add_wrong_entry(state: State, item_index: int, q_field: str, a_field: str, user_wrong: str, mode: str) -> None:
    item = state.deck[item_index]
    entry = {
        "id": str(uuid.uuid4()),
        "deck_id": state.deck_id,
        "item_index": item_index,
        "question_field": q_field,
        "question_value": item.get(q_field, ""),
        "answer_field": a_field,
        "correct_value": item.get(a_field, ""),
        "user_wrong": user_wrong,
        "mode": mode,
        "weight": 1,
        "last_seen": time.time(),
    }
    state.wrong_db.append(entry)
    dedup_wrong_db(state.wrong_db, state.wrong_path)
    save_wrong_db(state.wrong_path, state.wrong_db)


# --------------------------- UI helpers ---------------------------

def center_text(stdscr, y, text, attr=0):
    h, w = stdscr.getmaxyx()
    tx = str(text)
    x = max(0, (w - display_width(tx)) // 2)
    safe_addstr(stdscr, y, x, tx, attr)

def draw_header(stdscr, title: str):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    border = "─" * (w - 2 if w >= 2 else 0)
    if w >= 2:
        safe_addstr(stdscr, 0, 0, "┌" + border + "┐")
    title_line = f" {title} "
    center_text(stdscr, 0, title_line, curses.A_REVERSE)
    if w >= 2:
        safe_addstr(stdscr, 1, 0, "│")
        safe_addstr(stdscr, 1, w - 1, "│")
        safe_addstr(stdscr, 2, 0, "└" + border + "┘")


def wait_key(stdscr, prompt="任意键继续，X返回菜单"):
    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, h - 2, 2, " " * max(0, w - 4))
    safe_addstr(stdscr, h - 2, 2, prompt[: max(0, w - 4)])
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (ord("x"), ord("X")):
            return "esc"
        return "any"


def input_line(stdscr, prompt: str) -> str:
    h, w = stdscr.getmaxyx()
    y = min(4, h - 4)
    safe_addstr(stdscr, y, 2, " " * max(0, w - 4))
    safe_addstr(stdscr, y, 2, prompt[: max(0, w - 4)])
    stdscr.refresh()
    curses.echo()
    try:
        s = stdscr.getstr(y + 1, 2, 400).decode("utf-8", errors="ignore")
    finally:
        curses.noecho()
    return s.strip()


def paginate_lines(stdscr, lines: List[str], start_y=4):
    h, w = stdscr.getmaxyx()
    max_lines = max(0, h - start_y - 3)
    for i, line in enumerate(lines[:max_lines]):
        safe_addstr(stdscr, start_y + i, 2, line[: max(0, w - 4)])


# --------------------------- Question Builders ---------------------------

FIELDS = ["A", "B"]
FIELD_NAMES = {"A": "A", "B": "B"}


def build_mcq(state: State) -> Tuple[str, List[str], int, Dict]:
    item_idx = random.randrange(len(state.deck))
    q_field = random.choice(FIELDS)
    a_field = "B" if q_field == "A" else "A"
    item = state.deck[item_idx]
    q_val = item[q_field]
    correct = item[a_field]

    indices = list(range(len(state.deck)))
    indices.remove(item_idx)
    random.shuffle(indices)

    options = [correct]
    for j in indices:
        val = state.deck[j][a_field]
        if val not in options:
            options.append(val)
        if len(options) == 4:
            break
    # 兜底：样本太小时凑够 4 个
    while len(options) < min(4, len(state.deck)):
        val = state.deck[random.randrange(len(state.deck))][a_field]
        if val not in options:
            options.append(val)

    random.shuffle(options)
    correct_idx = options.index(correct)

    question = f"题干（{FIELD_NAMES[q_field]}）：{q_val}\n请选择对应的 {FIELD_NAMES[a_field]}："
    meta = {"item_index": item_idx, "q_field": q_field, "a_field": a_field}
    return question, options, correct_idx, meta


def build_fillin(state: State) -> Tuple[str, Dict, List[str]]:
    item_idx = random.randrange(len(state.deck))
    q_field = "B"
    a_field = "A"
    item = state.deck[item_idx]
    q_val = item[q_field]
    prompt = f"题干（{FIELD_NAMES[q_field]}）：{q_val}\n请输入对应的 {FIELD_NAMES[a_field]}："
    meta = {"item_index": item_idx, "q_field": q_field, "a_field": a_field}
    correct_values = split_alternatives(item[a_field])
    return prompt, meta, correct_values


def build_tf_new(state: State) -> Tuple[str, bool, Dict]:
    item_idx = random.randrange(len(state.deck))
    q_field = random.choice(FIELDS)
    a_field = "B" if q_field == "A" else "A"
    item = state.deck[item_idx]
    q_val = item[q_field]
    correct_val = item[a_field]

    is_true = random.choice([True, False])
    if is_true:
        shown_val = correct_val
    else:
        pool = [state.deck[i][a_field] for i in range(len(state.deck)) if i != item_idx]
        pool = [v for v in pool if norm_text(v) != norm_text(correct_val)]
        shown_val = random.choice(pool) if pool else correct_val

    statement = (
        f"题干（{FIELD_NAMES[q_field]}）：{q_val}\n"
        f"断言：{FIELD_NAMES[a_field]} = {shown_val}\n"
        "请判断：Q=正确  E=错误"
    )
    meta = {"item_index": item_idx, "q_field": q_field, "a_field": a_field, "correct_val": correct_val, "shown_val": shown_val}
    return statement, is_true, meta


# --------------------------- Modes ---------------------------

def mode_flashcards(stdscr, state: State):
    title = "记忆卡：A/D 或 ←/→ 切换；Q 切换随机/顺序；x返回"
    order = list(range(len(state.deck)))
    idx = 0
    random_mode = False
    while True:
        draw_header(stdscr, title + (" [随机]" if random_mode else " [顺序]"))
        item = state.deck[order[idx]]
        content = [
            f"序号: {order[idx]+1}/{len(state.deck)}",
            f"{FIELD_NAMES['A']}: {item['A']}",
            f"{FIELD_NAMES['B']}: {item['B']}",
        ]
        paginate_lines(stdscr, content)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (ord("x"), ord("X")):
            return
        elif ch in (ord("a"), ord("A"), curses.KEY_LEFT):
            idx = (idx - 1) % len(order)
        elif ch in (ord("d"), ord("D"), curses.KEY_RIGHT):
            idx = (idx + 1) % len(order)
        elif ch in (ord("q"), ord("Q")):
            random_mode = not random_mode
            order = list(range(len(state.deck)))
            if random_mode:
                random.shuffle(order)
            idx = 0


def mode_mcq(stdscr, state: State):
    title = "选择题：1-4 或 ↑/↓/W/S 选择，回车提交；x返回"
    if len(state.deck) < 2:
        draw_header(stdscr, "选择题")
        center_text(stdscr, 6, "词典条目太少（至少需要 2 条）。")
        stdscr.refresh()
        wait_key(stdscr)
        return

    while True:
        question, options, correct_idx, meta = build_mcq(state)
        sel = 0
        while True:
            draw_header(stdscr, title)
            paginate_lines(stdscr, question.split("\n"), start_y=4)
            for i, opt in enumerate(options):
                prefix = "➤ " if i == sel else "  "
                safe_addstr(stdscr, 7 + i, 4, f"{prefix}{i+1}. {opt}")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("x"), ord("X")):
                return
            elif ch in (ord("1"), ord("2"), ord("3"), ord("4")):
                sel = ch - ord("1")
                user_idx = min(sel, len(options) - 1)
                break
            elif ch in (curses.KEY_UP, ord("w"), ord("W")):
                sel = (sel - 1) % len(options)
            elif ch in (curses.KEY_DOWN, ord("s"), ord("S")):
                sel = (sel + 1) % len(options)
            elif ch in (10, 13):
                user_idx = sel
                break

        draw_header(stdscr, "结果")
        if user_idx == correct_idx:
            center_text(stdscr, 6, "✅ 正确！")
        else:
            center_text(stdscr, 6, f"❌ 错误。正确答案：{options[correct_idx]}")
            add_wrong_entry(
                state,
                item_index=meta["item_index"],
                q_field=meta["q_field"],
                a_field=meta["a_field"],
                user_wrong=options[user_idx] if user_idx < len(options) else "",
                mode="mcq",
            )
        stdscr.refresh()
        if wait_key(stdscr) == "esc":
            return


def mode_fillin(stdscr, state: State):
    title = "填空题：输入后回车；支持答案同义项（单元格里用 | 分隔）；x返回"
    while True:
        prompt, meta, correct_values = build_fillin(state)

        draw_header(stdscr, title)
        lines = prompt.split("\n")
        start_y = 4
        h, w = stdscr.getmaxyx()
        max_lines = max(0, h - start_y - 5)
        for i, line in enumerate(lines[:max_lines]):
            safe_addstr(stdscr, start_y + i, 2, line[: max(0, w - 4)])

        input_y = start_y + min(len(lines), max_lines) + 1
        if input_y >= h - 2:
            input_y = h - 3
        safe_addstr(stdscr, input_y, 2, "你的输入：")
        stdscr.refresh()

        curses.echo()
        try:
            s = stdscr.getstr(input_y + 1, 2, 400).decode("utf-8", errors="ignore")
        finally:
            curses.noecho()

        user = safe_str(s)
        draw_header(stdscr, "结果")

        if not user:
            center_text(stdscr, 6, "❗ 不能为空。")
            stdscr.refresh()
            if wait_key(stdscr) == "esc":
                return
            continue

        item = state.deck[meta["item_index"]]
        q_text = item[meta["q_field"]]
        a_text = " / ".join(correct_values)

        user_norm = norm_text(user)
        # 先严格再模糊：correct_values 里任意一个答案命中就算对
        def _match_one(ans: str) -> bool:
            wc = word_count(ans)
            if wc >= 3:
                return is_correct_fuzzy(user, ans, threshold=0.80, min_len=1)  # min_len在这里不再负责开关
            else:
                return norm_text(user) == norm_text(ans)

        ok = any(_match_one(ans) for ans in correct_values)

        if ok:
            safe_addstr(stdscr, 6, 4, f"题目：{q_text}")
            safe_addstr(stdscr, 7, 4, f"正确答案：{a_text}")
            center_text(stdscr, 9, "✅ 正确！")
        else:
            safe_addstr(stdscr, 6, 4, f"题目：{q_text}")
            safe_addstr(stdscr, 7, 4, f"正确答案：{a_text}")
            center_text(stdscr, 9, "❌ 错误")
            add_wrong_entry(
                state,
                item_index=meta["item_index"],
                q_field=meta["q_field"],
                a_field=meta["a_field"],
                user_wrong=user,
                mode="fill",
            )
        stdscr.refresh()
        if wait_key(stdscr) == "esc":
            return


def mode_tf_new(stdscr, state: State):
    title = "判断题：Q=正确  E=错误；x返回"
    if len(state.deck) < 2:
        draw_header(stdscr, "判断题")
        center_text(stdscr, 6, "词典条目太少（至少需要 2 条）。")
        stdscr.refresh()
        wait_key(stdscr)
        return

    while True:
        statement, is_true, meta = build_tf_new(state)
        draw_header(stdscr, title)
        paginate_lines(stdscr, statement.split("\n"), start_y=4)
        stdscr.refresh()

        while True:
            ch = stdscr.getch()
            if ch in (ord("x"), ord("X")):
                return
            elif ch in (ord("q"), ord("Q"), ord("e"), ord("E")):
                user_true = ch in (ord("q"), ord("Q"))
                draw_header(stdscr, "结果")
                if user_true == is_true:
                    center_text(stdscr, 6, "✅ 判断正确")
                else:
                    center_text(stdscr, 6, "❌ 判断错误")
                    safe_addstr(stdscr, 8, 4, f"正确应为：{FIELD_NAMES[meta['a_field']]} = {meta['correct_val']}")
                    add_wrong_entry(
                        state,
                        item_index=meta["item_index"],
                        q_field=meta["q_field"],
                        a_field=meta["a_field"],
                        user_wrong="q" if user_true else "e",
                        mode="tf-new",
                    )
                stdscr.refresh()
                if wait_key(stdscr) == "esc":
                    return
                break


def mode_tf_from_wrongbook(stdscr, state: State):
    if not any(e.get("weight", 1) > 0 for e in state.wrong_db):
        draw_header(stdscr, "错题本模式")
        center_text(stdscr, 6, "📭 错题本为空或无权重题，无法开始。")
        stdscr.refresh()
        wait_key(stdscr)
        return

    last_id = None
    title = "错题本模式：Q=正确  E=错误  P=删除权重为0  x返回"
    while True:
        entry = weighted_pick_wrong(state.wrong_db, exclude_id=last_id)
        if entry is None:
            draw_header(stdscr, "错题本模式")
            center_text(stdscr, 6, "📭 错题本为空或无权重题。")
            stdscr.refresh()
            wait_key(stdscr)
            return
        last_id = entry.get("id")

        use_correct = random.choice([True, False])
        a_field = entry["answer_field"]
        if not use_correct:
            cand = safe_str(entry.get("user_wrong", ""))
            if cand.lower() in ("q", "e") or not cand:
                pool = [state.deck[i][a_field] for i in range(len(state.deck)) if i != entry["item_index"]]
                cand = random.choice(pool) if pool else ""
            shown_val = cand
        else:
            shown_val = entry["correct_value"]

        statement = f"题干（{FIELD_NAMES[entry['question_field']]}）：{entry['question_value']}"
        assertion = f"断言：{FIELD_NAMES[a_field]} = {shown_val}"
        draw_header(stdscr, title)
        safe_addstr(stdscr, 4, 2, statement)
        safe_addstr(stdscr, 5, 2, assertion)
        safe_addstr(stdscr, 7, 2, "请判断：Q=正确  E=错误 （x返回）")
        stdscr.refresh()

        while True:
            ch = stdscr.getch()
            if ch in (ord("x"), ord("X")):
                return
            elif ch in (ord("q"), ord("Q"), ord("e"), ord("E")):
                user_true = ch in (ord("q"), ord("Q"))
                real_true = norm_text(shown_val) == norm_text(entry["correct_value"])
                draw_header(stdscr, "结果")
                if user_true == real_true:
                    center_text(stdscr, 6, "✅ 判断正确。权重 -1")
                    entry["weight"] = max(0, entry.get("weight", 1) - 1)
                    save_wrong_db(state.wrong_path, state.wrong_db)
                    if entry["weight"] == 0:
                        center_text(stdscr, 8, "按 P 删除该错题（权重=0），任意键跳过保留")
                        stdscr.refresh()
                        ch2 = stdscr.getch()
                        if ch2 in (ord("p"), ord("P")):
                            state.wrong_db[:] = [e for e in state.wrong_db if e.get("id") != entry.get("id")]
                            save_wrong_db(state.wrong_path, state.wrong_db)
                            center_text(stdscr, 10, "🗑️ 已删除。")
                else:
                    center_text(stdscr, 6, "❌ 判断错误。权重 +2")
                    safe_addstr(stdscr, 8, 4, f"正确应为：{FIELD_NAMES[a_field]} = {entry['correct_value']}")
                    entry["weight"] = entry.get("weight", 1) + 2
                    add_wrong_entry(
                        state,
                        item_index=entry["item_index"],
                        q_field=entry["question_field"],
                        a_field=entry["answer_field"],
                        user_wrong="q" if user_true else "e",
                        mode="tf-wb",
                    )
                    save_wrong_db(state.wrong_path, state.wrong_db)
                stdscr.refresh()
                if wait_key(stdscr) == "esc":
                    return
                break
            elif ch in (ord("p"), ord("P")) and entry.get("weight", 1) == 0:
                state.wrong_db[:] = [e for e in state.wrong_db if e.get("id") != entry.get("id")]
                save_wrong_db(state.wrong_path, state.wrong_db)
                break


def mode_load_deck(stdscr, state: State) -> Optional[State]:
    draw_header(stdscr, "加载新词典（x取消）")
    path = input_line(stdscr, "输入文件路径（.xlsx/.csv/.json）：")
    if not path:
        return None
    if path.lower() in ("x", "exit", "quit"):
        return None

    col_s = input_line(stdscr, "起始列号（1=第1列，第2列自动作B；默认1）：") or "1"
    sep = None
    sep_s = input_line(stdscr, "CSV分隔符（留空自动猜；\\t 表示Tab）：")
    if sep_s:
        sep = "\t" if sep_s.strip() == "\\t" else sep_s.strip()

    try:
        col = int(col_s.strip())
    except Exception:
        col = 1

    try:
        new_deck = load_deck(path, start_col_1based=col, sep=sep)
    except Exception as e:
        draw_header(stdscr, "加载失败")
        paginate_lines(stdscr, [f"错误：{e}", "", "检查路径/文件格式/列号。"])
        stdscr.refresh()
        wait_key(stdscr)
        return None

    if len(new_deck) < 1:
        draw_header(stdscr, "加载失败")
        center_text(stdscr, 6, "文件里没读到任何有效 A-B 行（要求两列都非空）。")
        stdscr.refresh()
        wait_key(stdscr)
        return None

    new_id = deck_id_from_path(path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    wrong_path = os.path.join(script_dir, f"wrong_book_{new_id}.json")
    wrong_db = load_wrong_db(wrong_path)

    draw_header(stdscr, "加载成功")
    paginate_lines(stdscr, [f"路径：{path}", f"条目数：{len(new_deck)}", f"错题本：{os.path.basename(wrong_path)}"])
    stdscr.refresh()
    wait_key(stdscr)
    set_last_deck_info(path, col, sep)
    return State(deck=new_deck, deck_path=path, deck_id=new_id, wrong_path=wrong_path, wrong_db=wrong_db)


def mode_info(stdscr, state: State):
    draw_header(stdscr, "当前词典信息（x返回）")
    lines = [
        f"词典路径：{state.deck_path}",
        f"条目数：{len(state.deck)}",
        f"错题本文件：{state.wrong_path}",
        f"当前错题（权重>0）：{len([e for e in state.wrong_db if e.get('weight', 1) > 0])}",
        "",
        "提示：",
        "- 选择题/判断题要求至少 2 条数据。",
        "- 填空题支持同义项：在 B（或 A）单元格里用 | 分隔，例如：bonjour|salut",
    ]
    paginate_lines(stdscr, lines, start_y=4)
    stdscr.refresh()
    wait_key(stdscr)


# --------------------------- Menu ---------------------------

MENU_ITEMS = [
    ("加载词典", "load"),
    ("当前词典信息", "info"),
    ("记忆卡", "flash"),
    ("选择题", "mcq"),
    ("填空题", "fill"),
    ("判断题", "tf_new"),
    ("错题本模式（权重强化判断）", "tfwb"),
    ("去重错题本", "dedup"),
    ("清空错题本（不可撤销）", "clear"),
    ("退出", "exit"),
]

def menu_handle_key(key: int, sel: int, items):
    """
    返回 (action, sel)
    - ↑/↓/w/s：只移动光标，action=None
    - Enter：触发当前项 action
    - q/Esc：退出 action="exit"
    - 数字键：只跳转光标（不触发）
    """
    import curses

    n = len(items)

    # 退出
    if key in (27, ord("q"), ord("Q")):
        return "exit", sel

    # 上移
    if key in (curses.KEY_UP, ord("w"), ord("W")):
        return None, (sel - 1) % n

    # 下移
    if key in (curses.KEY_DOWN, ord("s"), ord("S")):
        return None, (sel + 1) % n

    # 数字直达：1-9；0 表示 10（如果有第10项）
    if ord("0") <= key <= ord("9"):
        d = key - ord("0")
        if d == 0:
            target = 9  # 第10项
        else:
            target = d - 1
        if 0 <= target < n:
            sel = target
        return None, sel

    # 确认：Enter 才触发 action
    if key in (10, 13, curses.KEY_ENTER):
        return items[sel][1], sel

    return None, sel

def menu(stdscr, initial_state: State):
    curses.curs_set(0)
    state = initial_state
    sel = 0
    if not ensure_deck_ready(stdscr, state):
        return
    while True:
        draw_header(stdscr, "词典记忆助手  ⛽  ↑/↓ 或 W/S 移动，Enter 选择，数字直达，ESC 退出")
        for i, (name, _) in enumerate(MENU_ITEMS):
            marker = "➤" if i == sel else " "
            safe_addstr(stdscr, 4 + i, 4, f"{marker} {i+1}. {name}")
        safe_addstr(stdscr, 16, 4, f"条目：{len(state.deck)}    错题（权重>0）：{len([e for e in state.wrong_db if e.get('weight',1)>0])}")
        stdscr.refresh()

        ch = stdscr.getch()
        action = None;

        # Exit
        if ch in (27,):  # ESC
            break

        # Move selection only (do NOT execute)
        if ch in (curses.KEY_UP, ord("w"), ord("W")):
            sel = (sel - 1) % len(MENU_ITEMS)
            continue
        if ch in (curses.KEY_DOWN, ord("s"), ord("S")):
            sel = (sel + 1) % len(MENU_ITEMS)
            continue

        if ch in (10, 13, curses.KEY_ENTER):  # Enter
            action = MENU_ITEMS[sel][1]
        else:
            if ord("0") <= ch <= ord("9"):
                d = ch - ord("0")
                target = 9 if d == 0 else (d - 1);
                if 0 <= target < len(MENU_ITEMS):
                    sel = target
                continue
            else:
                continue

        # 主循环（示意：你要放在 while True: 里面）
        key = stdscr.getch()
        action, sel = menu_handle_key(key, sel, MENU_ITEMS)

        # 只移动光标、不触发任何动作
        if action is None:
            continue

        # 只有明确的 action 才会走到这里
        if action == "exit":
            break

        elif action == "load":
            new_state = mode_load_deck(stdscr, state)
            if new_state is not None:
                state = new_state
                set_last_deck_path(state.deck_path)
                # ✅ 关键新增：让错题本跟词典绑定
                if getattr(state, "deck_path", None) and os.path.isfile(state.deck_path):
                    state.wrong_path = wrongbook_path_for_deck(state.deck_path)
                    state.wrong_db = load_wrong_db(state.wrong_path)  # 读老错题本（不存在则空）

        elif action == "info":
            mode_info(stdscr, state)

        elif action == "flash":
            mode_flashcards(stdscr, state)

        elif action == "mcq":
            mode_mcq(stdscr, state)

        elif action == "fill":
            mode_fillin(stdscr, state)

        elif action == "tf_new":
            mode_tf_new(stdscr, state)

        elif action == "tfwb":
            mode_tf_from_wrongbook(stdscr, state)

        elif action == "dedup":
            before = len(state.wrong_db)
            state.wrong_db = dedup_wrong_db(state.wrong_db, state.wrong_path)
            after = len(state.wrong_db)
            draw_header(stdscr, "去重完成")
            center_text(stdscr, 6, f"🧹 去重成功：{before} → {after}")
            stdscr.refresh()
            wait_key(stdscr)

        elif action == "clear":
            state.wrong_db.clear()
            save_wrong_db(state.wrong_path, state.wrong_db)
            draw_header(stdscr, "清空完成")
            center_text(stdscr, 6, "🗑️ 已清空错题本")
            stdscr.refresh()
            wait_key(stdscr)

        else:
            # 防御：遇到未知 action 不至于乱跑
            draw_header(stdscr, "未知操作")
            center_text(stdscr, 6, f"Unknown action: {action}")
            stdscr.refresh()
            wait_key(stdscr)


def build_initial_state(args) -> State:
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if args.path:
        deck_path = args.path
        deck = load_deck(deck_path, start_col_1based=args.col, sep=args.sep)
        set_last_deck_info(deck_path, args.col, args.sep)
    else:
        # 默认词典：脚本目录下 dict.csv 或 dict.xlsx（如果存在）
        candidate = None
        for name in ("dict.xlsx", "dict.xlsm", "dict.csv", "dict.tsv", "dict.json"):
            p = os.path.join(script_dir, name)
            if os.path.exists(p):
                candidate = p
                break
        if candidate is None:
            # 最小内置词典，避免空跑
            deck_path = "<内置示例>"
            deck = [{"A": "bonjour", "B": "你好"}, {"A": "merci", "B": "谢谢"}]
        else:
            deck_path = candidate
            deck = load_deck(deck_path, start_col_1based=args.col, sep=args.sep)

    did = deck_id_from_path(deck_path) if args.path or deck_path != "<内置示例>" else "builtin"
    wrong_path = os.path.join(script_dir, f"wrong_book_{did}.json")
    wrong_db = load_wrong_db(wrong_path)
    return State(deck=deck, deck_path=deck_path, deck_id=did, wrong_path=wrong_path, wrong_db=wrong_db)


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("path", nargs="?", default=None, help="词典文件路径（.xlsx/.csv/.json）")
    parser.add_argument("--col", type=int, default=1, help="起始列号（1-based），B为下一列")
    parser.add_argument("--sep", type=str, default=None, help="CSV分隔符，默认自动猜；Tab 用 --sep $'\\t'")
    args = parser.parse_args()

    state = build_initial_state(args)
    _init_locale()
    curses.wrapper(lambda stdscr: menu(stdscr, state))


if __name__ == "__main__":
    main()
