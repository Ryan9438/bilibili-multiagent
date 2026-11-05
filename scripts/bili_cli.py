#!/usr/bin/env python3
"""bili_cli.py — 用已登录的 B站 cookie 做轻量操作（私用，凭据不落日志）。

子命令:
    check                    验证登录态
    toview-add  <id>...      加入「稍后再看」（bvid 或数字 aid）
    toview-list              列出「稍后再看」
    toview-clear             清空「稍后再看」
    comment <id> <文本> [--at 名字:mid]   发视频评论（可选真 @ 某人），发完自动回读验证
    comments <id> [N]        列出最新评论
    comment-del <id> <rpid>  删除自己发的评论

所有子命令都支持 `--why "发起原因"`，原因会写进 ~/Desktop/B站账号操作日志.md。

关键：发评论必须带 **WBI 签名 + 全量 cookie**，否则服务端返回 code=0 但把评论静默吞进
审核池（实测：只带 5 个 cookie、无签名时，评论永远不渲染）。见 _wbi_sign()。

凭据: ~/.hermes/bili/cookies.json (600)
"""
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op, why_from_argv  # noqa: E402  桌面操作日志
from bili_guard import leak_scan  # noqa: E402  出口过滤

CK_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/cookies.json"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
API = "https://api.bilibili.com"

MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
             36, 20, 34, 44, 52]


def load():
    if not os.path.exists(CK_PATH):
        sys.exit(f"缺少凭据文件 {CK_PATH}（需要先从浏览器抓一次 cookie）")
    ck = json.load(open(CK_PATH))
    # 全量 cookie：缺 b_lsid / buvid_fp / _uuid 等指纹字段会被判可疑请求
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    return ck, cookie


def call(path, data=None, cookie=None, referer="https://www.bilibili.com/"):
    url = API + path
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={
        "Cookie": cookie, "User-Agent": UA, "Referer": referer,
        "Origin": "https://www.bilibili.com",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # 412 = B站频控（短时间请求太多）；返回结构化结果，让上层按「未知」处理，别抛栈
        return {"code": e.code, "message": f"HTTP {e.code}", "data": None}


def _mixin_key(cookie):
    nav = call("/x/web-interface/nav", cookie=cookie)
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    raw = img + sub
    return "".join(raw[i] for i in MIXIN_TAB if i < len(raw))[:32]


def _wbi_sign(params, mixin):
    p = dict(params)
    p["wts"] = int(time.time())
    clean = [(k, "".join(ch for ch in str(v) if ch not in "!'()*"))
             for k, v in sorted(p.items())]
    query = urllib.parse.urlencode(clean)
    p["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return {"w_rid": p["w_rid"], "wts": p["wts"]}


def _anon(url):
    """不带 cookie 的匿名请求：只有它看得见，才算对外真的可见。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://www.bilibili.com/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def _anon_top_page(oid, pn, mixin, cursor=""):
    """未登录视角读顶层评论（按**时间序** mode=2，可翻页）。

    铁律（2026-10 实测，别再踩）：老接口 `/x/v2/reply` 在**无 cookie** 时，
    `sort=0`（热度）恒返回空——code=0 但 replies=None、acount=0，看起来就像
    “这视频没评论/我的评论被吞了”；`sort=1` 只给 3 条降级预览。
    只有 `/x/v2/reply/wbi/main` + WBI 签名（未登录）才拿到完整列表。
    热度序（mode=3）只够看前 20 条，自己 0 赞的评论早就沉底；找自己的评论必须走
    **时间序 mode=2**（新发的秒级出现），并沿 cursor.pagination_reply.next_offset 翻页。
    """
    p = {"oid": oid, "type": 1, "mode": 2, "plat": 1, "web_location": 1315875,
         "pagination_str": json.dumps({"offset": cursor or ""}, separators=(",", ":"))}
    q = urllib.parse.urlencode(p) + "&" + urllib.parse.urlencode(_wbi_sign(p, mixin))
    return _anon(f"{API}/x/v2/reply/wbi/main?{q}")


def _anon_next_cursor(d):
    cur = ((d.get("data") or {}).get("cursor") or {}).get("pagination_reply") or {}
    return cur.get("next_offset") or ""


def verify_comment(oid, rpid, root, cookie, pages=3):
    """回读自己刚发的评论，返回 (state, anon_visible, obj, note)。

    带 cookie 回读能读到被阿瓦隆隐藏的评论（state=17，仅自己可见），
    所以「已渲染」必须再用**无 cookie** 的匿名请求确认一遍。
    state 语义：0 正常 / 11 审核中 / 17 阿瓦隆仅自己可见（别人看不到 = 通知不会发）。

    anon_visible 三态：True 已对外可见 / False 真的不可见 / **None 检测接口失败**。
    None 绝不能当成「被吞」——那会怂恿人删掉一条其实发成功的评论。
    """
    mixin = _mixin_key(cookie)
    state, obj, note = None, None, ""
    for pn in range(1, pages + 1):
        ep = "reply/reply" if root else "reply"
        q = f"oid={oid}&type=1&pn={pn}&ps=20" + (f"&root={root}" if root else "&sort=1")
        d = call(f"/x/v2/{ep}?{q}", cookie=cookie)
        if d.get("code") not in (0, None):
            note = f"自己侧接口 code={d.get('code')} {d.get('message')}"
            break
        reps = (d.get("data") or {}).get("replies") or []
        for x in reps:
            if str(x.get("rpid")) == str(rpid):
                state, obj = x.get("state"), x
                break
        if obj or not reps:
            break

    anon, anon_got, exhausted = None, False, False
    cursor = ""
    for i in range(pages):
        try:
            if root:
                d = _anon(f"{API}/x/v2/reply/reply?oid={oid}&type=1&root={root}&pn={i + 1}&ps=20")
            else:
                d = _anon_top_page(oid, i + 1, mixin, cursor=cursor)
        except Exception as e:                                   # 网络异常 ≠ 被吞
            note = f"匿名请求异常 {type(e).__name__}"
            break
        code = d.get("code")
        if code != 0:
            note = f"匿名接口 code={code} {d.get('message')}"
            break
        data = d.get("data") or {}
        reps = data.get("replies") or []
        if reps:
            anon_got = True
        if any(str(x.get("rpid")) == str(rpid) for x in reps):
            anon = True
            break
        if root:
            if not reps:
                exhausted = True
                break
            continue
        nxt = _anon_next_cursor(d)
        if not reps or not nxt or nxt == cursor:
            exhausted = True
            break
        cursor = nxt
    if anon is None:
        # 翻到末页还没命中 → 真的不在对外列表；一页非空都没拿到 → 风控软屏蔽，判「未知」
        anon = False if (anon_got or exhausted) else None
        if not anon_got and not note:
            note = "匿名列表全程空响应（风控软屏蔽），可见性未知"
    return state, anon, obj, note


def to_aid(x, cookie):
    if str(x).isdigit():
        return int(x)
    d = call(f"/x/web-interface/view?bvid={x}", cookie=cookie)
    if d.get("code") != 0 or not d.get("data"):
        sys.exit(f"取 aid 失败: {d.get('code')} {d.get('message')}")
    return d["data"]["aid"]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    why = why_from_argv()   # 摘掉 --why "原因"，进日志用
    cmd = sys.argv[1]
    ck, cookie = load()
    me = str(ck.get("DedeUserID", ""))

    if cmd == "check":
        d = call("/x/web-interface/nav", cookie=cookie)
        if d.get("code") != 0 or not d.get("data", {}).get("isLogin"):
            log_op("读", "校验登录态", "nav", why=why, result=f"❌ 未登录 code={d.get('code')}")
            sys.exit(f"未登录: code={d.get('code')} {d.get('message')}")
        u = d["data"]
        print(f"✅ {u.get('uname')} (mid={u.get('mid')}, LV{u.get('level_info',{}).get('current_level')}, "
              f"硬币={u.get('money')})")
        log_op("读", "校验登录态", f"{u.get('uname')}(mid={u.get('mid')})", why=why, result="✅ 已登录")

    elif cmd == "toview-add":
        ids = sys.argv[2:]
        if not ids:
            sys.exit("用法: toview-add <bvid|aid>... [--why \"原因\"]")
        for i in ids:
            p = {"csrf": ck["bili_jct"]}
            p["bvid" if i.lower().startswith("bv") else "aid"] = i
            d = call("/x/v2/history/toview/add", p, cookie)
            ok = d.get("code") == 0
            print(("✅ " if ok else "❌ ") + f"{i}: {d.get('code')} {d.get('message')}")
            log_op("写", "加入稍后再看", i, why=why,
                   result=("✅ 成功" if ok else f"❌ {d.get('code')} {d.get('message')}"))

    elif cmd == "toview-list":
        d = call("/x/v2/history/toview", cookie=cookie)
        lst = (d.get("data") or {}).get("list") or []
        print(f"共 {len(lst)} 条")
        for i in lst:
            print(f"  [{i.get('aid')}] {i.get('title')}  — {i.get('owner',{}).get('name')}")
        log_op("读", "读取稍后再看列表", "-", why=why, result=f"共 {len(lst)} 条")

    elif cmd == "toview-clear":
        d = call("/x/v2/history/toview/clear", {"csrf": ck["bili_jct"]}, cookie)
        ok = d.get("code") == 0
        print(("✅ " if ok else "❌ ") + f"清空: {d.get('code')} {d.get('message')}")
        log_op("写", "清空稍后再看", "-", why=why,
               result=("✅ 成功" if ok else f"❌ {d.get('code')} {d.get('message')}"))

    elif cmd == "comment":
        args = sys.argv[2:]
        at = None
        root = parent = None
        for flag in ("--at", "--root", "--parent"):
            if flag in args:
                k = args.index(flag)
                val = args[k + 1]
                del args[k:k + 2]
                if flag == "--at":
                    at = val
                elif flag == "--root":
                    root = int(val)
                else:
                    parent = int(val)
        if len(args) < 2:
            sys.exit("用法: comment <bvid|aid> <文本> [--at 名字:mid] [--root rpid --parent rpid] [--why 原因]\n"
                     "  ⚠️ 发楼中楼必须 --root 与 --parent 成对传：--root 是那层楼的根评论 rpid，--parent 是你要回的那条的 rpid"
                     "（回根评论本身时 parent 填 root 同值）。只传 --root 时 B站会把 parent 归 0，整条落成顶层评论"
                     "（回读 root=0/parent=0），看着像回错了地方。")
        leaks = leak_scan(args[1])
        if leaks:
            detail = " / ".join(f"{w}({f})" for w, f in leaks)
            log_op("写", "发评论被出口过滤拦截", f"文本含敏感片段", why=why,
                   result=f"🛑 未发送：{detail}")
            sys.exit(f"🛑 出口过滤拦截，未发送。命中：{detail}")
        oid = to_aid(args[0], cookie)
        data = {
            "oid": oid, "type": 1, "message": args[1], "plat": 1,
            "csrf": ck["bili_jct"], "gain_source": "main_web",
            "statistics": json.dumps({"appId": 100, "platform": 5}),
        }
        if root:
            data["root"] = root
        if parent:
            data["parent"] = parent
        at_mid = None
        if at:
            name, at_mid = at.rsplit(":", 1)
            data["at_name_to_mid"] = json.dumps({name: at_mid}, ensure_ascii=False)
            mk = "@" + name
            if mk not in data["message"]:
                data["message"] = mk + " " + data["message"]

        mixin = _mixin_key(cookie)
        q = _wbi_sign(data, mixin)
        path = "/x/v2/reply/add?" + urllib.parse.urlencode(q)
        ref = f"https://www.bilibili.com/video/av{oid}"
        d = call(path, data, cookie, referer=ref)
        if d.get("code") != 0:
            log_op("写", "发评论", f"oid={oid}", why=why,
                   result=f"❌ {d.get('code')} {d.get('message')}")
            sys.exit(f"❌ 发送失败 {d.get('code')} {d.get('message')}")
        rpid = (d.get("data") or {}).get("rpid")
        print(f"✅ 接口已接受 rpid={rpid}")

        # 自动回读：作者带 cookie 看得见**不代表对外可见**（阿瓦隆 state=17 只对作者可见），
        # 必须匿名（无 cookie）再确认一遍，否则会拿「已渲染」骗自己、主人一条通知都收不到。
        time.sleep(5)
        state, anon, obj, note = verify_comment(oid, rpid, root, cookie)
        act = "发评论" + ("(回复楼中楼)" if root else "")
        tgt = f"oid={oid} rpid={rpid}" + (f" root={root}" if root else "") + \
              (f" @{at}" if at else "") + f" 正文「{data['message'][:30]}」"
        if obj is None:
            print("⚠️ 带 cookie 也看不到（state=None）—— 疑似审核池，别重发。")
            log_op("写", act, tgt, why=why, result="⚠️ 列表不可见 state=None，疑似审核池")
        elif state in (11, 17):
            why_state = {17: "阿瓦隆仅自己可见(17)", 11: "阿瓦隆审核中(11)"}[state]
            print(f"🛑 {why_state} —— 别人和主人都收不到，删掉换文案重发。"
                  f"  https://www.bilibili.com/video/av{oid}#reply{rpid}")
            log_op("写", act, tgt, why=why, result=f"🛑 {why_state}，未对外可见")
        elif anon is None:
            print(f"⚠️ 匿名检测不可用（{note}）—— **无法判断**，保留这条、不删不重发。"
                  f"  https://www.bilibili.com/video/av{oid}#reply{rpid}")
            log_op("写", act, tgt, why=why, result=f"⚠️ 匿名检测失败({note})，未下结论、保留未重发")
        elif not anon:
            print(f"⏳ 匿名列表暂未收录(state={state}) —— 实测刚发的评论会晚几分钟到几小时自己上线，"
                  f"**不删、不重发**，稍后 `verify` 子命令复核。"
                  f"  https://www.bilibili.com/video/av{oid}#reply{rpid}")
            log_op("写", act, tgt, why=why,
                   result=f"⏳ 待复核（state={state}，匿名暂未收录，未删未重发）")
        else:
            c = (obj or {}).get("content") or {}
            at_ok = bool(at_mid) and any(str(m.get("mid")) == str(at_mid)
                                         for m in (c.get("members") or []))
            print(f"✅ 已对外可见（state={state}，匿名 wbi/main 回读确认｜真@={at_ok}）"
                  f"  https://www.bilibili.com/video/av{oid}#reply{rpid}")
            log_op("写", act, tgt, why=why,
                   result=f"✅ 已对外可见 state={state} 匿名可见 真@={at_ok}")

    elif cmd == "verify":
        if len(sys.argv) < 4:
            sys.exit("用法: verify <id> <rpid> [--root N] [--pages N] [--why \"原因\"]")
        oid = to_aid(sys.argv[2], cookie)
        rpid = int(sys.argv[3])
        root, pages = None, 5
        args = sys.argv[4:]
        for flag in ("--root", "--pages"):
            if flag in args:
                k = args.index(flag)
                val = int(args[k + 1])
                del args[k:k + 2]
                if flag == "--root":
                    root = val
                else:
                    pages = val
        st, anon, obj, note = verify_comment(oid, rpid, root, cookie, pages=pages)
        msg = ((obj or {}).get("content") or {}).get("message", "")
        like = (obj or {}).get("like")
        if anon is True:
            verdict = "✅ 对外可见（匿名时间序命中）"
        elif obj is not None and st in (11, 17):
            verdict = "🛑 阿瓦隆（仅自己可见）"
        elif obj is not None and anon is False:
            verdict = "⏳ 已入库但匿名列表翻完没命中（过渡期或仅自己可见）"
        elif obj is None and anon is False:
            verdict = "❌ 不明（自己侧读不到、匿名也没命中；疑在审核池或已删）"
        else:
            verdict = f"❓ 未知（{note or '两侧都没拿到可靠数据'}）"
        print(f"{verdict}  state={st} 匿名={anon} 赞={like}")
        if note:
            print(f"  note: {note}")
        if msg:
            print(f"  正文: {msg[:80]}")
        log_op("读", "复核评论可见性", f"oid={oid} rpid={rpid}", why=why,
               result=f"state={st} 匿名={anon} 赞={like}")

    elif cmd == "comments":
        oid = to_aid(sys.argv[2], cookie)
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        d = call(f"/x/v2/reply?oid={oid}&type=1&sort=0&pn=1&ps={n}", cookie=cookie)
        cnt = 0
        for item in (d.get("data") or {}).get("replies") or []:
            c = item.get("content") or {}
            m = item.get("member") or {}
            cnt += 1
            print(f"  [{item.get('rpid')}] {m.get('uname')}(mid={item.get('mid')}): "
                  f"{(c.get('message') or '')[:60]}")
        log_op("读", "读取视频评论", f"oid={oid}", why=why, result=f"共 {cnt} 条")

    elif cmd == "comment-del":
        oid = to_aid(sys.argv[2], cookie)
        rpid = sys.argv[3]
        d = call("/x/v2/reply/del", {"oid": oid, "type": 1, "rpid": rpid,
                                     "csrf": ck["bili_jct"]}, cookie)
        ok = d.get("code") == 0
        print(("✅ " if ok else "❌ ") + f"删除: {d.get('code')} {d.get('message')}")
        log_op("写", "删除自己的评论", f"oid={oid} rpid={rpid}", why=why,
               result=("✅ 已删除" if ok else f"❌ {d.get('code')} {d.get('message')}"))

    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
