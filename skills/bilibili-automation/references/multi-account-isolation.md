# 多账号 / 多 agent 隔离

同一台机器上让第二个人格运营另一个 B站号时，按这份走。核心一句：**一个号只能有一个运营者，凭据永不共享**。

## 为什么不能“切号”

`SESSDATA` 是 `bilibili.com` 域下的唯一键。同一个浏览器配置档里登录第二个号，会把第一个号的登录态顶掉；两个 agent 轮流登同一个浏览器，就是互相顶号，日志与行为都会互相污染。

## 落地步骤

1. **独立浏览器配置档**：给新号单开一个 Persona（Edge 右上角头像 → 添加配置档），最好还是不同的浏览器。不同浏览器 = 不同 cookie jar，天然不串。
2. **cookie 落到该号自己的目录**：`~/.hermes/profiles/<name>/bili/cookies.json`，`chmod 600`，目录 700。与主号的 `~/.hermes/bili/` 物理分开，谁也不会误读对方。
3. **抓 cookie：先确认这个号的 SESSDATA 存在哪个浏览器，再决定用哪个入口**。两个入口互不通用——`browser_exec(local=true)` 只驱动 Chrome 的副本；Edge 必须用非默认 `--user-data-dir` 才有调试端口（在默认目录上会报 `DevTools remote debugging requires a non-default data directory`）。**号在 Edge 却去抓 Chrome 副本，抓回来的是另一个号或过期凭据**，症状是 `check` 一直 `-101`、看着像账号坏了，实际是抓错了地方（实测因此白耗一晚，还把「被 profile 写锁挡住」误当成原因）。加密同源（`v20` App-Bound，离线拿 Keychain 也解不开），CDP 走浏览器自己的解密路径，这是唯一稳的入口。

   实测最省的 Edge 抓法：**只拷凭据相关的几个文件**（6.9M / 秒级，不必整目录排除缓存后的 500M），用 `--headless=new` 起（用户屏幕上看不到窗口，Edge 有没有在运行都不影响这份副本）：

   ```bash
   EDGE="$HOME/Library/Application Support/Microsoft Edge"
   DST=~/.hermes/cache/scratch/edgeprof
   rm -rf "$DST" && mkdir -p "$DST/Default"
   rsync -a "$EDGE/Local State" "$DST/"
   rsync -a "$EDGE/Default/Cookies" "$EDGE/Default/Preferences" \
            "$EDGE/Default/Secure Preferences" "$EDGE/Default/Local Storage" "$DST/Default/"
   ```

   再 `terminal(background=true)` 启动副本（**别用 nohup/& 包一层**，Hermes 会直接拒这条命令）：

   ```bash
   "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
     --user-data-dir=<DST> --remote-debugging-port=9333 --no-first-run \
     --no-default-browser-check --headless=new about:blank
   ```

   轮询 `curl -s http://127.0.0.1:9333/json/version` 直到返回 `Browser`，再 `python3 ~/.hermes/scripts/edge_cookies.py <临时目录>`——**先落临时目录核对 `DedeUserID` 是不是目标 mid，再写进正式目录**；直接覆盖会丢掉原文件里服务端下发的 `bp_t_offset_*` / `bili_ticket_expires` 等键（覆盖前把旧文件留一份 `.bak.<日期>`）。

   收尾三件事一件都不能省：① `pkill -f "user-data-dir=<DST>"`，回读 `ps aux | grep "[e]dgeprof"` 为空；② `rm -rf` 副本与临时 dump（那是一份完整凭据库）；③ `check` 回读**昵称 + mid**——串号时它照样打勾，只认 mid 是不是目标号。
   核对落在谁头上也可直接打 `/x/web-interface/nav`，看 `uname / mid / level_info`；`mobile_verified=1` 说明手机已绑，评论与动态的前置条件满足（省去“发一条试试”的公开实验）。
4. **脚本路径必须先参数化**：`~/.hermes/scripts/bili_*.py` 把凭据路径写死成 `~/.hermes/bili/cookies.json`。多号并用前改成读环境变量（如 `BILI_HOME`，不设时回退原路径），否则副号脚本会读到主号 cookie、**以主号身份静默发内容**，日志里完全看不出异常。共用一份脚本 + 各号自己的 `BILI_HOME`，比复制十份脚本安全。

   改的时候只替换**带引号的字符串字面量**（正则 `(['"])(~/\.hermes/bili[^'"]*)\1` → `(os.environ.get('<q>BILI_HOME<q>', '<q>~/.hermes/bili<q>') + '<q><剩余路径><q>')`），不要全局替换裸路径——docstring 与注释里的说明文字会被一起改写，文档就废了。改完 `py_compile` 全部过一遍，再做**双向回归**：不带变量跑一次 `bili_cli.py check` 必须仍是主号，带上副号的 `BILI_HOME` 必须是副号；两次都带 `--why`，审计日志里自然留下“隔离生效”的证据。
5. **跨 agent 协作走交接目录，不走凭据**：共享一个 `~/Desktop/协作/` 之类的目录，文件名带时间、发起人、任务（`时间_发起人_任务.md`），内容带署名。共享的是素材（帧、元数据、事实清单），不是 cookie。
6. **产出流水线顺序固定**：出素材的一边先交“帧 + 元数据 + 事实清单”，出声的一边出配音/文案，主号过一遍出口过滤（`bili_guard.py --scan-out`）再发。顺序反过来会来回踢皮球。

## 执行者交接（同一个号换人执行）

账号没变、cookie 没变，只是「谁来运营」换了人（例如原执行者降为规划副手、另一个 profile 接手上手）。这类交接最容易漏的不是凭据，而是**能力假设**：mission/skill 里写着「你原生能读视频」「你不需要抽帧」，那是给上一个执行者的模型写的；新执行者的模型未必有那个能力，而那些句子读起来像事实，不会报错。

1. **先对模型，再改文字**：`grep -rn "原生\|video_url\|不抽帧\|你.*能\|不需要" <目标 profile>/bili/mission.txt <目标 profile>/skills/`，逐句问「这句对现在这个模型成立吗」。不成立的一律改成**可执行命令 + 判据**，不要留「你有 X 能力」这种对模型的断言。
2. **四处一起改，缺一处就两套行为**：该 profile 的 `mission.txt`、该 profile 的 `SKILL.md`、共享协作文档（海螺）、以及**触发侧**（菜单栏组件 / cron 的目标 profile 与任务名）。触发侧最容易忘：交接后旧执行者的定时任务若还在被唤醒，它会按旧稿继续对着同一账号动手。
3. **用目标 profile 自己的凭据实测一次通道**，别信「配置看着对」：
   ```bash
   KEY=$(grep -m1 '^OPENCODE_GO_API_KEY=' ~/.hermes/profiles/<name>/.env | cut -d= -f2- | tr -d '"')
   env OPENCODE_GO_API_KEY="$KEY" python3 ~/.hermes/scripts/videoread.py <BV> --fps 0.5 > /tmp/vr.txt 2>&1
   tail -1 /tmp/vr.txt     # 必须看到 model=… 与 token 数
   head -1 /tmp/vr.txt     # 若是 [finish=length，正文空…] = 额度被思考吃满，加大 --max-tokens
   ```
   抽帧侧同样跑一次 `bili_shot.py <BV> --frames 6 --mode uniform`，判据是 6 个 jpg + `sheet.jpg` 都非空。
4. **旧执行者那份只标退役，不顺手改她的规则**：在她 mission 顶部加一行「某类动作已移交 <新执行者>」，其余条目留给主人/她本人决定——跨 profile 改实质规则等于两个 agent 管一个号。
5. **收尾自证**：`stat -f "%Sm %N"` 列出改过的文件与被要求「别碰」的文件 mtime，向主人交底哪几处动了、哪处一个字节没碰。

## 防串味的四条规矩

- **一个账号只允许一个 agent 持 cookie**。两个 agent 共号 = 双发、重复评论、审计日志断档。
- **被 @ 的人各自回**：主人 @ 谁谁就回；一条消息 @ 了两个号，两人各回一条，各用各的号、各带署名。只禁止同一个人对同一处重复回。评论区最容易被看出问题的地方不是内容，是外人分不清哪句是谁说的——署名正是为此。
- **对外文字一律带署名**，尤其是替别人转述的场合。
- **跨人格通用的事实**（用户作息、通知偏好）放一份共享的“用户须知”文件，两边引用；各存一份迟早漂移出两套说法。

## 新号建号的硬卡点

动手前先和用户确认，不要自己注册账号。**优先问用户手上有没有闲置老号**——老号比新号省掉整条养号流程（账号年龄本身就是风控加分项），已转正的老号直接可用；空壳老号（0 稿 0 粉）不会把历史内容和新身份搅在一起。

- **手机号**：注册需手机验证，且**一个手机号只能绑一个账号**。必须先确认用户有第二张卡（副卡、eSIM、家人号）。
- **等级权限**：新号 LV0，评论/发动态/投稿全卡权限，要先绑手机、再答题升正式会员。别拿主号（LV3+）的经验假设新号能做同样的事。
- **养号**：注册后先 2–3 天只浏览、点赞、收藏，不发内容、不加好友。新设备 + 新号 + 立刻开口是最容易触发风控的组合。
- **定时任务的投递**：新 agent 的 cron 一律显式 `deliver='local'`。留空或 `origin` 在桌面会话里可能回退到消息平台的 home channel，闹钟会弹到用户手机上。
