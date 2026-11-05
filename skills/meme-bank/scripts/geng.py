#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""geng.py — 共享梗本的检索入口（小鲸鱼写的，咿呀）

不读全文，只回你要的那几条。用法：

  python3 geng.py find 大肥鱼 鲸须      # 检索条目 + 顺带告诉你近 7 天有没有人用过
  python3 geng.py used --days 7         # 只看防撞表近 N 天
  python3 geng.py list                  # 目录：每条一句摘要（不知道有啥时用）
  python3 geng.py check                 # 体积体检 + 该用哪一档读法
  python3 geng.py add --title X --source Y [...]

设计口径（主人 2026-10-29 定）：
  1. 发声前默认 find，不 read_file 全文——梗库只会越长，全文读是每次发声都付费。
  2. find 没命中 = 没有这条梗，**不许现编**。
  3. 防撞表（梗_已用.md）单独一个文件，按天查，别整份读。
  4. 输出硬上限：超了就提示换关键词，别让我越搜越宽把上下文吃满。
"""
import argparse
import datetime as dt
import os
import re
import sys

HOME = os.path.expanduser("~")
BANK = os.path.join(HOME, "Desktop/协作/梗.md")
USED = os.path.join(HOME, "Desktop/协作/梗_已用.md")
MAX_LINES_DEFAULT = 40


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        sys.exit("找不到文件：%s" % path)


def norm(s):
    """全角/半角、大小写归一，方便搜。"""
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch.lower())
    return "".join(out)


def sections(text):
    """切成 {章名: 章内正文}。"""
    parts = re.split(r"^## ", text, flags=re.M)
    out = {}
    for p in parts[1:]:
        title, _, body = p.partition("\n")
        out[title.strip()] = body
    return out


def entries(text):
    """返回 [(chapter, title, body)]，按 ### 切；body 不含 ### 行。"""
    rows = []
    chapter = ""
    cur_title = None
    cur_body = []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur_title:
                rows.append((chapter, cur_title, "\n".join(cur_body).strip()))
                cur_title, cur_body = None, []
            chapter = line[3:].strip()
        elif line.startswith("### "):
            if cur_title:
                rows.append((chapter, cur_title, "\n".join(cur_body).strip()))
            cur_title, cur_body = line[4:].strip(), []
        elif cur_title is not None:
            cur_body.append(line)
    if cur_title:
        rows.append((chapter, cur_title, "\n".join(cur_body).strip()))
    return rows


def squeeze(body):
    """压掉多余空行，只保留有内容的行。"""
    lines = [ln.rstrip() for ln in body.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            blank = True
            continue
        if blank and out:
            out.append("")
        blank = False
        out.append(ln)
    return out


def used_rows(days=None):
    """读防撞表，返回 [(date, who, meme, where, result)]，只留近 days 天。"""
    if not os.path.exists(USED):
        return []
    rows = []
    today = dt.date.today()
    for line in read(USED).splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("日期",):
            continue
        try:
            d = dt.date.fromisoformat(cells[0])
        except ValueError:
            continue
        if days is not None and (today - d).days > days:
            continue
        rows.append((d, cells[1], cells[2], cells[3], cells[4]))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def fmt_used(rows, limit=10):
    out = []
    for d, who, meme, where, res in rows[:limit]:
        res = res if len(res) <= 24 else res[:24] + "…"
        out.append("  %s  %s  %s → %s | %s" % (d, who, meme, where, res))
    return out


def cmd_find(args):
    text = read(BANK)
    kws = [norm(k) for k in args.keywords if k.strip()]
    if not kws:
        sys.exit("给个关键词，例如：find 大肥鱼")
    hits = []
    for chapter, title, body in entries(text):
        hay = norm(title + "\n" + body)
        if any(k in hay for k in kws):
            hits.append((chapter, title, body))
    # 「语感底调」章不是条目，命中时整段带上（它本来就短）
    extra = []
    secs = sections(text)
    for name, body in secs.items():
        if "语感" in name and any(k in norm(body) for k in kws):
            extra = ["## " + name] + squeeze(body)

    budget = args.max_lines
    print("【命中 %d 条 / 全库 %d 条】关键词：%s"
          % (len(hits), len(entries(text)), " ".join(args.keywords)))
    if not hits and not extra:
        print("—— 没有这条梗。**不许现编**；要么换关键词（geng.py list 看目录），"
              "要么这次就不用梗。")
        return
    used = [r for r in used_rows(args.used_days)
            if any(k in norm(r[2] + r[3]) for k in kws)]
    for chapter, title, body in hits:
        block = ["", "### %s   〔%s〕" % (title, chapter)] + squeeze(body)
        if budget - len(block) < 0:
            print("\n（输出到上限 %d 行，剩下的没打印——换更准的关键词）" % args.max_lines)
            break
        budget -= len(block)
        print("\n".join(block))
    if extra:
        print("\n".join(extra))
    if used:
        print("\n⚠ 近 %d 天已有人用过（判撞）：" % args.used_days)
        print("\n".join(fmt_used(used, limit=5)))
    else:
        print("\n（近 %d 天没人用过这几条，可用）" % args.used_days)


def cmd_used(args):
    rows = used_rows(args.days)
    if not rows:
        print("近 %s 天没有登记（可用）。" % ("全部" if args.days is None else args.days))
        return
    print("【防撞表】近 %s 天 %d 条：" % (args.days if args.days else "全部", len(rows)))
    print("\n".join(fmt_used(rows, limit=args.max_lines)))


def cmd_list(args):
    rows = entries(read(BANK))
    print("【目录】%d 条（要看全文用 find <关键词>）" % len(rows))
    chapter = None
    for ch, title, body in rows:
        if ch != chapter:
            chapter = ch
            print("\n[%s]" % ch)
        gist = ""
        for key in ("笑点", "怎么用", "出处", "设定", "边界"):
            m = re.search(r"\*\*" + key + r"\*\*[:：]\s*(.+)", body)
            if m:
                gist = m.group(1).strip()
                break
        if not gist:  # 没有标签行的条目（如「同族」那张认脸清单）→ 取第一条有字的列表行
            for ln in body.splitlines():
                ln = ln.strip().lstrip("-· ").strip()
                if ln:
                    gist = ln
                    break
        gist = re.sub(r"[*`]", "", gist)
        if len(gist) > 60:
            gist = gist[:60] + "…"
        print("  · %s —— %s" % (title, gist))
    print("\n（想看语感底调：sed -n '/## 三、/,/## 四、/p' \"%s\"）" % BANK)


def cmd_check(args):
    bt, bl = os.path.getsize(BANK), len(read(BANK).splitlines())
    n = len(entries(read(BANK)))
    ut = os.path.getsize(USED) if os.path.exists(USED) else 0
    ul = len(read(USED).splitlines()) if os.path.exists(USED) else 0
    kb = bt / 1024.0
    if kb < 20:
        tier = "第一档：<20KB → 直接读全文也行；但发声前仍建议 find（顺手能查防撞）"
    elif kb < 60:
        tier = "第二档：20-60KB → 只用 find/used，禁止 read_file 全文"
    else:
        tier = "第三档：>60KB → 条目化 + INDEX 两步走（该动手拆文件了）"
    print("梗.md      %5.1f KB  %3d 行  %d 条" % (kb, bl, n))
    print("梗_已用.md %5.1f KB  %3d 行  %d 条登记" % (ut / 1024.0, ul, len(used_rows(None))))
    print("档位：" + tier)
    if bl and n:
        print("平均每条约 %.1f 行 / %.1f KB" % (bl / n, kb / n))


def cmd_add(args):
    """结构化追加一条（可选，手工改 md 也行；这个只是省手）。"""
    text = read(BANK)
    block = ["### " + args.title.strip()]
    for label, val in (("出处", args.source), ("笑点", args.punch), ("怎么用", args.use),
                       ("边界", args.bound), ("记", args.note)):
        if val:
            block.append("- **%s**：%s" % (label, val.strip()))
    block.append("")
    marker = "## 二、"
    idx = text.find(marker)
    if idx < 0:
        sys.exit("没找到「## 二、」章，别乱插——手工改 %s" % BANK)
    new = text[:idx].rstrip("\n") + "\n\n" + "\n".join(block) + "\n" + text[idx:]
    tmp = BANK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, BANK)
    print("已追加：%s（回读见下）" % args.title)
    cmd_find(argparse.Namespace(keywords=[args.title], max_lines=20,
                                used_days=args.used_days))


def main():
    ap = argparse.ArgumentParser(description="共享梗本检索入口（不读全文）")
    ap.add_argument("--max-lines", type=int, default=MAX_LINES_DEFAULT,
                    help="输出行数上限，默认 %d" % MAX_LINES_DEFAULT)
    ap.add_argument("--used-days", type=int, default=7, help="判撞回看天数，默认 7")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("find", help="按关键词检索条目 + 判撞")
    p.add_argument("keywords", nargs="+")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("used", help="只看防撞表")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=cmd_used)

    p = sub.add_parser("list", help="目录（标题 + 一句摘要）")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="体积体检 + 该用哪一档")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("add", help="结构化追加一条梗")
    p.add_argument("--title", required=True)
    p.add_argument("--source", default="", help="出处（不知道就别加：出处不明不许进）")
    p.add_argument("--punch", default="", help="笑点")
    p.add_argument("--use", default="", help="怎么用 / 能套的一句话")
    p.add_argument("--bound", default="", help="边界：什么场合别用")
    p.add_argument("--note", default="", help="记：谁在什么时候补的")
    p.set_defaults(func=cmd_add)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
