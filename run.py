# launcher.py
# 脚本启动器：↑↓ 或 w/s 选择，Enter 运行（在系统 Terminal 中启动）
# 显示名取目标脚本第一行：# xxx （否则回退为文件名）

from __future__ import annotations
import os
import sys
import glob
import shlex
import subprocess
import shutil
from dataclasses import dataclass

# -------------------- utils --------------------

def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def list_py_files(dir_path: str) -> list[str]:
    files = sorted(glob.glob(os.path.join(dir_path, "*.py")))
    me = os.path.abspath(__file__)
    out = []
    for f in files:
        af = os.path.abspath(f)
        name = os.path.basename(af)
        if af == me:
            continue
        if name == "__init__.py":
            continue
        out.append(af)
    return out

def read_title_comment(path: str) -> str | None:
    # 第一行严格匹配：# xxx
    try:
        with open(path, "r", encoding="utf-8") as fp:
            line = fp.readline().strip("\n").strip()
    except UnicodeDecodeError:
        # 万一不是 utf-8（很少），尝试系统默认
        try:
            with open(path, "r") as fp:
                line = fp.readline().strip("\n").strip()
        except Exception:
            return None
    except Exception:
        return None

    if line.startswith("#"):
        t = line[1:].strip()
        return t if t else None
    return None

def open_terminal_and_run(cmd: str, cwd: str) -> None:
    """
    在系统 Terminal 打开新窗口/标签并执行命令。
    cmd: 要执行的完整 shell 命令（已包含 python + script）
    cwd: 先 cd 到该目录
    """
    plat = sys.platform

    if plat == "darwin":
        # macOS Terminal via AppleScript
        # 说明：Terminal 的 do script 默认会打开新窗口或新 tab（取决于设置）
        applescript = f'''
tell application "Terminal"
    activate
    do script "cd {escape_applescript(cwd)}; {escape_applescript(cmd)}"
end tell
'''
        subprocess.run(["osascript", "-e", applescript], check=False)
        return

    if plat.startswith("win"):
        # Windows: 用 cmd /k 保持窗口不关闭
        # start "" cmd /k "cd /d C:\path && python script.py"
        full = f'cd /d "{cwd}" && {cmd}'
        subprocess.run(["cmd", "/c", "start", "", "cmd", "/k", full], check=False)
        return

    # Linux / other: 尝试 x-terminal-emulator / gnome-terminal / konsole
    candidates = [
        ("x-terminal-emulator", ["x-terminal-emulator", "-e"]),
        ("gnome-terminal", ["gnome-terminal", "--"]),
        ("konsole", ["konsole", "-e"]),
        ("xterm", ["xterm", "-e"]),
    ]
    for exe, prefix in candidates:
        if shutil_which(exe):
            subprocess.Popen(prefix + ["bash", "-lc", f'cd {shlex.quote(cwd)}; {cmd}'])
            return

    # 实在不行：就在当前终端跑
    os.chdir(cwd)
    os.system(cmd)

def escape_applescript(s: str) -> str:
    # AppleScript 字符串里需要转义：\ 和 "
    return s.replace("\\", "\\\\").replace('"', '\\"')

def shutil_which(exe: str) -> str | None:
    # 轻量 which
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for p in paths:
        cand = os.path.join(p, exe)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None

@dataclass
class Item:
    path: str
    show: str

def build_items(dir_path: str) -> list[Item]:
    items: list[Item] = []
    for p in list_py_files(dir_path):
        title = read_title_comment(p)
        show = title if title else os.path.basename(p)
        items.append(Item(path=p, show=show))
    return items

# -------------------- simple TUI (no tkinter) --------------------

def is_real_terminal() -> bool:
    # PyCharm Run Console 通常不是 tty；TERM 也可能缺失
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    term = os.environ.get("TERM", "")
    if not term or term == "unknown":
        return False
    return True

def select_by_input(items: list["Item"]) -> str | None:
    """
    在非终端环境（PyCharm Run Console）用 input() 选择。
    支持：数字、q 退出。
    """
    print("脚本启动器（输入模式）")
    print("输入序号回车运行；输入 q 回车退出。\n")
    for i, it in enumerate(items, 1):
        print(f"{i:>2}. {it.show}   [{os.path.basename(it.path)}]")

    while True:
        s = input("\n> ").strip()
        if not s:
            # 空输入当退出，避免你误按回车一直卡着
            return None
        if s.lower() == "q":
            return None
        if not s.isdigit():
            print("请输入数字序号或 q。")
            continue

        idx = int(s)
        if 1 <= idx <= len(items):
            return items[idx - 1].path
        print("序号超出范围。")

def try_curses_menu(items: list["Item"]) -> str | None:
    """
    能用 curses 就用；不能就降级为 input()。
    """
    if not is_real_terminal():
        return select_by_input(items)

    try:
        import curses
        import locale
        locale.setlocale(locale.LC_ALL, "")
    except Exception:
        return select_by_input(items)

    def run(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(False)
        stdscr.keypad(True)
        try:
            curses.set_escdelay(25)
        except Exception:
            pass

        sel = 0
        top = 0

        def redraw():
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            title = "脚本启动器  ↑/↓ 或 w/s 选择  Enter运行  q/Esc退出"
            stdscr.addstr(0, 0, title[: max(0, w - 1)])
            stdscr.hline(1, 0, "-", max(0, w - 1))

            view_h = h - 3
            nonlocal top
            if sel < top:
                top = sel
            if sel >= top + view_h:
                top = sel - view_h + 1

            for i in range(view_h):
                idx = top + i
                if idx >= len(items):
                    break
                line = f"{idx+1:>2}. {items[idx].show}"
                if idx == sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(2 + i, 0, line[: max(0, w - 1)])
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(2 + i, 0, line[: max(0, w - 1)])

            stdscr.refresh()

        redraw()

        while True:
            k = stdscr.getch()

            if k in (curses.KEY_UP, ord("w"), ord("W")):
                sel = (sel - 1) % len(items)
                redraw()
                continue

            if k in (curses.KEY_DOWN, ord("s"), ord("S")):
                sel = (sel + 1) % len(items)
                redraw()
                continue

            if k in (10, 13, curses.KEY_ENTER):
                return items[sel].path

            if k in (27, ord("q"), ord("Q")):
                return None

    return curses.wrapper(run)

def fallback_menu(items: list[Item]) -> str | None:
    """
    非 curses 版本：用输入数字选择（应急用）
    """
    print("脚本启动器（fallback 模式）")
    for i, it in enumerate(items, 1):
        print(f"{i:>2}. {it.show}  ({os.path.basename(it.path)})")
    print("输入序号回车运行；直接回车退出。")
    s = input("> ").strip()
    if not s:
        return None
    if not s.isdigit():
        return None
    idx = int(s)
    if 1 <= idx <= len(items):
        return items[idx - 1].path
    return None

# -------------------- main --------------------

def main():
    dir_path = script_dir()
    items = build_items(dir_path)
    if not items:
        print("同目录下未找到可运行的 .py 文件。")
        return 1

    chosen = try_curses_menu(items)
    if not chosen:
        return 0

    py = sys.executable  # 跟 launcher 同一个解释器（venv）
    # 目标脚本可能需要参数：你可以在这里扩展，比如读取额外输入
    cmd = f"{shlex.quote(py)} {shlex.quote(chosen)}"

    open_terminal_and_run(cmd, cwd=dir_path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())