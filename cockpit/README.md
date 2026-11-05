# cockpit · 本地驾驶舱

纯本地实时仪表盘：今日消息 / token / B站读写 / cron 存活 / 累计成本 / 14 天曲线 / 夜巡漏斗（桑基图）/ 六人关系网 / 巡检告警（记忆用量、cookie 时效、备份未轮转、超额趟数）。

```bash
python3 docs_hub_serve.py    # http://127.0.0.1:8788
```

- 数据源：本地账本/日志/cron 记录聚合（见 docs_hub.py）；`DATA_ROOT` 等路径走环境变量，默认 `~/.hermes`
- 巡检阈值在脚本顶部可改；「LOCAL DATA」标签 = 不出本机、不上报
