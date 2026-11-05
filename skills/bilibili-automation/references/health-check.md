# 运行状态体检（账号运营链自检）

用户说「查一遍」「有问题就汇报」时，按这个顺序一次走完，只把异常和待办报上去——健康项压成一张表，别逐条复述命令。全程只读，不抽帧、不发评论、不改配置。

## 一、先定坐标

```bash
date "+%Y-%m-%d %A %H:%M:%S %Z"    # 判窗口、判今天是哪一天（会话可能跨天）
```

## 二、任务链（零 token）

```bash
python3 ~/.hermes/skills/media/bilibili-automation/scripts/cron_health.py
```

读三样：

1. **每个 profile 活着几条**。一线运营那两个 profile 应该各有「心跳 + 补漏守卫 + 夜巡守卫 + 1-2 条夜巡候选点」；退役副手整批 `PAUSED` 是正常态，不拉起来。
2. **末行「候选点数」要减 1**——它按名字匹配「夜巡」，`夜巡守卫`（cron 表达式）也被算进去，所以显示 3 其实只有 2 个真候选点。
3. **候选点是不是都在未来、`Repeat` 没打满**。同名任务存在 ≠ 链正常。

再看今天的执行史（按 profile 各查自己那份库）：

```bash
sqlite3 ~/.hermes/cron/executions.db "select job_id,started_at,status,substr(coalesce(error,''),1,80) from executions where started_at >= '<今天>T00:00' order by started_at;"
sqlite3 ~/.hermes/profiles/<name>/cron/executions.db "<同上>"
```

近三天失败分布：

```bash
sqlite3 ~/.hermes/cron/executions.db "select date(started_at),count(*) from executions where status='failed' and started_at>='<三天前>' group by 1;"
```

**判据**：`RuntimeError: Operation interrupted: waiting for model response (N s elapsed)` 且 N 很大 ＝ 机器睡过去了，不是模型或任务坏了；`GatewayUnavailableError: Gateway draining` ＝ 当时在更新重启。两类都不需要改任务，用来说明「为什么有一趟缺」。真正要动手的只有一种：排过的点 > 实际执行数且守卫没补点。

## 三、登录态与额度

```bash
env BILI_HOME=~/.hermes/bili python3 ~/.hermes/scripts/bili_cli.py check --why "早间状态体检：验证登录态"
env BILI_HOME=~/.hermes/bili python3 ~/.hermes/scripts/bili_quota.py
env BILI_HOME=~/.hermes/profiles/<name>/bili python3 ~/.hermes/scripts/bili_quota.py
```

- `check` 必须打印**昵称 + 目标 mid**，只看 `✅` 会漏掉串号。
- 一律带 `env BILI_HOME=…` 前缀：持久 shell 里可能残留上一个 profile 的导出值，串号时脚本照样打勾。
- `quota` 的 `runs` 会把 `bvid="-"` 的元信息行也算一趟，趟数以 executions.db 的 completed 条数为准。

## 四、收信

```bash
cat ~/.hermes/bili/watch_last.txt; stat -f "%Sm" ~/.hermes/bili/watch_last.txt
```

`NO_NEW` + mtime 在几分钟内 = 心跳刚扫过、真有新信的话下个 tick 就会报。要连「那句 NO_NEW 是不是假的」一起排除（私信接口挂了也会回 NO_NEW），跑一次全扫：

```bash
env BILI_HOME=~/.hermes/bili python3 ~/.hermes/scripts/bili_watch.py 2>&1 | tail -12
```

看 `DM … from 某人` 行有没有列出来——列得出会话就证明 `session_svr` / `fetch_session_msgs` 通。**接口偶发 404 / 空列表只算「未知」，下趟复查**，别据此下「账号异常」或「私信全丢」的结论。想读正文（尤其那条 `SYSTEM 账号安全通知` 到底写了什么）用附带脚本：

```bash
env BILI_HOME=~/.hermes/bili python3 ~/.hermes/skills/media/bilibili-automation/scripts/dm_peek.py
env BILI_HOME=… python3 …/dm_peek.py --talker 844424930131964     # 只看系统通知那个会话
```

系统通知类会话（`uid` 844424930131964）的正文会写「设备/平台、登录方式、参考登录地、登录时间」——用户自己换端登录是正常的，只有地点/设备都对不上才需要报给他。

## 五、本机卫生

```bash
ps aux | grep "[h]ermes/browser-profile" | wc -l          # 必须 0，见 SKILL.md「二、登录态接管」末条
df -h / | tail -1
```

## 六、汇报格式

两段，别混：

1. **一张健康表**（登录态 / 今日额度与候选点 / 心跳与守卫 / 未处理消息 / 另一个 profile 的状态 / 磁盘）——每行一句结论，不贴命令输出。
2. **编号的问题清单**，每条标清性质：`✅已修（做了什么、副作用是什么）` / `⚠️复发模式（依赖哪个守卫自愈、会不会再犯）` / `📋我的待办（谁负责、什么时候交）`。已修的那条必须给出回读证据（进程数归零、用户 Chrome 进程数不变），不能只说「清理了」。

不要在汇报里罗列完整命令序列——用户要的是「有没有事」和「要不要他动手」。
