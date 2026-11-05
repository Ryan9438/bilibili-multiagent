# 小鲸鱼 / 小大姐：私信正文查看器（只读）
#
# 体检时用：bili_watch.py 只报 id 与昵称，要读「他到底说了什么」用这个。
# 跟 BILI_HOME 走（默认 ~/.hermes/bili），不打印任何凭据，只打时间 / 方向 / 正文前 220 字。
#
#   env BILI_HOME=~/.hermes/bili python3 dm_peek.py
#   env BILI_HOME=... python3 dm_peek.py --talker <mid> [--talker <mid> ...] [--size 6]
#
# 不传 --talker 就先打 session_svr/get_sessions 拿会话列表（size=40）再逐个拉。

import argparse
import json
import os
import sys
import time
import urllib.request

HOME = os.environ.get("BILI_HOME", os.path.expanduser("~/.hermes/bili"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")


def load_home(home):
    with open(os.path.join(home, "cookies.json")) as f:
        ck = json.load(f)
    ckstr = "; ".join(f"{k}={v}" for k, v in ck.items() if isinstance(v, str))
    return ck, ckstr


def get(url, ckstr):
    req = urllib.request.Request(url, headers={
        "Cookie": ckstr,
        "Referer": "https://message.bilibili.com/",
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def sessions(ckstr):
    url = ("https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions"
           "?session_type=1&group_index=1&size=40")
    try:
        d = get(url, ckstr)
    except Exception as e:
        print(f"[sessions] ERROR {e}（接口抖动只算未知，下趟复查）")
        return []
    data = d.get("data") or {}
    out = []
    for s in data.get("session_list") or []:
        tid = s.get("talker_id")
        if tid:
            out.append(str(tid))
    return out


def logsafe(kind, action, target, why, result):
    """按 bili_log.log_op 的实际签名传参；签名未知就用 inspect 适配，失败静默。"""
    try:
        sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
        import inspect
        from bili_log import log_op
        vals = {"kind": kind, "rtype": kind, "type": kind, "action": action,
                "target": target, "obj": target, "object": target,
                "why": why, "reason": why, "result": result}
        kwargs = {n: vals[n] for n in inspect.signature(log_op).parameters if n in vals}
        log_op(**kwargs)
    except Exception:
        pass


def dump(home, talkers, size):
    ck, ckstr = load_home(home)
    me = str(ck.get("DedeUserID") or "")
    for t in talkers:
        url = ("https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs"
               f"?talker_id={t}&session_type=1&size={size}")
        try:
            d = get(url, ckstr)
        except Exception as e:
            print(f"talker={t} ERROR {e}")
            continue
        msgs = (d.get("data") or {}).get("messages") or []
        print(f"\ntalker={t} code={d.get('code')} n={len(msgs)}")
        # 接口按新→旧返回，倒过来按时间读
        for m in list(reversed(msgs)):
            ts = m.get("timestamp")
            try:
                ts = time.strftime("%m-%d %H:%M", time.localtime(int(ts)))
            except Exception:
                pass
            raw = m.get("content") or ""
            try:
                raw = json.loads(raw).get("content") or raw
            except Exception:
                pass
            mine = "我>" if str(m.get("sender_uid")) == me else "对>"
            print(f"  {ts} {mine} {str(raw)[:220]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--talker", action="append", default=None, help="会话对方 mid，可重复")
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--why", default="体检：读私信正文")
    a = ap.parse_args()

    _, ckstr = load_home(HOME)
    talkers = a.talker or sessions(ckstr)
    if not talkers:
        print("没有可读会话（或会话列表接口抖动）")
        return
    dump(HOME, talkers, a.size)
    logsafe("读", "读取私信正文", f"{HOME} 共 {len(talkers)} 个会话", a.why, "只读查看，未发送")


if __name__ == "__main__":
    main()
