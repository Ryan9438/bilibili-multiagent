#!/usr/bin/env python3
"""bili_shot.py — 抓 B站视频并按关键帧抽帧截图。

用法:
    bili_shot.py <URL> [--mode scene|uniform] [--frames 24] [--quality 360] [--out DIR]

模式:
    scene   （默认）场景切换检测，只抽画面真正变化的关键帧，凑不够再补均匀帧
    uniform 按时间轴均匀抽 N 帧

产物:
    <outdir>/frame_XX.jpg    关键帧截图
    <outdir>/sheet.jpg       拼图预览（一次看完全场，便于视觉模型快速扫）
    stdout                   JSON（标题/UP/时长/每帧路径与时间戳/sheet 路径）

依赖: yt-dlp (~/.local/bin 或 PATH), ffmpeg。
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

YTDLP = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


def run(cmd, timeout=None):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def pick_evenly(items, k):
    """从列表里均匀挑 k 个（保留首尾，尽量覆盖全程）。"""
    if len(items) <= k:
        return items
    if k <= 1:
        return items[:1]
    step = (len(items) - 1) / (k - 1)
    return [items[round(i * step)] for i in range(k)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--mode", choices=["scene", "uniform"], default="scene")
    ap.add_argument("--frames", type=int, default=24, help="目标帧数上限（scene 模式下取变化最大的前 N 个）")
    ap.add_argument("--quality", type=int, default=360, help="最大高度: 360/480/720")
    ap.add_argument("--scene-thresh", type=float, default=0.30, help="场景切换灵敏度，越低抽得越多")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()

    # BV / av 号也认（2026-10-23：GLM 那边习惯贴 BV，而 yt-dlp 只吃完整 URL）
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", a.url):
        a.url = f"https://www.bilibili.com/video/{a.url}"
    elif re.fullmatch(r"av\d+", a.url, re.I):
        a.url = f"https://www.bilibili.com/video/{a.url}"

    if not os.path.exists(YTDLP):
        sys.exit(json.dumps({"ok": False, "error": "yt-dlp 未安装"}, ensure_ascii=False))

    base = ["--no-warnings", "--no-playlist", "--socket-timeout", "20",
            "--extractor-args", "bilibili:prefer_multi_flv=false"]

    # ---- 1) 元信息
    rc, out, err = run([YTDLP, "-J", *base, a.url], timeout=120)
    if rc != 0:
        sys.exit(json.dumps({"ok": False, "error": "取信息失败", "detail": err[-500:]}, ensure_ascii=False))
    meta = json.loads(out)
    title = meta.get("title") or "untitled"

    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", title)[:60] or "video"
    outdir = a.out or os.path.join(tempfile.gettempdir(), "bili_shot", safe)
    os.makedirs(outdir, exist_ok=True)
    for old in glob.glob(os.path.join(outdir, "frame_*.jpg")) + glob.glob(os.path.join(outdir, "sheet.jpg")):
        os.remove(old)

    # ---- 2) 下载（只取视频流，抽帧不需要音频）
    tmp = tempfile.mkdtemp(prefix="bilishot_")
    tmpl = os.path.join(tmp, "v.%(ext)s")
    rc, out, err = run([YTDLP, *base,
                        "-f", f"bv*[height<={a.quality}]/b[height<={a.quality}]/b",
                        "-o", tmpl, a.url], timeout=1800)
    vids = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith("v.")]
    if rc != 0 or not vids:
        sys.exit(json.dumps({"ok": False, "error": "下载失败", "detail": err[-500:]}, ensure_ascii=False))
    video = vids[0]

    rc, out, err = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", video])
    duration = float(out.strip() or 0) or float(meta.get("duration") or 0)
    if duration <= 0:
        sys.exit(json.dumps({"ok": False, "error": "无法获取时长"}, ensure_ascii=False))

    target = max(1, a.frames)

    # ---- 3) 抽帧
    times = []
    work = tempfile.mkdtemp(prefix="biliframe_")
    pattern = os.path.join(work, "f_%04d.jpg")

    if a.mode == "scene":
        rc, out, err = run([FFMPEG, "-y", "-loglevel", "info", "-i", video,
                            "-vf", f"select='gt(scene,{a.scene_thresh})',scale=540:-2,showinfo",
                            "-fps_mode", "vfr", "-q:v", "4", pattern], timeout=1800)
        times = [float(m) for m in re.findall(r"pts_time:\s*([0-9.]+)", err)]
        files = sorted(glob.glob(os.path.join(work, "f_*.jpg")))
        if len(files) != len(times):          # 对不齐就用均匀兜底
            times = [i * duration / max(1, len(files)) for i in range(len(files))]

        if len(files) > target:               # 关键帧太多 -> 均匀裁到目标数
            keep = pick_evenly(list(range(len(files))), target)
            for i, f in enumerate(files):
                if i not in keep:
                    os.remove(f)
            files = [files[i] for i in keep]
            times = [times[i] for i in keep]

        if len(files) < max(3, target // 3):  # 太平淡的视频 -> 补均匀帧
            step = duration / (target - len(files) + 1)
            complement = []
            for k in range(1, target - len(files) + 1):
                p = os.path.join(work, f"u_{k:04d}.jpg")
                rc2, _, _ = run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{k * step:.2f}",
                                 "-i", video, "-frames:v", "1", "-vf", "scale=540:-2",
                                 "-q:v", "4", p], timeout=120)
                if rc2 == 0 and os.path.exists(p):
                    complement.append((k * step, p))
            files = sorted(files) + [p for _, p in complement]
            times = times + [t for t, _ in complement]
    else:
        fps = target / duration
        rc, out, err = run([FFMPEG, "-y", "-loglevel", "error", "-i", video,
                            "-vf", f"fps={fps:.6f},scale=540:-2", "-q:v", "4", pattern], timeout=1800)
        files = sorted(glob.glob(os.path.join(work, "f_*.jpg")))
        times = [(i + 0.5) * duration / max(1, len(files)) for i in range(len(files))]

    if not files:
        sys.exit(json.dumps({"ok": False, "error": "抽帧失败", "detail": err[-500:]}, ensure_ascii=False))

    # ---- 4) 落到输出目录 + 拼图
    pairs = sorted(zip(times, files), key=lambda x: x[0])
    frames = []
    for i, (t, src) in enumerate(pairs, 1):
        dst = os.path.join(outdir, f"frame_{i:02d}.jpg")
        shutil.copyfile(src, dst)
        frames.append({"path": dst, "t": round(t)})

    sheet = None
    if not a.no_sheet and len(frames) >= 2:
        cols = min(4, len(frames))
        rows = math.ceil(len(frames) / cols)
        sheet = os.path.join(outdir, "sheet.jpg")
        rc, out, err = run([FFMPEG, "-y", "-loglevel", "error",
                            "-i", os.path.join(outdir, "frame_%02d.jpg"),
                            "-vf", f"scale=320:-2,tile={cols}x{rows}:padding=4:color=white",
                            "-frames:v", "1", "-q:v", "3", sheet], timeout=300)
        if rc != 0 or not os.path.exists(sheet):
            sheet = None

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

    print(json.dumps({
        "ok": True,
        "url": a.url,
        "title": title,
        "uploader": meta.get("uploader"),
        "duration_s": round(duration),
        "view_count": meta.get("view_count"),
        "mode": a.mode,
        "frame_count": len(frames),
        "outdir": outdir,
        "sheet": sheet,
        "frames": frames,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
