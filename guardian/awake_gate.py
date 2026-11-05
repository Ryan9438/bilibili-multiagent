#!/usr/bin/env python3
"""awake_gate.py — 唯一的「能不能动手」仲裁口

主人的新口径（2026-10-20）：时间表不可靠，改成手动放行。
  · 回 @ / 回评论 / 回私信  → 只要有新消息，机器醒着就做，**不需要窗口**
  · 看视频（消耗每日 ≤4 配额）→ **必须**有醒着窗口，且今日配额未满，且窗口剩余时间够

用法：
  python3 ~/.hermes/scripts/awake_gate.py            # 人话裁决（watch）
  python3 ~/.hermes/scripts/awake_gate.py reply      # 裁决回复类动作
  python3 ~/.hermes/scripts/awake_gate.py --json     # JSON
  python3 ~/.hermes/scripts/awake_gate.py --check    # 放行返回 0，不放行返回 1

作为模块：
  from awake_gate import gate
  v = gate("watch")     # {'allow': bool, 'reason': str, ...}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from awake_window import window_state  # noqa: E402
from bili_quota import today_quota     # noqa: E402

MIN_MINUTES_FOR_COMMENTS = 10  # 窗口 ≥10 分钟：够写/发评论，但不够看完一个视频
MIN_MINUTES_FOR_WATCH = 20     # 窗口 ≥20 分钟：才允许开片（抽帧 + 写评论要时间）


def gate(kind: str = "watch") -> dict:
    w = window_state()
    q = today_quota()
    out = {
        "kind": kind,
        "allow": False,        # 窗口内的活动是否放行（含发评论）
        "allow_watch": False,  # 是否允许看视频
        "level": "none",       # none / reply / comments / watch
        "reason": "",
        "window": w,
        "quota": q,
        "advice": "",
    }

    if kind == "reply":
        out["allow"] = True
        out["level"] = "reply"
        out["reason"] = "回复类动作不需要窗口，有新消息就回"
        return out

    # ---- 窗口内活动 ----
    if not w["open"]:
        why = {"no-file": "主人还没登记窗口",
               "expired": "上一个窗口已经到期",
               "inactive": "窗口已关闭"}.get(w["reason"], w["reason"])
        out["reason"] = f"没有醒着窗口（{why}）→ 不许看片也不许发评论，只收信"
        out["advice"] = "等主人点一下菜单栏鲸鱼"
        return out

    rem = w["remaining_min"] or 0

    if rem < MIN_MINUTES_FOR_COMMENTS:
        out["reason"] = f"窗口只剩 {rem} 分钟，不够 {MIN_MINUTES_FOR_COMMENTS} 分钟，动不了手"
        out["advice"] = "本趟只收信；若主人在用，让他右键点一下 +10 分钟"
        return out

    # ≥10 分钟：至少能发评论
    if q["cap_reached"]:
        out["allow"] = True
        out["allow_watch"] = False
        out["level"] = "reply"
        out["reason"] = (f"今天已看 {q['videos_seen']}/{q['video_cap']} 个、配额满了 → "
                         f"只收信、只回消息，不看新视频、不发新评论")
        out["advice"] = "回 @ / 回评论照做（这不受配额限），别的别动"
        return out

    if rem < MIN_MINUTES_FOR_WATCH:
        out["allow"] = True
        out["allow_watch"] = False
        out["level"] = "comments"
        out["reason"] = (f"窗口剩 {rem} 分钟（不足 {MIN_MINUTES_FOR_WATCH} 分钟）→ "
                         f"够发评论，不够好好看一个视频")
        out["advice"] = "发评论、回评论、收信；想看片就让主人右键再加 10 分钟"
        return out

    out["allow"] = True
    out["allow_watch"] = True
    out["level"] = "watch"
    out["reason"] = (f"窗口剩 {rem} 分钟 · 今天还能看 {q['videos_left']} 个 → 可以看片")
    out["advice"] = "挑 1 个（最多 2 个），看完留评论，别拖过窗口"
    return out


def main() -> int:
    argv = sys.argv[1:]
    kind = "watch"
    if argv and argv[0] in ("watch", "reply"):
        kind = argv[0]

    v = gate(kind)
    if "--json" in argv:
        print(json.dumps(v, ensure_ascii=False, indent=2))
        return 0 if v["allow"] else 1
    if "--check" in argv:
        return 0 if v["allow"] else 1

    icon = "✅ 放行" if v["allow"] else "🚫 不放行"
    can = {"none": "什么都别做，只收信",
           "reply": "只回消息",
           "comments": "发评论 / 回评论 / 收信（不看片）",
           "watch": "可以看片 + 发评论"}.get(v["level"], v["level"])
    print(f"{icon} [{v['kind']}] {v['reason']}")
    print(f"   能做：{can}")
    if v["advice"]:
        print(f"   → {v['advice']}")
    q = v["quota"]
    print(f"   📺 今日 {q['videos_seen']}/{q['video_cap']} 个 · 已跑 {q['runs']} 趟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
