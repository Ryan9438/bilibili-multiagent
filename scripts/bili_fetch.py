#!/usr/bin/env python3
"""Fetch B站 msgfeed (reply/at) and DM sessions. Usage: bili_fetch.py reply|at [id]"""
import json, sys, subprocess, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op, why_from_argv  # noqa: E402  桌面操作日志

CKDIR = os.path.expanduser((os.environ.get('BILI_HOME', '~/.hermes/bili') + ''))
ck = json.load(open(os.path.join(CKDIR, 'cookies.json')))
if isinstance(ck, dict) and 'cookies' in ck:
    ck = ck['cookies']
COOKIE = '; '.join(f'{k}={v}' for k, v in ck.items())
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")

def get(url, referer='https://message.bilibili.com/'):
    r = subprocess.run(['curl', '-s', '-H', f'Cookie: {COOKIE}', '-H', f'User-Agent: {UA}',
                        '-H', f'Referer: {referer}', url],
                       capture_output=True, text=True, timeout=40)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {'code': -999, 'raw': r.stdout[:500]}

WHY = why_from_argv("调试/收信时手动拉取消息")
kind = sys.argv[1] if len(sys.argv) > 1 else 'reply'
want = sys.argv[2] if len(sys.argv) > 2 else None

if kind in ('reply', 'at'):
    url = f'https://api.bilibili.com/x/msgfeed/{kind}?platform=web&build=0&mobi_app=web&pn=1&ps=20'
    d = get(url)
    print('code', d.get('code'), d.get('message'))
    items = (d.get('data') or {}).get('items') or []
    print('total', len(items))
    for it in items:
        if want and str(it.get('id')) != str(want):
            continue
        print(json.dumps(it, ensure_ascii=False, indent=1))
    if want:
        print('=== LIST OF IDS ===')
        for it in items:
            item = it.get('item') or {}
            print(it.get('id'), '|', it.get('user', {}).get('nickname'), '|',
                  (item.get('title') or '')[:40], '|', (item.get('source_content') or '')[:60],
                  '| aid', item.get('subject_id'), 'root', item.get('root_id'), 'src', item.get('source_id'))
    log_op('读', f'拉取 {kind} 消息列表', f'共 {len(items)} 条' + (f'，筛 id={want}' if want else ''),
           why=WHY, result=f'code={d.get("code")}')
elif kind == 'dm':
    talker = want or os.environ.get("BILI_MID_OWNER", "")
    if not str(talker).isdigit():
        print('talker_id 必须是数字')
        sys.exit(2)
    d = get(f'https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs?talker_id={talker}&session_type=1&size=10',
            referer='https://message.bilibili.com/')
    print('code', d.get('code'), d.get('message'))
    msgs = (d.get('data') or {}).get('messages', [])
    for m in msgs:
        print('---', m.get('msg_key'), 'from', m.get('sender_uid'), 'type', m.get('msg_type'))
        print(m.get('content', '')[:500])
    log_op('读', '拉取私信会话', f'talker_id={talker}', why=WHY,
           result=f'code={d.get("code")}，{len(msgs)} 条')
