#!/usr/bin/env python3
"""bili_backlog_guard.py — 给收信心跳补一层「漏了就补」的兜底（只在固定时刻开工）。

为什么需要它（2026-10-21 漏回姐姐 @ 的复盘）：
心跳是 cron 的 monitor 模式——**监控脚本输出变了才叫醒 agent**。机器合盖时
系统只给 45-60 秒的 DarkWake，agent 拉 skill、等模型开口都不够，跑到一半就被
睡回去，cron 记 FAILED；而这时监控输出已经「变过了」，之后再也不会变化，于是
那批消息永远没人处理，一直躺在 watch_last.txt 里等人手动发现。

这个脚本不解决「叫醒失败」，它解决「失败之后不再重试」，而且只在主人指定的
三个时刻检查（13:20 / 21:10，各开 30 分钟窗口）：

  · 窗口外：输出固定串 "BACKLOG OK"，什么都不做（零唤醒成本）
  · 窗口内且 watch_last.txt 里有未 ack 的 id → 升级成 "BACKLOG STALE n=… L<k> …"
    制造一次输出变化，让 monitor 叫醒 agent 补做
  · 同一批消息在窗口内每 RETRY_MIN 分钟才重试一次（默认 10 分钟 → 一个窗口最多
    三次机会，抗机器睡眠把那次运行睡回去）

输出必须确定性（monitor 用精确字节 hash 抑制唤醒，输出一抖就会白叫醒）：
不带时间戳、不带会自己变化的分钟数；同一批消息在两次重试之间输出完全一致。

用法：
    python3 bili_backlog_guard.py                       # 默认 13:20 / 18:20 / 22:30
    python3 bili_backlog_guard.py --at "13:20,18:20,22:30" --window-min 30 --retry-min 10
    python3 bili_backlog_guard.py --ignore-window       # 调试：不看时间窗，立刻判定
BILI_HOME 决定看哪个号的缓存（默认 ~/.hermes/bili；小大姐那边由转发壳指过去）。
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta

BILI_HOME = os.path.expanduser(os.environ.get("BILI_HOME", "~/.hermes/bili"))
CACHE = os.path.join(BILI_HOME, "watch_last.txt")
STATE = os.path.join(BILI_HOME, "backlog_guard_state.json")


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE)


def pending_ids():
    """watch_last.txt 里 `NEW a b c` 那行的 id 列表（保持原顺序）。"""
    try:
        with open(CACHE, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return [], ""
    for line in text.splitlines():
        if line.startswith("NEW "):
            return line.split()[1:], line
    return [], ""


def parse_ats(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":")
        out.append((int(hh), int(mm)))
    return out


def in_window(now, ats, window_min):
    for hh, mm in ats:
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start <= now < start + timedelta(minutes=window_min):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="13:20,21:10,22:45", help="每天检查的时刻，逗号分隔")
    ap.add_argument("--window-min", type=int, default=30)
    ap.add_argument("--retry-min", type=int, default=10)
    ap.add_argument("--ignore-window", action="store_true", help="调试用：忽略时间窗")
    a = ap.parse_args()

    ids, new_line = pending_ids()

    if not ids:
        if os.path.exists(STATE):
            os.remove(STATE)          # 清干净，下次新消息重新计时
        print("BACKLOG OK")
        return

    if not a.ignore_window and not in_window(datetime.now(), parse_ats(a.at), a.window_min):
        # 不在检查点：保持固定输出，不叫醒任何人
        print("BACKLOG OK")
        return

    h = hashlib.md5(" ".join(ids).encode()).hexdigest()[:10]
    st = load_state()
    now = int(time.time())

    if st.get("hash") != h:
        st = {"hash": h, "alerts": 0, "last_alert": 0, "n": len(ids)}
        save_state(st)

    if st["alerts"] > 0 and now - st.get("last_alert", 0) < a.retry_min * 60:
        # 同一窗口内刚叫过，输出与上次一致 → 不重复唤醒
        print(f"BACKLOG STALE n={len(ids)} L{st['alerts']} {new_line}")
        return

    st["alerts"] += 1
    st["last_alert"] = now
    st["n"] = len(ids)
    save_state(st)
    print(f"BACKLOG STALE n={len(ids)} L{st['alerts']} {new_line}")


if __name__ == "__main__":
    main()
