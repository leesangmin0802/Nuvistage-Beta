"""390px responsive UI verification harness. Separate test data, same application code.
Run: python3 tests/browser_harness.py
Open http://localhost:8878/test/mobile?route=/dashboard
"""
from pathlib import Path
import sys
from urllib.parse import urlparse, parse_qs
from html import escape
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Handler, create_server


class ResponsiveHandler(Handler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/test/start' and getattr(self.server,'ui_session',None) and self.server.auth.loopback(self.client_address[0]):
            return self.reply(302,b'',headers={'Location':'/dashboard','Set-Cookie':self.server.auth.cookie(self.server.ui_session)})
        if parsed.path == '/test/mobile':
            route = parse_qs(parsed.query).get('route', ['/dashboard'])[0]
            if not route.startswith('/') or route.startswith('//'):
                route = '/dashboard'
            raw = f'''<!doctype html><html><head><meta charset="utf-8"><title>390px 모바일 검증</title></head>
<body style="background:#dce2ec;margin:0;padding:20px;font-family:system-ui"><p>390 × 844 · 실제 iframe viewport</p>
<iframe title="모바일 검증" src="{escape(route,quote=True)}" width="390" height="844" style="border:1px solid #b9c6dc;border-radius:12px;background:white"></iframe></body></html>'''.encode()
            return self.reply(200, raw, 'text/html; charset=utf-8')
        return super().do_GET()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('/private/tmp/pisignage-responsive.json'))
    parser.add_argument('--ui-session',action='store_true',help='격리된 임시 데이터와 일회용 테스트 세션으로 시작')
    parser.add_argument('--seed',type=Path)
    args = parser.parse_args()
    temporary = None
    if args.ui_session:
        import tempfile,json,secrets
        temporary=tempfile.TemporaryDirectory(prefix='pisignage-ui-')
        args.data=Path(temporary.name)/'data.json'
        if args.seed:
            seed=json.loads(args.seed.read_text())
            if isinstance(seed,dict):
                args.data.write_text(json.dumps(seed))
            else:
                templates=seed
                ad=templates[0]
                screen={k:ad[k] for k in ('type','title','subtitle','accent','content')}
                screen.update(id='demo-menu',name='주 메뉴판',status='active',revision=1,location='카운터 · 메인 Pi')
                args.data.write_text(json.dumps(dict(screens=[screen])))
    server = create_server(port=8878, data_path=args.data)
    server.RequestHandlerClass = ResponsiveHandler
    if args.ui_session:
        password=secrets.token_urlsafe(24)
        server.auth.setup('test-admin',password)
        session,status=server.auth.login('test-admin',password,'127.0.0.1')
        server.ui_session=session[0]
    print('Responsive harness: http://localhost:8878/test/mobile', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        if temporary: temporary.cleanup()
