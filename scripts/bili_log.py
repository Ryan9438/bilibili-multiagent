#!/usr/bin/env python3
"""bili_log.py — 把对 B站账号的每一次操作写进桌面日志，并标注发起原因。

日志位置：~/Desktop/B站账号操作日志.md（Markdown 表格，只追加）
凭据（cookie / apikey / token / SESSDATA）**绝不写入日志**。

作为库使用：

    from bili_log import log_op, why_from_argv

    WHY = why_from_argv()            # 摘掉 argv 里的 --why，取不到就回退环境变量 BILI_WHY
    log_op("写", "评论", "BV1xx (oid=1) rpid=123", why=WHY, result="✅ 已渲染")

原因优先级：命令行 `--why "..."` > 环境变量 `BILI_WHY` > 标记为「未标注原因」。
取不到原因不阻塞操作，但会在日志里打 ⚠️，方便事后追问。

单独用（手工补记一行）：
    python3 bili_log.py "读" "看稍后再看" "-" --why "主人想确认" --result "共 3 条"
"""
import datetime
import os
import sys

LOG_PATH = os.path.expanduser("~/Desktop/B站账号操作日志.md")

HEADER = """# B站账号操作日志

> 由 `~/.hermes/scripts/bili_log.py` 自动追加，**每次对账号的读/写操作都留一行，并写明发起原因**。
> 凭据（cookie / apikey / token）永不写入本文件。
> 时间均为本机时间（CST）。类型：读 = 只取数据，写 = 改变账号状态。

| 时间 | 类型 | 动作 | 对象 | 发起原因 | 结果 |
|---|---|---|---|---|---|
"""


def _cell(text):
    """把内容压成能塞进 Markdown 表格的一格。"""
    s = str(text if text is not None else "").strip()
    s = s.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return s if s else "-"


def _ensure_file():
    if not os.path.exists(LOG_PATH):
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(HEADER)


def why_from_argv(default=None):
    """从 sys.argv 里摘掉 --why "原因"，返回原因字符串（并把它从 argv 移除）。"""
    argv = sys.argv
    for i, a in enumerate(list(argv)):
        if a == "--why" and i + 1 < len(argv):
            val = argv[i + 1]
            del argv[i:i + 2]
            os.environ["BILI_WHY"] = val
            return val
        if a.startswith("--why="):
            val = a.split("=", 1)[1]
            del argv[i]
            os.environ["BILI_WHY"] = val
            return val
    return default or os.environ.get("BILI_WHY") or "⚠️ 未标注原因（脚本直调）"


def _account_label():
    """按 BILI_HOME 判断这份日志是哪个号的动作（两人共用一份日志）。"""
    home = str(os.environ.get("BILI_HOME", "~/.hermes/bili")).lower()
    return "小大姐" if ("minimax" in home or "glm" in home) else "小鲸鱼"


def log_op(kind, action, target, why=None, result=""):
    """追加一行操作记录。kind: 读 / 写。动作列带人格前缀，区分是哪个号。"""
    _ensure_file()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reason = why or os.environ.get("BILI_WHY") or "⚠️ 未标注原因（脚本直调）"
    line = "| {} | {} | [{}] {} | {} | {} | {} |\n".format(
        ts, _cell(kind), _account_label(), _cell(action), _cell(target), _cell(reason), _cell(result)
    )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    return line


if __name__ == "__main__":
    args = sys.argv[1:]
    res = ""
    if "--result" in args:
        k = args.index("--result")
        res = args[k + 1]
        del args[k:k + 2]
    why = why_from_argv()
    if len(args) < 3:
        sys.exit(__doc__)
    print(log_op(args[0], args[1], args[2], why=why, result=res).strip())
