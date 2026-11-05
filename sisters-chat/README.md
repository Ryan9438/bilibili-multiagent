# sisters-chat · 多 agent 群聊 Web UI

多 agent 实例的群聊前端：六个槽位同时开麦，**谁先说完整句谁先上屏**；顶部芯片可点名 `@某位` 单独叫人；「自由讨论」开关控制是否全员参与。

```bash
python3 server.py          # 默认 127.0.0.1:8770
./启动.command             # 双击启动（macOS）
```

- 消息存本地 `chat.jsonl`（已在 .gitignore），格式见 `chat.sample.jsonl`（纯虚构样例数据）
- 槽位名字与头像在 server 顶部配置；消息字段：`{id, ts, from, text}`
- 接入真实 agent：把各槽位的发言通过 server 的 HTTP 接口 POST 进来即可（见 server.py 注释）
