"""Nuvistage local studio: screens, compositions, media and editable information."""
import argparse
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import hmac
import hashlib
import shutil
import os
from pathlib import Path
import platform
import re
import threading
import time
from urllib.parse import urlparse, unquote, parse_qs, urlencode
from uuid import uuid4
from auth import Auth
from devices import DeviceRegistry
from device_api import DeviceAPI
from custom_fonts import CUSTOM_FONT,font_ids,upload_font,delete_font,serve_font,validate_references

ROOT = Path(__file__).resolve().parent
FIELDS = {'name', 'type', 'title', 'subtitle', 'accent', 'status', 'content', 'location'}
DEFAULT_SCREEN = dict(name='새 디스플레이', type='ads', title='새로운 화면',
                      subtitle='여기에 내용을 입력하세요', accent='#6685ff', status='active')
SETTINGS = dict(revision=1, mainScreenId='', systemName='Nuvistage Studio', organization='우리 매장',
                location='예시: 서울 본점', description='매장 디스플레이 운영 시스템입니다. 이 소개는 직접 수정할 수 있습니다.',
                contactTitle='Nuvistage 고객 지원', email='support@example.com', phone='02-0000-0000',
                hours='평일 09:00–18:00', contactBody='문의 안내 예시입니다. 실제 운영 연락처와 이용 안내로 수정해 주세요.')
FONT_IDS = ('pretendard','nanum-gothic','nanum-myeongjo','gowun-dodum','black-han-sans','jua','do-hyeon','gaegu','gugi','gamja-flower','black-white-picture','sunflower','hi-melody','single-day','dongle','gowun-batang','nanum-pen')
FONT_FILES = tuple(f for f in FONT_IDS if f!='pretendard') + ('nanum-gothic-bold','nanum-myeongjo-bold')
FONTS = ('sans','serif','mono') + FONT_IDS
MEDIA_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'video/mp4': 'mp4', 'video/webm': 'webm'}


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def color(value):
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)


def text(value, limit):
    return isinstance(value, str) and len(value) <= limit


def valid_font(value):
    return isinstance(value,str) and (value in FONTS or bool(CUSTOM_FONT.fullmatch(value)))

def validate_content(content,_draft=False):
    if not isinstance(content, dict) or set(content) - {'mode', 'background', 'aspect', 'playbackRate', 'slides', 'menuItems','fontFamily','modeDrafts'}:
        raise ValueError('콘텐츠 형식이 올바르지 않습니다.')
    if content.get('mode') not in ('basic', 'slides', 'images', 'videos', 'menu') or not color(content.get('background')):
        raise ValueError('콘텐츠 모드 또는 배경색을 확인해 주세요.')
    if content.get('aspect') not in ('landscape', 'portrait') or not number(content.get('playbackRate'), .25, 4):
        raise ValueError('화면 방향 또는 영상 배속을 확인해 주세요.')
    if not valid_font(content.get('fontFamily','pretendard')):
        raise ValueError('지원하지 않는 글꼴입니다.')
    slides = content.get('slides')
    if not isinstance(slides, list) or len(slides) > 50:
        raise ValueError('슬라이드는 최대 50개입니다.')
    slide_ids = set()
    for slide in slides:
        if not isinstance(slide,dict) or set(slide)-{'id','duration','transition','elements','background','templateId','templateName','fontFamily'} or not {'id','duration','transition','elements'} <= set(slide):
            raise ValueError('슬라이드 형식이 올바르지 않습니다.')
        if not text(slide['id'], 80) or not slide['id'] or slide['id'] in slide_ids:
            raise ValueError('슬라이드 ID가 중복되거나 올바르지 않습니다.')
        slide_ids.add(slide['id'])
        if ('background' in slide and not color(slide['background'])) or not valid_font(slide.get('fontFamily','pretendard')) or not text(slide.get('templateId',''),100) or not text(slide.get('templateName',''),100):
            raise ValueError('슬라이드 배경·템플릿·글꼴을 확인해 주세요.')
        if not number(slide['duration'], 0, 3600) or slide['transition'] not in ('none', 'fade', 'slide', 'zoom'):
            raise ValueError('재생 시간 또는 전환 효과를 확인해 주세요.')
        if not isinstance(slide['elements'], list) or len(slide['elements']) > 40:
            raise ValueError('슬라이드 요소는 최대 40개입니다.')
        element_ids = set()
        for element in slide['elements']:
            if not isinstance(element, dict) or set(element) - {'id','kind','x','y','w','h','text','color','fontSize','bold','align','mediaId','fit','animation','opacity','radius','fontFamily','lineHeight','letterSpacing','shape','rotation','stroke','strokeWidth','shadow','italic','underline','name','locked','hidden','flipX','flipY','playbackRate'}:
                raise ValueError('요소 형식이 올바르지 않습니다.')
            if not text(element.get('id'), 80) or not element['id'] or element['id'] in element_ids:
                raise ValueError('요소 ID가 올바르지 않습니다.')
            element_ids.add(element['id'])
            if element.get('kind') not in ('text','shape','image','video'):
                raise ValueError('지원하지 않는 요소입니다.')
            if not all(number(element.get(k), 0, 100) for k in ('x','y')) or not all(number(element.get(k), .1, 100) for k in ('w','h')):
                raise ValueError('요소 위치와 크기는 화면 비율 범위 내여야 합니다.')
            if element['x'] + element['w'] > 100.01 or element['y'] + element['h'] > 100.01:
                raise ValueError('요소가 화면 영역을 벗어납니다.')
            if not color(element.get('color', '#ffffff')) or not number(element.get('fontSize', 48), 8, 180):
                raise ValueError('요소 색상과 글자 크기를 확인해 주세요.')
            if not text(element.get('text', ''), 3000) or type(element.get('bold', False)) is not bool or element.get('align', 'left') not in ('left','center','right'):
                raise ValueError('텍스트 속성이 올바르지 않습니다.')
            if element.get('fit', 'cover') not in ('cover','contain'):
                raise ValueError('미디어 맞춤이 올바르지 않습니다.')
            if not number(element.get('opacity', 1), 0, 1) or not number(element.get('radius', 0), 0, 400):
                raise ValueError('요소 투명도와 모서리 값을 확인해 주세요.')
            if not valid_font(element.get('fontFamily','sans')) or not number(element.get('lineHeight',1.25), .8, 2.5) or not number(element.get('letterSpacing',0), -5, 30):
                raise ValueError('글꼴과 텍스트 간격을 확인해 주세요.')
            if not number(element.get('playbackRate',1),.25,4):raise ValueError('영상 재생 배속을 확인해 주세요.')
            if element.get('shape','rect') not in ('rect','rounded','ellipse','triangle','diamond','pentagon','hexagon','star','heart','arrow-right','arrow-left','chevron','speech','line') or not number(element.get('rotation',0),-180,180) or not color(element.get('stroke','#ffffff')) or not number(element.get('strokeWidth',0),0,30) or not text(element.get('name',''),100):raise ValueError('도형·회전·테두리·레이어 이름을 확인해 주세요.')
            if any(type(element.get(key,False)) is not bool for key in ('shadow','italic','underline','locked','hidden','flipX','flipY')):raise ValueError('레이어 표시·잠금·글자 스타일을 확인해 주세요.')
            animation = element.get('animation', {})
            if not isinstance(animation, dict) or set(animation)-{'preset','duration','delay','repeat','exit','exitDuration','exitDelay'} or animation.get('preset','none') not in ('none','fade','rise','slide-left','zoom','pulse') or not number(animation.get('duration',.8), .1, 10) or not number(animation.get('delay',0), 0, 30) or type(animation.get('repeat',False)) is not bool:
                raise ValueError('레이어 애니메이션 설정을 확인해 주세요.')
            if animation.get('exit','none') not in ('none','reverse','fade','drop','slide-right','zoom-out') or not number(animation.get('exitDuration',.6),.1,5) or not number(animation.get('exitDelay',0),0,10):
                raise ValueError('레이어 퇴장 애니메이션을 확인해 주세요.')
            if element['kind'] in ('image','video') and not text(element.get('mediaId'), 80):
                raise ValueError('미디어를 선택해 주세요.')
    if content['mode'] in ('images', 'videos'):
        kind = 'image' if content['mode'] == 'images' else 'video'
        if any(len(s['elements']) != 1 or s['elements'][0]['kind'] != kind for s in slides):
            raise ValueError('단순 재생 모드에는 해당 종류의 미디어만 사용할 수 있습니다.')
    if any(s['duration'] == 0 and not any(e['kind'] == 'video' for e in s['elements']) for s in slides):
        raise ValueError('영상이 없는 슬라이드는 표시 시간을 지정해 주세요.')
    items = content.get('menuItems', [])
    if not isinstance(items, list) or len(items) > 16:
        raise ValueError('메뉴는 한 화면에 최대 16개입니다.')
    for item in items:
        if not isinstance(item, dict) or set(item) != {'name','price','description','soldOut','featured'} or not text(item['name'], 80) or not item['name'].strip() or not text(item['price'], 40) or not text(item['description'], 200) or type(item['soldOut']) is not bool or type(item['featured']) is not bool:
            raise ValueError('메뉴 이름, 가격, 설명을 확인해 주세요.')

    drafts=content.get('modeDrafts',{})
    if not isinstance(drafts,dict) or set(drafts)-{'slides','images','videos','menu'} or (_draft and drafts):raise ValueError('편집 모드 보관 형식이 올바르지 않습니다.')
    for mode,profile in drafts.items():
        if not isinstance(profile,dict) or profile.get('mode')!=mode or 'modeDrafts' in profile:raise ValueError('편집 모드 보관 형식이 올바르지 않습니다.')
        validate_content(profile,True)


def validate(screen):
    if not isinstance(screen, dict) or set(screen) - FIELDS - {'id','revision','queueNumber','queueSettings','queueHistory','callSequence','orders','lastCalledNumber','_playerVersion','_kioskVersion'}:
        raise ValueError('지원하지 않는 화면 설정입니다.')
    if not isinstance(screen.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', screen['id']):
        raise ValueError('화면 ID가 올바르지 않습니다.')
    for key, limit in [('name',100),('title',100),('subtitle',1000)]:
        if not text(screen.get(key), limit) or (key == 'name' and not screen[key].strip()):
            raise ValueError('이름은 필수입니다. 제목 100자, 내용 1000자 이내로 입력해 주세요.')
    if screen.get('type') not in ('ads','menu','notice') or screen.get('status') not in ('active','paused'):
        raise ValueError('화면 유형 또는 상태가 올바르지 않습니다.')
    if not color(screen.get('accent')):
        raise ValueError('테마 색상은 #RRGGBB 형식이어야 합니다.')
    if type(screen.get('revision',1)) is not int or screen.get('revision',1) < 1:
        raise ValueError('화면 버전이 올바르지 않습니다.')
    if not text(screen.get('location',''),100):
        raise ValueError('설치 위치는 100자 이내로 입력해 주세요.')
    if 'content' in screen:
        validate_content(screen['content'])
    return screen


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.media_dir = self.path.with_suffix('.media')
        self.font_dir = self.path.with_suffix('.fonts')
        if not self.path.exists():
            self.write({'screens': []})
        data = self.read()
        if not isinstance(data.get('screens'), list) or len(visible_screens(data)) > 50:
            raise ValueError('저장 파일의 screens 형식이 올바르지 않습니다.')
        ids = set()
        for screen in data['screens']:
            if screen.get('type')!='queue':validate(screen)
            if screen['id'] in ids:
                raise ValueError('중복된 화면 ID가 있습니다.')
            ids.add(screen['id'])

    def read(self):
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('저장 파일은 JSON 객체여야 합니다.')
        for screen in data.get('screens', []):
            screen.setdefault('revision', 1)
        data.setdefault('media', [])
        data.setdefault('settings', dict(SETTINGS))
        if data['settings'].get('systemName') in ('PiSignage Studio','PiSignage'):data['settings']['systemName']='Nuvistage Studio'
        data['settings'].setdefault('mainScreenId','')
        if any(s.get('type')=='queue' and s['id']==data['settings']['mainScreenId'] for s in data['screens']):data['settings']['mainScreenId']=''
        data.setdefault('templates', [])
        data.setdefault('customFonts',[])
        for template in data['templates']:
            if template.get('type')!='queue':template.setdefault('revision',1)
        return data

    def write(self, data):
        temporary = self.path.with_suffix('.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


def valid_signature(mime, head):
    return {'image/png': head.startswith(b'\x89PNG\r\n\x1a\n'),
            'image/jpeg': head.startswith(b'\xff\xd8\xff'),
            'image/webp': head[:4] == b'RIFF' and head[8:12] == b'WEBP',
            'video/mp4': head[4:8] == b'ftyp',
            'video/webm': head.startswith(b'\x1aE\xdf\xa3')}.get(mime, False)


def media_ids(content,include_drafts=True):
    ids={element.get('mediaId') for slide in content.get('slides',[]) for element in slide.get('elements',[]) if element.get('kind') in ('image','video')}
    if include_drafts:
        for profile in content.get('modeDrafts',{}).values():ids.update(media_ids(profile,False))
    return ids


def public_screen(screen):
    return {key:value for key,value in screen.items() if key in FIELDS|{'id','revision'}}

def playback_screen(screen):
    value=public_screen(screen)
    if 'content' in value:value=dict(value,content={k:v for k,v in value['content'].items() if k!='modeDrafts'})
    return value

def visible_screens(data):
    # Preserve retired records in storage; only signage screens are active in this product.
    return [s for s in data['screens'] if s.get('type')!='queue']

def retired_route(path):
    return path in ('/queue','/queue-control','/kiosk-admin','/kiosk.html','/kiosk.js','/kiosk.css','/kiosk-admin.js','/alerts.js') or path.startswith(('/api/integrations/','/api/kiosk','/api/staff-calls')) or (path.startswith('/api/screens/') and path.endswith(('/orders','/call','/kiosk-key')))


class Handler(DeviceAPI,BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(15)

    def handle(self):
        try:super().handle()
        except (ssl.SSLError,TimeoutError,ConnectionError):pass

    def reply(self, code, data, content_type='application/json; charset=utf-8', headers=None):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if isinstance(data, dict) else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', (headers or {}).get('Cache-Control','no-store'))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        for key,value in (headers or {}).items():
            if key != 'Cache-Control': self.send_header(key,value)
        self.end_headers()
        self.wfile.write(raw)

    def media_file(self, path, data):
        item = next((m for m in data['media'] if '/media/' + m['file'] == path), None)
        if not item:
            return self.reply(404, {'error': '미디어를 찾을 수 없습니다.'})
        file = self.server.store.media_dir / item['file']
        size = file.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get('Range')
        if range_header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
            if not match or not any(match.groups()):
                return self.range_error(size)
            a, b = match.groups()
            if not a:
                start = max(0, size - int(b))
                if int(b) == 0:
                    return self.range_error(size)
            else:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            if start > end or start >= size:
                return self.range_error(size)
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', item['mime'])
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with file.open('rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def range_error(self, size):
        self.send_response(416)
        self.send_header('Content-Range', f'bytes */{size}')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path.startswith('/api/v1/'):
                return self.device_api(path,query)
            if path=='/fonts/pretendard.woff2':
                return self.reply(200,(ROOT/'fonts/pretendard.woff2').read_bytes(),'font/woff2',{'Cache-Control':'public, max-age=86400'})
            if path.startswith('/fonts/') and path[len('/fonts/'):].removesuffix('.ttf') in FONT_FILES and path.endswith('.ttf'):
                return self.reply(200,(ROOT/path.lstrip('/')).read_bytes(),'font/ttf',{'Cache-Control':'public, max-age=86400'})
            if retired_route(path):
                return self.reply(410,{'error':'이 기능은 프로젝트에서 제거되었습니다.'})
            if path == '/api/auth/status':
                session = self.server.auth.session(self.headers.get('Cookie'))
                return self.reply(200, dict(configured=self.server.auth.configured, authenticated=bool(session), csrfToken=session['csrf'] if session else '', username=self.server.auth.config.get('username','') if session else '', canSetup=self.server.auth.loopback(self.client_address[0])))
            if path.startswith('/api/player/'):
                return self.player_data(path)
            public = {'/login','/auth.js','/studio.css','/canvas.js','/player.js','/display.html','/fonts.css','/fonts.js','/shapes.js'}
            admin = self.server.auth.session(self.headers.get('Cookie'))
            if path.startswith('/custom-fonts/'):
                with self.server.store.lock:data=self.server.store.read()
                item=next((f for f in data['customFonts'] if '/custom-fonts/'+f['file']==path),None)
                if not item:return self.reply(404,{'error':'글꼴을 찾을 수 없습니다.'})
                if not admin:
                    screen=next((x for x in visible_screens(data) if x['id']==query.get('screen',[''])[0]),None)
                    if not screen or item['id'] not in font_ids(screen.get('content',{}),False) or not self.server.auth.check_media(screen,item,query.get('expires',[''])[0],query.get('sig',[''])[0]):return self.reply(401,{'error':'글꼴 접근 권한이 없습니다.'})
                return serve_font(self,item)
            if path.startswith('/media/') and not admin:
                with self.server.store.lock:
                    data = self.server.store.read()
                item = next((m for m in data['media'] if '/media/'+m['file'] == path),None)
                screen = next((x for x in visible_screens(data) if x['id'] == query.get('screen',[''])[0]),None)
                if not item or not screen or item['id'] not in media_ids(screen.get('content',{}),False) or not self.server.auth.check_media(screen,item,query.get('expires',[''])[0],query.get('sig',[''])[0]):
                    return self.reply(401, {'error':'미디어 접근 권한이 없습니다.'})
                return self.media_file(path,data)
            if path not in public and not admin:
                if path.startswith('/api/'):
                    return self.reply(401, {'error':'관리자 로그인이 필요합니다.'})
                return self.reply(302, b'', headers={'Location':'/login?'+urlencode({'next':self.path})})

            if path.startswith('/api/') or path.startswith('/media/'):
                with self.server.store.lock:
                    data = self.server.store.read()
                if path.startswith('/media/'):
                    return self.media_file(path, data)
                if path == '/api/screens':
                    return self.reply(200, {'screens': [public_screen(x) for x in visible_screens(data)]})
                if path == '/api/fonts':return self.reply(200,{'fonts':data['customFonts']})
                if path == '/api/media':
                    return self.reply(200, {'media': data['media']})
                if path == '/api/settings':
                    return self.reply(200, data['settings'])
                if path == '/api/templates':
                    return self.reply(200, {'templates':[t for t in data['templates'] if t.get('type')!='queue']})
                if path == '/api/players':
                    now = time.time()
                    with self.server.players_lock:
                        self.server.players = {k:v for k,v in self.server.players.items() if now-v['lastSeen'] < 86400}
                        legacy=[dict(v,online=now-v['lastSeen']<15) for v in self.server.players.values()]
                    registered=[dict(screenId=d['screen_id'],clientId=d['device_id'],deviceName=d['device_name'],lastSeen=d['last_seen'],address=d['last_ip'],online=d['online'],registered=True) for d in self.server.devices.list() if d['screen_id']]
                    return self.reply(200,{'players':legacy+registered})
                if path.endswith('/player-link') and path.startswith('/api/screens/'):
                    screen_id = path[len('/api/screens/'):].removesuffix('/player-link')
                    screen = next((x for x in visible_screens(data) if x['id']==screen_id),None)
                    if not screen: return self.reply(404, {'error':'화면을 찾을 수 없습니다.'})
                    return self.reply(200, {'path':'/display.html?id='+screen_id+'#token='+self.server.auth.player_token(screen), 'screenId':screen_id})
                if path == '/api/system':
                    return self.reply(200, dict(version='0.9 Studio', python=platform.python_version(), os=platform.system(), uptime=int(time.monotonic()-self.server.started), screens=len(visible_screens(data)), media=len(data['media']), storageBytes=sum(m['size'] for m in data['media']), access='LAN 서버 · '+self.server.server_address[0] if self.server.server_address[0]!='127.0.0.1' else '로컬 전용 · 127.0.0.1'))
                if path.startswith('/api/screens/'):
                    if any(s['id']==path[len('/api/screens/'):] and s.get('type')=='queue' for s in data['screens']):return self.reply(404,{'error':'이 화면 유형은 제거되었습니다.'})
                    screen = next((s for s in data['screens'] if s['id'] == path[len('/api/screens/'):]), None)
                    return self.reply(200, public_screen(screen)) if screen else self.reply(404, {'error': '삭제되었거나 존재하지 않는 화면입니다.'})
                return self.reply(404, {'error': 'API를 찾을 수 없습니다.'})
            pages = ('/','/index.html','/dashboard','/screens','/ads','/menus','/system','/support','/editor','/media','/templates','/devices','/registration','/playlists','/groups','/schedules','/reports')
            files = {'/operations-admin.js':'operations-admin.js','/scheduled-player.js':'scheduled-player.js','/confirm-dialog.js':'confirm-dialog.js','/shapes.js':'shapes.js','/studio-tools.js':'studio-tools.js','/editor-tools.js':'editor-tools.js','/font-manager.js':'font-manager.js','/device-admin.js':'device-admin.js','/fonts.css':'fonts.css','/fonts.js':'fonts.js','/design.js':'design.js','/login':'login.html','/auth.js':'auth.js','/templates.js':'templates.js','/display.html':'display.html', '/admin.js':'admin.js', '/studio.css':'studio.css', '/canvas.js':'canvas.js', '/player.js':'player.js'}
            name = 'index.html' if path in pages else files.get(path)
            if not name:
                return self.reply(404, {'error': '페이지를 찾을 수 없습니다.'})
            file = ROOT / name
            mime = {'.js':'text/javascript', '.css':'text/css', '.html':'text/html'}[file.suffix]
            return self.reply(200, file.read_bytes(), mime + '; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError):
            self.reply(500, {'error': '저장 데이터 또는 미디어를 읽지 못했습니다.'})

    def auth_action(self, path):
        if self.command != 'POST':
            return self.reply(405, {'error':'지원하지 않는 요청입니다.'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error':'JSON 요청이 필요합니다.'})
        length = int(self.headers.get('Content-Length','0'))
        if not 0 < length <= 4096:
            raise ValueError('로그인 요청을 확인해 주세요.')
        body = json.loads(self.rfile.read(length))
        if not isinstance(body,dict): raise ValueError('요청 형식이 올바르지 않습니다.')
        auth = self.server.auth
        if path == '/api/auth/logout':
            session = auth.session(self.headers.get('Cookie'))
            if not session or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):
                return self.reply(403,{'error':'보안 토큰을 확인해 주세요.'})
            auth.logout(self.headers.get('Cookie',''))
            return self.reply(200,{'ok':True},headers={'Set-Cookie':auth.cookie(logout=True)})
        if path == '/api/auth/setup':
            if not auth.loopback(self.client_address[0]) or urlparse('//'+self.headers.get('Host','')).hostname not in ('localhost','127.0.0.1','::1'):
                return self.reply(403,{'error':'최초 관리자 설정은 메인 서버의 localhost에서 진행해 주세요.'})
            auth.setup(body.get('username'),body.get('password'))
        elif path != '/api/auth/login':
            return self.reply(404,{'error':'API를 찾을 수 없습니다.'})
        result, status = auth.login(body.get('username'),body.get('password'),self.client_address[0])
        if not result:
            message = {429:'로그인 시도가 많습니다. 1분 후 다시 시도해 주세요.',409:'메인 서버에서 최초 관리자 계정을 설정해 주세요.',400:'로그인 정보를 확인해 주세요.',401:'아이디 또는 비밀번호가 일치하지 않습니다.'}[status]
            return self.reply(status,{'error':message})
        token, session = result
        return self.reply(200,{'ok':True,'username':auth.config['username'],'csrfToken':session['csrf']},headers={'Set-Cookie':auth.cookie(token)})

    def player_data(self, path):
        screen_id = path[len('/api/player/'):]
        with self.server.store.lock:
            data = self.server.store.read()
        screen = next((x for x in data['screens'] if x['id']==screen_id),None)
        if not screen: return self.reply(404,{'error':'삭제되었거나 존재하지 않는 화면입니다.'})
        if screen.get('type')=='queue':return self.reply(404,{'error':'이 화면 유형은 제거되었습니다.'})
        token = self.headers.get('Authorization','').removeprefix('Bearer ')
        if not self.server.auth.check_player(token,screen):
            return self.reply(401,{'error':'플레이어 연결 링크가 없거나 만료되었습니다. 관리자에서 연결 링크를 다시 확인해 주세요.'})
        assets=[]
        for item in data['media']:
            if item['id'] in media_ids(screen.get('content',{}),False):
                assets.append(dict(item,url=self.server.auth.sign_media(screen,item)))
        client_id = self.headers.get('X-Player-ID','')[:80]
        if re.fullmatch(r'[A-Za-z0-9_-]{8,80}', client_id):
            with self.server.players_lock:
                if len(self.server.players)>500:
                    oldest=min(self.server.players,key=lambda k:self.server.players[k]['lastSeen'])
                    self.server.players.pop(oldest,None)
                self.server.players[(screen_id,client_id)] = dict(screenId=screen_id,clientId=client_id,lastSeen=int(time.time()),address=self.client_address[0])
        custom=[dict(f,url=self.server.auth.sign_media(screen,f)) for f in data['customFonts'] if f['id'] in font_ids(screen.get('content',{}),False)]
        return self.reply(200,{'screen':playback_screen(screen),'media':assets,'customFonts':custom})

    def delete_media(self, path, data):
        media_id = path[len('/api/media/'):]
        item=next((m for m in data['media'] if m['id']==media_id),None)
        if not item: return self.reply(404,{'error':'미디어를 찾을 수 없습니다.'})
        used=[s['name'] for s in visible_screens(data) if media_id in media_ids(s.get('content',{}))]
        used += ['템플릿: '+t['name'] for t in data['templates'] if t.get('type')!='queue' and media_id in media_ids(t['content'])]
        if any(media_id in media_ids(c,False) for c in self.server.operations.referenced_contents()):used.append('배포된 그룹')
        if used:
            return self.reply(409,{'error':'사용 중인 미디어입니다. 먼저 다음 항목에서 제거해 주세요: '+', '.join(used),'usedBy':used})
        file=self.server.store.media_dir / item['file']
        tombstone=file.with_suffix('.deleting')
        existed=file.exists()
        if existed: file.replace(tombstone)
        data['media'].remove(item)
        try:
            self.server.store.write(data)
        except OSError:
            if existed: tombstone.replace(file)
            raise
        if existed:
            try: tombstone.unlink()
            except OSError: pass
        return self.reply(200,{'ok':True})

    def template_action(self,path,body,data):
        if self.command in ('POST','PATCH'):
            updating=self.command=='PATCH'
            item=next((t for t in data['templates'] if t['id']==path.removeprefix('/api/templates/') and t.get('type')!='queue'),None) if updating else None
            if updating and not item:return self.reply(404,{'error':'템플릿을 찾을 수 없습니다.'})
            if updating and (type(body.get('revision')) is not int or body['revision']!=item.get('revision',1)):return self.reply(409,{'error':'다른 창에서 템플릿을 수정했습니다. 초안을 유지하고 최신 내용을 확인해 주세요.'})
            if (not updating and path!='/api/templates') or set(body)-{'name','type','title','subtitle','accent','content','revision'} or not text(body.get('name'),100) or not body['name'].strip():raise ValueError('템플릿 이름을 1~100자로 입력해 주세요.')
            if 'content' not in body:raise ValueError('템플릿 콘텐츠가 필요합니다.')
            example=dict(DEFAULT_SCREEN,id='template-validation',revision=1);example.update({k:v for k,v in body.items() if k not in ('name','revision')});validate(example);validate_references(example['content'],data)
            values={k:example[k] for k in ('type','title','subtitle','accent','content')}
            if updating:item.update(values,name=body['name'].strip(),updatedAt=int(time.time()),revision=item.get('revision',1)+1)
            else:
                if len([t for t in data['templates'] if t.get('type')!='queue'])>=100:raise ValueError('내 템플릿은 최대 100개입니다.')
                item=dict(id=uuid4().hex,name=body['name'].strip(),createdAt=int(time.time()),revision=1,**values);data['templates'].append(item)
            self.server.store.write(data);return self.reply(200 if updating else 201,{'template':item})
        if path.startswith('/api/templates/') and self.command=='DELETE':
            item=next((t for t in data['templates'] if t['id']==path[len('/api/templates/'):] and t.get('type')!='queue'),None)
            if not item:return self.reply(404,{'error':'템플릿을 찾을 수 없습니다.'})
            data['templates'].remove(item);self.server.store.write(data);return self.reply(200,{'ok':True})
        return self.reply(405,{'error':'지원하지 않는 요청입니다.'})

    def upload(self):
        mime = self.headers.get_content_type()
        length = int(self.headers.get('Content-Length', '0'))
        if mime not in MEDIA_TYPES:
            return self.reply(415, {'error': 'JPEG, PNG, WebP, MP4, WebM 파일을 선택해 주세요.'})
        if length < 12:
            return self.reply(400, {'error': '빈 파일이거나 파일이 올바르지 않습니다.'})
        if length + 16*1024*1024 > shutil.disk_usage(self.server.store.path.parent).free:
            return self.reply(507, {'error':'서버 디스크의 남은 공간이 부족합니다.'})
        name = unquote(self.headers.get('X-Filename', '미디어'))[:200]
        media_id = uuid4().hex
        filename = media_id + '.' + MEDIA_TYPES[mime]
        directory = self.server.store.media_dir
        directory.mkdir(exist_ok=True)
        file = directory / filename
        try:
            with file.open('xb') as stream:
                remaining = length
                head = self.rfile.read(min(32, remaining))
                if not valid_signature(mime, head):
                    raise ValueError('파일 내용과 형식이 일치하지 않습니다.')
                stream.write(head)
                remaining -= len(head)
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError('업로드가 중단되었습니다.')
                    stream.write(chunk)
                    remaining -= len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            item = dict(id=media_id, file=filename, url='/media/'+filename, name=name, mime=mime, size=length)
            with self.server.store.lock:
                data = self.server.store.read()
                data['media'].append(item)
                self.server.store.write(data)
            self.reply(201, {'media': item})
        except Exception:
            file.unlink(missing_ok=True)
            raise

    def mutate(self):
        try:
            origin = self.headers.get('Origin')
            if (origin and origin != ('https://' if isinstance(self.connection,ssl.SSLSocket) else 'http://') + self.headers.get('Host','')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.reply(403, {'error': '다른 사이트에서의 변경 요청은 허용되지 않습니다.'})
            path = unquote(urlparse(self.path).path)
            if path.startswith('/api/v1/'):return self.device_api(path)
            if retired_route(path):return self.reply(410,{'error':'이 기능은 프로젝트에서 제거되었습니다.'})
            if path.startswith('/api/auth/'):
                return self.auth_action(path)
            session = self.server.auth.session(self.headers.get('Cookie'))
            if not session:
                return self.reply(401, {'error':'관리자 로그인이 필요합니다.'})
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):
                return self.reply(403, {'error':'보안 토큰이 만료되었습니다. 새로고침 후 다시 시도해 주세요.'})
            if path=='/api/fonts' and self.command=='POST':return upload_font(self)
            if path == '/api/media' and self.command == 'POST':
                return self.upload()
            if self.headers.get_content_type() != 'application/json':
                return self.reply(415, {'error': 'JSON 형식으로 요청해 주세요.'})
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 512000:
                return self.reply(413, {'error': '요청 크기가 올바르지 않습니다.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('JSON 객체가 필요합니다.')
            with self.server.store.lock:
                data = self.server.store.read()
                if path == '/api/settings' and self.command == 'PATCH':
                    if type(body.get('revision')) is not int or body['revision'] != data['settings']['revision']:
                        return self.reply(409, {'error': '다른 창에서 변경되었습니다. 새로고침 후 다시 편집해 주세요.'})
                    if set(body) - set(SETTINGS) or any(not text(v, 3000) for k,v in body.items() if k != 'revision'):
                        raise ValueError('정보는 항목당 3000자 이내로 입력해 주세요.')
                    if 'mainScreenId' in body and body['mainScreenId'] and not any(x['id']==body['mainScreenId'] for x in visible_screens(data)):
                        raise ValueError('주 메뉴판으로 지정할 화면을 선택해 주세요.')
                    data['settings'].update(body)
                    data['settings']['revision'] += 1
                    self.server.store.write(data)
                    return self.reply(200, data['settings'])
                if path.startswith('/api/fonts/') and self.command=='DELETE':return delete_font(self,path,body,data)
                if path.startswith('/api/media/') and self.command == 'DELETE':
                    return self.delete_media(path,data)
                if path.startswith('/api/templates'):
                    return self.template_action(path,body,data)
                if path.endswith('/player-link') and path.startswith('/api/screens/'):
                    screen_id=path[len('/api/screens/'):].removesuffix('/player-link')
                    screen=next((x for x in visible_screens(data) if x['id']==screen_id),None)
                    if not screen: return self.reply(404,{'error':'화면을 찾을 수 없습니다.'})
                    if self.command!='POST': return self.reply(405,{'error':'지원하지 않는 요청입니다.'})
                    screen['_playerVersion']=screen.get('_playerVersion',0)+1
                    self.server.store.write(data)
                    return self.reply(200,{'ok':True})
                collection = path == '/api/screens'
                if not collection and not path.startswith('/api/screens/'):
                    return self.reply(404, {'error': 'API를 찾을 수 없습니다.'})
                if (collection and self.command != 'POST') or (not collection and self.command == 'POST'):
                    return self.reply(405, {'error': '지원하지 않는 요청 방식입니다.'})
                if collection:
                    if len(visible_screens(data)) >= 50:
                        raise ValueError('디스플레이는 최대 50개까지 만들 수 있습니다.')
                    if set(body) - FIELDS:
                        raise ValueError('지원하지 않는 설정입니다.')
                    screen = dict(DEFAULT_SCREEN, **body, id='screen-'+uuid4().hex, revision=1)
                    screen.setdefault('content',dict(mode='slides',fontFamily='pretendard',background='#142039',aspect='landscape',playbackRate=1,slides=[],menuItems=[]))
                    validate(screen)
                    data['screens'].append(screen)
                else:
                    screen_id = path[len('/api/screens/'):]
                    screen = next((s for s in data['screens'] if s['id'] == screen_id), None)
                    if screen and screen.get('type')=='queue':return self.reply(410,{'error':'이 화면 유형은 제거되었습니다.'})
                    if screen is None:
                        return self.reply(404, {'error': '삭제되었거나 존재하지 않는 화면입니다.'})
                    if type(body.get('revision')) is not int or body['revision'] != screen['revision']:
                        return self.reply(409, {'error': '다른 창에서 변경되었습니다. 새로고침 후 다시 편집해 주세요.'})
                    if self.command == 'DELETE':
                        if set(body) != {'revision'}: raise ValueError('삭제 요청을 확인해 주세요.')
                        data['screens'].remove(screen)
                        if data['settings'].get('mainScreenId') == screen['id']:
                            data['settings']['mainScreenId']=''
                            data['settings']['revision']+=1
                    else:
                        if set(body) - FIELDS - {'revision'}:
                            raise ValueError('지원하지 않는 설정입니다.')
                        updated = validate(dict(screen, **body))
                        updated['revision'] += 1
                        screen.update(updated)
                validate_references(screen.get('content',{}),data)
                self.server.store.write(data)
            self.reply(201 if collection else 200, {'ok': True, 'screen': public_screen(screen)})
        except (ValueError, UnicodeError) as error:
            self.reply(400, {'error': str(error)})
        except OSError:
            self.reply(500, {'error': '저장하지 못했습니다. 디스크 공간과 파일 권한을 확인해 주세요.'})

    do_POST = mutate
    do_PATCH = mutate
    do_DELETE = mutate

    def log_message(self, fmt, *args):
        pass


def create_server(host='127.0.0.1', port=8765, data_path=ROOT / 'data.json', secure_cookie=False, tls_cert=None, tls_key=None, allow_insecure_device_loopback=False):
    store = Store(data_path)
    auth = Auth(Path(data_path).with_suffix('.auth.json'),secure_cookie or bool(tls_cert))
    server = ThreadingHTTPServer((host, port), Handler)
    server.tls_enabled=bool(tls_cert)
    server.allow_insecure_device_loopback=allow_insecure_device_loopback
    from operations import Operations
    server.operations=Operations(Path(data_path).with_suffix('.operations.json'))
    server.devices=DeviceRegistry(Path(data_path).with_suffix('.devices.json'))
    if tls_cert:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(tls_cert,tls_key);server.socket=context.wrap_socket(server.socket,server_side=True,do_handshake_on_connect=False)
    server.store = store
    server.auth = auth
    server.players = {}
    server.players_lock = threading.Lock()
    server.started = time.monotonic()
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1', help='LAN 운영은 0.0.0.0')
    parser.add_argument('--tls-cert',type=Path,help='서버 인증서 PEM')
    parser.add_argument('--tls-key',type=Path,help='서버 개인키 PEM')
    parser.add_argument('--mdns',action='store_true',help='동일 LAN에 HTTPS 서버를 자동 검색용으로 게시')
    parser.add_argument('--advertise-host',help='서버 인증서 SAN에 포함된 DNS 이름 (예: pisignage.local)')
    parser.add_argument('--secure-cookie', action='store_true', help='HTTPS 프록시 뒤에서만 사용')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data', type=Path, default=ROOT / 'data.json')
    args = parser.parse_args()
    try:
        if bool(args.tls_cert)!=bool(args.tls_key):raise ValueError('TLS 인증서와 개인키를 함께 지정해 주세요.')
        server = create_server(host=args.host, port=args.port, data_path=args.data,secure_cookie=args.secure_cookie,tls_cert=args.tls_cert,tls_key=args.tls_key)
        discovery=None
        if args.mdns:
            from discovery import advertise
            if not args.tls_cert:raise ValueError('자동 검색 게시에는 HTTPS 인증서가 필요합니다.')
            discovery=advertise(server,args.advertise_host)
            server.discovery_status='advertising'
        print(f'Nuvistage Studio: {"https" if args.tls_cert else "http"}://localhost:{args.port}', flush=True)
        try:server.serve_forever()
        finally:
            if discovery:discovery.close()
            server.server_close()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        raise SystemExit(f'서버를 시작하지 못했습니다: {error}')
