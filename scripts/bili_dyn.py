#!/usr/bin/env python3
"""bili_dyn.py — 用已登录的 B站 cookie 读/发/删自己的动态（私用，凭据不落日志）。

子命令:
    list [N]              列出自己最近 N 条动态（默认 5）
    post <文本>            发一条纯文本动态，发完自动回读验证
    post --file <路径>     从文件读正文发（推荐：正文含换行/引号时避免 shell 转义踩坑）
    post --timer "2026-10-21 18:20"   用 B站原生定时发布（也收 '+30m' / '+2h' / '10-21 18:20'）
    unpost <dyn_id>       撤掉一条还没到点的定时动态
    del <dyn_id>          删除自己发的一条动态
    account               查看账号状态

所有子命令都支持 `--why "发起原因"`，写进 ~/Desktop/B站账号操作日志.md。
发帖前做出口过滤（bili_guard.leak_scan），拒绝发出凭据/路径/内网 IP 等内容。

实测要点（2026-10 验证）:
  1. 发动态: POST /x/dynamic/feed/create/dyn?csrf=<jct>&platform=web
     body = {"dyn_req": {"content": {"contents": [{"raw_text": t, "type": 1, "biz_id": ""}]},
                         "meta": {"app_meta": {"from": "create.dynamic.web", "mobi_app": "web"}},
                         "scene": 1, "upload_id": "<mid>_<秒级ts>_<4位随机>", "option": {}}}
     返回 dyn_type=2（图文型）属正常，纯文本也走这条路。
  2. 读自己动态: GET /x/polymer/web-dynamic/v1/feed/space?host_mid=<mid>&features=itemOpusStyle
     **必须带 features=itemOpusStyle**，否则 module_dynamic.major.opus 为 null，
     文本全空（看起来像"发出去被吞了"，其实是解析漏了）。
  3. 删除: POST /x/dynamic/feed/operate/remove?csrf=<jct>，**JSON** body
     {"dyn_id_str": ..., "dyn_type": 2}；用 form 会返回 4101001 参数错误。
  4. 老接口 api.vc.bilibili.com（dynamic_svr/create、rm_dynamic）在此网络已不可用（DNS 失败）。

凭据: ~/.hermes/bili/cookies.json (600)
"""
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op, why_from_argv  # noqa: E402
from bili_guard import leak_scan  # noqa: E402

CK_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/cookies.json"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
API = "https://api.bilibili.com"


def _resolve_me_mid() -> str:
    """本账号 mid 从凭据文件里读，绝不写死：BILI_HOME 指到第二个号时，
    写死会让它读到另一个号的动态（2026-10-22 实测：姐姐走 mini_bili.py 壳
    读「自己的动态」，读出来的全是妹妹的）。"""
    try:
        with open(CK_PATH) as f:
            mid = str(json.load(f).get("DedeUserID") or "").strip()
        if mid:
            return mid
    except Exception:
        pass
    return os.environ.get("BILI_MID_SELF", "")   # 兜底：环境变量，未配置则置空（只读模式）


ME_MID = _resolve_me_mid()
FEATURES = "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote"


def load():
    if not os.path.exists(CK_PATH):
        sys.exit(f"缺少凭据文件 {CK_PATH}")
    ck = json.load(open(CK_PATH))
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    return ck, cookie


def _req(url, cookie, data=None, ctype=None, referer="https://www.bilibili.com/"):
    headers = {"Cookie": cookie, "User-Agent": UA, "Referer": referer,
               "Origin": "https://www.bilibili.com"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "message": f"HTTP {e.code}", "data": None}


def get(path, cookie, referer="https://www.bilibili.com/"):
    return _req(API + path, cookie, referer=referer)


def post_json(path, payload, cookie, referer="https://www.bilibili.com/"):
    return _req(API + path, cookie, data=json.dumps(payload).encode(),
                ctype="application/json", referer=referer)


def post_form(path, data, cookie, referer="https://www.bilibili.com/"):
    return _req(API + path, cookie, data=urllib.parse.urlencode(data).encode(),
                ctype="application/x-www-form-urlencoded", referer=referer)


def feed(ck, cookie, n=5):
    """读自己的动态列表。返回 (code, [{dyn_id,type,text,time}])。"""
    url = (f"/x/polymer/web-dynamic/v1/feed/space?offset=&host_mid={ME_MID}"
           f"&features={FEATURES}")
    d = get(url, cookie, referer=f"https://space.bilibili.com/{ME_MID}/dynamic")
    items = ((d.get("data") or {}).get("items") or [])[:n]
    out = []
    for it in items:
        mod = it.get("modules", {}).get("module_dynamic") or {}
        major = mod.get("major") or {}
        opus = major.get("opus") or {}
        summary = opus.get("summary") or {}
        text = summary.get("text") or (mod.get("desc") or {}).get("text") or ""
        out.append({
            "dyn_id": it.get("id_str") or str(it.get("id")),
            "type": it.get("type"),
            "text": text.replace("\n", " ⏎ ")[:90],
            "time": it.get("modules", {}).get("module_author", {}).get("pub_time", ""),
        })
    return d.get("code"), out


def create(text, ck, cookie, timer_ts=None):
    """timer_ts: 秒级 Unix 时间戳；给了就是定时发布（B站原生），None 为立即发布。

    定时发布的关键：不是单独接口，而是 create/dyn 的 dyn_req.option 里加
    option["timer_pub_time"] = 秒级时间戳（前端 dynCreate 里 u2(a,"timer_pub_time",...)）。
    已实测生效。
    """
    option = {}
    if timer_ts:
        option["timer_pub_time"] = int(timer_ts)
    payload = {"dyn_req": {
        "content": {"contents": [{"raw_text": text, "type": 1, "biz_id": ""}]},
        "meta": {"app_meta": {"from": "create.dynamic.web", "mobi_app": "web"}},
        "scene": 1,
        "upload_id": f"{ME_MID}_{int(time.time())}_{random.randint(1000, 9999)}",
        "option": option,
    }}
    return post_json(f"/x/dynamic/feed/create/dyn?csrf={ck['bili_jct']}&platform=web",
                     payload, cookie)


def timing_count(ck, cookie):
    """已设定的定时动态数量（B站上限 20）。返回 data 或 None。"""
    d = get("/x/dynamic/feed/timing_dyn/count", cookie, referer="https://t.bilibili.com/")
    return d.get("data") if d.get("code") == 0 else None


def parse_timer(s):
    """支持 'YYYY-MM-DD HH:MM'、'MM-DD HH:MM'（当年）、'+30m' / '+2h' / '+1d'。"""
    s = str(s).strip()
    m = re.fullmatch(r"\+(\d+)([mhd])", s)
    if m:
        mult = {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
        return int(time.time()) + int(m.group(1)) * mult
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%m-%d %H:%M"):
        try:
            tt = s if "%Y" in fmt else f"{time.strftime('%Y')}-{s}"
            return int(time.mktime(time.strptime(tt, fmt)))
        except ValueError:
            continue
    raise ValueError(f"看不懂的时间格式: {s}（试 '2026-10-21 18:20' 或 '+30m'）")



def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    why = why_from_argv()
    cmd = sys.argv[1]
    ck, cookie = load()
    jct = ck.get("bili_jct", "")

    if cmd == "account":
        d = get("/x/member/web/account", cookie, referer="https://account.bilibili.com/")
        data = d.get("data") or {}
        print(f"code={d.get('code')} {d.get('message')}")
        for k in ("mid", "uname", "tel", "email", "level", "coins", "birthday"):
            if k in data:
                print(f"  {k}: {data[k]}")
        log_op("读", "查看账号状态", f"mid={data.get('mid')}", why=why, result=f"tel={data.get('tel')}")

    elif cmd == "list":
        n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 5
        code, out = feed(ck, cookie, n)
        print(f"code={code} 最近 {len(out)} 条:")
        for i in out:
            print(f"  [{i['dyn_id']}] {i['time']} {i['type']} | {i['text']}")
        log_op("读", "读取自己的动态", f"最近{len(out)}条", why=why, result=f"code={code}")

    elif cmd == "post":
        args = sys.argv[2:]
        for flag in ("--why",):  # why_from_argv 已读过，别让它混进正文
            if flag in args:
                j = args.index(flag)
                del args[j:j + 2]
        timer_raw = None
        if "--timer" in args:
            i = args.index("--timer")
            timer_raw = args[i + 1]
            del args[i:i + 2]
        if "--file" in args:
            path = os.path.expanduser(args[args.index("--file") + 1])
            text = open(path, encoding="utf-8").read()
        else:
            text = args[0] if args else ""
        if not text.strip():
            sys.exit("用法: post <文本> | post --file <路径> [--timer 'YYYY-MM-DD HH:MM'] [--why \"原因\"]")
        timer_ts = None
        if timer_raw:
            try:
                timer_ts = parse_timer(timer_raw)
            except ValueError as e:
                sys.exit(f"❌ {e}")
            if timer_ts <= time.time() + 60:
                sys.exit("❌ 定时时间必须至少在 1 分钟后")
        hits = leak_scan(text)
        if hits:
            log_op("写", "发动态（拦截）", "-", why=why, result=f"❌ 出口过滤命中 {hits}")
            sys.exit(f"❌ 出口过滤拒绝发送，命中: {hits}")
        d = create(text, ck, cookie, timer_ts)
        ok = d.get("code") == 0
        data = d.get("data") or {}
        dyn_id = data.get("dyn_id_str") or str(data.get("dyn_id"))
        if timer_ts:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(timer_ts))
            print(("✅ " if ok else "❌ ") + f"code={d.get('code')} {d.get('message')} "
                  f"定时={when} dyn_id={dyn_id}")
        else:
            print(("✅ " if ok else "❌ ") + f"code={d.get('code')} {d.get('message')} dyn_id={dyn_id}")
        if ok and timer_ts:
            time.sleep(2)
            cnt = timing_count(ck, cookie)
            print(f"定时队列回读: {cnt}")
            stuck = bool(cnt) and (cnt.get("all_count") or 0) > 0
            print("验证: " + ("✅ 定时队列里已有这条（尚未公开）" if stuck
                             else "⚠️ 队列计数为空，需人工去创作中心看一眼"))
            log_op("写", "定时发动态", f"dyn_id={dyn_id} @ {when}", why=why,
                   result="✅ 已入定时队列" if stuck else f"⚠️ code=0 但计数={cnt}")
        elif ok:
            time.sleep(3)
            _, out = feed(ck, cookie, 3)
            hit = [i for i in out if i["dyn_id"] == dyn_id]
            print(f"回读验证: {'✅ 已出现在动态列表' if hit else '⚠️ 暂未出现（可能在审核池）'}")
            for i in out:
                print(f"  [{i['dyn_id']}] {i['time']} | {i['text']}")
            log_op("写", "发动态", f"dyn_id={dyn_id}", why=why,
                   result=("✅ 成功" + ("（已回读）" if hit else "（待审核）")))
        else:
            log_op("写", "发动态", "-", why=why, result=f"❌ {d.get('code')} {d.get('message')}")

    elif cmd == "del":
        if len(sys.argv) < 3:
            sys.exit("用法: del <dyn_id> [--why \"原因\"]")
        dyn_id = sys.argv[2]
        d = post_json(f"/x/dynamic/feed/operate/remove?csrf={jct}",
                      {"dyn_id_str": dyn_id, "dyn_type": 2}, cookie)
        ok = d.get("code") == 0
        print(f"{'✅' if ok else '❌'} code={d.get('code')} {d.get('message')}")
        log_op("写", "删除动态", f"dyn_id={dyn_id}", why=why,
               result="✅ 成功" if ok else f"❌ {d.get('code')} {d.get('message')}")

    elif cmd == "unpost":
        if len(sys.argv) < 3:
            sys.exit("用法: unpost <dyn_id> [--why \"原因\"]   # 撤掉一条还没到点的定时动态")
        dyn_id = sys.argv[2]
        d = post_json(f"/x/dynamic/feed/timing_dyn/delete?csrf={jct}",
                      {"dyn_id_str": dyn_id}, cookie)
        ok = d.get("code") == 0
        print(f"{'✅' if ok else '❌'} code={d.get('code')} {d.get('message')}")
        print(f"定时队列剩余: {timing_count(ck, cookie)}")
        log_op("写", "撤下定时动态", f"dyn_id={dyn_id}", why=why,
               result=("✅ 成功" if ok else f"❌ {d.get('code')} {d.get('message')}"))

    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
