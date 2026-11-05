#!/usr/bin/env python3
"""bili_probe_upload.py — 只读探测：小号是否具备投稿（视频上传）资格。

不创建稿件、不上传任何字节，只做三次 GET：
  1) /x/web-interface/nav        登录态 / 等级 / 大会员
  2) member /x/web/archives      已有稿件列表（能读到=是 UP 主视角）
  3) member /preupload           预上传探测（返回 OK:1 + 上传端点 = 有投稿权限）

用法: python3 bili_probe_upload.py --why "验证投稿资格"
凭据: ~/.hermes/bili/cookies.json (600)，绝不打印。
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
WHY = why_from_argv("验证小号投稿资格")


def get(url, cookie, referer="https://member.bilibili.com/", timeout=25):
    req = urllib.request.Request(url, headers={
        "Cookie": cookie, "User-Agent": UA, "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return {"__http": e.code, "body": e.read().decode()[:400]}
    except Exception as e:
        return {"__err": f"{type(e).__name__}: {e}"}


def main():
    if not os.path.exists(CK_PATH):
        sys.exit(f"缺少凭据 {CK_PATH}")
    ck = json.load(open(CK_PATH))
    cookie = "; ".join(f"{k}={v}" for k, v in ck.items())
    print(f"cookie 字段数 {len(ck)}（含 SESSDATA={'SESSDATA' in ck}）\n")

    # 1) 登录态与等级
    nav = get("https://api.bilibili.com/x/web-interface/nav", cookie,
              referer="https://www.bilibili.com/")
    d = nav.get("data") or {}
    print("== 1. 登录态 /nav ==")
    print(f"  code={nav.get('code')} isLogin={d.get('isLogin')} mid={d.get('mid')} "
          f"uname={d.get('uname')}")
    li = d.get("level_info") or {}
    print(f"  等级 LV{li.get('current_level')} "
          f"(经验 {li.get('current_exp')}/{li.get('next_exp')})  "
          f"大会员={d.get('vipStatus')} 硬币={d.get('money')}")
    print(f"  未实名标记 isLogin={d.get('isLogin')} | "
          f"hasPhone={'✓' if (d.get('mobile_verified') or d.get('phone')) else '未知/未返回'}")

    # 2) 已有稿件（UP 主视角）
    print("\n== 2. 稿件列表 /x/web/archives ==")
    arc = get("https://member.bilibili.com/x/web/archives"
              "?status=is_pubing%2Cpubed%2Cnot_pubed&pn=1&ps=5&coop=1&interactive=1", cookie)
    if "__err" in arc or "__http" in arc:
        print(f"  失败: {arc}")
    else:
        print(f"  code={arc.get('code')} message={arc.get('message')}")
        dd = arc.get("data") or {}
        print(f"  稿件数 page.count={dd.get('page', {}).get('count')} "
              f"| 列表={len(dd.get('arc_audits') or dd.get('archives') or [])} 条")

    # 3) 预上传探测（有权限才返回 OK:1 + 端点）
    print("\n== 3. 投稿预上传 /preupload ==")
    q = urllib.parse.urlencode({
        "name": "probe.mp4", "size": 1048576, "r": "upos",
        "profile": "ugcfx/bup", "ssl": 0, "version": "2.14.0",
        "build": 2140000, "platform": "pc",
    })
    pre = get(f"https://member.bilibili.com/preupload?{q}", cookie,
              referer="https://member.bilibili.com/platform/upload/video/frame")
    if "__err" in pre or "__http" in pre:
        print(f"  失败: {pre}")
    else:
        print(f"  OK={pre.get('OK')} code={pre.get('code')} msg={pre.get('message')}")
        for k in ("endpoint", "upos_uri", "biz_id", "auth", "chunk_size"):
            if k in pre:
                v = pre[k]
                if k == "auth":
                    v = f"<{len(str(v))} 字符>"
                print(f"  {k} = {v}")
    print()
    # 4) 分片写入实测（1KB 哑数据，验证 auth 真的能用；不提交稿件）
    put_ok = "未测"
    if pre.get("OK") == 1 and pre.get("auth") and pre.get("upos_uri"):
        base = ("https:" + pre["endpoint"] + "/" +
                pre["upos_uri"].replace("upos://", ""))
        purl = (base + "?partNumber=1&chunk=0&chunks=1&size=1024"
                "&start=0&end=1023&total=1024")
        req2 = urllib.request.Request(purl, data=b"\0" * 1024, method="PUT", headers={
            "Cookie": cookie, "User-Agent": UA,
            "Referer": "https://member.bilibili.com/platform/upload/video/frame",
            "X-Upos-Auth": pre["auth"], "Content-Type": "application/octet-stream",
        })
        try:
            with urllib.request.urlopen(req2, timeout=30) as r2:
                put_ok = f"HTTP {r2.status} {r2.read().decode(errors='replace')[:20]}"
        except Exception as e:
            put_ok = f"{type(e).__name__}"
        print(f"  分片 PUT 探测 -> {put_ok}")

    print()
    verdict = "可投稿" if pre.get("OK") == 1 else "未能确认可投稿"
    log_op("读", "探测投稿资格", f"mid={d.get('mid')} LV{li.get('current_level')}",
           why=WHY, result=f"{verdict} (preupload OK={pre.get('OK')}, put={put_ok}, archives code={arc.get('code')})")
    print(f"结论: {verdict}")


if __name__ == "__main__":
    main()
