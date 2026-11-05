# B站 API 速查

公共请求头：

```
Cookie: SESSDATA=...; bili_jct=...; DedeUserID=...; buvid3=...
User-Agent: <桌面 Chrome UA>
Referer: https://www.bilibili.com/
```

写操作（POST）必须带 `csrf=<bili_jct 的值>`，它是 URL 参数或表单字段，不是 header。

## 匿名可访问（无需 cookie）

| 用途 | 端点 | 关键参数 |
|---|---|---|
| 综合热门 | `GET api.bilibili.com/x/web-interface/popular` | `ps` 条数，`pn` 页码 |
| 排行榜 | `GET api.bilibili.com/x/web-interface/ranking/v2` | `rid=0` 全站，`type=all` |
| 视频详情 | `GET api.bilibili.com/x/web-interface/view` | `bvid=BV...` 或 `aid=` |

**带 wbi 签名的接口（用户空间投稿、搜索）优先交给 yt-dlp** —— `yt-dlp -J <url>` 已实现签名逻辑，比手写 wbi 稳得多。抽帧脚本就是这么取元信息的。

## 需登录态

| 用途 | 端点 | 方式 |
|---|---|---|
| 身份校验 | `/x/web-interface/nav` | GET，返回 `isLogin/uname/mid/level_info/money` |
| 稍后再看：列表 | `/x/v2/history/toview` | GET，`data.count` / `data.list[]` |
| 稍后再看：加 | `/x/v2/history/toview/add` | POST，`bvid=` 或 `aid=`，+ `csrf` |
| 稍后再看：删 | `/x/v2/history/toview/del` | POST，`aid=`，+ `csrf` |
| 稍后再看：清空 | `/x/v2/history/toview/clear` | POST，+ `csrf` |
| 发复杂动态 | `/x/dynamic/feed/create/dyn` | POST JSON（`dyn_req`，`scene`=1 纯文本/2 带图） |
| 发纯文本动态 | `api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/create` | 表单，`dynamic_id=0&type=4&rid=0&content=...` |
| 发图（动态配图） | `/x/dynamic/feed/draw/upload_bfs` | multipart，`file_up`，先传图拿 `img_src` |
| 私信 | `api.vc.bilibili.com/web_im/v1/web_im/send_msg` | 表单，`msg[sender_uid]` `msg[receiver_id]` `msg[msg_type]=1` `msg[content]={"content":"..."}` |
| 发表评论 | `/x/v2/reply/add` | POST 表单，`oid=aid` `type=1` `message` `plat=1` `csrf`（可选 `at_name_to_mid`） |
| 评论列表（**已弃用**） | `/x/v2/reply` | GET，`oid` `type=1` `sort=0` `pn` `ps`；顶层常返回 `code=0` + 0 条，别据此判断「评论区戒严」 |
| 评论列表（现行） | `/x/v2/reply/wbi/main` | GET + WBI 签名；`oid` `type=1` `mode=3`(最新) `pagination_str={"offset":""}` `plat=1` `web_location=1315875`；总数看 `data.cursor.all_count` |
| 删除评论 | `/x/v2/reply/del` | POST 表单，`oid` `type=1` `rpid` `csrf` |
| 搜用户 | `/x/web-interface/search/type` | GET，`search_type=bili_user&keyword=`，返回 `data.result[].mid/uname/fans` |
| 收信：@我的 | `/x/msgfeed/at` | GET，`platform=web&build=0&mobi_app=web&pn=1&ps=20`，Referer 要 `https://message.bilibili.com/` |
| 收信：回复我的 | `/x/msgfeed/reply` | 同上。字段：`item.subject_id`=aid、`item.root_id`=根评论、`item.source_id`=对方评论rpid |
| 回复子评论 | `/x/v2/reply/add` | 多传 `root=<根评论rpid>&parent=<对方rpid>` |
| 查子回复 | `/x/v2/reply/reply` | GET，`oid&type=1&root=<根rpid>&pn=1&ps=20`（子回复不在顶层列表里，必须用这个验证） |

## 投稿（视频上传）

全部走 `member.bilibili.com`，Referer 用 `https://member.bilibili.com/platform/upload/video/frame`（取端点的接口用 `www.bilibili.com`）。§cookie 同主站，csrf 仍是 `bili_jct`。

| 步骤 | 端点 | 方式 |
|---|---|---|
| 已有稿件 | `GET member.bilibili.com/x/web/archives?status=is_pubing,pubed,not_pubed&pn=1&ps=5&coop=1&interactive=1` | 能读到（哪怕 0 条）就是 UP 视角 |
| 取上传子 | `GET member.bilibili.com/preupload?name=<f>&size=<bytes>&r=upos&profile=ugcfx%2Fbup&ssl=0&version=2.14.0&build=2140000&platform=pc` | 回 `OK:1` + `endpoint/upos_uri/auth/biz_id/chunk_size(10MB)/threads(3)` |
| 传分片 | `PUT https://{endpoint}/{upos_uri 去 "upos://"}?partNumber=N&chunk=I&chunks=T&size=&start=&end=&total=` | 头 `X-Upos-Auth: <auth>`，成功回文本 `PUT_OK` |
| 合并（upos） | `POST ...?output=json&name=<f>&profile=ugcfx%2Fbup` | 分片全部 PUT_OK 后调用，回 cid |
| 提交稿件 | `POST member.bilibili.com/x/vu/web/add/v3?t=<ts>` | form + `csrf`，`title/tid/desc/tag/copyright/videos([{filename,cid,title}])` |

**不是 S3 协议**：`?uploads&output=json` 做 init 会回 `400 {"code":"InvalidArgument","ec":400001001}`；那只是协议不匹配，不代表账号没权限。

**资质不可预查**：`/x/web/realname/status` 与实际路径不符（404），`/nav` 也不返实名字段；实名认证卡点在 `add/v3` 真正提交时，探不探得到别人说不了。`rank="正式会员"` 是能看到的最低门槛。

**权限 vs 参数要分清**：`add/v3` 故意传非法参数会回 `21001 参数错误`——这证明请求已经穿过权限层、到了参数校验（否则会回上未实名/无权限码）。21001 ≠ 没资格。

## 错误码

| code | 含义 | 处置 |
|---|---|---|
| `0` | 成功 | — |
| `-101` | 账号未登录 | cookie 过期或未带 |
| `-111` | csrf 校验失败 | `csrf` 必须是 `bili_jct` 的值 |
| `-352` | 风控校验失败 | 请求过频 / 缺 buvid3 / UA 不对，降频或补 cookie |
| `4126021` | 没有绑定手机，无法发布动态 | 必须先绑手机 |
| `21001` | 参数错误（投稿 add/v3） | 参数不全；能回这个说明权限层已过 |
| `400001004` / `InvalidArgument` | upos 分片参数/协议不对 | 用 `?partNumber=&chunk=&chunks=&size=&start=&end=&total=` 直接 PUT，别走 S3 init |

## 已知延迟与陷阱

- **`toview/add` 有缓存**：`code=0` 立刻查列表可能仍是旧的，等约 3s 再查。别把缓存延迟误判成风控失败。
- **发评论必须带 WBI 签名 + 全量 cookie**（实测 2026-10）：只带 SESSDATA/bili_jct/buvid3 等 5 个 cookie、URL 不带 `w_rid`/`wts` 时，`/x/v2/reply/add` 照样返回 `code=0` 并给出 `rpid`，但评论会**静默进审核池、永不渲染**（登录态、匿名态、页面源码三处都查不到，等 25 秒也无）。补上 WBI 签名（mixin_key 由 nav 的 `wbi_img.img_url/sub_url` 拼出，按 MIXIN_TAB 重排取前 32 位，`md5(query+mixin)`）+ **全部 33 个 cookie**（缺 `b_lsid`/`buvid_fp`/`_uuid` 等指纹字段会被当可疑请求），评论 5 秒内正常渲染、真 @ 生效。`bili_cli.py` 已内置。
- 因此：**接口返回 code=0 ≠ 评论已发布**。发完必须回读（`comments <bvid> 20` 或看 CLI 打的「已渲染」）才能算成功；看到「⚠️ 疑似进审核池」就作罢，绝不重发。
- 回读评论只能看到「已渲染」的评论 —— 看不到自己刚发的那条，先怀疑审核，而不是接口写错了。
- **`state` 字段是判断评论生死的正解**：`0` 正常 / `11` 阿瓦隆审核中（可能转正常、转 17 或被删）/ `17` 阿瓦隆「仅自己可见」——**对作者本人照常返回，对外隐藏**。所以带自己 cookie 回读永远「看得见」，必须**无 cookie 匿名**查一遍 `/x/v2/reply/reply?...&root=` 才作数；`bili_cli.py comment` 的 `verify_comment()` 已按此实现（匿名可见 + `state` 一起报）。
- **`/x/msgfeed/reply` 的 `root_id` / `target_id` 语义**：别人回复你的一级评论时 `root_id == target_id ==` 你的根评论 rpid；回复你的子评论时 `target_id ==` 你那条子评论 rpid，`root_id` 才是楼顶。用它反推「什么请求会通知谁」，比猜 `@` 靠谱。
- **通知是否送达与评论是否在线是两件事**：消息设置（消息中心 → 设置 →「回复我的」「@我的」：所有人 / 关注的人 / 不接受任何消息）会整层拦掉提醒。对方说没收到时先确认这一项，再怀疑代码。
- **评论 @ 的正确参数**（参数对，但能否过审是另一回事）：`at_name_to_mid` 传 JSON 字符串 `{"主人Demo号":"1110000000000002"}`，同时 `message` 正文里要带 `@用户名 `，两者缺一不可。回读验证：拉 `/x/v2/reply?sort=0`，看自己那条的 `content.members[]` 里有没有目标 `mid` —— 有就是真 @（会触发通知），没有就是死文本。
- **动态 @ 人**要同时给 `at_uids=<逗号分隔 uid>` 和 `ctrl=[{"location":起,"length":长,"type":1,"data":uid}]` 富文本结构，只写 "@名字" 文本不会变成真 @。可靠度也不如私信（易被折叠）。
- **新号/小号**发动态、评论易触发人机验证；读操作和「稍后再看」相对安全。
- B站**一个手机号只能绑一个账号**，用户名会被手机号占位。
