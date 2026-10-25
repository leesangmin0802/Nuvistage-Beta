import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import create_server
from device_client import DeviceClient,ClientError
from scripts.create_tls import create_certificates

PASSWORD='device-registration-test-only'
ADMIN='admin-test-passphrase-only'

class DeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_temp=tempfile.TemporaryDirectory();cls.certs=create_certificates(Path(cls.cert_temp.name)/'tls',['pisignage-test.local'])
    @classmethod
    def tearDownClass(cls):cls.cert_temp.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/'data.json';self.context=ssl.create_default_context(cafile=self.certs/'ca.pem');self.cookie='';self.csrf='';self.start()
    def start(self,port=0):
        self.server=create_server(port=port,data_path=self.data,tls_cert=self.certs/'server.pem',tls_key=self.certs/'server-key.pem');self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url=f'https://localhost:{self.server.server_port}';self.cookie=''
        path='/api/auth/login' if self.server.auth.configured else '/api/auth/setup'
        code,result=self.req(path,'POST',dict(username='test-admin',password=ADMIN),auth=False);self.assertEqual(code,200);self.csrf=result['csrfToken']
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def tearDown(self):self.stop();self.temp.cleanup()
    def req(self,path,method='GET',body=None,auth=True,token=None,device_id=None,raw=False,extra=None):
        headers={'Content-Type':'application/json'}
        if auth:headers.update(Cookie=self.cookie,**{'X-CSRF-Token':self.csrf})
        if token:headers['Authorization']='Bearer '+token
        if device_id:headers['X-Device-ID']=device_id
        headers.update(extra or {})
        request=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers=headers)
        try:
            with urlopen(request,context=self.context,timeout=10) as response:
                if response.headers.get('Set-Cookie'):self.cookie=response.headers['Set-Cookie'].split(';')[0]
                data=response.read();return response.status,(data if raw else json.loads(data))
        except HTTPError as error:
            with error:return error.code,json.loads(error.read())
    def allow(self,password=PASSWORD):
        code,settings=self.req('/api/v1/settings/registration');self.assertEqual(code,200)
        code,result=self.req('/api/v1/settings/registration','PATCH',dict(revision=settings['revision'],registration_allowed=True,registration_password=password));self.assertEqual(code,200);return result
    def register(self,name='카운터 Player',device_id=None,password=PASSWORD,nonce=None):
        body=dict(device_id=device_id or str(uuid.uuid4()),device_name=name,registration_password=password,player_version='0.1.0')
        if nonce:body['registration_nonce']=nonce
        return self.req('/api/v1/devices/register','POST',body,auth=False)
    def client(self,name='가상 Player',directory='player'):
        client=DeviceClient(self.root/directory,self.certs/'ca.pem');client.register(self.url,name,PASSWORD);return client
    def test_https_registration_permissions_and_secret_storage(self):
        self.assertEqual(self.register()[0],423);self.allow();code,result=self.register();self.assertEqual(code,201)
        did=result['device']['device_id'];token=result['device_token'];self.assertEqual(len(token),43)
        stored=self.server.devices.read();device=stored['devices'][did];self.assertNotIn(token,json.dumps(stored));self.assertNotIn(PASSWORD,json.dumps(stored));self.assertEqual(device['token_hash'],hashlib.sha256(token.encode()).hexdigest());self.assertEqual(os.stat(self.server.devices.path).st_mode&0o777,0o600)
        self.assertEqual(self.req('/api/v1/devices/me',auth=False,token=token)[0],200)
        self.assertEqual(self.req('/api/v1/devices/me',auth=False)[0],401)
        self.assertEqual(self.req('/api/v1/devices/')[0],404)
        self.assertEqual(self.req('/api/v1/devices',auth=False,token=token)[0],401)
        self.assertEqual(self.req('/api/screens',auth=False,token=token)[0],401)
        self.assertEqual(self.req('/api/v1/settings/registration','PATCH',dict(revision=2,registration_allowed=False),extra={'X-CSRF-Token':'wrong'})[0],403)
        listing=self.req('/api/v1/devices')[1]['devices'];self.assertEqual(len(listing),1);self.assertNotIn('token_hash',listing[0]);self.assertNotIn('registration_nonce_hash',listing[0]);self.assertNotIn('password',self.req('/api/v1/settings/registration')[1])
    def test_password_lock_rate_limits_and_safe_failure_audit(self):
        self.allow()
        for _ in range(8):self.assertEqual(self.register(password='wrong')[0],401)
        self.assertEqual(self.register()[0],429)
        settings=self.req('/api/v1/settings/registration')[1];self.assertEqual(len(settings['failures']),9)
        serialized=json.dumps(settings,ensure_ascii=False);self.assertNotIn('wrong',serialized);self.assertIn('요청 제한',serialized)
        self.server.devices.attempts={};code,result=self.req('/api/v1/settings/registration','PATCH',dict(revision=settings['revision'],registration_allowed=False));self.assertEqual(code,200);self.assertEqual(self.register()[0],423)
    def test_duplicate_identity_lost_response_and_authenticated_confirmation(self):
        self.allow();did=str(uuid.uuid4());nonce=secrets.token_urlsafe(32);code,first=self.register(device_id=did,nonce=nonce);self.assertEqual(code,201)
        self.assertEqual(self.register(device_id=did,nonce=secrets.token_urlsafe(32))[0],409)
        code,recovered=self.register(device_id=did,nonce=nonce);self.assertEqual(code,201);self.assertTrue(recovered['recovered']);self.assertNotEqual(first['device_token'],recovered['device_token'])
        self.assertEqual(self.req('/api/v1/devices/me',auth=False,token=first['device_token'])[0],401)
        token=recovered['device_token'];self.assertEqual(self.req('/api/v1/devices/heartbeat','POST',dict(device_id=did,player_version='0.1.0'),auth=False,token=token)[0],200)
        self.assertEqual(self.register(device_id=did,nonce=nonce)[0],409)
        self.assertEqual(self.req('/api/v1/devices/heartbeat','POST',dict(device_id=str(uuid.uuid4()),player_version='0.1.0'),auth=False,token=token)[0],401)
    def test_multiple_players_dhcp_password_change_and_restart(self):
        self.allow();a=self.client('카운터','a');b=self.client('입구','b');self.assertNotEqual(a.config['device_id'],b.config['device_id']);a.reconnect(lambda:[]);b.reconnect(lambda:[])
        device=self.server.devices.authenticate(a.config['device_token']);self.server.devices.heartbeat(a.config['device_token'],dict(device_id=device['device_id'],player_version='0.1.1'),'192.168.50.123')
        listed=self.req('/api/v1/devices')[1]['devices'];self.assertEqual(len(listed),2);self.assertTrue(all(d['online'] for d in listed));self.assertIn('192.168.50.123',[d['last_ip'] for d in listed])
        self.allow('changed-registration-test-passphrase');self.assertEqual(self.req('/api/v1/devices/me',auth=False,token=a.config['device_token'])[0],200)
        self.assertEqual(self.register(password=PASSWORD)[0],401)
        port=self.server.server_port;self.stop();self.start(port)
        rebooted=DeviceClient(self.root/'a');self.assertEqual(rebooted.config['device_id'],a.config['device_id']);self.assertEqual(rebooted.reconnect(lambda:[])['device']['device_id'],a.config['device_id']);self.assertNotIn(PASSWORD,(self.root/'a/credentials.json').read_text());self.assertEqual(os.stat(self.root/'a/credentials.json').st_mode&0o777,0o600)
    def test_assignment_device_bound_media_revocation_and_delete(self):
        self.allow();client=self.client();token=client.config['device_token'];did=client.config['device_id']
        self.assertIsNone(self.req('/api/v1/devices/me/screen',auth=False,token=token)[1]['screen'])
        png=b'\x89PNG\r\n\x1a\nfixture'
        request=Request(self.url+'/api/media',data=png,method='POST',headers={'Content-Type':'image/png','X-Filename':'test.png','Cookie':self.cookie,'X-CSRF-Token':self.csrf})
        with urlopen(request,context=self.context) as response:item=json.loads(response.read())['media']
        content=dict(mode='images',background='#112233',aspect='landscape',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=5,transition='none',elements=[dict(id='e',kind='image',mediaId=item['id'],x=0,y=0,w=100,h=100)])])
        code,result=self.req('/api/screens','POST',dict(name='메뉴판',content=content));screen=result['screen'];self.assertEqual(code,201)
        self.assertEqual(self.req('/api/v1/devices/'+did+'/assign','POST',dict(revision=1,screen_id=screen['id']))[0],200)
        result=self.req('/api/v1/devices/me/screen',auth=False,token=token)[1];url=result['media'][0]['url'];self.assertEqual(self.req(url,auth=False,raw=True)[1],png)
        cached=client.reconnect(lambda:[]);self.assertEqual(cached['screen']['id'],screen['id']);self.assertTrue(list((client.directory/'cache/media').glob('*.png')))
        self.assertIn('data:font/woff2;base64,',(client.directory/'cache/fonts/pretendard.css').read_text());self.assertNotIn(token,(client.directory/'cache/snapshot.js').read_text())
        self.assertEqual(self.req('/api/v1/devices/'+did,'PATCH',dict(revision=2,blocked=True))[0],200);self.assertEqual(self.req(url,auth=False)[0],401);self.assertEqual(self.req('/api/v1/devices/me',auth=False,token=token)[0],403)
        self.assertEqual(self.req('/api/v1/devices/'+did,'PATCH',dict(revision=3,blocked=False))[0],200);self.assertEqual(self.req('/api/v1/devices/'+did+'/revoke','POST',dict(revision=4))[0],200);self.assertEqual(self.req('/api/v1/devices/me',auth=False,token=token)[0],401)
        self.assertEqual(self.req('/api/v1/devices/'+did+'/reset','POST',dict(revision=5))[0],200);client.register(self.url,'카운터 재등록',PASSWORD);self.assertNotEqual(client.config['device_token'],token)
        device=self.req('/api/v1/devices/me',auth=False,token=client.config['device_token'])[1]['device'];self.assertEqual(self.req('/api/v1/devices/'+did,'DELETE',dict(revision=device['revision']))[0],200);self.assertEqual(self.req('/api/v1/devices/me',auth=False,token=client.config['device_token'])[0],401)
    def test_device_fonts_signed_cache_and_revocation(self):
        self.allow();client=self.client();did=client.config['device_id'];token=client.config['device_token']
        binary=(Path(__file__).resolve().parents[1]/'fonts/gowun-dodum.ttf').read_bytes()
        request=Request(self.url+'/api/fonts',data=binary,method='POST',headers={'Content-Type':'application/octet-stream','X-Filename':'fixture.ttf','Cookie':self.cookie,'X-CSRF-Token':self.csrf})
        with urlopen(request,context=self.context) as response:font=json.loads(response.read())['font']
        content=dict(mode='slides',background='#112233',aspect='landscape',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=5,transition='none',elements=[dict(id='e',kind='text',text='글꼴 출력',fontFamily=font['id'],x=10,y=10,w=70,h=20),dict(id='shape',kind='shape',shape='heart',x=5,y=40,w=20,h=20)])])
        screen=self.req('/api/screens','POST',dict(name='외부 글꼴',content=content))[1]['screen']
        self.assertEqual(self.req('/api/v1/devices/'+did+'/assign','POST',dict(revision=1,screen_id=screen['id']))[0],200)
        snapshot=self.req('/api/v1/devices/me/screen',auth=False,token=token)[1];url=snapshot['customFonts'][0]['url']
        self.assertEqual(self.req(url,auth=False,raw=True)[1],binary)
        client.reconnect(lambda:[])
        self.assertEqual((client.directory/'cache/custom-font-files'/font['file']).read_bytes(),binary)
        css=(client.directory/'cache/fonts'/(font['id']+'.css')).read_text();self.assertIn('data:font/ttf;base64,',css);self.assertIn('Pi '+font['id'],css)
        runtime=(client.directory/'cache/index.html').read_text();self.assertIn('function shapeMarkup',runtime);self.assertIn('installCustomFonts(data.customFonts',runtime)
        self.assertEqual(self.req('/api/v1/devices/'+did+'/revoke','POST',dict(revision=2))[0],200)
        self.assertEqual(self.req(url,auth=False)[0],401)

    def test_network_outage_cache_server_identity_and_recovery(self):
        self.allow();client=self.client();client.reconnect(lambda:[]);snapshot=(client.directory/'cache/snapshot.json').read_bytes();real=self.url
        with patch.object(client,'request',side_effect=ClientError('오프라인')):
            with self.assertRaises(ClientError):client.reconnect(lambda:[])
        self.assertEqual((client.directory/'cache/snapshot.json').read_bytes(),snapshot)
        view=(client.directory/'cache/snapshot.js').read_bytes();diagnostics=json.loads(snapshot);diagnostics['device']['last_seen']+=100;client.publish(diagnostics);self.assertEqual((client.directory/'cache/snapshot.js').read_bytes(),view)
        client.config['server_url']='https://localhost:1'
        recovered=client.reconnect(lambda:[dict(server_id=client.config['server_id'],url=real)]);self.assertEqual(recovered['server_id'],client.config['server_id']);self.assertEqual(client.config['server_url'],real)
        with self.assertRaises(ClientError):client.verify(real,str(uuid.uuid4()))
        outsider=DeviceClient(self.root/'untrusted')
        with self.assertRaises(ClientError):outsider.verify(real)
        with self.assertRaises(ClientError):client.verify('http://localhost:8765')
    def test_registration_write_failure_is_atomic_and_conflicts(self):
        self.allow()
        with patch.object(self.server.devices,'write',side_effect=OSError('full')):self.assertEqual(self.register()[0],500)
        self.assertEqual(self.req('/api/v1/devices')[1]['devices'],[])
        code,result=self.register();did=result['device']['device_id'];self.assertEqual(code,201)
        self.assertEqual(self.req('/api/v1/devices/'+did,'PATCH',dict(revision=0,device_name='잘못된 버전'))[0],409)
        self.assertEqual(self.req('/api/v1/devices/'+did+'/assign','POST',dict(revision=1,screen_id='missing'))[0],404)
        self.assertEqual(self.req('/api/v1/devices/'+did,'PATCH',dict(revision=1,device_name='로비 화면'))[0],200)
        body=dict(device_id='not-a-uuid',device_name='이름',registration_password=PASSWORD,player_version='0.1.0')
        self.assertEqual(self.req('/api/v1/devices/register','POST',body,auth=False)[0],400)
    def test_http_device_endpoints_are_rejected(self):
        insecure=create_server(port=0,data_path=self.root/'http.json');thread=threading.Thread(target=insecure.serve_forever,daemon=True);thread.start()
        try:
            request=Request(f'http://localhost:{insecure.server_port}/api/v1/devices/register',data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as caught:urlopen(request)
            self.assertEqual(caught.exception.code,426);caught.exception.close()
        finally:insecure.shutdown();insecure.server_close();thread.join()
    def test_mdns_discovers_two_distinct_https_server_candidates(self):
        try:import zeroconf
        except ImportError:self.skipTest('requirements-device.txt의 zeroconf가 필요합니다.')
        from discovery import advertise,discover
        from types import SimpleNamespace
        other=str(uuid.uuid4());fake=SimpleNamespace(devices=SimpleNamespace(server_id=other),server_port=8444)
        a=advertise(self.server,hostname='pisignage-test.local',addresses=['127.0.0.1'],interfaces=['127.0.0.1'])
        b=advertise(fake,hostname='pisignage-second.local',addresses=['127.0.0.1'],interfaces=['127.0.0.1'])
        try:
            found=discover(2,interfaces=['127.0.0.1']);ids={s['server_id'] for s in found};self.assertIn(self.server.devices.server_id,ids);self.assertIn(other,ids);self.assertTrue(all(s['url'].startswith('https://') for s in found))
        finally:b.close();a.close()

    def test_code_pairing_without_shared_password_and_recovery(self):
        from pairing import normalize_code
        config=self.req('/api/v1/settings/registration')[1]
        self.assertEqual(self.req('/api/v1/settings/registration','PATCH',dict(revision=config['revision'],registration_allowed=True))[0],200)
        client=DeviceClient(self.root/'code-player',self.certs/'ca.pem');code=client.pairing_code
        self.assertEqual(len(code),16);self.assertEqual(DeviceClient(client.directory).pairing_code,code)
        client.begin_pairing(self.url,'코드 Player');self.assertEqual(client.poll_pairing()['status'],'waiting')
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code),auth=False)[0],401)
        self.assertEqual(self.req('/api/v1/pairing/poll','POST',dict(device_id=client.config['device_id'],pairing_secret=secrets.token_urlsafe(32)),auth=False)[0],401)
        code_formatted='-'.join(code[i:i+4] for i in range(0,16,4));self.assertEqual(normalize_code(code_formatted),code)
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code_formatted,device_name='입구 Player'))[0],201)
        secret=client.config['pairing_secret'];result=client.poll_pairing();token=result['device_token'];self.assertEqual(result['status'],'registered')
        # A lost first response is recoverable until the first authenticated heartbeat.
        again=self.req('/api/v1/pairing/poll','POST',dict(device_id=client.config['device_id'],pairing_secret=secret),auth=False)[1];self.assertEqual(again['device_token'],token)
        self.assertNotIn(secret,json.dumps(self.server.devices.read()));self.assertNotIn(token,json.dumps(self.server.devices.read()))
        client.reconnect(lambda:[]);self.assertEqual(self.req('/api/v1/pairing/poll','POST',dict(device_id=client.config['device_id'],pairing_secret=secret),auth=False)[0],401)
        rebooted=DeviceClient(client.directory);self.assertEqual(rebooted.config['device_token'],token);rebooted.reconnect(lambda:[])
        d=self.req('/api/v1/devices/me',auth=False,token=token)[1]['device'];self.assertEqual(self.req('/api/v1/devices/'+d['device_id']+'/reset','POST',dict(revision=d['revision']))[0],200)
        client.config.pop('device_token');client.save();client.begin_pairing(self.url,'재연결');self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code))[0],201);self.assertEqual(client.poll_pairing()['status'],'registered');self.assertNotEqual(client.config['device_token'],token)

    def test_code_pairing_lock_collision_and_bad_requests(self):
        client=DeviceClient(self.root/'code-a',self.certs/'ca.pem');client.begin_pairing(self.url,'A');code=client.pairing_code
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code))[0],423)
        config=self.req('/api/v1/settings/registration')[1];self.req('/api/v1/settings/registration','PATCH',dict(revision=config['revision'],registration_allowed=True))
        b=DeviceClient(self.root/'code-b',self.certs/'ca.pem');b.config['pairing_code']=code;b.save()
        with self.assertRaises(ClientError) as caught:b.begin_pairing(self.url,'B')
        self.assertEqual(caught.exception.status,409)
        for body in ({},{'device_id':client.config['device_id'],'pairing_secret':False}):self.assertEqual(self.req('/api/v1/pairing/poll','POST',body,auth=False)[0],400)
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code='123'))[0],400)
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code,screen_id='missing'))[0],404)
        waiting=self.req('/api/v1/pairing/pending')[1]['pending'];self.assertEqual(len(waiting),1);self.assertNotIn('code',waiting[0])
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code))[0],201)
        self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code))[0],404)

    def workflow_fixture(self):
        self.allow();client=self.client();content=dict(mode='slides',aspect='landscape',background='#112233',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=8,transition='fade',elements=[dict(id='e',kind='text',text='배포 전 원본',x=10,y=10,w=70,h=20,color='#ffffff',fontSize=50)])])
        screen=self.req('/api/screens','POST',dict(name='운영 콘텐츠',content=content))[1]['screen']
        playlist=self.req('/api/v1/operations/playlists','POST',dict(name='기본 재생목록',items=[dict(screen_id=screen['id'],duration=0)]))[1]
        body=dict(name='로비 그룹',device_ids=[client.config['device_id']],default_playlist_id=playlist['id'],timezone='Asia/Seoul',rules=[],ticker='운영 안내',clock=True)
        code,group=self.req('/api/v1/operations/groups','POST',body);self.assertEqual(code,201,group)
        return client,screen,playlist,group,body

    def test_playlist_group_deploy_snapshot_override_and_diagnostics(self):
        client,screen,playlist,group,body=self.workflow_fixture();gid=group['id'];base='/api/v1/operations/groups/'+gid
        self.assertIsNone(client.reconnect(lambda:[])['screen'])
        self.assertEqual(self.req(base+'/deploy','POST',dict(revision=1))[0],201)
        first=client.reconnect(lambda:[]);self.assertEqual(first['screen']['content']['slides'][0]['elements'][0]['text'],'배포 전 원본');self.assertEqual(first['program']['revision'],1);self.assertNotIn('device_ids',first['program'])
        changed=copy.deepcopy(screen['content']);changed['slides'][0]['elements'][0]['text']='배포 후 변경'
        self.assertEqual(self.req('/api/screens/'+screen['id'],'PATCH',dict(revision=1,title='수정',content=changed))[0],200)
        second=client.reconnect(lambda:[]);self.assertEqual(second['screen']['content']['slides'][0]['elements'][0]['text'],'배포 전 원본')
        listing=self.req('/api/v1/operations')[1];self.assertTrue(listing['groups'][0]['dirty']);self.assertTrue(any(e['action']=='device_received' for e in listing['events']))
        self.assertEqual(self.req(base+'/deploy','POST',dict(revision=2))[0],201);updated=client.reconnect(lambda:[]);self.assertEqual(updated['program']['revision'],2);self.assertEqual(updated['screen']['content']['slides'][0]['elements'][0]['text'],'배포 후 변경')
        code,result=self.req(base+'/override','POST',dict(revision=3,message='긴급 안내',minutes=1));self.assertEqual(code,201,result)
        result=client.reconnect(lambda:[]);self.assertEqual(result['screen']['name'],'임시 안내')
        self.assertEqual(self.req(base+'/override','POST',dict(revision=4,clear=True))[0],201);self.assertEqual(client.reconnect(lambda:[])['screen']['name'],'기본 재생목록')
        self.assertEqual(self.req(base,'PATCH',dict(body,revision=1))[0],409)
        self.assertEqual(self.req('/api/v1/operations/playlists/'+playlist['id'],'DELETE',dict(revision=1))[0],409)
        token=client.config['device_token'];self.assertEqual(self.req('/api/v1/operations',auth=False,token=token)[0],401)
        self.assertEqual(self.req('/api/v1/operations/groups','POST',body,extra={'X-CSRF-Token':'bad'})[0],403)

    def test_group_zones_and_schedule_cache_preserves_all_assets(self):
        client,screen,playlist,group,body=self.workflow_fixture();png=b'\x89PNG\r\n\x1a\nfixture';request=Request(self.url+'/api/media',data=png,method='POST',headers={'Content-Type':'image/png','X-Filename':'test.png','Cookie':self.cookie,'X-CSRF-Token':self.csrf})
        with urlopen(request,context=self.context) as response:asset=json.loads(response.read())['media']
        c=dict(mode='images',aspect='landscape',background='#112233',playbackRate=1,menuItems=[],slides=[dict(id='s',duration=5,transition='fade',elements=[dict(id='e',kind='image',mediaId=asset['id'],x=0,y=0,w=100,h=100)])])
        other=self.req('/api/screens','POST',dict(name='보조 콘텐츠',content=c))[1]['screen'];p2=self.req('/api/v1/operations/playlists','POST',dict(name='보조 재생',items=[dict(screen_id=other['id'],duration=0)]))[1]
        rule=dict(id='night',playlist_id=p2['id'],paused=False,days=[0,1,2,3,4,5,6],start='00:00',end='00:00',date_from='2099-01-01',date_to='',priority=5)
        code,g=self.req('/api/v1/operations/groups/'+group['id'],'PATCH',dict(body,revision=1,rules=[rule],layout='six',zone_playlists=[p2['id']]*5));self.assertEqual(code,200,g)
        self.assertEqual(self.req('/api/v1/operations/groups/'+group['id']+'/deploy','POST',dict(revision=2))[0],201)
        snapshot=client.reconnect(lambda:[]);self.assertEqual(len(snapshot['program']['zones']),6);self.assertEqual(len(snapshot['media']),1)
        self.assertEqual(self.req(snapshot['media'][0]['url'],auth=False,raw=True)[1],png)
        self.assertTrue((client.directory/'cache/media'/(asset['id']+'.png')).exists())
        self.req('/api/screens/'+other['id'],'DELETE',dict(revision=1));self.assertEqual(self.req('/api/media/'+asset['id'],'DELETE',{})[0],409)
        self.assertEqual(self.req('/api/v1/operations/groups/'+group['id'],'DELETE',dict(revision=3))[0],200)
        self.assertEqual(self.req('/api/media/'+asset['id'],'DELETE',{})[0],200)

    def test_virtual_process_can_pair_by_code_without_password(self):
        config=self.req('/api/v1/settings/registration')[1];self.req('/api/v1/settings/registration','PATCH',dict(revision=config['revision'],registration_allowed=True))
        process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve().parents[1]/'scripts/device_player.py'),'--state',str(self.root/'new-process'),'--ca',str(self.certs/'ca.pem'),'--server',self.url,'--name','가상 코드 Player','--once','--headless'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            import select,re
            ready,_,_=select.select([process.stdout],[],[],8);self.assertTrue(ready)
            first=process.stdout.readline();code=re.sub(r'[^0-9]','',first);self.assertEqual(len(code),16)
            deadline=time.time()+8
            while time.time()<deadline:
                if self.req('/api/v1/pairing/pending')[1]['pending']:break
                time.sleep(.05)
            self.assertEqual(self.req('/api/v1/pairing/claim','POST',dict(code=code))[0],201)
            stdout,stderr=process.communicate(timeout=15);self.assertEqual(process.returncode,0,stderr);self.assertIn('연결됨',stdout)
            credentials=json.loads((self.root/'new-process/credentials.json').read_text());self.assertNotIn(credentials['device_token'],stdout+stderr);self.assertNotIn('pairing_secret',credentials)
        finally:
            if process.poll() is None:process.kill();process.communicate()

    def test_virtual_process_uses_saved_credentials(self):
        self.allow();client=self.client();result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/device_player.py'),'--state',str(client.directory),'--once','--headless','--setup-ui'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('연결됨',result.stdout);self.assertNotIn(client.config['device_token'],result.stdout+result.stderr);self.assertNotIn(PASSWORD,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
