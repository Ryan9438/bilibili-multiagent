#!/usr/bin/env python3
"""bili_quota.py — B站夜巡的每日看片配额账本

配额口径（来自 mission.txt，2026-10-20）：
  - 全天视频合计 ≤ 4 个
  - 每天 2-4 趟，趟间 ≥ 90 分钟
  - 每趟 1-2 个视频

用法：
  python3 ~/.hermes/scripts/bili_quota.py            # 人话
  python3 ~/.hermes/scripts/bili_quota.py --json     # JSON
  python3 ~/.hermes/scripts/bili_quota.py --left     # 只打印还能看几个（给 shell 用）

作为模块：
  from bili_quota import today_quota
  q = today_quota()
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

# BILI_HOME 按人格切换（小鲸鱼 =~/.hermes/bili；小大姐 =~/.hermes/profiles/minimax/bili）
# 配额必须各记各的，否则两个 agent 会互相吃额度。咿呀
_BILI_HOME = Path(os.path.expanduser(os.environ.get("BILI_HOME", "~/.hermes/bili")))
NIGHT_LOG = _BILI_HOME / "night_log.json"
# 每日上限也可按人格覆盖（小大姐一天只跑 2 趟、看 2 个视频）
DAILY_VIDEO_CAP = int(os.environ.get("BILI_VIDEO_CAP", "4"))
DAILY_RUN_CAP = int(os.environ.get("BILI_RUN_CAP", "4"))

# 只有「真打开过这个视频」的记录才消耗看片额度。
# 在别人的评论楼下回话时，日志记录的 bvid 也挂着那个视频号，但那不是看片
# —— 曾被白算成额度（2026-10-20 出现 5/4 假满额）。
_META_TITLE_PREFIXES = ("本次运行元信息", "自发评论", "本次运行", "心跳收信", "心跳")
# 「抽帧 9 张」这类才是真抽帧；「未抽帧」不算
_FRAME_RE = re.compile(r"抽[^。；]{0,4}帧[^。；]{0,4}\d+")


def is_watch_record(r: dict) -> tuple[bool, str]:
    """一条日志记录是否算「今天看过这个视频」→ (是否算, 理由)。"""
    bvid = (r.get("bvid") or "").strip()
    title = (r.get("title") or "").strip()
    action = r.get("action") or ""
    verdict = r.get("verdict") or ""
    if not bvid.startswith("BV"):
        return False, "没有视频号（元信息行）"
    # 先认「回复类记录」——它们的 bvid 只是评论挂靠的视频，根本没打开过。
    # 注意：不能只看「抽帧」二字，回复类 verdict 里常写「未打开任何视频、未抽帧」。
    if title.startswith(_META_TITLE_PREFIXES) or action.startswith(("ack", "comment")):
        if "toview-add" in action or "seen=" in action:
            return True, "本趟顺手加进稍后再看"
        return False, "回复/收信类记录，只是评论挂在该视频下，未打开视频"
    if "toview-add" in action or "seen=" in action or _FRAME_RE.search(action + " " + verdict):
        return True, "有看片痕迹（toview-add / 抽帧 N 张）"
    return True, "有真实视频标题，视为看过"


def _today_str() -> str:
    return date.today().isoformat()


def today_quota(today: str | None = None) -> dict:
    """统计今天的看片与趟数消耗。"""
    today = today or _today_str()
    out = {
        "date": today,
        "videos_seen": 0,
        "runs": 0,
        "video_cap": DAILY_VIDEO_CAP,
        "run_cap": DAILY_RUN_CAP,
        "videos_left": DAILY_VIDEO_CAP,
        "runs_left": DAILY_RUN_CAP,
        "cap_reached": False,
        "bvid_list": [],
        "excluded": [],
        "last_run_at": None,
        "minutes_since_last_run": None,
        "error": None,
    }
    try:
        recs = json.loads(NIGHT_LOG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["error"] = "night_log.json 不存在，视为今天没看过"
        return out
    except Exception as e:
        out["error"] = f"night_log.json 读不了: {e}"
        return out

    if not isinstance(recs, list):
        out["error"] = "night_log.json 结构异常（不是列表）"
        return out

    seen: list[str] = []
    excluded: list[dict] = []
    runs = 0
    # 趟数：一条记录若 action 里含 run_seq=，或 bvid 为 "-"（元信息行），都算标记过趟
    seq_seen = set()
    for r in recs:
        if not isinstance(r, dict) or r.get("date") != today:
            continue
        bvid = (r.get("bvid") or "").strip()
        if bvid.startswith("BV") and bvid not in seen:
            counts, why = is_watch_record(r)
            if counts:
                seen.append(bvid)
            else:
                excluded.append({"bvid": bvid, "reason": why})
        act = r.get("action") or ""
        for token in act.split():
            if token.startswith("run_seq="):
                seq_seen.add(token.split("=", 1)[1])

    if seq_seen:
        runs = len(seq_seen)
    else:
        # 没有 run_seq 标记时，按「元信息行」数趟，退化为按视频条数
        meta = [r for r in recs if isinstance(r, dict) and r.get("date") == today
                and (r.get("bvid") or "").strip() == "-"]
        runs = len(meta) if meta else (1 if seen else 0)

    out["videos_seen"] = len(seen)
    out["excluded"] = excluded
    out["bvid_list"] = seen
    out["runs"] = runs
    out["videos_left"] = max(0, DAILY_VIDEO_CAP - len(seen))
    out["runs_left"] = max(0, DAILY_RUN_CAP - runs)
    out["cap_reached"] = len(seen) >= DAILY_VIDEO_CAP

    # 距上一趟多久（用文件 mtime 不可靠，用 run_seq 元信息的时间戳字段若有）
    stamps = []
    for r in recs:
        if isinstance(r, dict) and r.get("date") == today:
            ts = r.get("finished_at") or r.get("ts") or r.get("time")
            if ts:
                stamps.append(ts)
    if stamps:
        try:
            last = datetime.fromisoformat(str(stamps[-1]))
            out["last_run_at"] = last.isoformat()
            out["minutes_since_last_run"] = int(
                (datetime.now(last.tzinfo) - last).total_seconds() // 60)
        except Exception:
            pass
    return out


def main() -> int:
    q = today_quota()
    argv = sys.argv[1:]
    if "--left" in argv:
        print(q["videos_left"])
        return 0
    if "--json" in argv:
        print(json.dumps(q, ensure_ascii=False, indent=2))
        return 0

    bar = "●" * q["videos_seen"] + "○" * q["videos_left"]
    print(f"📺 {q['date']} 看片配额：{bar}  {q['videos_seen']}/{q['video_cap']}"
          f"（还能看 {q['videos_left']} 个）")
    print(f"🔁 今天已跑 {q['runs']} 趟（上限 {q['run_cap']} 趟）")
    if q["bvid_list"]:
        print("   已看：" + "、".join(q["bvid_list"]))
    if q["minutes_since_last_run"] is not None:
        gap = q["minutes_since_last_run"]
        print(f"⏱  距上一趟 {gap} 分钟"
              + ("（不足 90 分钟，按规矩不该再开一趟）" if gap < 90 else ""))
    if q["excluded"]:
        uniq = sorted({e["bvid"] for e in q["excluded"]})
        print(f"   （另 {len(uniq)} 个视频只是在下面回话，不算看片：" + "、".join(uniq) + "）")
    if q["cap_reached"]:
        print("🛑 今天看满了，只收信不挑片。")
    if q["error"]:
        print("⚠️  " + q["error"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
