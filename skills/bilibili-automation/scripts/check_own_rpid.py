#!/usr/bin/env python3
"""查自己在某个视频下某条顶层评论的 state 与匿名可见性。

为什么需要它：`bili_cli.py verify <BV> <rpid> --pages N` 只翻自己侧 sort=1 的前 N 页，
热门视频（上千条评论）里，几小时前发的那条早已沉到几百条之后 —— 报「自己侧读不到」
不等于评论没了，只看 verify 的结论很容易误判成被吞。本脚本改用
`/x/v2/reply/wbi/main` + mode=2（时间序）带 cookie 翻页，能直接命中自己的评论并读出 state。

用法：python3 check_own_rpid.py <BV|aid> <rpid> [最大翻页数=10]
判读：self FOUND + state=0 = 存在且正常；anon NOT_FOUND 在评论量大时属正常（沉底），
只有 anon 拿到数据且明确不含目标、且 self 也找不到，才考虑审核/删除。绝不据此重发。
"""
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import bili_cli as B  # noqa: E402


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    target, rpid = sys.argv[1], sys.argv[2]
    pages = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    ck, cookie = B.load()
    if target.lower().startswith("bv"):
        v = B.call(f"/x/web-interface/view?bvid={target}", cookie=cookie)
        oid = (v.get("data") or {}).get("aid")
        print("oid", oid, "title", ((v.get("data") or {}).get("title") or "")[:40])
    else:
        oid = int(target)
    if not oid:
        sys.exit("拿不到 oid")

    mixin = B._mixin_key(cookie)
    for label, use_cookie in (("self", True), ("anon", False)):
        cursor, found = "", None
        for i in range(pages):
            p = {"oid": oid, "type": 1, "mode": 2, "plat": 1, "web_location": 1315875,
                 "pagination_str": json.dumps({"offset": cursor}, separators=(",", ":"))}
            q = urllib.parse.urlencode(p) + "&" + urllib.parse.urlencode(B._wbi_sign(p, mixin))
            url = f"{B.API}/x/v2/reply/wbi/main?{q}"          # 匿名用完整 URL
            path = f"/x/v2/reply/wbi/main?{q}"                # 带 cookie 走 B.call，它自己会拼 API 前缀
            d = B.call(path, cookie=cookie) if use_cookie else B._anon(url)
            reps = (d.get("data") or {}).get("replies") or []
            if i == 0:
                cur = (d.get("data") or {}).get("cursor") or {}
                print(label, "code", d.get("code"), "page_n", len(reps), "all_count", cur.get("all_count"))
            for x in reps:
                if str(x.get("rpid")) == str(rpid):
                    c = x.get("content") or {}
                    found = {"state": x.get("state"), "ctime": x.get("ctime"), "like": x.get("like"),
                             "message": c.get("message", "")[:70],
                             "members": [m.get("uname") for m in (c.get("members") or [])]}
                    break
            if found:
                break
            cursor = (((d.get("data") or {}).get("cursor") or {})
                      .get("pagination_reply") or {}).get("next_offset") or ""
            if not cursor:
                break
        print(label, "FOUND" if found else "NOT_FOUND",
              json.dumps(found, ensure_ascii=False) if found else "")


if __name__ == "__main__":
    main()
