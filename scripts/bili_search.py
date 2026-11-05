#!/usr/bin/env python3
"""WBI 搜索小工具：按关键词搜 B站视频，打印候选（不写操作日志，纯公开只读数据）。"""
import json
import sys
import urllib.parse
import os
sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
import bili_cli

ck, cookie = bili_cli.load()
mixin = bili_cli._mixin_key(cookie)

for kw in sys.argv[1:]:
    print("=== " + kw + " ===")
    p = {"search_type": "video", "keyword": kw, "page": 1, "page_size": 20}
    q = urllib.parse.urlencode(p) + "&" + urllib.parse.urlencode(bili_cli._wbi_sign(p, mixin))
    d = bili_cli.call("/x/web-interface/wbi/search/type?" + q, cookie=cookie,
                      referer="https://search.bilibili.com/")
    res = (d.get("data") or {}).get("result") or []
    for v in res:
        title = (v.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
        print(f"{v.get('bvid')} {v.get('duration')} {v.get('author')} | {title} | 播放{v.get('play')} 弹幕{v.get('video_review')}")
