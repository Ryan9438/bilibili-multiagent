#!/usr/bin/env python3
"""bili_verify_reply.py — 翻页复核某条子回复是否真的渲染出来（防误判进审核池）。

用法: python3 bili_verify_reply.py <aid|bvid> <root_rpid> <rpid>
输出末行 RESULT: RENDERED / NOT_VISIBLE

长楼（>20 条回复）里 /x/v2/reply/reply 一页 20 条，新回复常在 pn=2，
只查 pn=1 会把已渲染的回复误判成被吞。
"""
import json
import os
import sys
import urllib.request

CK = os.path.expanduser("~/.hermes/bili/cookies.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")


def get(url, cookie):
    r = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": UA,
                                             "Referer": "https://www.bilibili.com/"})
    with urllib.request.urlopen(r, timeout=25) as resp:
        return json.loads(resp.read().decode())


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    aid, root, want = sys.argv[1], sys.argv[2], sys.argv[3]
    if not str(aid).isdigit():
        d = get(f"https://api.bilibili.com/x/web-interface/view?bvid={aid}",
                "; ".join(f"{k}={v}" for k, v in json.load(open(CK)).items()))
        aid = d["data"]["aid"]
    cookie = "; ".join(f"{k}={v}" for k, v in json.load(open(CK)).items())
    found = False
    for pn in range(1, 6):
        d = get(f"https://api.bilibili.com/x/v2/reply/reply?oid={aid}&type=1"
                f"&root={root}&pn={pn}&ps=20&sort=0", cookie)
        reps = ((d.get("data") or {}).get("replies") or [])
        for r in reps:
            if str(r.get("rpid")) == str(want):
                found = True
                print(f"FOUND pn={pn} rpid={r.get('rpid')} mid={r.get('mid')} "
                      f"ctime={r.get('ctime')} like={r.get('like')}")
                print(((r.get("content") or {}).get("message")))
        print(f"pn={pn} code={d.get('code')} n={len(reps)}")
        if not reps:
            break
    print("RESULT:", "RENDERED" if found else "NOT_VISIBLE")


if __name__ == "__main__":
    main()
