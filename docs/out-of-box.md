# 开箱即用设计 · Out-of-Box

> 目标：**只有 1-2 个 provider key 的用户，clone 下来就能跑一个有意义的功能子集；以后加新模型/新 key，不改代码不冲突。**

## 一、角色槽由你命名，能力是标签不是名字

系统只有四个**槽位概念**，每个槽叫什么完全由用户在 `config/roles.yaml` 里定（示范团队里叫小鲸鱼/大姐/军师，你叫什么都行）：

| 槽位概念 | 职责 | 必须吗 |
|---|---|---|
| 执行槽 | 跑夜巡/收信/发声，持账号 | 必须有一个 |
| 第二执行槽 | 另一个账号的执行层 | 可选 |
| 副手槽 | 选题/复盘/规划，`readonly: true` | 可选 |
| 栏目槽 | 今日诗一类的固定栏目写手 | 可选（可并入执行槽） |

**两条铁律**：

1. mission、脚本、协作文档里**只出现槽名，永不出现模型 id**。
2. 「有没有第二个账号」**不是能力**，是槽位上的 `account` 绑定 —— 那是组织决策（要不要姐妹），不是技术能力。能力只描述模型能干什么。

**能力标签**（由启动探测写入 `provider_probe.json`，驾驶舱可见）：

| 标签 | 探测方式 | True | False |
|---|---|---|---|
| `video_vision` | 发一小段测试视频 | videoread.py 整段读 | bili_shot.py 抽帧 + sheet（任何多模态模型都能走） |
| `image_vision` | 发一张测试图 | 抽帧流程可用 | 降级为只读文字信息 + 评论区，verdict 照写、诚实标注「未看片」 |
| `tool_use` | 小工具调用测试 | 完整任务链 | 纯 prompt 单步模式，守卫改由外部 shell 编排 |

探测 30 秒、缓存、结果对用户可见（「你的执行槽模型不支持视频，已走抽帧路径」）——**没有静默降级**。

## 二、渐进式分层（Tier）

每层都完整可用、可停在那：

```
Tier 0  一个 provider key（任意 OpenAI 兼容端点）
        ✅ 匿名只读夜巡：排行榜/搜索/热门（公开 API，无需 cookie）
        ✅ 抽帧看片、night_log、梗库、驾驶舱
        ❌ 一切站内写操作
        → 先当「内容雷达」用，零账号风险

Tier 1  + 一个 B站 cookie
        ✅ 单号全链路：收信心跳、配额账本、评论/动态、操作审计、注入防御

Tier 2  + 第二个 cookie（第二执行槽）
        ✅ 双号分层、海螺协作、姐妹群聊、防撞规则
        （一个 key 也能跑双执行变体——provider 是绑定不是消耗品）

Tier 3  + macOS 守护件（可选装配）
        ✅ 菜单栏放行门禁、launchd 保活；非 macOS 走 time_window 等价配置
```

每个 Tier 对应 mission 的增量段（`mission/mission.tiers.md`），启动时按探测结果装配。

## 三、加新模型为什么不冲突

1. Provider 注册进 `.env` + `providers.yaml`，**代码里没有模型 id**；
2. 槽位 → provider 是配置映射，支持 fallback 链：`provider: [main, backup]`，第一个不可用自动降级——加新 key = append 一行；
3. 能力探测与 provider 解耦：新模型接入先跑 probe，能力表更新，下游自动换路径，mission 零改动；
4. 硬编码清零：本仓库版本已整改（mid 走 `BILI_MID_SELF/OWNER`、看片模型走 `VIDEO_READ_MODELS`、API 走 `VIDEO_READ_API_URL`）。

## 四、第一次运行

```bash
cp .env.example .env            # 填 1 个 key
python3 setup.py probe          # 能力探测 → provider_probe.json + 推荐 Tier
python3 scripts/bili_search.py "关键词"   # Tier 0 即可体验
```

缺什么 setup 直接说缺什么，不静默降到诡异状态。解锁 Tier 1 = 填 `BILI_COOKIES_PATH`；玩双号 = 复制 `profiles/template-sister/` 再加一条槽。

## 五、随包防呆

- `.env.example` 全占位 + 每项注释对应哪个 Tier
- cookie 只给 schema 样例（假值）与格式说明，**不内置抓取工具**
- cron 投递默认 `deliver=local`（原部署实测 origin 会静默外泄到聊天软件）
- 账本、门禁、操作审计默认全开：开箱即安全，不是开箱即裸奔
