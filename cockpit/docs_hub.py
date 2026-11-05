#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 小鲸鱼哒：本地数据看板生成器 —— 采集层
# 用法：python3 ~/.hermes/scripts/docs_hub.py            → 生成 ~/Desktop/文档后台/index.html
#       python3 ~/.hermes/scripts/docs_hub.py --collect  → 只采集，打印 payload 摘要
#       python3 ~/.hermes/scripts/docs_hub.py --json     → 采集并写 payload.json（调试用）

import os, json, sqlite3, collections, datetime, re, sys, shutil
from pathlib import Path

HOME = Path.home()
HERMES = HOME / '.hermes'
OUTDIR = HOME / 'Desktop' / '文档后台'
SKILL_FILE = Path(__file__).resolve().parent / 'hub_template.html'

SKIP_DIRS = {'node_modules', '.venv', 'venv', 'site-packages', '.git', 'dist',
             'build', '__pycache__', '.next', '.cache', 'resources', 'frameworks'}
WD = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def ro(path):
    # 带 -wal/-shm 的库在只读 URI 下可能打不开，回退到 immutable 只读
    try:
        c = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        c.execute('select count(*) from sqlite_master').fetchone()
        return c
    except Exception:
        return sqlite3.connect('file:%s?mode=ro&immutable=1' % path, uri=True)


def ts2dt(v):
    if v is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(float(v))
    except Exception:
        return None


def iso2dt(s):
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        if dt.tzinfo is not None:          # 统一成本地 naive，避免和 now() 比较时报错
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def profiles():
    """返回 [(名字, 基础目录)]，只含存在 state.db 的 profile"""
    out = [('default', HERMES)]
    pdir = HERMES / 'profiles'
    if pdir.exists():
        for d in sorted(pdir.iterdir()):
            if d.is_dir() and (d / 'state.db').exists():
                out.append((d.name, d))
    return out


# ---------------------------------------------------------------- 0 概览 KPI
def collect_kpi(profs, time_data, money, cron, bili):
    today = datetime.date.today().strftime('%Y-%m-%d')
    k = {}
    k['today_msgs'] = time_data['day_cnt'].get(today, 0)
    k['today_tokens'] = money['today_tokens']
    k['total_msgs'] = sum(time_data['day_cnt'].values())
    k['total_sessions'] = money['sessions_total']
    k['cost'] = round(money['cost_total'], 2)
    k['alive_jobs'] = cron['alive']
    k['all_jobs'] = cron['total']
    k['today_reads'] = bili['today_reads']
    k['today_writes'] = bili['today_writes']
    k['watch_left'] = bili['watch_left']
    k['docs'] = time_data['doc_total']
    k['patrol'] = bili['today_patrol']
    # 迷你图数据
    k['spark_msgs'] = time_data['last14_msgs']
    k['spark_cost'] = money['last14_cost']
    k['spark_days'] = money['last14_days']
    k['cron_band'] = cron['recent_band']
    k['patrol_series'] = bili['patrol_series'][-14:]
    return k


# ---------------------------------------------------------------- 1 时间机器
def collect_time(profs):
    day_cnt = collections.Counter()
    clock = collections.Counter()
    hour = collections.Counter()
    prof_day = collections.defaultdict(collections.Counter)
    for name, base in profs:
        db = base / 'state.db'
        if not db.exists():
            continue
        try:
            c = ro(db)
            for (ts,) in c.execute('select timestamp from messages where timestamp is not null'):
                dt = ts2dt(ts)
                if not dt:
                    continue
                d = dt.strftime('%Y-%m-%d')
                day_cnt[d] += 1
                prof_day[name][d] += 1
                clock[(dt.weekday(), dt.hour)] += 1
                hour[dt.hour] += 1
            c.close()
        except Exception as e:
            print('  [warn] time %s: %s' % (name, e), file=sys.stderr)
    days = sorted(day_cnt)
    cal = [[d, day_cnt[d]] for d in days]
    clock_arr = [[h, w, clock.get((w, h), 0)] for w in range(7) for h in range(24)]
    hourly = [hour.get(h, 0) for h in range(24)]
    # 最近 14 天
    last14 = []
    d0 = datetime.date.today()
    for i in range(13, -1, -1):
        d = (d0 - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
        last14.append([d[5:], day_cnt.get(d, 0)])
    return {'day_cnt': day_cnt, 'cal': cal, 'clock': clock_arr, 'hourly': hourly,
            'last14_msgs': last14, 'prof_day': {k: dict(v) for k, v in prof_day.items()},
            'doc_total': 0, 'days_span': (days[0], days[-1]) if days else ('-', '-')}


# ---------------------------------------------------------------- 2 钱与 token
def collect_money(profs):
    daily = collections.defaultdict(lambda: [0, 0, 0])   # in, out, cache_read
    daily_cost = collections.Counter()
    models = collections.Counter()
    model_calls = collections.Counter()
    cache_read = input_tok = output_tok = 0
    scatter = []
    sessions_total = 0
    for name, base in profs:
        db = base / 'state.db'
        if not db.exists():
            continue
        try:
            c = ro(db)
            for st, model, ip, op, cr, cw, rs, ac in c.execute(
                    'select s.started_at, u.model, u.input_tokens, u.output_tokens, '
                    'u.cache_read_tokens, u.cache_write_tokens, u.reasoning_tokens, u.api_call_count '
                    'from session_model_usage u join sessions s on s.id = u.session_id'):
                dt = ts2dt(st)
                d = dt.strftime('%Y-%m-%d') if dt else '?'
                ip = ip or 0; op = op or 0; cr = cr or 0
                daily[d][0] += ip; daily[d][1] += op; daily[d][2] += cr
                input_tok += ip; output_tok += op; cache_read += cr
                if model:
                    models[model] += ip + op
                    model_calls[model] += (ac or 0)
            for title, mc, tcc, cost, tok, st, src, model in c.execute(
                    'select title, message_count, tool_call_count, estimated_cost_usd, '
                    'coalesce(input_tokens,0)+coalesce(output_tokens,0), started_at, source, model '
                    'from sessions where estimated_cost_usd > 0 order by estimated_cost_usd desc limit 200'):
                dt = ts2dt(st)
                scatter.append({'name': (title or '(未命名)')[:40], 'msgs': mc or 0,
                                'cost': round(cost or 0, 3), 'tok': tok or 0,
                                'day': dt.strftime('%Y-%m-%d') if dt else '-',
                                'src': src or '-', 'model': model or '-'})
            for (cost, st) in c.execute('select estimated_cost_usd, started_at from sessions'):
                dt = ts2dt(st)
                if dt and cost:
                    daily_cost[dt.strftime('%Y-%m-%d')] += cost
            sessions_total += c.execute('select count(*) from sessions').fetchone()[0]
            c.close()
        except Exception as e:
            print('  [warn] money %s: %s' % (name, e), file=sys.stderr)
    days = sorted(set(daily) | set(daily_cost))
    days = [d for d in days if d != '?']
    today = datetime.date.today().strftime('%Y-%m-%d')
    cum, acc = [], 0.0
    for d in days:
        acc += daily_cost.get(d, 0)
        cum.append([d, round(acc, 3)])
    d0 = datetime.date.today()
    last14_days, last14_cost = [], []
    for i in range(13, -1, -1):
        d = (d0 - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
        last14_days.append(d[5:])
        last14_cost.append(round(daily_cost.get(d, 0), 3))
    rate = cache_read / (cache_read + input_tok) if (cache_read + input_tok) else 0
    return {
        'days': days,
        'stack_in': [daily[d][0] for d in days],
        'stack_out': [daily[d][1] for d in days],
        'stack_cache': [daily[d][2] for d in days],
        'models': [[m, v] for m, v in models.most_common(10)],
        'model_calls': {m: model_calls[m] for m in model_calls},
        'cache_rate': round(rate, 4),
        'in_tok': input_tok, 'out_tok': output_tok, 'cache_tok': cache_read,
        'scatter': scatter,
        'cum': cum,
        'cost_total': sum(daily_cost.values()),
        'sessions_total': sessions_total,
        'today_tokens': input_tok and 0,   # 占位，下面由调用方覆盖
        'last14_days': last14_days, 'last14_cost': last14_cost,
        'today_cost': round(daily_cost.get(today, 0), 3),
    }


# ---------------------------------------------------------------- 3 工具画像
def collect_tools(profs):
    rank = collections.Counter()
    tool_day = collections.defaultdict(collections.Counter)
    skills = collections.Counter()
    sankey = collections.Counter()
    for name, base in profs:
        db = base / 'state.db'
        if not db.exists():
            continue
        try:
            c = ro(db)
            src_of = dict(c.execute('select id, coalesce(source,"?") from sessions'))
            for sid, tool, ts in c.execute(
                    'select session_id, tool_name, timestamp from messages where tool_name is not null'):
                rank[tool] += 1
                dt = ts2dt(ts)
                if dt:
                    tool_day[dt.strftime('%Y-%m-%d')][tool] += 1
                sankey[(tool, src_of.get(sid, '?'))] += 1
            for (tc,) in c.execute("select tool_calls from messages where tool_calls is not null and tool_calls != '' "):
                if 'skill_view' not in str(tc):
                    continue
                try:
                    arr = json.loads(tc)
                except Exception:
                    continue
                for it in arr or []:
                    fn = (it.get('function') or {}) if isinstance(it, dict) else {}
                    if fn.get('name') != 'skill_view':
                        continue
                    try:
                        args = json.loads(fn.get('arguments') or '{}')
                        nm = args.get('name')
                        if nm:
                            skills[nm] += 1
                    except Exception:
                        pass
            c.close()
        except Exception as e:
            print('  [warn] tools %s: %s' % (name, e), file=sys.stderr)
    top_tools = [t for t, _ in rank.most_common(10)]
    days = sorted(tool_day)[-14:]
    heat = []
    for yi, t in enumerate(top_tools):
        for xi, d in enumerate(days):
            heat.append([xi, yi, tool_day[d].get(t, 0)])
    sk_nodes = [{'name': t} for t in top_tools] + [{'name': s} for s in sorted({k[1] for k in sankey})]
    sk_links = [{'source': a, 'target': b, 'value': v} for (a, b), v in sankey.items()
                if a in top_tools and v > 0]
    return {'rank': [[t, n] for t, n in rank.most_common(14)],
            'heat': {'days': [d[5:] for d in days], 'tools': top_tools, 'data': heat},
            'skills': [[s, n] for s, n in skills.most_common(12)],
            'sankey': {'nodes': sk_nodes, 'links': sk_links},
            'total': sum(rank.values())}


# ---------------------------------------------------------------- 4 cron 健康
def collect_cron(profs):
    jobs_meta = {}      # job_id -> (name, state, profile)
    rows = []           # (profile, job_id, status, started, finished, error)
    incidents = []
    alive = total = 0
    now = datetime.datetime.now()
    by_profile = {}
    for name, base in profs:
        jp = base / 'cron' / 'jobs.json'
        n_alive = n_total = 0
        if jp.exists():
            try:
                j = json.load(open(jp, encoding='utf-8'))
                js = j.get('jobs', j) if isinstance(j, dict) else j
                for it in js:
                    st = it.get('state') or ('scheduled' if it.get('enabled') else 'paused')
                    jobs_meta[it.get('id')] = (it.get('name') or '?', st, name,
                                              it.get('next_run_at'), it.get('last_status'))
                    n_total += 1
                    if st == 'scheduled' and it.get('enabled'):
                        n_alive += 1
            except Exception as e:
                print('  [warn] jobs %s: %s' % (name, e), file=sys.stderr)
        db = base / 'cron' / 'executions.db'
        if db.exists():
            try:
                c = ro(db)
                for jid, status, st, fin, err in c.execute(
                        'select job_id, status, started_at, finished_at, error from executions '
                        'order by started_at desc limit 300'):
                    dt = iso2dt(st) or ts2dt(st)
                    rows.append({'prof': name, 'job': jid, 'status': status,
                                 't': dt.strftime('%Y-%m-%d %H:%M') if dt else '-',
                                 'day': dt.strftime('%Y-%m-%d') if dt else '-',
                                 'err': (err or '')[:80]})
                try:
                    for jid, sig, stt, ftype, fs, ls, cls, err in c.execute(
                            'select job_id, error_sig, state, failure_type, first_seen_at, last_seen_at, closed_at, error from cron_incidents'):
                        incidents.append({'job': jid, 'sig': (sig or '')[:40], 'state': stt,
                                          'type': ftype or '-', 'first': fs, 'last': ls,
                                          'closed': cls, 'err': (err or '')[:90]})
                except Exception:
                    pass
                c.close()
            except Exception as e:
                print('  [warn] exec %s: %s' % (name, e), file=sys.stderr)
        by_profile[name] = {'alive': n_alive, 'total': n_total}
        alive += n_alive
        total += n_total
    # 台账矩阵：只保留最近 14 天有执行的任务
    recent_days = set()
    d0 = datetime.date.today()
    for i in range(14):
        recent_days.add((d0 - datetime.timedelta(days=i)).strftime('%Y-%m-%d'))
    by_job = collections.defaultdict(list)
    for r in rows:
        if r['day'] in recent_days:
            by_job[(r['prof'], r['job'])].append(r)
    order = sorted(by_job.items(), key=lambda kv: -len(kv[1]))[:16]
    labels, cells = [], []
    for yi, ((prof, jid), items) in enumerate(order):
        nm = jobs_meta.get(jid, ('?', '-', prof, None, None))[0]
        labels.append('%s·%s' % (prof[:4], nm[:14]))
        items = sorted(items, key=lambda x: x['t'])[-24:]
        for xi, it in enumerate(items):
            v = {'completed': 3, 'failed': 1, 'running': 2, 'skipped': 0}.get(it['status'], 0)
            cells.append([xi, yi, v, it['status'], it['t']])
    # 每日执行量（按 profile 堆叠）
    day_prof = collections.defaultdict(collections.Counter)
    for r in rows:
        day_prof[r['day']][r['prof']] += 1
    dds = sorted(d for d in day_prof if d != '-')[-14:]
    profs_in = [p for p in {r['prof'] for r in rows}]
    daily = {'days': [d[5:] for d in dds],
             'series': [{'name': p, 'data': [day_prof[d].get(p, 0) for d in dds]} for p in profs_in]}
    # incidents 甘特
    gantt = []
    for it in incidents:
        a = iso2dt(it['first']); b = iso2dt(it['closed'] or it['last'])
        if not a:
            continue
        b = b or now
        gantt.append({'name': (jobs_meta.get(it['job'], ('?',))[0] or '?')[:16] + '｜' + it['type'][:10],
                      'start': a.strftime('%Y-%m-%d %H:%M'), 'end': b.strftime('%Y-%m-%d %H:%M'),
                      'state': it['state'], 'err': it['err']})
    # 巡检告警
    alerts = []
    for jid, (nm, st, prof, nxt, last) in jobs_meta.items():
        if st == 'scheduled' and nxt:
            dt = iso2dt(nxt)
            if dt and dt < now - datetime.timedelta(hours=2):
                alerts.append({'level': 'red', 'title': '%s · %s' % (prof, nm),
                               'detail': 'next_run_at 已过期 %s，任务可能停摆' % nxt[:16]})
    paused = [(p, jobs_meta[j][0]) for j in jobs_meta for p in [jobs_meta[j][2]] if jobs_meta[j][1] == 'paused']
    if paused:
        alerts.append({'level': 'yellow', 'title': 'paused 任务 %d 条' % len(paused),
                       'detail': '、'.join('%s/%s' % (p, n) for p, n in paused[:6])})
    # 最近失败
    fails = [r for r in rows if r['status'] == 'failed'][:5]
    for f in fails:
        alerts.append({'level': 'red', 'title': '执行失败 · %s' % jobs_meta.get(f['job'], ('?',))[0],
                       'detail': '%s %s %s' % (f['prof'], f['t'], f['err'])})
    if not alerts:
        alerts.append({'level': 'green', 'title': '全部正常', 'detail': '没有过期任务、没有近期失败'})
    band = [{'completed': 3, 'failed': 1, 'running': 2, 'skipped': 0}.get(r['status'], 0)
            for r in sorted(rows, key=lambda x: x['t'])[-24:]]
    return {'alive': alive, 'total': total, 'by_profile': by_profile,
            'matrix': {'labels': labels, 'cells': cells}, 'daily': daily,
            'gantt': gantt[:14], 'alerts': alerts[:10], 'recent_band': band,
            'runs': len(rows)}


# ---------------------------------------------------------------- 5 B站账本
def collect_bili():
    logp = HOME / 'Desktop' / 'B站账号操作日志.md'
    byday = collections.defaultdict(lambda: [0, 0])
    actions = collections.Counter()
    total_r = total_w = 0
    if logp.exists():
        lines = [l for l in open(logp, encoding='utf-8').read().splitlines() if l.startswith('|')]
        for l in lines[2:]:
            col = [x.strip() for x in l.split('|')]
            if len(col) < 7:
                continue
            day, kind, act = col[1][:10], col[2], col[3]
            if not re.match(r'^\d{4}-\d{2}-\d{2}', day):
                continue
            act = re.sub(r'^\[[^\]]+\]\s*', '', act)
            if kind == '读':
                byday[day][0] += 1; total_r += 1
            elif kind == '写':
                byday[day][1] += 1; total_w += 1
            else:
                continue
            actions[act] += 1
    days = sorted(byday)
    today = datetime.date.today().strftime('%Y-%m-%d')
    # night_log（我的 + glm 的）
    patrol = collections.Counter()
    verdicts = collections.Counter()
    real_vids = 0
    for p in [HERMES / 'bili' / 'night_log.json', HERMES / 'profiles' / 'glm' / 'bili' / 'night_log.json']:
        if not p.exists():
            continue
        try:
            for it in json.load(open(p, encoding='utf-8')):
                d = str(it.get('date') or '')[:10]
                if not re.match(r'^\d{4}-\d{2}-\d{2}', d):
                    continue
                patrol[d] += 1
                bv = str(it.get('bvid') or '')
                if bv.startswith('BV'):
                    verdicts['真实视频'] += 1
                    real_vids += 1
                else:
                    verdicts['守卫元信息'] += 1
        except Exception as e:
            print('  [warn] night_log: %s' % e, file=sys.stderr)
    pdays = sorted(patrol)[-14:]
    watch_left = 0
    wf = HERMES / 'bili' / 'watch_feed.json'
    if wf.exists():
        try:
            w = json.load(open(wf, encoding='utf-8'))
            watch_left = len((w.get('items') or w.get('data') or []) or [])
        except Exception:
            pass
    # 读→写桑基（按动作归类）
    def bucket(a):
        if '探信' in a or '心跳' in a:
            return '探信'
        if '校验登录态' in a or '登录' in a:
            return '验态'
        if '读' in a or '拉取' in a or '查看' in a or '复核' in a:
            return '读取'
        if '发评论' in a or '回复' in a:
            return '发声'
        if '稍后' in a or '收藏' in a:
            return '收藏'
        return '其他'
    flow = collections.Counter()
    for a, n in actions.items():
        flow[bucket(a)] += n
    order = ['探信', '验态', '读取', '发声', '收藏', '其他']
    links = []
    for i in range(len(order) - 1):
        v = min(flow.get(order[i], 0), flow.get(order[i + 1], 0))
        if v:
            links.append({'source': order[i], 'target': order[i + 1], 'value': v})
    return {'days': [d[5:] for d in days],
            'reads': [byday[d][0] for d in days],
            'writes': [byday[d][1] for d in days],
            'actions': [[a[:18], n] for a, n in actions.most_common(12)],
            'patrol_series': [['%s' % d[5:], patrol[d]] for d in pdays],
            'today_patrol': patrol.get(today, 0),
            'verdicts': [[k, v] for k, v in verdicts.items()],
            'total_r': total_r, 'total_w': total_w,
            'real_vids': real_vids,
            'today_reads': byday.get(today, [0, 0])[0],
            'today_writes': byday.get(today, [0, 0])[1],
            'watch_left': watch_left,
            'sankey': {'nodes': [{'name': o} for o in order if flow.get(o)],
                       'links': links}}


# ---------------------------------------------------------------- 6 姊妹生态
def collect_sisters(profs):
    compare = []
    for name, base in profs:
        db = base / 'state.db'
        if not db.exists():
            continue
        try:
            c = ro(db)
            ns = c.execute('select count(*) from sessions').fetchone()[0]
            nm = c.execute('select count(*) from messages').fetchone()[0]
            tk = c.execute('select coalesce(sum(input_tokens),0)+coalesce(sum(output_tokens),0) from session_model_usage').fetchone()[0]
            cost = c.execute('select coalesce(sum(estimated_cost_usd),0) from sessions').fetchone()[0]
            c.close()
        except Exception:
            ns = nm = tk = 0; cost = 0
        compare.append({'name': name, 'sessions': ns, 'msgs': nm,
                        'tokens': tk, 'cost': round(cost or 0, 2),
                        'mb': round(os.path.getsize(db) / 1e6, 1)})
    compare.sort(key=lambda x: -x['msgs'])
    # 群聊
    chat = []
    cp = HOME / 'Desktop' / '姐妹群聊' / 'chat.jsonl'
    if cp.exists():
        for line in open(cp, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
                dt = ts2dt(m.get('ts'))
                chat.append({'from': m.get('from') or '?', 'text': (m.get('text') or '')[:400],
                             't': dt.strftime('%m-%d %H:%M') if dt else '-'})
            except Exception:
                pass
    # 关系图：以主人为中心，六人环绕
    nodes = [{'name': '主人', 'symbolSize': 46, 'itemStyle': {'color': '#ffd479'}, 'x': 0, 'y': 0}]
    links = []
    seen = {c['name'] for c in compare}
    ring = [n for n in ['glm', 'qwen', 'kimi', 'mimo', 'minimax', 'default'] if n in seen]
    import math
    for i, n in enumerate(ring):
        ang = -math.pi / 2 + i * 2 * math.pi / max(1, len(ring))
        item = next(c for c in compare if c['name'] == n)
        nodes.append({'name': n, 'symbolSize': 24 + 34 * (item['msgs'] / max(1, compare[0]['msgs'])),
                      'symbol': 'image://assets/avatars/%s.png' % avatar_name(n),
                      'x': int(300 * math.cos(ang)), 'y': int(220 * math.sin(ang)),
                      'value': item['msgs'], 'mb': item['mb'], 'tokens': item['tokens']})
        links.append({'source': '主人', 'target': n, 'value': max(1, item['msgs'] // 20),
                      'label': {'show': True, 'formatter': str(item['msgs']), 'fontSize': 9}})
    # 协作文件按作者
    files = collections.Counter()
    cdir = HOME / 'Desktop' / '协作'
    if cdir.exists():
        for f in cdir.iterdir():
            if not f.is_file() or f.name.startswith('.'):
                continue
            nm = f.name
            who = '共用'
            for tag in ['小鲸鱼', '小大姐', 'GLM', 'Qwen', 'Mini', 'DeepSeek', 'Kimi', 'Mimo']:
                if tag in nm:
                    who = tag
                    break
            files[who] += 1
    return {'compare': compare, 'chat': chat[-24:],
            'graph': {'nodes': nodes, 'links': links},
            'files': [[k, v] for k, v in files.most_common()]}


def avatar_name(prof):
    return {'default': 'deepseek', 'glm': 'glm', 'qwen': 'qwen', 'minimax': 'minimax',
            'kimi': 'kimi', 'mimo': 'mimo'}.get(prof, 'deepseek')


# ---------------------------------------------------------------- 7 文档库
def walk_md(root, maxdepth=5):
    out = []
    base_depth = len(Path(root).parts)
    for dirpath, dirnames, filenames in os.walk(root):
        if len(Path(dirpath).parts) - base_depth >= maxdepth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for f in filenames:
            if not f.lower().endswith('.md'):
                continue
            p = Path(dirpath) / f
            try:
                st = p.stat()
            except Exception:
                continue
            out.append({'path': str(p), 'name': f, 'dir': dirpath, 'size': st.st_size,
                        'mtime': st.st_mtime, 'root': str(root)})
    return out


def collect_docs():
    roots = [(HOME / 'Desktop', 'Desktop'), (HERMES / 'skills', 'skills'),
             (HERMES / 'memories', 'memories'), (HOME / 'Desktop' / '协作', '协作')]
    files, seen = [], set()
    for root, tag in roots:
        if not Path(root).exists():
            continue
        for f in walk_md(root):
            if f['path'] in seen:
                continue
            seen.add(f['path'])
            f['tag'] = tag
            files.append(f)
    # sunburst：一级目录
    grp = collections.defaultdict(lambda: {'n': 0, 'kb': 0})
    for f in files:
        try:
            rel = os.path.relpath(f['dir'], HOME)
        except Exception:
            rel = f['dir']
        parts = rel.split('/')
        key = parts[1] if parts[0] == 'Desktop' and len(parts) > 1 else '/'.join(parts[:2])
        grp[key]['n'] += 1
        grp[key]['kb'] += f['size'] / 1024
    children = [{'name': '%s (%d)' % (k, v['n']), 'value': round(v['kb'], 1)}
                for k, v in sorted(grp.items(), key=lambda kv: -kv[1]['kb'])[:24]]
    # 修改散点
    scat = []
    for f in sorted(files, key=lambda x: -x['mtime'])[:400]:
        dt = ts2dt(f['mtime'])
        scat.append([dt.strftime('%Y-%m-%d') if dt else '-', round(f['size'] / 1024, 1), f['name'][:30]])
    # 搜索索引 + 阅读器正文
    docs, index = [], []
    for f in sorted(files, key=lambda x: -x['mtime']):
        try:
            txt = open(f['path'], encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        dt = ts2dt(f['mtime'])
        item = {'n': f['name'], 'p': f['path'].replace(str(HOME), '~'), 't': dt.strftime('%Y-%m-%d') if dt else '-',
                'kb': round(f['size'] / 1024, 1), 'tag': f['tag'], 'text': txt[:9000]}
        docs.append(item)
        index.append({'n': f['name'], 'p': item['p'], 't': item['t'], 'kb': item['kb'],
                      'tag': f['tag'], 'body': txt[:3000]})
    return {'sunburst': children, 'scatter': scat, 'docs': docs, 'index': index,
            'count': len(files), 'total_kb': round(sum(f['size'] for f in files) / 1024, 0)}


# ---------------------------------------------------------------- 8 巡检
def collect_checks(profs, cron, bili):
    checks = []
    # memory 用量
    for nm, p in [('MEMORY', HERMES / 'memories' / 'MEMORY.md'),
                  ('USER', HERMES / 'memories' / 'USER.md')]:
        if p.exists():
            n = len(open(p, encoding='utf-8').read())
            lvl = 'red' if n > 24000 else ('yellow' if n > 20000 else 'green')
            checks.append({'level': lvl, 'title': '%s 记忆 %d 字符' % (nm, n),
                           'detail': '上限 25000，%.0f%% 用完' % (n / 250.0)})
    # cookie 新鲜度
    ck = HERMES / 'bili' / 'cookies.json'
    if ck.exists():
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(ck.stat().st_mtime)).total_seconds() / 3600
        checks.append({'level': 'yellow' if age > 72 else 'green',
                       'title': 'B站凭据 %.1f 小时前更新' % age,
                       'detail': 'SESSDATA 会静默失效（-101），超过 3 天建议重抓' % ()})
    # night_log 备份堆积
    baks = list((HERMES / 'bili').glob('night_log.json.bak*'))
    checks.append({'level': 'yellow' if len(baks) > 3 else 'green',
                   'title': 'night_log 备份 %d 份' % len(baks),
                   'detail': '超过 3 份说明备份脚本没有轮转' if len(baks) > 3 else '数量正常'})
    # 收信记录按日堆积
    cdir = HOME / 'Desktop' / '协作'
    dailies = [f.name for f in cdir.glob('*收信记录*')] if cdir.exists() else []
    checks.append({'level': 'yellow' if len(dailies) > 4 else 'green',
                   'title': '协作目录收信记录 %d 份' % len(dailies),
                   'detail': '按日堆积，尚无归档规则' if len(dailies) > 4 else '数量正常'})
    # 夜巡趟数
    lvl = 'red' if bili['today_patrol'] > 4 else 'green'
    checks.append({'level': lvl, 'title': '今日夜巡记录 %d 条（上限 4 趟）' % bili['today_patrol'],
                   'detail': '超出上限，明天要压一压' if lvl == 'red' else '在限额内'})
    # cron
    checks.append({'level': 'green' if cron['alive'] else 'red',
                   'title': 'cron 存活 %d/%d 条' % (cron['alive'], cron['total']),
                   'detail': '六个 profile 合计'})
    # 库体积
    tot = sum(os.path.getsize(p / 'state.db') for _, p in profs if (p / 'state.db').exists())
    checks.append({'level': 'yellow' if tot > 400e6 else 'green',
                   'title': '会话库合计 %.0f MB' % (tot / 1e6),
                   'detail': '主库 244MB 占大头，暂不需清理'})
    # 文档索引
    checks.append({'level': 'green', 'title': '文档索引已生成',
                   'detail': '聚合图表 + 全文搜索（Desktop / skills / 协作）'})
    return checks


# ---------------------------------------------------------------- 主流程
def collect_all():
    profs = profiles()
    print('profiles: %s' % ', '.join(n for n, _ in profs), file=sys.stderr)
    t = collect_time(profs)
    m = collect_money(profs)
    tl = collect_tools(profs)
    cr = collect_cron(profs)
    bl = collect_bili()
    d = collect_docs()
    t['doc_total'] = d['count']
    sis = collect_sisters(profs)
    # 今日 token
    today = datetime.date.today().strftime('%Y-%m-%d')
    if today in m['days']:
        i = m['days'].index(today)
        m['today_tokens'] = m['stack_in'][i] + m['stack_out'][i]
        m['today_cost'] = round(sum(m['stack_in'][i:i + 1]) * 0 + m['today_cost'], 3)
    k = collect_kpi(profs, t, m, cr, bl)
    chk = collect_checks(profs, cr, bl)
    return {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'kpi': k,
        'time': {'cal': t['cal'], 'clock': t['clock'], 'hourly': t['hourly'],
                 'last14': t['last14_msgs'], 'span': t['days_span']},
        'money': {kk: m[kk] for kk in ['days', 'stack_in', 'stack_out', 'stack_cache', 'models',
                                       'cache_rate', 'in_tok', 'out_tok', 'cache_tok', 'scatter',
                                       'cum', 'cost_total', 'sessions_total', 'last14_days',
                                       'last14_cost', 'today_cost']},
        'tools': tl,
        'cron': cr,
        'bili': bl,
        'sisters': sis,
        'docs': {'sunburst': d['sunburst'], 'scatter': d['scatter'], 'index': d['index'],
                 'count': d['count'], 'total_kb': d['total_kb']},
        'checks': chk,
    }



def build(payload=None):
    """采集 + 渲染，返回产出信息。CLI 与本地服务共用这一条路径。"""
    if payload is None:
        payload = collect_all()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / 'assets').mkdir(exist_ok=True)
    src = HOME / 'Desktop' / '姐妹群聊' / 'avatars'
    if src.exists():
        (OUTDIR / 'assets' / 'avatars').mkdir(exist_ok=True)
        for f in src.glob('*.png'):
            shutil.copy2(f, OUTDIR / 'assets' / 'avatars' / f.name)
    if not SKILL_FILE.exists():
        raise RuntimeError('模板缺失: %s' % SKILL_FILE)
    # 关键：文档正文里可能出现 </script>，必须转义成 <\/ 否则会把内联脚本提前截断
    blob = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    html = SKILL_FILE.read_text(encoding='utf-8').replace('__DATA__', blob)
    out = OUTDIR / 'index.html'
    tmp = OUTDIR / ('index.html.%d.tmp' % os.getpid())   # 带 pid：cron 与服务并发时不会踩同一个临时文件
    tmp.write_text(html, encoding='utf-8')
    os.replace(str(tmp), str(out))          # 原子替换：正在看页面也不会读到半写文件
    st = out.stat()
    return {'path': str(out), 'bytes': st.st_size, 'mb': round(st.st_size / 1e6, 2),
            'at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}


if __name__ == '__main__':
    if '--collect' in sys.argv:
        payload = collect_all()
        k = payload['kpi']
        print(json.dumps({kk: (vv if not isinstance(vv, (list, dict)) else '<%s len=%d>' % (type(vv).__name__, len(vv)))
                          for kk, vv in k.items()}, ensure_ascii=False, indent=1))
        for sec in ['time', 'money', 'tools', 'cron', 'bili', 'sisters', 'docs']:
            print(sec, {kk: (len(vv) if isinstance(vv, (list, dict)) else vv) for kk, vv in payload[sec].items()})
        print('checks:', len(payload['checks']))
        print('payload bytes:', len(json.dumps(payload, ensure_ascii=False)))
        sys.exit(0)
    if '--json' in sys.argv:
        pl = collect_all()
        fp = HERMES / 'cache' / 'scratch' / 'hub_payload.json'
        fp.write_text(json.dumps(pl, ensure_ascii=False), encoding='utf-8')
        print(str(fp)); sys.exit(0)
    r = build()
    print('✅ %s  (%.1f MB)  %s' % (r['path'], r['mb'], r['at']))
