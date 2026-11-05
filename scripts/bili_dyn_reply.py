#!/usr/bin/env python3
"""动态(type=11)评论回复：WBI 签名 + 回读验证。
用法: dyn_reply.py <oid> <文本> [--root rpid] [--parent rpid] [--referer URL]
"""
import hashlib, json, os, sys, time, urllib.parse, urllib.request

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


def req(url, data=None, referer="https://www.bilibili.com/"):
    body = urllib.parse.urlencode(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers={
        "Cookie": COOKIE, "User-Agent": UA, "Referer": referer,
        "Origin": "https://www.bilibili.com",
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(r, timeout=25) as resp:
        return json.loads(resp.read().decode())


def mixin_key():
    nav = req("https://api.bilibili.com/x/web-interface/nav")
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    raw = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0] + \
          wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    return "".join(raw[i] for i in MIXIN_TAB if i < len(raw))[:32]


def wbi(params, mixin):
    p = dict(params)
    p["wts"] = int(time.time())
    clean = [(k, "".join(c for c in str(v) if c not in "!'()*")) for k, v in sorted(p.items())]
    q = urllib.parse.urlencode(clean)
    return {"w_rid": hashlib.md5((q + mixin).encode()).hexdigest(), "wts": p["wts"]}


WHY = why_from_argv()   # 先摘掉 --why "原因"，再解析位置参数
args = sys.argv[1:]
root = parent = None
ref = "https://www.bilibili.com/"
ctype = 11
for flag in ("--root", "--parent", "--referer", "--ctype"):
    if flag in args:
        k = args.index(flag)
        v = args[k + 1]
        del args[k:k + 2]
        if flag == "--root":
            root = int(v)
        elif flag == "--parent":
            parent = int(v)
        elif flag == "--ctype":
            ctype = int(v)
        else:
            ref = v
oid, msg = args[0], args[1]

_leaks = leak_scan(msg)
if _leaks:
    _d = " / ".join(f"{w}({f})" for w, f in _leaks)
    log_op("写", "发动态评论被出口过滤拦截", f"oid={oid}", why=WHY, result=f"🛑 未发送：{_d}")
    sys.exit(f"🛑 出口过滤拦截，未发送。命中：{_d}")

data = {"oid": oid, "type": ctype, "message": msg, "plat": 1, "csrf": ck["bili_jct"],
        "gain_source": "main_web",
        "statistics": json.dumps({"appId": 100, "platform": 5})}
if root:
    data["root"] = root
if parent:
    data["parent"] = parent

q = wbi(data, mixin_key())
d = req("https://api.bilibili.com/x/v2/reply/add?" + urllib.parse.urlencode(q), data, referer=ref)
if d.get("code") != 0:
    log_op("写", "发动态评论", f"oid={oid} ctype={ctype}", why=WHY,
           result=f"❌ {d.get('code')} {d.get('message')}")
    sys.exit(f"❌ 发送失败 {d.get('code')} {d.get('message')}")
rpid = (d.get("data") or {}).get("rpid")
print(f"✅ 接口已接受 rpid={rpid}")
tgt = f"oid={oid} ctype={ctype} rpid={rpid}" + (f" root={root}" if root else "") + \
      f" 正文「{msg[:40]}」"

time.sleep(6)
if root:
    lst = req(f"https://api.bilibili.com/x/v2/reply/reply?oid={oid}&type={ctype}&root={root}&pn=1&ps=20")
else:
    lst = req(f"https://api.bilibili.com/x/v2/reply?oid={oid}&type={ctype}&sort=0&pn=1&ps=20")
rs = (lst.get("data") or {}).get("replies") or []
hit = [x for x in rs if x.get("rpid") == rpid]
if hit:
    print("✅ 已渲染：", (hit[0].get("content") or {}).get("message", "")[:200].replace("\n", " "))
    log_op("写", "发动态评论" + ("(回复楼中楼)" if root else ""), tgt, why=WHY,
           result="✅ 已渲染")
else:
    print("⚠️ 列表里没看到 —— 疑似进审核池，别重发。code", lst.get("code"), lst.get("message"))
    log_op("写", "发动态评论" + ("(回复楼中楼)" if root else ""), tgt, why=WHY,
           result="⚠️ 列表不可见，疑似进审核池")
