import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'data.json'
        self.cookie = ''
        self.csrf = ''
        self.start()

    def start(self):
        self.server = create_server(port=0, data_path=self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.cookie = ''
        self.csrf = ''
        self.authenticate()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def authenticate(self):
        status = json.loads(self.request('/api/auth/status', authenticated=False)[1])
        route = '/api/auth/login' if status['configured'] else '/api/auth/setup'
        code, raw = self.request(route, 'POST', {'username':'test-admin','password':'test-only-strong-passphrase'}, authenticated=False)
        self.assertEqual(code, 200, raw)
        self.csrf = json.loads(raw)['csrfToken']

    def request(self, path='/api/screens', method='GET', body=None, headers=None, authenticated=True):
        request_headers = {'Content-Type':'application/json'}
        if authenticated:
            request_headers.update({'Cookie':self.cookie,'X-CSRF-Token':self.csrf})
        request_headers.update(headers or {})
        req = Request(self.url + path, method=method, data=None if body is None else json.dumps(body).encode(), headers=request_headers)
        try:
            with urlopen(req) as response:
                self.last_headers = dict(response.headers)
                cookie = response.headers.get('Set-Cookie')
                if cookie: self.cookie = cookie.split(';')[0]
                return response.status, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.read()

    def create(self, name):
        code, raw = self.request(method='POST', body={'name': name})
        self.assertEqual(code, 201)
        return json.loads(raw)['screen']

    def test_independent_update_restart_delete(self):
        a, b = self.create('A'), self.create('B')
        self.assertNotEqual(a['id'], b['id'])
        path = '/api/screens/' + a['id']
        code, raw = self.request(path, 'PATCH', {'title': 'A만 변경', 'subtitle': '콘텐츠 A', 'revision': 1})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.request('/api/screens/' + b['id'])[1]), b)
        self.stop()
        self.start()
        self.assertEqual(json.loads(self.request(path)[1])['title'], 'A만 변경')
        self.assertEqual(self.request(path, 'DELETE', {'revision': 2})[0], 200)
        self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(json.loads(self.request('/api/screens/' + b['id'])[1]), b)

    def test_validation_and_conflict(self):
        screen = self.create('A')
        path = '/api/screens/' + screen['id']
        for body in [{'accent': 'red'}, {'name': ' '}, {'type': 'evil'}, {'status': 'online'}, {'queueNumber': True}, {'subtitle': 'a' * 1001}, {'unknown': 1}]:
            self.assertEqual(self.request(path, 'PATCH', dict(body, revision=1))[0], 400)
        self.assertEqual(self.request(path, 'PATCH', {'title': 'ok', 'revision': 1})[0], 200)
        self.assertEqual(self.request(path, 'PATCH', {'title': 'lost', 'revision': 1})[0], 409)
        self.assertEqual(self.request(path, 'DELETE', {'revision': 1})[0], 409)
        self.assertEqual(json.loads(self.request(path)[1])['title'], 'ok')

    def test_routes_security_and_failed_write(self):
        for path in ['/', '/display.html?id=x', '/admin.js']:
            self.assertEqual(self.request(path)[0], 200)
        for path in ['/data.json', '/server.py', '/../data.json']:
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request(method='POST', body={}, headers={'Origin': 'https://other.example', 'Content-Type': 'application/json'})[0], 403)
        self.assertEqual(self.request(method='POST', body=[], headers={'Content-Type': 'application/json'})[0], 400)
        from unittest.mock import patch
        with patch.object(self.server.store, 'write', side_effect=OSError('disk full')):
            self.assertEqual(self.request(method='POST', body={})[0], 500)
        self.assertEqual(json.loads(self.request()[1])['screens'], [])

    def test_legacy_data_retained(self):
        screen = self.create('원본')
        del screen['revision']
        self.stop()
        self.path.write_text(json.dumps({'screens': [screen]}))
        self.start()
        actual = json.loads(self.request()[1])['screens'][0]
        self.assertEqual(actual['revision'], 1)
        self.assertEqual(actual['id'], screen['id'])

    def upload(self, raw, mime='image/png', filename='테스트.png'):
        from urllib.parse import quote
        req = Request(self.url + '/api/media', method='POST', data=raw,
                      headers={'Content-Type': mime, 'X-Filename': quote(filename), 'Cookie':self.cookie,'X-CSRF-Token':self.csrf})
        try:
            with urlopen(req) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_media_composition_ranges_and_persistence(self):
        import base64
        raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
        code, uploaded = self.upload(raw)
        self.assertEqual(code, 201)
        media = uploaded['media']
        self.assertEqual(media['name'], '테스트.png')
        self.assertEqual(self.request(media['url'])[1], raw)
        self.assertEqual(self.request(media['url'], headers={'Range':'bytes=0-7'})[0], 206)
        self.assertEqual(self.request(media['url'], headers={'Range':'bytes=0-7'})[1], raw[:8])
        self.assertEqual(self.request(media['url'], headers={'Range':'bytes=-4'})[1], raw[-4:])
        self.assertEqual(self.request(media['url'], headers={'Range':'bytes=99999-'})[0], 416)
        self.assertEqual(self.upload(b'not an image at all')[0], 400)
        self.assertEqual(self.upload(raw, 'text/html')[0], 415)
        self.assertEqual(len(json.loads(self.request('/api/media')[1])['media']), 1)
        a, b = self.create('광고 A'), self.create('광고 B')
        content = dict(mode='images', background='#142039', aspect='landscape', playbackRate=1,
                       menuItems=[], slides=[dict(id='slide-1', duration=2, transition='fade',
                       elements=[dict(id='e1', kind='image', mediaId=media['id'], x=0, y=0, w=100, h=100)])])
        path = '/api/screens/' + a['id']
        self.assertEqual(self.request(path, 'PATCH', {'revision':1, 'content':content})[0], 200)
        self.assertEqual(json.loads(self.request('/api/screens/' + b['id'])[1])['content']['mode'],'slides')
        self.stop()
        self.start()
        self.assertEqual(json.loads(self.request(path)[1])['content'], content)
        self.assertEqual(self.request(media['url'])[1], raw)
        content['slides'][0]['elements'][0]['x'] = 99
        self.assertEqual(self.request(path, 'PATCH', {'revision':2, 'content':content})[0], 400)
        content['slides'][0]['elements'][0]['x'] = 0
        content['slides'][0]['elements'][0]['mediaId'] = 'missing'
        self.assertEqual(self.request(path, 'PATCH', {'revision':2, 'content':content})[0], 400)
        content['slides'][0]['elements'][0]['mediaId'] = media['id']
        content['slides'][0]['duration'] = 0
        self.assertEqual(self.request(path, 'PATCH', {'revision':2, 'content':content})[0], 400)


    def test_menu_and_video_validation(self):
        screen = self.create('메뉴')
        content = dict(mode='menu', background='#112233', aspect='portrait', playbackRate=1, slides=[],
                       menuItems=[dict(name='아메리카노',price='3,500원',description='커피',soldOut=False,featured=True)])
        path='/api/screens/'+screen['id']
        self.assertEqual(self.request(path,'PATCH',dict(revision=1,type='menu',content=content))[0],200)
        content['menuItems'][0]['soldOut']='false'
        self.assertEqual(self.request(path,'PATCH',dict(revision=2,content=content))[0],400)
        content['menuItems'][0]['soldOut']=False
        content['playbackRate']=float('nan')
        self.assertEqual(self.request(path,'PATCH',dict(revision=2,content=content))[0],400)

    def test_authentication_sessions_csrf_and_throttling(self):
        self.assertEqual(self.request(authenticated=False)[0],401)
        self.assertEqual(self.request('/api/settings',authenticated=False)[0],401)
        self.assertIn(b'auth.js',self.request('/dashboard',authenticated=False)[1])
        self.assertEqual(self.request(method='POST',body={},headers={'X-CSRF-Token':''})[0],403)
        status=json.loads(self.request('/api/auth/status')[1])
        self.assertTrue(status['authenticated'])
        self.assertNotIn('password',json.dumps(status).lower())
        auth_file=self.path.with_suffix('.auth.json')
        self.assertNotIn('test-only-strong-passphrase',auth_file.read_text())
        self.assertEqual(auth_file.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.request('/api/auth/setup','POST',dict(username='other',password='long-enough-password'),authenticated=False)[0],400)
        self.assertEqual(self.request('/api/auth/logout','POST',{})[0],200)
        self.assertEqual(self.request()[0],401)
        self.authenticate()
        self.assertIn('HttpOnly',self.last_headers['Set-Cookie'])
        self.assertIn('SameSite=Strict',self.last_headers['Set-Cookie'])
        for _ in range(5):
            self.assertEqual(self.request('/api/auth/login','POST',dict(username='wrong',password='wrong'),authenticated=False)[0],401)
        self.assertEqual(self.request('/api/auth/login','POST',dict(username='wrong',password='wrong'),authenticated=False)[0],429)

    def test_player_permissions_signatures_rotation_and_restart(self):
        import base64
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
        item=self.upload(png)[1]['media']
        a,b=self.create('A'),self.create('B')
        content=dict(mode='images',background='#112233',aspect='landscape',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=2,transition='none',elements=[dict(id='e',kind='image',mediaId=item['id'],x=0,y=0,w=100,h=100)])])
        self.assertEqual(self.request('/api/screens/'+a['id'],'PATCH',dict(revision=1,content=content))[0],200)
        link=json.loads(self.request('/api/screens/'+a['id']+'/player-link')[1])['path']
        token=link.split('#token=')[1]
        headers={'Authorization':'Bearer '+token,'X-Player-ID':'test-player-12345'}
        player_path='/api/player/'+a['id']
        self.assertEqual(self.request(player_path,authenticated=False)[0],401)
        code,raw=self.request(player_path,headers=headers,authenticated=False)
        self.assertEqual(code,200)
        result=json.loads(raw)
        self.assertEqual(result['screen']['name'],'A')
        self.assertEqual(len(result['media']),1)
        self.assertNotIn('_playerVersion',result['screen'])
        signed=result['media'][0]['url']
        self.assertEqual(self.request(signed,authenticated=False)[1],png)
        self.assertEqual(self.request(item['url'],authenticated=False)[0],401)
        self.assertEqual(self.request(signed+'x',authenticated=False)[0],401)
        self.assertEqual(self.request('/api/player/'+b['id'],headers=headers,authenticated=False)[0],401)
        self.assertEqual(self.request('/api/screens/'+a['id'],'PATCH',dict(revision=2,title='hack'),headers=headers,authenticated=False)[0],401)
        self.assertTrue(json.loads(self.request('/api/players')[1])['players'][0]['online'])
        self.stop();self.start()
        self.assertEqual(self.request(player_path,headers=headers,authenticated=False)[0],200)
        self.assertEqual(self.request('/api/screens/'+a['id']+'/player-link','POST',{})[0],200)
        self.assertEqual(self.request(player_path,headers=headers,authenticated=False)[0],401)
        self.assertEqual(self.request(signed,authenticated=False)[0],401)


    def test_media_delete_guards_template_roundtrip_and_rollback(self):
        import base64
        from unittest.mock import patch
        raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=')
        item=self.upload(raw)[1]['media'];path='/api/media/'+item['id']
        file=self.server.store.media_dir/item['file']
        with patch.object(self.server.store,'write',side_effect=OSError('disk full')):
            self.assertEqual(self.request(path,'DELETE',{})[0],500)
        self.assertTrue(file.exists())
        self.assertEqual(self.request(item['url'])[1],raw)
        content=dict(mode='images',background='#112233',aspect='landscape',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=2,transition='none',elements=[dict(id='e',kind='image',mediaId=item['id'],x=0,y=0,w=100,h=100)])])
        template=dict(name='내 메뉴',type='menu',title='TITLE',subtitle='',accent='#123456',content=content)
        code,body=self.request('/api/templates','POST',template);self.assertEqual(code,201)
        saved=json.loads(body)['template']
        self.assertEqual(self.request(path,'DELETE',{})[0],409)
        self.stop();self.start()
        self.assertEqual(json.loads(self.request('/api/templates')[1])['templates'][0]['content'],content)
        self.assertEqual(self.request('/api/templates/'+saved['id'],'DELETE',{})[0],200)
        screen=self.create('미디어 사용 화면')
        self.assertEqual(self.request('/api/screens/'+screen['id'],'PATCH',dict(revision=1,content=content))[0],200)
        self.assertEqual(self.request(path,'DELETE',{})[0],409)
        self.assertEqual(self.request('/api/screens/'+screen['id'],'DELETE',dict(revision=2))[0],200)
        self.assertEqual(self.request(path,'DELETE',{})[0],200)
        self.assertFalse(file.exists())
        self.assertEqual(self.request(item['url'])[0],404)

    def test_layer_animation_validation_and_screen_naming_main_assignment(self):
        screen=self.create('처음 이름');path='/api/screens/'+screen['id']
        element=dict(id='e',kind='text',text='TEST',x=10,y=10,w=80,h=30,fontSize=96,color='#ffffff',animation=dict(preset='rise',duration=.8,delay=.2,repeat=False),fontFamily='serif',letterSpacing=2,lineHeight=1.1,opacity=.8)
        content=dict(mode='slides',background='#112233',aspect='landscape',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=8,transition='fade',elements=[element])])
        code,raw=self.request(path,'PATCH',dict(revision=1,name='주 메뉴판',location='카운터 · 메인 Pi',content=content));self.assertEqual(code,200)
        element['animation']['delay']=float('nan')
        self.assertEqual(self.request(path,'PATCH',dict(revision=2,content=content))[0],400)
        settings=json.loads(self.request('/api/settings')[1])
        self.assertEqual(self.request('/api/settings','PATCH',dict(revision=settings['revision'],mainScreenId=screen['id']))[0],200)
        self.stop();self.start()
        current=json.loads(self.request(path)[1]);self.assertEqual(current['name'],'주 메뉴판')
        self.assertEqual(current['location'],'카운터 · 메인 Pi')
        self.assertEqual(current['content']['slides'][0]['elements'][0]['animation']['preset'],'rise')
        self.assertEqual(json.loads(self.request('/api/settings')[1])['mainScreenId'],screen['id'])
        self.assertEqual(self.request(path,'DELETE',dict(revision=2))[0],200)
        self.assertEqual(json.loads(self.request('/api/settings')[1])['mainScreenId'],'')

    def test_upload_larger_than_old_100mb_limit_streams_to_disk(self):
        import http.client
        total=101*1024*1024
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
        connection.putrequest('POST','/api/media')
        for k,v in {'Content-Type':'image/png','Content-Length':str(total),'X-Filename':'stream-test.png','Cookie':self.cookie,'X-CSRF-Token':self.csrf}.items():
            connection.putheader(k,v)
        connection.endheaders()
        head=b'\x89PNG\r\n\x1a\n'+b'0'*24
        connection.send(head)
        remaining=total-len(head);chunk=b'0'*65536
        while remaining:
            count=min(remaining,len(chunk));connection.send(chunk[:count]);remaining-=count
        response=connection.getresponse();self.assertEqual(response.status,201)
        item=json.loads(response.read())['media'];connection.close()
        self.assertEqual(item['size'],total)
        self.assertEqual((self.server.store.media_dir/item['file']).stat().st_size,total)
        self.assertEqual(self.request('/api/media/'+item['id'],'DELETE',{})[0],200)

    def test_local_setup_guard_and_player_config(self):
        from unittest.mock import patch
        from auth import Auth
        with patch.object(Auth,'loopback',return_value=False):
            self.assertEqual(self.request('/api/auth/setup','POST',dict(username='outside',password='long-password-outside'),authenticated=False)[0],403)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
        from run_player import load_player_url,chromium_command
        file=Path(self.temp.name)/'player.json'
        url='http://192.168.1.10:8765/display.html?id=screen-1#token='+('a'*64)
        file.write_text(json.dumps(dict(playerUrl=url)))
        self.assertEqual(load_player_url(file),url)
        self.assertEqual(chromium_command(url,'chromium')[-1],url)
        file.write_text(json.dumps(dict(playerUrl='javascript:alert(1)')))
        with self.assertRaises(ValueError):load_player_url(file)








    def test_removed_business_routes_and_legacy_data_preserved(self):
        active=self.create('광고판')
        legacy=dict(id='legacy-orders',type='queue',name='이전 보드',title='주문',subtitle='',accent='#123456',status='active',revision=5,orders=dict(preparing=[dict(id='o1',number='101')],ready=[]))
        old_template=dict(id='legacy-t',type='queue',name='이전 주문 템플릿',content={})
        self.stop()
        raw=json.loads(self.path.read_text());raw['screens'].append(legacy);raw['templates']=[old_template];raw['orderReceipts']={'keep':{'old':'data'}};raw['kiosk']={'old':'config'}
        self.path.write_text(json.dumps(raw));self.start()
        self.assertEqual([s['id'] for s in json.loads(self.request()[1])['screens']],[active['id']])
        self.assertEqual(json.loads(self.request('/api/templates')[1])['templates'],[])
        self.assertEqual(self.request('/api/screens/legacy-orders')[0],404)
        self.assertEqual(self.request('/api/player/legacy-orders',authenticated=False)[0],404)
        self.assertEqual(self.request('/api/screens/legacy-orders','PATCH',dict(revision=5,title='blocked'))[0],410)
        self.assertEqual(self.request(method='POST',body=dict(type='queue',name='새 호출'))[0],400)
        for route in ('/queue','/queue-control','/kiosk-admin','/kiosk.html','/api/kiosk-config','/api/kiosk-link','/api/kiosk/screen/catalog','/api/staff-calls','/api/integrations/orders','/api/screens/legacy-orders/orders','/api/screens/legacy-orders/call','/api/screens/legacy-orders/kiosk-key'):
            self.assertEqual(self.request(route,authenticated=False)[0],410,route)
        self.assertEqual(self.request('/api/integrations/orders','POST',{},authenticated=False)[0],410)
        self.create('메뉴판')
        stored=json.loads(self.path.read_text());self.assertEqual(next(s for s in stored['screens'] if s['id']==legacy['id']),legacy);self.assertEqual(stored['templates'],[old_template]);self.assertEqual(stored['orderReceipts'],raw['orderReceipts']);self.assertEqual(stored['kiosk'],raw['kiosk'])
        self.assertEqual(json.loads(self.request('/api/system')[1])['screens'],2)

    def test_settings_and_signage_page_routes(self):
        for page in ['/dashboard','/screens','/ads','/menus','/system','/support','/editor','/canvas.js','/player.js','/studio.css']:
            self.assertEqual(self.request(page)[0],200)
        settings=json.loads(self.request('/api/settings')[1]);body=dict(revision=settings['revision'],organization='내 매장',email='owner@example.com')
        self.assertEqual(self.request('/api/settings','PATCH',body)[0],200)
        self.assertEqual(self.request('/api/settings','PATCH',body)[0],409)
        self.stop();self.start();self.assertEqual(json.loads(self.request('/api/settings')[1])['organization'],'내 매장')

    def test_local_fonts_independent_slides_and_empty_media_modes(self):
        from copy import deepcopy
        families=('nanum-gothic','nanum-myeongjo','gowun-dodum','black-han-sans','jua','do-hyeon','gaegu','gugi','gamja-flower','black-white-picture','sunflower','hi-melody','single-day','dongle','gowun-batang','nanum-pen')
        for name in families:
            code,raw=self.request('/fonts/'+name+'.ttf',authenticated=False);self.assertEqual(code,200);self.assertIn(raw[:4],(b'\x00\x01\x00\x00',b'OTTO'))
        self.assertEqual(self.request('/fonts/pretendard.woff2',authenticated=False)[1][:4],b'wOF2')
        e=dict(id='e',kind='text',text='한국어',x=10,y=10,w=80,h=30,fontFamily='jua',animation=dict(preset='rise',exit='reverse',exitDuration=.6,exitDelay=.2))
        a=dict(id='a',duration=1,transition='fade',elements=[e],background='#111111',templateId='a',templateName='A');b=deepcopy(a);b.update(id='b',background='#ffffff',templateName='B')
        content=dict(mode='slides',aspect='landscape',background='#123456',fontFamily='pretendard',playbackRate=1,slides=[a,b],menuItems=[])
        screen=json.loads(self.request(method='POST',body=dict(name='독립 디자인',content=content))[1])['screen'];content['slides'][1]['background']='#aabbcc'
        self.assertEqual(self.request('/api/screens/'+screen['id'],'PATCH',dict(revision=1,content=content))[0],200)
        self.stop();self.start();actual=json.loads(self.request('/api/screens/'+screen['id'])[1])
        self.assertEqual(actual['content']['slides'][0]['background'],'#111111');self.assertEqual(actual['content']['slides'][1]['background'],'#aabbcc')
        for mode in ('images','videos'):
            empty=dict(mode=mode,aspect='landscape',background='#123456',playbackRate=1,slides=[],menuItems=[])
            self.assertEqual(self.request(method='POST',body=dict(name='빈 미디어',content=empty))[0],201)

    def test_mode_archives_and_template_revision(self):
        from copy import deepcopy
        content=dict(mode='slides',aspect='landscape',background='#142039',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=8,transition='fade',elements=[dict(id='e',kind='shape',shape='star',rotation=35,stroke='#ffffff',strokeWidth=2,shadow=True,locked=True,hidden=False,x=10,y=10,w=20,h=20)])])
        archived=deepcopy(content)
        content=dict(mode='images',aspect='landscape',background='#142039',playbackRate=1,menuItems=[],slides=[],modeDrafts=dict(slides=archived))
        screen=self.create('보관 검증');path='/api/screens/'+screen['id']
        self.assertEqual(self.request(path,'PATCH',dict(revision=1,content=content))[0],200)
        self.stop();self.start()
        self.assertEqual(json.loads(self.request(path)[1])['content'],content)
        from server import playback_screen
        self.assertNotIn('modeDrafts',playback_screen(json.loads(self.request(path)[1]))['content'])
        template=dict(name='직접 만든 템플릿',type='ads',content=content)
        code,raw=self.request('/api/templates','POST',template);self.assertEqual(code,201,raw)
        item=json.loads(raw)['template'];target='/api/templates/'+item['id']
        self.assertEqual(self.request(target,'PATCH',dict(template,revision=1,name='수정 완료'))[0],200)
        self.assertEqual(self.request(target,'PATCH',dict(template,revision=1))[0],409)
        invalid=deepcopy(content);invalid['modeDrafts']['slides']['modeDrafts']={}
        self.assertEqual(self.request(path,'PATCH',dict(revision=2,content=invalid))[0],400)
        invalid=deepcopy(content);invalid['modeDrafts']['slides']['slides'][0]['elements'][0]['rotation']=999
        self.assertEqual(self.request(path,'PATCH',dict(revision=2,content=invalid))[0],400)

    def test_custom_font_upload_reference_and_player_access(self):
        from copy import deepcopy
        from unittest.mock import patch
        raw=(Path(__file__).resolve().parents[1]/'fonts/gowun-dodum.ttf').read_bytes()
        def upload_font(payload,authenticated=True):
            headers={'Content-Type':'application/octet-stream','X-Filename':'fixture.ttf'}
            if authenticated:headers.update(Cookie=self.cookie,**{'X-CSRF-Token':self.csrf})
            try:
                with urlopen(Request(self.url+'/api/fonts',method='POST',data=payload,headers=headers)) as r:return r.status,json.loads(r.read())
            except HTTPError as e:return e.code,json.loads(e.read())
        self.assertEqual(upload_font(b'test',False)[0],401)
        self.assertEqual(upload_font(b'not a font')[0],400)
        code,result=upload_font(raw);self.assertEqual(code,201,result);font=result['font']
        self.assertEqual(self.request(font['url'],authenticated=False)[0],401)
        self.assertEqual(self.request(font['url'])[1],raw)
        content=dict(mode='slides',aspect='landscape',background='#142039',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=8,transition='none',elements=[dict(id='e',kind='text',text='한국어',fontFamily=font['id'],x=10,y=10,w=50,h=20)])])
        screen=self.create('글꼴 검증');path='/api/screens/'+screen['id']
        self.assertEqual(self.request(path,'PATCH',dict(revision=1,content=content))[0],200)
        token=json.loads(self.request(path+'/player-link')[1])['path'].split('#token=')[1]
        code,payload=self.request('/api/player/'+screen['id'],headers={'Authorization':'Bearer '+token,'X-Player-ID':'font-test-player'},authenticated=False)
        self.assertEqual(code,200,payload);signed=json.loads(payload)['customFonts'][0]['url']
        self.assertEqual(self.request(signed,authenticated=False)[1],raw)
        self.assertEqual(self.request('/api/fonts/'+font['id'],'DELETE',{})[0],409)
        inactive=dict(mode='images',aspect='landscape',background='#142039',playbackRate=1,menuItems=[],slides=[],modeDrafts=dict(slides=deepcopy(content)))
        self.assertEqual(self.request(path,'PATCH',dict(revision=2,content=inactive))[0],200)
        self.assertEqual(self.request('/api/fonts/'+font['id'],'DELETE',{})[0],409)
        self.assertEqual(self.request(signed,authenticated=False)[0],401)
        unknown=deepcopy(content);unknown['slides'][0]['elements'][0]['fontFamily']='custom-'+'f'*32
        self.assertEqual(self.request(path,'PATCH',dict(revision=3,content=unknown))[0],400)
        self.assertEqual(self.request(path,'DELETE',dict(revision=3))[0],200)
        file=self.server.store.font_dir/font['file']
        with patch.object(self.server.store,'write',side_effect=OSError('disk full')):
            self.assertEqual(self.request('/api/fonts/'+font['id'],'DELETE',{})[0],500)
        self.assertTrue(file.exists())
        self.assertEqual(self.request('/api/fonts/'+font['id'],'DELETE',{})[0],200)
        self.assertFalse(file.exists())

if __name__ == '__main__':
    unittest.main()
