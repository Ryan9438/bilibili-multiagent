#!/usr/bin/env python3
"""bili_watch.py — 盯 B站 新消息（@我的 / 回复我的 / 私信），给 cron monitor 模式用。

用法:
    bili_watch.py                 输出 KNOWN 清单（单调追加，ack 不改变它）
    bili_watch.py ack <id>...     把已处理的消息标记为已读，并刷新给 agent 读的缓存

为什么有两种输出（2026-10-19 改）：

* stdout（cron monitor 拿它算 hash）—— `KNOWN <n>` + 历史发现过的 id 清单。
  只在「首次发现新 id」时改变。旧版输出的是「未 ack 的 id」，于是 agent 处理完
  执行 ack 后 stdout 又变一次，下一个 tick 就白唤醒 agent 一轮（日志里那些
  「心跳假唤醒复核」）。改成单调清单后，ack 不动 stdout，假唤醒消失。
* ~/.hermes/bili/watch_last.txt（给 agent 读）—— 未 ack 的 id + DM/GUARD 行。
  agent 醒来直接读这个文件，不再重跑本脚本：旧版 prompt 让它再跑一遍，
  导致每次唤醒全量扫两次 B站 API（at + reply + 全部私信会话）并重复记日志。

私信覆盖范围：**全部会话**，不只主人那条。规则是「每个会话的最新一条如果
不是我发的、且在 DM_WINDOW 天内 → 视为待处理」。回复后该会话不再重复弹出。
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op  # noqa: E402  桌面操作日志
from bili_guard import judge  # noqa: E402  静态风险预筛

CK = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/cookies.json"))
SEEN_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/seen_msgs.json"))
NICK_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/nick_cache.json"))
FEED_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/watch_feed.json"))
CACHE_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/watch_last.txt"))
DM_WINDOW = 7 * 86400   # 只看 7 天内的私信，避免首跑把几年前的会话全翻出来
FEED_KEEP_HOURS = 72    # feed 里保留多久的「已发现」记录（清理会让 stdout 变一次）
FEED_MAX = 120          # feed 条目上限
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")


# ---------- 状态文件 ----------

def _atomic_write(path, text, mode=0o600):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def load_seen():
    return load_json(SEEN_PATH, [])


def save_seen(ids):
    _atomic_write(SEEN_PATH, json.dumps(sorted(set(ids))[-500:]))


def load_feed():
    feed = load_json(FEED_PATH, {"items": []})
    items = feed.get("items") if isinstance(feed, dict) else None
    return {"items": items if isinstance(items, list) else []}


def prune_feed(feed):
    """丢掉过期/超量的条目。注意：清理会让 stdout 变化一次（agent 空跑一轮），
    所以窗口给得宽（72h / 120 条），一天最多碰上一次。"""
    cutoff = time.time() - FEED_KEEP_HOURS * 3600
    items = [it for it in feed["items"] if it.get("ts", 0) >= cutoff]
    return {"items": items[-FEED_MAX:]}


def save_feed(feed):
    _atomic_write(FEED_PATH, json.dumps(feed, ensure_ascii=False))


# ---------- 输出渲染 ----------

def _id_block(ids, per_line=8):
    return [" ".join(ids[i:i + per_line]) for i in range(0, len(ids), per_line)]


def render_known(items):
    """给 cron monitor 的稳定输出：只在新 id 首次出现时变化。"""
    ids = [it["id"] for it in items]
    lines = [f"KNOWN {len(ids)}"] + _id_block(ids)
    for it in items:
        if it.get("guard") and it["guard"] != "benign":
            lines.append(f'GUARD {it["id"]} {it["guard"].upper()} {it.get("why") or ""}'.rstrip())
    for it in items:
        if it.get("dm"):
            lines.append(f'DM {it["id"]} from {it["dm"]}')
    return "\n".join(lines)


def render_pending(items, seen):
    """给 agent 的缓存：还没 ack 的那部分。"""
    pending = [it for it in items if it["id"] not in seen]
    if not pending:
        return "NO_NEW"
    ids = [it["id"] for it in pending]
    lines = ["NEW " + " ".join(ids)]
    for it in pending:
        if it.get("dm"):
            lines.append(f'DM {it["id"]} from {it["dm"]}')
    for it in pending:
        if it.get("guard") and it["guard"] != "benign":
            lines.append(f'GUARD {it["id"]} {it["guard"].upper()} {it.get("why") or ""}'.rstrip())
    lines.append(_ack_hint(ids))
    return "\n".join(lines)


def _ack_hint(ids):
    """ack 提示行（咿呀，这行以前写死过，害人）。

    以前这里恒输出 `python3 ~/.hermes/scripts/bili_watch.py ack …`：默认号照抄没问题，
    但第二个号（BILI_HOME 指到 profiles/minimax）照抄就会用**别人的凭据**去 ack，
    状态写错目录、还白记一行日志。所以非默认目录时把 BILI_HOME 一并写进提示。
    """
    home = os.environ.get("BILI_HOME", "~/.hermes/bili")
    prefix = ""
    if os.path.expanduser(home).rstrip("/") != os.path.expanduser("~/.hermes/bili").rstrip("/"):
        prefix = f"BILI_HOME={home} "
    return "# 处理完后执行: " + prefix + "python3 ~/.hermes/scripts/bili_watch.py ack " + " ".join(ids)


def refresh_cache(items, seen):
    text = render_pending(items, seen)
    _atomic_write(CACHE_PATH, text + "\n")
    return text


# ---------- B站 API ----------

def get(url, cookie):
    r = urllib.request.Request(url, headers={
        "Cookie": cookie, "User-Agent": UA,
        "Referer": "https://message.bilibili.com/",
        "Origin": "https://message.bilibili.com",
    })
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read().decode())


def dm_sessions(cookie):
    """全部私信会话的 talker_id。"""
    d = get("https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions"
            "?session_type=1&group_index=1&size=40&build=0&mobi_app=web", cookie)
    return [s["talker_id"] for s in ((d.get("data") or {}).get("session_list") or [])
            if s.get("talker_id")]


def dm_latest(cookie, talker):
    """某会话的最新一条消息。"""
    d = get(f"https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs"
            f"?talker_id={talker}&session_type=1&size=3", cookie)
    msgs = (d.get("data") or {}).get("messages") or []
    return msgs[0] if msgs else None


def load_nicks():
    return load_json(NICK_PATH, {})


def nick_of(cookie, mid, cache):
    """昵称带本地缓存，避免每 5 分钟重复请求。"""
    if str(mid) in cache:
        return cache[str(mid)]
    try:
        d = get(f"https://api.bilibili.com/x/web-interface/card?mid={mid}", cookie)
        nm = ((d.get("data") or {}).get("card") or {}).get("name") or ""
    except Exception:
        nm = ""
    if nm:
        cache[str(mid)] = nm
        try:
            _atomic_write(NICK_PATH, json.dumps(cache, ensure_ascii=False))
        except Exception:
            pass
    return nm or "?"


def dm_text(raw):
    """私信 content 是 JSON 串，解开取正文。"""
    try:
        o = json.loads(raw or "{}")
        if isinstance(o, dict):
            return o.get("content") or o.get("title") or raw or ""
    except Exception:
        pass
    return raw or ""


def collect():
    ck = json.load(open(CK))
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    found = []

    for kind, url in (
        ("at", "https://api.bilibili.com/x/msgfeed/at?platform=web&build=0&mobi_app=web&pn=1&ps=20"),
        ("reply", "https://api.bilibili.com/x/msgfeed/reply?platform=web&build=0&mobi_app=web&pn=1&ps=20"),
    ):
        try:
            d = get(url, cookie)
            for it in ((d.get("data") or {}).get("items") or []):
                if it.get("id"):
                    # 顺手把正文带上，供本地预筛用；输出里只出现判定，不出现原文
                    item = it.get("item") or {}
                    found.append((f"{kind}:{it['id']}",
                                  item.get("source_content") or item.get("title") or ""))
        except Exception as e:
            print(f"# WARN {kind} fetch failed: {type(e).__name__}", file=sys.stderr)

    # 私信：扫描**全部**会话，每个会话只看最新一条；
    # 最新一条不是我发的且在 DM_WINDOW 天内 → 有待处理（我回过后自动不再弹）
    dm_meta = {}
    nicks = load_nicks()
    try:
        me = str(ck.get("DedeUserID"))
        cutoff = time.time() - DM_WINDOW
        for t in dm_sessions(cookie):
            try:
                latest = dm_latest(cookie, t)
            except Exception:
                continue
            if not latest:
                continue
            if str(latest.get("sender_uid")) == me:
                continue
            if (latest.get("timestamp") or 0) < cutoff:
                continue
            k = f"dm:{latest.get('msg_key') or latest.get('timestamp')}"
            found.append((k, dm_text(latest.get("content"))))
            dm_meta[k] = f"{nick_of(cookie, t, nicks)}({t})"
    except Exception as e:
        print(f"# WARN dm fetch failed: {type(e).__name__}", file=sys.stderr)

    # 同一 id 只留一条（内容取第一条非空的）
    dedup = {}
    for k, txt in found:
        if k not in dedup or (not dedup[k] and txt):
            dedup[k] = txt
    return dedup, dm_meta


# ---------- 主流程 ----------

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "ack":
        ids = load_seen() + sys.argv[2:]
        save_seen(ids)
        # 只刷新给 agent 的缓存；stdout（KNOWN 清单）不依赖 ack → 不再假唤醒
        items = prune_feed(load_feed())["items"]
        refresh_cache(items, set(ids))
        print(f"ACKED {len(sys.argv) - 2} 条，累计已读 {len(set(ids))}")
        return

    seen = set(load_seen())
    msgs, dm_meta = collect()

    feed = prune_feed(load_feed())
    known = {it["id"] for it in feed["items"]}
    fresh = sorted(k for k in msgs if k not in known)

    for k in fresh:
        r = judge(msgs.get(k, ""))
        why = " / ".join(f'{h["category"]}:{h["why"]}' for h in r["hits"])
        feed["items"].append({
            "id": k,
            "ts": int(time.time()),
            "guard": r["level"],
            "why": why,
            "dm": dm_meta.get(k, ""),
        })
    if fresh:
        save_feed(feed)

    # stdout：稳定清单，cron monitor 只有在新 id 出现时才看到变化
    print(render_known(feed["items"]))
    # 缓存：agent 醒来直接读，不再重跑本脚本
    refresh_cache(feed["items"], seen)

    # 空轮询不记日志；只有「真·未处理」的新消息才留一行
    loggable = [k for k in fresh if k not in seen]
    if not loggable:
        return
    kinds = {}
    for x in loggable:
        kinds[x.split(":")[0]] = kinds.get(x.split(":")[0], 0) + 1
    n_atk = sum(1 for it in feed["items"]
                if it["id"] in loggable and it["guard"] == "attack")
    log_op("读", "心跳探信（@/回复/私信）", ", ".join(f"{k}×{v}" for k, v in kinds.items()),
           why="收信心跳 cron（每 5 分钟自动探测）",
           result=f"发现 {len(loggable)} 条新消息" + (f"，本地预筛判为攻击 {n_atk} 条" if n_atk else ""))


if __name__ == "__main__":
    main()
