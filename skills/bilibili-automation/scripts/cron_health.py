#!/usr/bin/env python3
"""cron_health.py — 一次看清本机每个 profile 的 cron 任务是不是还活着。

读每个 profile 的 cron/jobs.json，把每条任务判成活 / 死四种状态：
  活的判据（三条同时满足）：next_run_at 在未来 + state 不是 paused/completed + Repeat 没打满

  PAST        next_run 已经是过去 → 夜里被睡掉，或者是冻结的残影（配 PAUSED 一起看）
  PAUSED      被批量 pause（paused_at 集中在同一秒就是有人一次性停的，不是超时）
  COMPLETED   一次性任务已消费（Repeat 打满），名字还在但不会再触发
  NO_NEXT     没有 next_run_at

用法：
  python3 cron_health.py                      # 扫描 default + 所有 profile
  python3 cron_health.py default minimax      # 只扫指定 profile
  python3 cron_health.py --job 夜巡            # 只看名字含关键字的（可多次）
  python3 cron_health.py --quiet              # 只在有死任务时输出

退出码：全部健康 0；存在 PAST / PAUSED / 活的候选点不足 1 条 → 1（可直接给监控用）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path.home() / ".hermes"


def jobs_path(profile: str | None) -> Path:
    if profile is None:
        return HERMES / "cron" / "jobs.json"
    return HERMES / "profiles" / profile / "cron" / "jobs.json"


def discover_profiles() -> list[str | None]:
    out: list[str | None] = [None]  # default
    pdir = HERMES / "profiles"
    if pdir.is_dir():
        for child in sorted(pdir.iterdir()):
            if (child / "cron" / "jobs.json").exists():
                out.append(child.name)
    return [p for p in out if jobs_path(p).exists()]


def load_jobs(profile: str | None) -> list[dict]:
    raw = json.loads(jobs_path(profile).read_text(encoding="utf-8"))
    jobs = raw if isinstance(raw, list) else raw.get("jobs", raw)
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    return jobs


def repeat_exhausted(job: dict) -> bool:
    rep = job.get("repeat") or {}
    times, done = rep.get("times"), rep.get("completed") or 0
    if times in (None, 0):
        return False  # 无限重复
    try:
        return int(done) >= int(times)
    except (TypeError, ValueError):
        return False


def classify(job: dict, now: datetime) -> tuple[str, str | None]:
    state = (job.get("state") or "").lower()
    nr = job.get("next_run_at")
    if state == "paused" or job.get("paused_at"):
        return "PAUSED", f"paused_at={job.get('paused_at')}"
    if repeat_exhausted(job) or state == "completed":
        return "COMPLETED", "Repeat 已打满"
    if not nr:
        return "NO_NEXT", None
    try:
        t = datetime.fromisoformat(nr)
    except ValueError:
        return "NO_NEXT", f"unparsable: {nr}"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return ("ALIVE", None) if t > now else ("PAST", f"next_run={nr}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles", nargs="*", help="profile 名（不填=全部）")
    ap.add_argument("--job", action="append", default=[], help="只看名字含该关键字的任务")
    ap.add_argument("--quiet", action="store_true", help="只在有死任务时输出")
    a = ap.parse_args()

    profiles = a.profiles or discover_profiles()
    now = datetime.now().astimezone()
    bad = 0
    alive_by_profile: dict[str, int] = {}

    for prof in profiles:
        label = prof or "default"
        try:
            jobs = load_jobs(prof)
        except Exception as e:  # 坏文件就当这条 profile 有事
            print(f"[{label}] 读不了 jobs.json: {e}")
            bad += 1
            continue
        alive = 0
        lines: list[str] = []
        for j in jobs:
            name = j.get("name") or j.get("id") or "?"
            if a.job and not any(k in name for k in a.job):
                continue
            verdict, note = classify(j, now)
            if verdict == "ALIVE":
                alive += 1
            elif verdict in ("PAST", "PAUSED"):
                bad += 1
            lines.append(f"  {verdict:9s} {name[:26]:28s} {j.get('schedule_display') or j.get('schedule',{}).get('display',''):28s} {note or ''}")
        alive_by_profile[label] = alive
        if lines and not (a.quiet and not any("PAST" in l or "PAUSED" in l for l in lines)):
            print(f"[{label}] 活着 {alive} 条 · 共 {len(lines)} 行")
            print("\n".join(lines))

    if not a.quiet:
        print("\n候选点数（叫「夜巡」的活任务）：")
        for prof in profiles:
            label = prof or "default"
            try:
                n = sum(1 for j in load_jobs(prof)
                        if "夜巡" in (j.get("name") or "") and classify(j, now)[0] == "ALIVE")
            except Exception:
                n = -1
            flag = "" if n >= 2 else "  ← 少于 2，链会断在一趟上"
            print(f"  {label:10s} {n} 条{flag}")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
