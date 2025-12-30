import os
import sys
import glob
import shlex
import subprocess
import shutil
from dataclasses import dataclass

# ... 你原来的 Item / build_items / open_terminal_and_run 等都保持不动

def is_real_terminal() -> bool:
    # PyCharm Run Console 通常不是 tty；TERM 也可能缺失
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    term = os.environ.get("TERM", "")
    if not term or term == "unknown":
        return False
    return True

def select_by_input(items: list[Item]) -> str | None:
    # 任何环境都强制输出
    print("\n脚本启动器（输入模式）", flush=True)
    print("输入序号回车运行；输入 q 回车退出。\n", flush=True)

    for i, it in enumerate(items, 1):
        print(f"{i:>2}. {it.show}   [{os.path.basename(it.path)}]", flush=True)

    while True:
        try:
            # 用 stdin.readline 比 input() 更不容易在 IDE 里“无声失败”
            sys.stdout.write("\n> ")
            sys.stdout.flush()
            s = sys.stdin.readline()
            if s == "":  # EOF：PyCharm 有时会直接给 EOF
                print("\n(收到 EOF，退出)", flush=True)
                return None
            s = s.strip()
        except Exception as e:
            print(f"\n(读取输入失败：{e})", flush=True)
            return None

        if not s:
            print("空输入：退出。", flush=True)
            return None
        if s.lower() == "q":
            return None
        if not s.isdigit():
            print("请输入数字序号或 q。", flush=True)
            continue

        idx = int(s)
        if 1 <= idx <= len(items):
            return items[idx - 1].path
        print("序号超出范围。", flush=True)


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