#!/usr/bin/env python3
"""关注 + 私信 某 UP（小号身份）。用法: social_ops.py follow <mid> | dm <mid> <文本>"""
import json, os, re, sys, time, uuid, hashlib, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op, why_from_argv  # noqa: E402  桌面操作日志
from bili_guard import leak_scan  # noqa: E402  出口过滤

CK = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/cookies.json"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
             36, 20, 34, 44, 52]

ck = json.load(open(CK))
COOKIE = "; ".join(f"{k}={v}" for k, v in ck.items() if isinstance(v, str))
ME = str(ck.get("DedeUserID"))


def post(url, data, referer="https://www.bilibili.com/"):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Cookie": COOKIE, "User-Agent": UA, "Referer": referer,
        "Origin": "https://www.bilibili.com",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def get(url, referer="https://www.bilibili.com/"):
    req = urllib.request.Request(url, headers={
        "Cookie": COOKIE, "User-Agent": UA, "Referer": referer})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def _mixin_key():
    nav = get("https://api.bilibili.com/x/web-interface/nav")
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    raw = img + sub
    return "".join(raw[i] for i in MIXIN_TAB if i < len(raw))[:32]


def _wbi(params, mixin):
    p = dict(params)
    p["wts"] = int(time.time())
    clean = [(k, "".join(c for c in str(v) if c not in "!'()*")) for k, v in sorted(p.items())]
    q = urllib.parse.urlencode(clean)
    p["w_rid"] = hashlib.md5((q + mixin).encode()).hexdigest()
    return {"w_rid": p["w_rid"], "wts": p["wts"]}


def follow(mid):
    d = post("https://api.bilibili.com/x/relation/modify",
             {"fid": mid, "act": 1, "re_src": 11, "csrf": ck["bili_jct"]})
    print("follow:", d.get("code"), d.get("message"))
    time.sleep(1)
    r = get(f"https://api.bilibili.com/x/relation?fid={mid}")
    att = (r.get("data") or {}).get("attribute")
    print("relation attribute:", att, "(2/6 = 已关注)")
    ok = att in (2, 6)
    log_op("写", "关注 UP", f"mid={mid}", why=WHY,
           result=("✅ 已关注 attribute=%s" % att) if ok else
                  f"❌ 未生效 attribute={att} code={d.get('code')}")


def dm(mid, text):
    leaks = leak_scan(text)
    if leaks:
        detail = " / ".join(f"{w}({f})" for w, f in leaks)
        log_op("写", "发私信被出口过滤拦截", f"mid={mid}", why=WHY,
               result=f"🛑 未发送：{detail}")
        sys.exit(f"🛑 出口过滤拦截，未发送。命中：{detail}")
    ts = int(time.time() * 1000)
    data = {
        "msg[sender_uid]": ME,
        "msg[receiver_id]": mid,
        "msg[receiver_type]": 1,
        "msg[msg_type]": 1,
        "msg[msg_status]": 0,
        "msg[timestamp]": int(time.time()),
        "msg[dev_id]": str(uuid.uuid4()).upper(),
        "msg[content]": json.dumps({"content": text}, ensure_ascii=False),
        "csrf": ck["bili_jct"],
        "csrf_token": ck["bili_jct"],
        "build": 0,
        "mobi_app": "web",
    }
    d = post("https://api.vc.bilibili.com/web_im/v1/web_im/send_msg", data,
             referer="https://message.bilibili.com/")
    print("send:", d.get("code"), d.get("message"), "| msg_key", (d.get("data") or {}).get("msg_key"))
    time.sleep(3)
    chk = get(f"https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs"
              f"?talker_id={mid}&session_type=1&size=5",
              referer="https://message.bilibili.com/")
    msgs = (chk.get("data") or {}).get("messages") or []
    print("readback:", chk.get("code"))
    seen = False
    norm = lambda s: re.sub(r"\s+", "", s or "")
    for m in msgs[:5]:
        print("  from", m.get("sender_uid"), "|", (m.get("content") or "")[:160].replace("\n", " "))
        raw = m.get("content") or ""
        try:  # 私信 content 是 JSON 串（含 \n 转义），先解出来再比
            raw = (json.loads(raw).get("content") or raw)
        except Exception:
            pass
        if str(m.get("sender_uid")) == str(ME) and norm(text)[:20] in norm(raw):
            seen = True
    log_op("写", "发私信", f"mid={mid} 正文「{text[:40]}」", why=WHY,
           result=("✅ 回读可见" if seen else
                   f"⚠️ 回读未见（code={chk.get('code')} 发送 code={d.get('code')}）"))


if __name__ == "__main__":
    cmd = sys.argv[1]
    WHY = why_from_argv()
    if cmd == "follow":
        follow(sys.argv[2])
    elif cmd == "dm":
        dm(sys.argv[2], sys.argv[3])
    elif cmd == "whoami":
        n = get("https://api.bilibili.com/x/web-interface/nav")
        u = n.get("data") or {}
        print(u.get("uname"), u.get("mid"), "isLogin", u.get("isLogin"))
        log_op("读", "查询登录身份", f"mid={u.get('mid')}", why=WHY,
               result=f"{u.get('uname')} isLogin={u.get('isLogin')}")
