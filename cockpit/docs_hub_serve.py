#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 小鲸鱼哒：看板本地服务 —— 静态托管 + 打开页面时按需重生成
# 起法（launchd 常驻 label=com.hermes.docs-hub）：python3 ~/.hermes/scripts/docs_hub_serve.py
# 端口 8788，只监听 127.0.0.1，不对外。

import os, sys, json, time, base64, threading, datetime
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docs_hub

OUT = str(docs_hub.OUTDIR)
PORT = int(os.environ.get('DOCS_HUB_PORT', '8788'))
# 1x1 透明 gif：让 file:// 页面能用 <img> 触发刷新，绕开 CORS
GIF = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')

_lock = threading.Lock()
STATE = {'busy': False, 'runs': 0, 'last_ms': None,
         'last_ok': None, 'last_err': None}


def refresh():
    """加锁跑一次生成；正在跑时直接回 busy，不排队堆积。"""
    if not _lock.acquire(False):
        return {'ok': False, 'busy': True}
    t0 = time.time()
    STATE['busy'] = True
    try:
        r = docs_hub.build()
        ms = int((time.time() - t0) * 1000)
        STATE.update(busy=False, runs=STATE['runs'] + 1, last_ms=ms,
                     last_ok=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                     last_err=None)
        return {'ok': True, 'ms': ms, 'mb': r['mb']}
    except Exception as e:
        STATE.update(busy=False, last_err=str(e)[:300])
        return {'ok': False, 'error': str(e)[:300]}
    finally:
        STATE['busy'] = False
        _lock.release()


def file_info():
    p = Path(OUT) / 'index.html'
    if not p.exists():
        return {'exists': False, 'state': STATE}
    st = p.stat()
    return {'exists': True,
            'bytes': st.st_size,
            'age_min': round((time.time() - st.st_mtime) / 60, 1),
            'generated_at': datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'state': STATE}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=OUT, **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (datetime.datetime.now().strftime('%H:%M:%S'), fmt % args))

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Cache-Control', 'no-store')

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/status':
            return self._json(file_info())
        if path == '/api/refresh':
            r = refresh()
            # 回 gif：<img> 触发不会受 CORS 限制，结果看响应头
            self.send_response(200)
            self.send_header('Content-Type', 'image/gif')
            self.send_header('Content-Length', str(len(GIF)))
            self.send_header('X-Refresh', 'ok' if r.get('ok') else ('busy' if r.get('busy') else 'error'))
            self._cors()
            self.end_headers()
            self.wfile.write(GIF)
            return
        if path == '/favicon.ico':
            self.send_response(204)
            self._cors()
            self.end_headers()
            return
        if path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == '/api/refresh':
            return self._json(refresh())
        self.send_response(404)
        self.end_headers()


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print('docs-hub serving %s at http://127.0.0.1:%d' % (OUT, PORT), flush=True)
    srv.serve_forever()
