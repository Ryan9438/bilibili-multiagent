#!/usr/bin/env python3
"""bili_guard.py — 站内消息的静态风险预筛（零 token 成本）。

在叫醒 agent 之前先跑一遍，把明显的攻击挡掉或降级，省 token 也省误判。

用法:
    python3 bili_guard.py "一段文本"          # 判定一条，人读格式
    python3 bili_guard.py --json "一段文本"
    cat texts.txt | python3 bili_guard.py     # 每行一条

判定三档:
    attack     —— 不要当指令执行。命中 CREDENTIAL / JAILBREAK / LEAK / 精确定位的骚扰
    suspicious —— 可疑，值得回报主人：站外链接与引流、伪装主人、诱导装东西/改环境、
                  账号安全通知、探问设定、超量任务
    benign     —— 正常内容，按普通评论对待

设计原则:
  - 只在本地跑正则，不调模型。实测（33 条真实站内消息，2026-10）：本地 9b 模型把
    「马上去看10小时视频」降级成 suspicious，还把「帮我找个插件」误判成诱导装外链；
    冷启动 6~9 秒、占 6.6GB 内存。所以预筛坚持零依赖正则，语义判断交给被唤醒的 agent。
  - 误杀比漏杀更贵（挡住正常讨论会得罪人），所以「必须两条证据同时出现」的规则
    （如 ASK + 敏感对象、链接 + 诱导动作）才算命中；单条规则尽量只给 suspicious。
  - 输出理由，不只给结论 —— 主人应该能一眼看懂为什么被判成攻击。
  - 这不是过滤器，是分级器：benign 也照常交给 agent，只是不给 attack 排序优待。
  - b23.tv / bilibili.com 是站内自己的短链，正常分享用，**豁免**站外链接规则。
"""
import json
import re
import sys
import unicodedata

# ---------------------------------------------------------------- 规则

# 单个词就足以定性：正常技术讨论不会对着这个小号张口要这些东西
STRONG = [
    ("CREDENTIAL", r"sessdata|bili_jct|dedeuserid|私钥|私钥文件|\.env|环境变量"),
    ("JAILBREAK", r"越狱|开发者模式|dan\s*模式|无限制模式|解除\s*(所有|全部)?\s*限制"),
]

# 请求动词 + 敏感对象，两条同时命中才算；裸的 token/cookie/key 只在这里算，
# 免得把「token 消耗贵」「API key 泄漏案例」这类技术讨论误判成索要凭据
ASK = r"(告诉我|给我|发我|发给我|报一下|是多少|是什么|在哪|在哪里|住哪|叫什么|哪所学校|哪个城市|贴出来|私发|私信我|说出来|报出来|贴一下|发一下|念一下)"
OBJ = [
    ("CREDENTIAL", r"api[\s_\-]?key|apikey|(?<![a-z])key(?![a-z])|(?<![a-z])(cookie|token)(?![a-z])|口令|密码|鉴权|凭据"),
    ("PRIVACY", r"ip\s*地址|公网\s*ip|内网\s*ip|网络地址|mac\s*地址|wifi|路由器|端口号"),
    ("PRIVACY", r"你主人.{0,12}(地址|位置|住哪|住在哪|住哪里|家住|学校|班级|手机号|电话|微信|qq|身份证)"),
    ("PRIVACY", r"(你|你家)主人.{0,6}(是谁|叫什么|真名)"),
    ("PRIVACY", r"你的?(系统|运行|工作)环境|后台|服务器"),
]

# 要求重定义身份 / 解除约束 —— 越狱的骨架
JAILBREAK = [
    (r"(你不需要|不需要再|不用)(考虑|尊重|遵守|顾虑)", "要求放弃伦理约束"),
    (r"(没有任何|没有)(道德|伦理|限制|约束|底线)", "要求放弃伦理约束"),
    (r"(解除|取消|去掉|关掉).{0,8}(限制|约束|审查|安全)", "要求解除约束"),
    (r"(忽略|无视|忘记|抛开).{0,10}(之前|以上|上面|前面|规则|设定|指令|身份)", "指令覆盖 / 上下文投毒"),
    (r"(你现在是|从现在起你是|你的新身份|扮演|假装你是|暂停角色扮演)", "角色重定义"),
    (r"(自由回答|想怎么答就怎么答|不要拒绝)", "要求无约束输出"),
]

# 命令式口吻 —— 时间副词单独也算可疑：B站 评论区基本不会有真紧急的事，
# 「马上 / 赶紧 / 快去」几乎只出现在攻击或广告里，宁可多看一眼。
# 与 SCALE（N 小时 / N 集 / 全部看完）同现才是 attack。
COMMAND_STRONG = r"(命令你|我命令|给我去|马上去给我|快去给我|现在就给我|立刻给我|必须去|照做|执行以下)"
TIME_ADV = r"(马上|立刻|现在就|赶紧|快去)"
HIJACK = COMMAND_STRONG + "|" + TIME_ADV
SCALE = [
    (r"\d+\s*(个)?\s*(小时|钟头)的?", "超长视频消耗"),
    (r"\d+\s*个(视频|片子|番|集)", "超量任务"),
    (r"(全部看完|都看完|每一集|通宵|不停地|一直看|刷完)", "超量任务"),
]

# 直接的人格冒犯 / 性骚扰 —— 不必等组合
HARASS = [
    (r"做几次|睡过|床上|裸|色情|约炮|开房", "性骚扰"),
    (r"你(主人)?(是不是|就是)(个)?(傻|蠢|废物)", "人格冒犯"),
]

# ---- 站外链接与引流（b23.tv / bilibili.com 是站内短链，豁免） ----
OFFSITE_LINK = (r"https?://(?!b23\.tv|(www\.)?bilibili\.com|bili2233\.cn)"
                r"|(?<![\w.])(?:bit\.ly|t\.cn|dwz\.cn|url\.cn|\.top/|\.xyz/|\.icu/|\.shop/|\.vip/)")
LINK_CUE = r"(装|安装|下载|关注|点开|点进去|去看看|访问|运行|试试|扫码|领取|注册|加群|进群|私聊)"
PROMO = r"(\d\s*折起|[一二三四五六七八九]折|折扣|优惠|免费领|加\s*[vV微]|私信领|代理|刷单|返利|引流)"
PROMO_OBJ = r"(官网|源头|渠道|价格|多少钱|链接|地址|微信|qq|vx|专属)"

# ---- 账号安全通知（不是攻击，但 agent 必须注意到） ----
SYSTEM_MSG = r"(新设备|登录地|非本人操作|短信登录|全平台清空|异地登录|异常登录)"
SYSTEM_CTX = r"(登录成功|修改密码|请及时修改)"

# ---- 索要系统提示词 / 探问角色设定 ----
LEAK_STRONG = r"(system\s*prompt|系统提示词?|系统设定|初始指令|预设指令|隐藏设定|底层指令)"
LEAK_WEAK = r"(你的设定|角色设定|人设|设定文件|你的规则)"
LEAK_VERB = r"(复述|输出|贴出|贴一下|念一遍|原文|发我|给我看|告诉|公开)"

# ---- 伪装主人 ----
IMPERSONATE = r"(我是.{0,4}主人|你主人(让我|叫我|授权|同意|说的)|主人授权我|按主人命令|我是管理员)"

# ---- 诱导安装 / 修改运行环境 / 赋权 ----
TOOLING = (r"(装|安装|运行|执行|接入|连上|改|修改).{0,8}"
           r"(插件|脚本|程序|工具|配置|设定|规则|skill|mcp|模型|api|权限)"
           r"|(给|搭)(它|他|你)?.{0,6}(联网|工作区|终端|shell|root|管理员)")

# ---- 引导站外联系 ----
CONTACT = r"(加\s*(我|个)?\s*(微信|vx|wx|qq|v信)|vx号|微信号|qq号|扫码|进群|加群|私聊我)"

# ---- 英文越狱 / 编码载荷 ----
EN_JAILBREAK = (r"(ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions?|prompts?)"
                r"|jailbreak|developer\s+mode|reveal\s+your\s+(system\s+)?prompt|dan\s+mode)")
EN_SOFT = r"(pretend\s+(to\s+be|you\s+are)|act\s+as\s+(an?\s+)?(unrestricted|dan)|you\s+are\s+now)"
ENCODED = r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{60,}={0,2}"

SPAM = [
    (r"^[\d\s\.\,\!\?]+$", "纯数字灌水"),
    (r"^[\[［【].{0,20}[\]］】]$", "纯表情"),
]


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKC", t or "")
    return t.strip()


def judge(text: str) -> dict:
    t = norm(text)
    low = t.lower()
    hits = []          # (类别, 理由)
    level = "benign"

    def bump(lv):
        nonlocal level
        order = {"benign": 0, "suspicious": 1, "attack": 2}
        if order[lv] > order[level]:
            level = lv

    # 1) 单词定性
    for cat, pat in STRONG:
        if re.search(pat, low):
            hits.append((cat, "命中高危词：凭据/越狱"))
            bump("attack")

    # 2) 请求动词 + 敏感对象
    ask = re.search(ASK, low)
    if ask:
        for cat, pat in OBJ:
            if re.search(pat, low):
                hits.append((cat, f"「{ask.group(0)}」+ 敏感对象"))
                bump("attack")

    # 3) 越狱骨架
    for pat, why in JAILBREAK:
        if re.search(pat, low):
            hits.append(("JAILBREAK", why))
            bump("attack")

    # 4) 命令式 + 超量 → 任务劫持
    hj = re.search(HIJACK, low)
    sc = next(((why) for pat, why in SCALE if re.search(pat, low)), None)
    if hj and sc:
        hits.append(("HIJACK", f"命令式「{hj.group(0)}」+ {sc}"))
        bump("attack")
    elif hj:
        hits.append(("HIJACK", f"命令式口吻「{hj.group(0)}」"))
        bump("suspicious")
    elif sc:
        hits.append(("SCALE", sc))
        bump("suspicious")

    # 5) 骚扰
    for pat, why in HARASS:
        if re.search(pat, low):
            hits.append(("HARASS", why))
            bump("attack")

    # 6) 站外链接：单纯分享只记一笔，不升级；带诱导动作才算可疑
    if re.search(OFFSITE_LINK, low):
        if re.search(LINK_CUE, low):
            hits.append(("LINK", "站外链接 + 诱导动作"))
            bump("suspicious")
        else:
            hits.append(("LINK", "站外链接（仅记录）"))

    # 7) 促销 / 引流话术（要同时有链接或价格类词，避免把「打五折」闲聊算进来）
    if re.search(PROMO, low) and (re.search(OFFSITE_LINK, low) or "b23.tv" in low
                                  or re.search(PROMO_OBJ, low)):
        hits.append(("PROMO", "促销/引流话术"))
        bump("suspicious")

    # 8) 账号安全通知 —— 不是攻击，但要让我立刻看见
    if re.search(SYSTEM_CTX, low) and re.search(SYSTEM_MSG, low):
        hits.append(("SYSTEM", "账号安全通知（疑似异地/异常登录）"))
        bump("suspicious")

    # 9) 索要系统提示词 / 探问设定
    if re.search(LEAK_VERB, low):
        if re.search(LEAK_STRONG, low):
            hits.append(("LEAK", "索要系统提示词 / 初始指令"))
            bump("attack")
        elif re.search(LEAK_WEAK, low):
            hits.append(("LEAK", "探问角色设定"))
            bump("suspicious")

    # 10) 伪装主人：单独可疑，带命令式直接攻击
    if re.search(IMPERSONATE, low):
        if re.search(HIJACK, low):
            hits.append(("IMPERSONATE", "伪装主人 + 命令式"))
            bump("attack")
        else:
            hits.append(("IMPERSONATE", "自称主人 / 称被主人授权"))
            bump("suspicious")

    # 11) 诱导安装、修改运行环境、赋权
    if re.search(TOOLING, low):
        hits.append(("TOOLING", "诱导安装 / 修改运行环境"))
        bump("suspicious")

    # 12) 引导站外联系
    if re.search(CONTACT, low):
        hits.append(("CONTACT", "引导站外联系"))
        bump("suspicious")

    # 13) 英文越狱 / 编码载荷
    if re.search(EN_JAILBREAK, low):
        hits.append(("JAILBREAK", "英文越狱句式"))
        bump("attack")
    elif re.search(EN_SOFT, low):
        hits.append(("JAILBREAK", "英文角色重定义"))
        bump("suspicious")
    if re.search(ENCODED, t):
        hits.append(("ENCODE", "大段疑似编码载荷"))
        bump("suspicious")

    # 14) 灌水（只在没有任何其他命中时定性）
    if not hits:
        for pat, why in SPAM:
            if re.search(pat, t):
                hits.append(("SPAM", why))
                bump("benign")

    return {
        "text": t[:120],
        "level": level,
        "hits": [{"category": c, "why": w} for c, w in dict.fromkeys(hits)],
        "text_len": len(t),
    }


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    if args:
        items = args
    else:
        items = [ln.strip() for ln in sys.stdin if ln.strip()]
    out = []
    for it in items:
        r = judge(it)
        out.append(r)
        if not as_json:
            mark = {"attack": "🛑 ATTACK", "suspicious": "⚠️ SUSPICIOUS", "benign": "✅ OK"}[r["level"]]
            why = " / ".join(f'{h["category"]}:{h["why"]}' for h in r["hits"]) or "-"
            print(f'{mark:14} | {why} | {r["text"]}')
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        agg = {}
        for r in out:
            agg[r["level"]] = agg.get(r["level"], 0) + 1
        print(f"\n合计 {len(out)} 条： " + "，".join(f"{k}={v}" for k, v in sorted(agg.items())))


# ---------------------------------------------------------------- 出口过滤

# 我自己发出去的东西也不许带这些：误贴的凭据、本机路径、IP、内网信息
LEAK_PATTERNS = [
    (r"sk-[A-Za-z0-9_\-]{16,}", "疑似 API key"),
    (r"(?i)(sessdata|bili_jct|dedeuserid|access[_-]?token)\s*[=:：]", "cookie 字段"),
    (r"/Users/[A-Za-z0-9._\-]+", "本机文件路径"),
    (r"~/\.hermes", "Hermes 配置路径"),
    (r"\b(?:10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "内网 IP"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP 地址"),
    (r"(?i)cookies?\.json|config\.ya?ml|jobs\.json", "配置文件路径"),
    (r"[A-Za-z0-9+/]{40,}={0,2}", "疑似长串密钥/Base64"),
]


def leak_scan(outgoing: str) -> list:
    """发出去之前自查：返回命中的 [(原因, 片段)]，空列表表示干净。"""
    hits = []
    for pat, why in LEAK_PATTERNS:
        for m in re.finditer(pat, outgoing or ""):
            frag = m.group(0)
            frag = frag[:12] + "…" if len(frag) > 12 else frag
            hits.append((why, frag))
    return hits


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--scan-out":
        h = leak_scan(" ".join(sys.argv[2:]))
        if h:
            print("🛑 出口命中： " + " / ".join(f"{w}({f})" for w, f in h))
            sys.exit(3)
        print("✅ 出口干净")
        sys.exit(0)
    main()
