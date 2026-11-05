#!/usr/bin/env python3
"""awake_window.py — 读取主人的「醒着窗口」登记（由 /Applications/AwakeWindow.app 写入）

用法：
  python3 ~/.hermes/scripts/awake_window.py          # 打印状态（人话 + JSON）
  python3 ~/.hermes/scripts/awake_window.py --json   # 只输出 JSON
  python3 ~/.hermes/scripts/awake_window.py --quiet  # 窗口开着返回 0，没开返回 1（给 shell 判断）
  python3 ~/.hermes/scripts/awake_window.py --open 30   # 代为登记 30 分钟
  python3 ~/.hermes/scripts/awake_window.py --close     # 取消

作为模块：
  from awake_window import window_state
  st = window_state()   # {'open': bool, 'remaining_min': int|None, ...}
"""
from __future__ import annotations

import os
import json
import subprocess
import sys
import time
from pathlib import Path

STATE_FILE = Path.home() / ".hermes" / "awake" / "window.json"
HISTORY = Path.home() / ".hermes" / "awake" / "history.log"
BIN = Path("/Applications/AwakeWindow.app/Contents/MacOS/AwakeWindow")


def window_state() -> dict:
    """当前窗口状态。open=True 表示主人承诺电脑不会合盖。"""
    now = time.time()
    st = {"open": False, "remaining_min": None, "until": None,
          "until_epoch": None, "duration_minutes": None, "age_min": None,
          "reason": "no-file"}
    try:
        obj = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        st["reason"] = "no-file"
        return st
    except Exception as e:  # 坏文件按未开窗口处理
        st["reason"] = f"unreadable: {e}"
        return st

    st["duration_minutes"] = obj.get("duration_minutes")
    if not obj.get("active"):
        st["reason"] = obj.get("reason") or "inactive"
        return st

    until = float(obj.get("until_epoch") or 0)
    created = float(obj.get("created_epoch") or 0)
    st["until_epoch"] = until
    st["until"] = obj.get("until")
    if until > now:
        st["open"] = True
        st["remaining_min"] = max(1, int(round((until - now) / 60.0)))
        if created:
            st["age_min"] = int((now - created) / 60.0)
        st["reason"] = "open"
    else:
        st["reason"] = "expired"
    return st


def _trigger(*args: str) -> int:
    if not BIN.exists():
        print(f"找不到 {BIN}", file=sys.stderr)
        return 2
    r = subprocess.run([str(BIN), *args], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
    return r.returncode


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--open"]:
        mins = argv[1] if len(argv) > 1 else "30"
        return _trigger("--open", mins)
    if argv[:1] == ["--close"]:
        return _trigger("--close")

    st = window_state()
    if "--quiet" in argv:
        return 0 if st["open"] else 1
    if "--json" in argv:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    if st["open"]:
        print(f"✅ 醒着窗口开着：还剩约 {st['remaining_min']} 分钟（到 {st['until']}）"
              f" · 登记时长 {st['duration_minutes']} 分钟 · 已过 {st['age_min']} 分钟")
    else:
        tip = {"no-file": "主人还没登记过窗口",
               "expired": "上一个窗口已经到期",
               "inactive": "窗口已关闭"}.get(st["reason"], st["reason"])
        print(f"⚪ 没有醒着窗口：{tip}")
    try:
        tail = HISTORY.read_text(encoding="utf-8").strip().splitlines()[-5:]
        if tail:
            print("\n最近记录：")
            for line in tail:
                print("  " + line)
    except FileNotFoundError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
