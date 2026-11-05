#!/usr/bin/env python3
"""videoread.py — 让 MiniMax M3 真的"看"一段视频（不抽帧）。

原理：opencode-go 的 minimax-m3（默认；m3.1-flash 作为备用，出问题自动降级）
端到端支持 video_url content part，
模型一次吃下整段（fps 可降），返回文字描述。Hermes 自己的多模态只到图片，所以走这条自建通道。

用法：
    python3 videoread.py <URL|BV号> [--fps 1] [--res 360] [--maxmb 40]
                                 [--chunk 150] [--prompt "自定义提问"]
输出：stdout 打描述文本；--json 打结构化结果。临时文件落在 TMPDIR，跑完即删。

凭据：环境变量 OPENCODE_GO_API_KEY（或自动从 ~/.hermes/.env 读）。
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, uuid

API = os.environ.get("VIDEO_READ_API_URL", "https://api.openai.com/v1/chat/completions")
# 模型列表走环境变量 VIDEO_READ_MODELS（逗号分隔：首选在前，其余为不可用时自动降级备选）。
# 例：export VIDEO_READ_MODELS=your-vision-model,backup-vision-model
_env_models = os.environ.get("VIDEO_READ_MODELS", "")
MODELS = [m.strip() for m in _env_models.split(",") if m.strip()]
if not MODELS:
    sys.exit("未配置 VIDEO_READ_MODELS —— 本脚本需要能吃视频的视觉模型；只吃图的模型请走 bili_shot.py 抽帧路径")
MODEL = MODELS[0]
DEFAULT_PROMPT = ("用中文分点描述这段视频：画面里在发生什么、场景与人物如何变化、"
                  "有无字幕/文字信息、整体节奏。只描述看得见的，不猜。")


def env_key():
    k = os.environ.get("VIDEO_READ_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if k:
        return k
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(p):
        for name in ("VIDEO_READ_API_KEY", "OPENAI_API_KEY"):
            for line in open(p):
                m = re.match(rf"\s*{name}\s*=\s*(.+)", line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
    sys.exit("找不到 VIDEO_READ_API_KEY / OPENAI_API_KEY（环境变量或 ~/.hermes/.env）")


def norm_url(s):
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", s):
        return f"https://www.bilibili.com/video/{s}"
    if re.fullmatch(r"av\d+", s, re.I):
        return f"https://www.bilibili.com/video/{s}"
    return s


def download(url, res, tmp):
    out = os.path.join(tmp, "src.%(ext)s")
    cmd = ["yt-dlp", "-q", "--no-warnings", "-f",
           f"bv*[height<={res}]/b[height<={res}]/bv*", "--no-playlist",
           "-o", out, url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    files = [f for f in os.listdir(tmp) if f.startswith("src.")]
    if not files:
        sys.exit(f"下载失败：{(p.stderr or p.stdout)[-300:]}")
    return os.path.join(tmp, files[0])


def shrink(path, tmp, maxmb):
    """压到 maxmb 以内（降到 240p + 低码率）。返回新路径。"""
    dst = os.path.join(tmp, "small.mp4")
    for scale, crf in ((360, 30), (240, 34), (240, 38)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-vf", f"scale=-2:{scale}", "-r", "10",
                        "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
                        "-an", dst], check=False)
        if os.path.exists(dst) and os.path.getsize(dst) <= maxmb * 1024 * 1024:
            return dst
    return dst


def probe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,size", "-of", "json", path],
                       capture_output=True, text=True)
    d = (json.loads(p.stdout).get("format") or {})
    return float(d.get("duration") or 0), int(d.get("size") or os.path.getsize(path))


def split(path, tmp, sec):
    dst = os.path.join(tmp, "part_%03d.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                    "-c", "copy", "-f", "segment", "-segment_time", str(sec),
                    "-reset_timestamps", "1", dst], check=False)
    return sorted(os.path.join(tmp, f) for f in os.listdir(tmp)
                  if f.startswith("part_") and f.endswith(".mp4"))


def _split_think(txt):
    """minimax-m3 把思考塞在 content 里（<think>…</think>，reasoning_content 为空），
    而 m3.1-flash 走 reasoning_content 字段。这里统一剥掉思考段，只留正文。
    返回 (正文, 是否未闭合)。未闭合说明输出被思考吃空/截断。"""
    if not txt or "<think>" not in txt:
        return txt, False
    i = txt.find("<think>")
    head = txt[:i].strip()
    j = txt.rfind("</think>")
    if j == -1 or j < i:
        return head, True
    return (head + "\n" + txt[j + len("</think>"):]).strip(), False


def ask(key, video_path, prompt, fps, tmp, idx=0, model=None, max_tokens=16000):
    b64 = base64.b64encode(open(video_path, "rb").read()).decode()
    body = {"model": model or MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + b64, "fps": fps}}]}]}
    payload = os.path.join(tmp, f"body_{idx}.json")
    with open(payload, "w") as f:
        json.dump(body, f)
    p = subprocess.run(["curl", "-s", "--max-time", "900", API,
                        "-H", f"Authorization: Bearer {key}",
                        "-H", "Content-Type: application/json",
                        "-H", "User-Agent: opencode-cli/1.0",
                        "-H", f"x-opencode-session: {uuid.uuid4()}",
                        "-d", "@" + payload], capture_output=True, text=True)
    os.remove(payload)
    try:
        d = json.loads(p.stdout)
    except Exception:
        return f"[解析失败] {p.stdout[:300]}", None
    if "choices" not in d:
        return f"[接口错误] {json.dumps(d, ensure_ascii=False)[:400]}", None
    ch = d["choices"][0]
    msg = ch.get("message") or {}
    usage = d.get("usage") or {}
    txt = (msg.get("content") or "").strip()
    if not txt:
        # M3.1 会先想再答；思考吃完 max_tokens 时 content 为空，退回 reasoning 并标注
        rc = (msg.get("reasoning_content") or "").strip()
        txt = f"[finish={ch.get('finish_reason')}，正文空，以下为思考内容]\n{rc}" if rc \
            else f"[空响应 finish={ch.get('finish_reason')}]"
    txt, unclosed = _split_think(txt)
    if unclosed and not txt:
        return (f"[接口错误] think 未闭合：正文被思考吃空 "
                f"(finish={ch.get('finish_reason')})"), usage
    return txt, usage


RETRY_HINTS = ("deprecated", "not found", "not enabled", "not_found",
               "unknown model", "does not exist",
               # 2026-10-23: 备用要真的能兜底 —— 服务端 5xx / 限流 / 超时 也切下一个模型
               "\"code\": 5", "\"code\":5", "internal", "overloaded",
               "rate limit", "timed out", "timeout", "unavailable",
               "think 未闭合")


def ask_any(key, video_path, prompt, fps, tmp, idx=0, max_tokens=16000):
    """按 MODELS 顺序试：前一个被下架/停用/服务端抽风就自动换下一个，不中断整趟。
    注意别无脑重试——视频一次几十万 token，只在 RETRY_HINTS 命中时才换模型。"""
    last_txt, last_usage = "[没有可用模型]", None
    for model in MODELS:
        txt, usage = ask(key, video_path, prompt, fps, tmp, idx, model=model,
                         max_tokens=max_tokens)
        if not (txt or "").startswith(("[接口错误]", "[解析失败]")):
            return txt, usage, model
        low = (txt or "").lower()
        if any(k in low for k in RETRY_HINTS):
            last_txt, last_usage = txt, usage
            continue
        return txt, usage, model
    return last_txt, last_usage, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--res", type=int, default=360)
    ap.add_argument("--maxmb", type=float, default=40.0)
    ap.add_argument("--chunk", type=int, default=150, help="超过 maxmb 时按秒切片")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--max-tokens", type=int, default=16000,
                    help="M3.1 先想再答，给小了正文会被思考吃空（默认 16000）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    key = env_key()
    tmp = tempfile.mkdtemp(prefix="videoread_")
    src = download(norm_url(a.url), a.res, tmp)
    dur, size = probe(src)

    parts = []
    if size > a.maxmb * 1024 * 1024:
        src = shrink(src, tmp, a.maxmb)
        dur, size = probe(src)
    target = src if size <= a.maxmb * 1024 * 1024 else None
    if target is None:
        parts = split(src, tmp, a.chunk)
        target_list = parts
    else:
        target_list = [src]

    results, tokens = [], 0
    models_used = set()
    for i, path in enumerate(target_list):
        prompt = a.prompt if len(target_list) == 1 else \
            f"这是同一段视频的第 {i+1}/{len(target_list)} 片。{a.prompt}"
        txt, usage, used = ask_any(key, path, prompt, a.fps, tmp, i,
                                   max_tokens=a.max_tokens)
        models_used.add(used or "?")
        if usage:
            tokens += int(usage.get("total_tokens") or 0)
        results.append(txt)

    out = {"url": a.url, "duration_s": round(dur, 1), "video_mb": round(size / 1e6, 2),
           "fps": a.fps, "chunks": len(results), "total_tokens": tokens,
           "model": "/".join(sorted(m for m in models_used if m)),
           "description": "\n\n".join(results)}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out["description"])
        print(f"\n--- {out['duration_s']}s / {out['video_mb']}MB / fps={a.fps} / "
              f"{out['chunks']} 段 / {tokens} tokens / model={out['model']}")


main()
