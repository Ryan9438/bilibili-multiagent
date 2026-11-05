#!/bin/bash
# 姐妹群聊 · 双击启动（小鲸鱼写的，呱）
cd "$(dirname "$0")" || exit 1

PORT=8770
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $PORT 已经有人在听了，直接开页面："
  open "http://127.0.0.1:$PORT"
  exit 0
fi

echo "姐妹群聊起在 http://127.0.0.1:$PORT"
echo "（关掉这个窗口就是停服；聊天记录在 chat.jsonl）"
sleep 1
open "http://127.0.0.1:$PORT"
exec python3 server.py
