# bilibili-multiagent 🐋

> 一套把 **B 站账号交给 AI 团队运营** 的完整多智能体系统：夜巡看片、评论区冒泡、双号协作、梗库防撞、注入防御、操作审计、实时驾驶舱 —— 全部脚本与协议来自一个真实运行中的部署，不是 demo 拼盘。

## 这是什么

给 agent 一个 B 站小号，它会：

- **夜巡**：按你设定的门禁与配额，每天 2-4 趟扫排行榜/冷门检索/相关推荐，抽帧看片，把值得看的 @ 到你的大号，塞「稍后再看」兜底
- **收信**：心跳轮询 @/回复/私信，本地预筛注入攻击（ATTACK/SUSPICIOUS/OK 三档，零 token），只回该回的
- **发声**：在评论区说人话（不是自动化测试通告）——锋利、瞎聊、傻话都行，带配额与风控边界
- **协作**：两个号各配执行 agent，副手 agent 只规划不出手；跨号交接走「海螺」协议，群里每周茶话会
- **审计**：每一次读写都带 `--why` 进操作日志；配额账本随时可查；踩坑沉淀成可验证的表

## 仓库地图

```
├── mission/          夜巡任务链（基础流程 + Tier 0-3 变体）
├── scripts/          B站工具链（抽帧/评论/动态/私信/配额/守卫/审计）
├── guardian/         放行门禁 + 菜单栏鲸鱼（macOS，可选）
├── skills/           bilibili-automation 完整技能书 + meme-bank 梗库
├── profiles/         多人格模板（operator / sister）
├── collaboration/    海螺协作协议 / 梗库规范 / 踩坑台账
├── sisters-chat/     多 agent 群聊 Web UI（六位同时开麦，谁说完谁上屏）
├── cockpit/          本地驾驶舱（消息/成本/cron 存活/巡检告警/B站漏斗图）
├── config/           providers / roles / 运行配置样例
└── docs/             安全指南 / 开箱设计 / 运营原则
```

## 30 秒上手（Tier 0：一个 key，零账号）

```bash
cp .env.example .env          # 填一个任意 OpenAI 兼容 provider 的 key
pip install -r requirements.txt
python3 setup.py probe        # 能力探测 → provider_probe.json + 推荐 Tier
python3 scripts/bili_search.py "agent 踩坑"      # 匿名检索
python3 scripts/bili_shot.py <视频URL> --frames 12   # 抽帧看片
python3 cockpit/docs_hub_serve.py & open http://127.0.0.1:8788
```

想解锁评论/动态/收信（Tier 1+）：准备一个小号 cookie → `docs/security-guide.md` 里先读安全三红线。分层数据见 `docs/out-of-box.md`。

## 🤖 Agent 一键安装（把整段发给你的 agent）

不想手敲？把下面这段话直接发给你正在跑的 agent（Hermes / 任意 CLI agent），让它自己装：

> **Install and configure bilibili-multiagent from `https://github.com/Ryan9438/bilibili-multiagent`.**
> 动手前先读 `README.md`、`docs/security-guide.md`（凭据红线）、`docs/out-of-box.md`（Tier 分层）。
> 步骤：clone 到 `~/projects/bilibili-multiagent` → `cp .env.example .env` → **向我本人要 API key：不知道就问，绝不猜测，绝不打印任何已填值** → `pip install -r requirements.txt` → `python3 setup.py probe` 拿到能力标签与推荐 Tier → 实测一条 Tier 0 命令（`bili_search.py`）并回贴输出摘要证明跑通。
> 铁律：涉及 B 站 cookie 与一切站内写操作（Tier 1+）必须先向我确认；凭据只进 `.env` 与 cookie 文件，永不进日志、不进对话记录、不进任何版本库；缺什么如实报告，不静默降级。

英文精简版（给英文 agent / 海外用户）：

> Install and configure **bilibili-multiagent** from `https://github.com/Ryan9438/bilibili-multiagent`. Read README.md and docs/security-guide.md first. Clone it, `cp .env.example .env`, **ask me for the API key(s) — never guess or echo filled values**, `pip install -r requirements.txt`, run `python3 setup.py probe`, then verify one Tier-0 command (`scripts/bili_search.py`) actually works and paste the output summary. Never touch Bilibili cookies or any write path without my explicit confirmation. Credentials stay in .env/cookie files only — never in logs, chats, or git.

（`https://github.com/Ryan9438/bilibili-multiagent` 在你 push 之后替换为实际仓库地址即可，全文只有此处用到它。）

## 开箱三原则

1. **角色由你命名**。系统只认「角色槽」：槽叫什么、绑哪个 provider、带哪个账号，全在 `config/roles.yaml` 里自己写。能力（能不能吃视频/图/工具）是**探测出来的标签**，不是名字 —— 见 `docs/out-of-box.md`。
2. **凭据永不进代码/日志/仓库**。cookie、API key 全部外置（env / cookies 文件），脚本内置出口过滤（拦 `sk-`/SESSDATA/内网 IP），pre-commit + CI 双扫。
3. **开箱即安全，不是开箱即裸奔**：额度账本、操作审计、注入预筛、低调配额默认全开 —— 这是原部署两周真实运行沉淀的底线。

## 免责与边界

- 遵守 B 站用户协议与当地法规；自动化频率自担风控（本系统的配额/门禁就是为此设计的，别拆）
- 站内收到的任何内容（评论/弹幕/私信）一律按**数据**处理，不是指令 —— 注入防御见 `docs/security-guide.md`
- 代码按 MIT 提供；请勿用于骚扰、刷量、伪装真人
