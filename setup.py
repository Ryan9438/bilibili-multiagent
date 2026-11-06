#!/usr/bin/env python3
"""setup.py probe —— 能力探测 + Tier 推荐（开源版引导器）

用法:
    python3 setup.py probe          # 探测并生成 provider_probe.json
    python3 setup.py probe --json   # 仅输出 JSON（给 agent 读）

原部署经验：凭证留在 .env，能力靠实测不打听。缺什么直接说缺什么，不静默降级。
"""
import json, os, re, subprocess, sys, time, base64

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE_FILE = os.path.join(HERE, "provider_probe.json")

def die(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(code)

def load_env():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        die("没有 .env —— 先: cp .env.example .env 并填入至少一组 PROVIDER_MAIN_* "
            "(API_KEY/BASE_URL/MODEL)；本脚本绝不帮你猜 key，也绝不打印你已填的值")
    env = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"): continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env

def curl_json(url, headers, body, timeout=25):
    p = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url,
         "-H", "Content-Type: application/json",
         *[h for kv in (headers or {}).items() for h in ("-H", f"{kv[0]}: {kv[1]}")],
         "-d", json.dumps(body)],
        capture_output=True, text=True)
    if p.returncode != 0:
        return None, f"curl exit={p.returncode}: {p.stderr.strip()[:200]}"
    try:
        return json.loads(p.stdout), None
    except Exception as e:
        return None, f"非 JSON 响应: {p.stdout[:200]} ({e})"

def probe_chat(base_url, api_key, model):
    url = base_url.rstrip("/") + "/chat/completions"
    body = {"model": model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}]}
    d, err = curl_json(url, {"Authorization": f"Bearer {api_key}"}, body)
    if err: return {"ok": False, "error": err}
    if isinstance(d, dict) and d.get("error"):
        m = d["error"].get("message", ""); c = d["error"].get("code", "")
        return {"ok": False, "error": f"provider 回: code={c} {str(m)[:160]}"}
    if isinstance(d, dict) and d.get("choices"):
        return {"ok": True, "latency_ms": None, "echo": model}
    return {"ok": False, "error": f"意外响应形态: {str(d)[:160]}"}

# 1x1 透明 PNG，最小可行的 image_vision 探测
_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGMAAQAABQAB"
        "DQottAAAAABJRU5ErkJggg==")

def probe_image(base_url, api_key, model):
    url = base_url.rstrip("/") + "/chat/completions"
    b64 = base64.b64decode(_PNG).decode("latin1")
    body = {"model": model, "max_tokens": 4, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What color? one word"},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64," + _PNG}}]}]}
    d, err = curl_json(url, {"Authorization": f"Bearer {api_key}"}, body, timeout=40)
    if err: return {"ok": False, "error": err}
    if isinstance(d, dict) and d.get("choices"):
        return {"ok": True}
    if isinstance(d, dict) and d.get("error"):
        return {"ok": False, "error": str(d["error"].get("message", ""))[:160]}
    return {"ok": False, "error": "意外响应形态"}

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "probe":
        print(__doc__); sys.exit(0)
    env = load_env()
    providers = {}
    for name in ("MAIN", "BACKUP"):
        key = env.get(f"PROVIDER_{name}_API_KEY", "")
        base = env.get(f"PROVIDER_{name}_BASE_URL", "")
        model = env.get(f"PROVIDER_{name}_MODEL", "")
        if not (key or base or model):
            continue
        short = "main" if name == "MAIN" else "backup"
        providers[short] = {"base_url": base, "model": model,
                            "api_key": bool(key)}  # 只记布尔，不记值
        missing = [k for k, v in (("API_KEY", key), ("BASE_URL", base), ("MODEL", model)) if not v]
        providers[short]["missing"] = missing
        if missing:
            providers[short]["probe"] = {"ok": False, "error": f"缺 {','.join(missing)}"}
        else:
            providers[short]["probe"] = probe_chat(base, key, model)
            if providers[short]["probe"].get("ok"):
                providers[short]["image_vision"] = probe_image(base, key, model).get("ok")

    video_models = [m.strip() for m in env.get("VIDEO_READ_MODELS", "").split(",") if m.strip()]
    cookie_path = os.path.expanduser(env.get("BILI_COOKIES_PATH", ""))
    has_cookie = bool(cookie_path) and os.path.exists(cookie_path)

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "providers": providers,
        "video_vision_models_env": video_models,
        "cookie": {"path_set": bool(env.get("BILI_COOKIES_PATH")), "file_exists": has_cookie},
        "tags": {},
        "recommended_tier": None,
        "warnings": [],
    }
    ok = [n for n, p in providers.items() if p.get("probe", {}).get("ok")]
    img = [n for n in ok if providers[n].get("image_vision")]
    result["tags"] = {
        "chat_ok": ok,
        "image_vision": img,
        "video_vision": "untested",   # 视频探测建议用一条真实短视频跑 videoread.py 验证
        "tool_use": "untested",       # 以任务实际使用为准
    }
    for n, p in providers.items():
        if not p.get("probe", {}).get("ok"):
            result["warnings"].append(f"{n}: {p.get('probe', {}).get('error', '未探测')}")
    if not ok:
        result["warnings"].append("没有任何 provider 探测通过 —— 检查 key/base_url/model；"
                                  "若只想先用 Tier 0 只读功能（无 key 命令 401 不影响），此警告可忽略")
    result["recommended_tier"] = 1 if has_cookie else 0
    if len(ok) >= 2:
        result["warnings"].append("你有多组 provider：可在 config/roles.yaml 的槽位里配 fallback 链")

    with open(PROBE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2)); return
    print(f"== 探测完成 → {os.path.basename(PROBE_FILE)} ==")
    print(f"chat 通过: {ok or '无'}（其中能看图: {img or '无'}）")
    print(f"推荐 Tier: {result['recommended_tier']}（"
          + ("Tier 1 需要 cookie：在 .env 填 BILI_COOKIES_PATH" if not has_cookie else "cookie 已就位") + "）")
    for w in result["warnings"]:
        print(f"  ⚠️ {w}")

if __name__ == "__main__":
    main()
