#!/usr/bin/env python3
"""bili_probe_upload2.py — 深一层只读探测：upos 上传链路是否真的打开。

preupload 只给端点，不代表真能传。这里做两步：
  1) POST {endpoint}{upos_uri}?uploads&output=json  → 拿 upload_id（不传任何字节）
  2) 若成功，再 PUT 一个 1KB 的哑分片到该 upload_id，确认服务端接受
整个过程**不提交稿件**（不调 /x/vu/web/add），不产生任何稿件或草稿。

用法: python3 bili_probe_upload2.py --why "验证上传链路"
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op, why_from_argv  # noqa: E402

CK_PATH = os.path.expanduser((os.environ.get("BILI_HOME", "~/.hermes/bili") + "/cookies.json"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
WHY = why_from_argv("验证小号上传链路")


def req(url, cookie, method="GET", headers=None, data=None, timeout=30):
    h = {"Cookie": cookie, "User-Agent": UA,
         "Referer": "https://member.bilibili.com/platform/upload/video/frame",
         "Origin": "https://member.bilibili.com"}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def main():
    ck = json.load(open(CK_PATH))
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    print(f"cookie 字段 {len(ck)} | 含 bili_jct(csrf)={'bili_jct' in ck}\n")

    q = urllib.parse.urlencode({"name": "probe.mp4", "size": 1048576, "r": "upos",
                                "profile": "ugcfx/bup", "ssl": 0, "version": "2.14.0",
                                "build": 2140000, "platform": "pc"})
    st, body = req(f"https://member.bilibili.com/preupload?{q}", cookie)
    pre = json.loads(body) if body.strip().startswith("{") else {}
    endpoint, uri, auth = pre.get("endpoint", ""), pre.get("upos_uri", ""), pre.get("auth", "")
    print(f"preupload -> HTTP {st} OK={pre.get('OK')}")
    if not (endpoint and uri and auth):
        print("端点信息不全，停止"); return
    base = "https:" + endpoint + "/" + uri.replace("upos://", "")
    print(f"目标 base = {base[:80]}...")

    print("\n== A. 初始化分片上传（不上传字节） ==")
    st, body = req(f"{base}?uploads&output=json", cookie, method="POST",
                   headers={"X-Upos-Auth": auth}, data=b"")
    print(f"HTTP {st} -> {body[:300]}")
    try:
        j = json.loads(body)
        upid = j.get("upload_id") or ""
    except Exception:
        upid = ""
    print(f"upload_id = {upid or '未取得'}")

    ok_put = ""
    if upid:
        print("\n== B. 哑分片 PUT（1KB，验证写入权限） ==")
        st2, body2 = req(f"{base}?partNumber=1&uploadId={upid}&chunk=0&chunks=1&size=1024"
                         f"&start=0&end=1023&total=1024", cookie, method="PUT",
                         headers={"X-Upos-Auth": auth,
                                  "Content-Type": "application/octet-stream"},
                         data=b"\0" * 1024)
        print(f"HTTP {st2} -> {body2[:300]}")
        ok_put = f"partPUT HTTP {st2}"

    result = f"init={'OK' if upid else 'fail'}; {ok_put or 'no put'}; 未提交稿件"
    log_op("写", "探测上传链路(哑数据)", "upos init+1KB part，无稿件产生", why=WHY, result=result)
    print(f"\n结论: {result}")
    print("注: 未调用 /x/vu/web/add，账号内不会出现新稿件/草稿。")


if __name__ == "__main__":
    main()
