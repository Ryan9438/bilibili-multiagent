#!/usr/bin/env python3
"""读某条评论下的楼中楼（子回复）。用法: bili_subreplies.py <oid> <root_rpid> [pn] [--why 原因]"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_log import log_op, why_from_argv  # noqa: E402  桌面操作日志

WHY = why_from_argv("读取楼中楼内容")
ck = json.load(open(os.path.expanduser((os.environ.get('BILI_HOME', '~/.hermes/bili') + '/cookies.json'))))
if isinstance(ck, dict) and 'cookies' in ck:
    ck = ck['cookies']
C = '; '.join(f'{k}={v}' for k, v in ck.items())
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")

oid, root = sys.argv[1], sys.argv[2]
pn = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].isdigit() else "1"
url = (f"https://api.bilibili.com/x/v2/reply/reply?oid={oid}&type=1&root={root}"
       f"&pn={pn}&ps=20")
r = subprocess.run(['curl', '-s', '-H', f'Cookie: {C}', '-H', f'User-Agent: {UA}',
                    '-H', 'Referer: https://www.bilibili.com/', url],
                   capture_output=True, text=True)
try:
    d = json.loads(r.stdout)
except Exception:
    print(r.stdout[:400]); sys.exit(1)
print('code', d.get('code'), d.get('message'))
reps = ((d.get('data') or {}).get('replies') or [])
for rep in reps:
    print('---', rep['rpid'], rep['member']['uname'], rep['member']['mid'])
    print((rep['content']['message'] or '')[:200])
log_op('读', '读取楼中楼', f'oid={oid} root={root} pn={pn}', why=WHY,
       result=f'code={d.get("code")}，{len(reps)} 条')
