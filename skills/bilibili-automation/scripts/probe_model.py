#!/usr/bin/env python3
"""probe_model.py — opencode-go 现在还有哪些模型、某个模型名是不是已经下架。

用在两处：videoread.py 突然报错、或某个 profile 的 cron 集体静默失败时，
先确认模型名还在不在名单里，别先去改 mission / prompt。

用法：
    python3 probe_model.py                  # 列出全部模型 id
    python3 probe_model.py --grep minimax   # 只看名字匹配的（大小写不敏感）
    python3 probe_model.py --ping <model>   # 发一条最小请求，看 HTTP 状态与错误类型
    python3 probe_model.py --ping one --ping two    # 可重复，对比两个名字

判据：
    不在 /v1/models 名单里 + --ping 返回 410 {"type":"ModelDeprecated"}  → 已被下架，换名
    在名单里但 --ping 报 402 / Endpoint is unavailable                → provider 侧抖动，重试或换 provider
    在名单里且 --ping 200 但 content 为空                              → max_tokens 被 reasoning 吃光，不是模型坏了

凭据：环境变量 OPENCODE_GO_API_KEY，或 ~/.hermes/.env（不打印、不外传）。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid

BASE = "https://opencode.ai/zen/go"
MODELS_URL = BASE + "/v1/models"
CHAT_URL = BASE + "/v1/chat/completions"


def api_key():
    k = os.environ.get("OPENCODE_GO_API_KEY")
    if k:
        return k.strip()
    for name in ("~/.hermes/.env", "~/.hermes/profiles/minimax/.env"):
        p = os.path.expanduser(name)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8", errors="replace"):
            m = re.match(r"\s*OPENCODE_GO_API_KEY\s*=\s*(.+)", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    sys.exit("找不到 OPENCODE_GO_API_KEY（环境变量或 ~/.hermes/.env）")


def _req(url, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        # 普通 urllib UA 会被 Cloudflare 挡成 403/1010
        "User-Agent": "opencode-cli/1.0",
        "x-opencode-session": str(uuid.uuid4()),
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:600]
    except Exception as e:  # 网络抖动 / DNS 抖动都归这里，原样重跑通常就好
        return "ERR", str(e)[:300]


def list_models(key, pattern):
    st, body = _req(MODELS_URL, key)
    if st != 200:
        print(f"拉模型名单失败：HTTP {st}\n{body}")
        return []
    ids = [d.get("id") for d in json.loads(body).get("data", []) if d.get("id")]
    shown = [i for i in ids if not pattern or pattern.lower() in i.lower()]
    print(f"共 {len(ids)} 个模型，匹配 {len(shown)} 个：")
    for i in shown:
        print("  ", i)
    return ids


def ping(key, model):
    st, body = _req(CHAT_URL, key, {
        "model": model, "max_tokens": 32,
        "messages": [{"role": "user", "content": "回一个字：好"}],
    })
    note = ""
    if st == 200:
        try:
            d = json.loads(body)
            ch = (d.get("choices") or [{}])[0]
            txt = ((ch.get("message") or {}).get("content") or "").strip()
            note = f"content={txt[:40]!r} finish={ch.get('finish_reason')}"
        except Exception:
            note = body[:120]
    else:
        note = body.replace("\n", " ")[:220]
    print(f"  {model:32} HTTP {st}  {note}")
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", default="", help="只看名字含此子串的模型")
    ap.add_argument("--ping", action="append", default=[], help="探测指定模型能否调通，可重复")
    a = ap.parse_args()

    key = api_key()
    ids = list_models(key, a.grep)
    for m in a.ping:
        st = ping(key, m)
        if m in ids:
            print(f"      ↳ 在名单里{'，但调用失败' if st != 200 else ''}")
        else:
            print("      ↳ 不在名单里" + ("，已下架（换名）" if st == 410 else ""))


main()
