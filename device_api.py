"""Versioned registration API; admin cookies and device tokens are separate authorities."""
import hashlib
import hmac
import json
import ssl
import time
from urllib.parse import parse_qs,urlparse
from devices import DeviceError,valid_id
from custom_fonts import font_ids,serve_font
from operations import program_screens

class DeviceAPI:
    def device_json(self,max_length=8192):
        if self.headers.get_content_type()!='application/json':raise DeviceError('JSON 형식으로 요청해 주세요.',415)
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise DeviceError('요청 크기를 확인해 주세요.')
        if not 0<length<=max_length:raise DeviceError('요청 크기가 허용 범위를 초과했습니다.',413)
        try:body=json.loads(self.rfile.read(length))
        except (ValueError,UnicodeError):raise DeviceError('요청 JSON 형식을 확인해 주세요.')
        if not isinstance(body,dict):raise DeviceError('JSON 객체가 필요합니다.')
        return body
    def device_transport(self):
        if not isinstance(self.connection,ssl.SSLSocket) and not (self.server.allow_insecure_device_loopback and self.server.auth.loopback(self.client_address[0])):
            raise DeviceError('장치 등록과 연결에는 인증된 HTTPS 서버 주소가 필요합니다.',426)
    def device_admin(self):
        session=self.server.auth.session(self.headers.get('Cookie'))
        if not session:raise DeviceError('관리자 로그인이 필요합니다.',401)
        if self.command!='GET' and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']):raise DeviceError('보안 토큰이 만료되었습니다. 새로고침해 주세요.',403)
    def device_signature(self,device,screen_id,media_id,expires):
        message=f"device-media:{device['device_id']}:{device['token_hash']}:{device['revision']}:{screen_id}:{media_id}:{expires}"
        return hmac.new(bytes.fromhex(self.server.auth.config['secret']),message.encode(),hashlib.sha256).hexdigest()
    def device_api(self,path,query=None):
        registry=self.server.devices
        try:
            if path=='/api/v1/operations' or path.startswith('/api/v1/operations/'):
                from operations_api import handle_operations
                return handle_operations(self,path)
            if path=='/api/v1/server-info' and self.command=='GET':
                return self.reply(200,dict(server_id=registry.server_id,name='Nuvistage Server',api_version=1,https_required=True,pairing='code',tls=bool(self.server.tls_enabled),discovery=getattr(self.server,'discovery_status','not_started')))
            if path=='/api/v1/pairing/claim':
                self.device_admin()
                if self.command!='POST':raise DeviceError('지원하지 않는 요청입니다.',405)
                from pairing import claim
                body=self.device_json()
                with self.server.store.lock:
                    data=self.server.store.read()
                    if not isinstance(body.get('screen_id',''),str) or (body.get('screen_id') and not any(s['id']==body['screen_id'] and s.get('type')!='queue' for s in data['screens'])):raise DeviceError('배정할 출력 화면을 찾을 수 없습니다.',404)
                    result=claim(registry,body,self.server.auth.config['secret'])
                return self.reply(201,result)
            if path=='/api/v1/pairing/pending':
                self.device_admin()
                if self.command!='GET':raise DeviceError('지원하지 않는 요청입니다.',405)
                from pairing import pending_public
                return self.reply(200,dict(pending=pending_public(registry)))
            if path in ('/api/v1/pairing/announce','/api/v1/pairing/poll'):
                self.device_transport()
                if self.command!='POST':raise DeviceError('지원하지 않는 요청입니다.',405)
                from pairing import announce,poll
                body=self.device_json()
                result=announce(registry,body,self.client_address[0]) if path.endswith('/announce') else poll(registry,body,self.client_address[0],self.server.auth.config['secret'])
                return self.reply(200,result)
            if path=='/api/v1/settings/registration':
                self.device_admin()
                if self.command=='GET':settings=registry.settings()
                elif self.command=='PATCH':settings=registry.configure(self.device_json())
                else:raise DeviceError('지원하지 않는 요청 방식입니다.',405)
                settings.update(tls_enabled=self.server.tls_enabled,discovery=getattr(self.server,'discovery_status','not_started'))
                return self.reply(200,settings)
            if path=='/api/v1/devices' or (path.startswith('/api/v1/devices/') and path.split('/')[4] not in ('register','heartbeat','me','media','fonts')):
                self.device_admin()
                if path=='/api/v1/devices':
                    if self.command!='GET':raise DeviceError('지원하지 않는 요청 방식입니다.',405)
                    return self.reply(200,dict(devices=registry.list(),server_id=registry.server_id))
                parts=path.strip('/').split('/')
                if len(parts) not in (4,5) or not valid_id(parts[3]):raise DeviceError('장치 API를 찾을 수 없습니다.',404)
                device_id=parts[3];action=parts[4] if len(parts)==5 else ''
                if (self.command,action) not in (('PATCH',''),('DELETE',''),('POST','assign'),('POST','revoke'),('POST','reset')):raise DeviceError('지원하지 않는 장치 요청입니다.',405)
                body=self.device_json()
                if action=='assign':
                    if not isinstance(body.get('screen_id'),str):raise DeviceError('출력 화면을 선택해 주세요.')
                    with self.server.store.lock:
                        data=self.server.store.read()
                        if body['screen_id'] and not any(s['id']==body['screen_id'] and s.get('type')!='queue' for s in data['screens']):raise DeviceError('배정할 출력 화면이 없습니다.',404)
                        result=registry.change(device_id,'assign',body)
                else:result=registry.change(device_id,{'PATCH':'update','DELETE':'delete','POST':action}[self.command],body)
                return self.reply(200,dict(device=result))
            if path.startswith('/api/v1/devices/'):
                self.device_transport()
                if path=='/api/v1/devices/register' and self.command=='POST':return self.reply(201,registry.register(self.device_json(),self.client_address[0]))
                token=self.headers.get('Authorization','').removeprefix('Bearer ')
                if path.startswith('/api/v1/devices/fonts/') and self.command=='GET':
                    q=query or {};did=q.get('device_id',[''])[0];fid=path.split('/')[-1];expires=q.get('expires',[''])[0];sig=q.get('sig',[''])[0]
                    with registry.lock:
                        d=registry.read()['devices'].get(did)
                        if not d or d['blocked'] or not d['token_hash'] or not expires.isdigit() or len(expires)>12 or not time.time()<=int(expires)<=time.time()+901 or not hmac.compare_digest(sig,self.device_signature(d,d['screen_id'],fid,expires)):raise DeviceError('장치 글꼴 인증이 만료되었습니다.',401)
                    with self.server.store.lock:data=self.server.store.read()
                    s,program=self.server.operations.delivery(d,data);assigned=program_screens(program) if program else ([s] if s else [])
                    f=next((f for f in data['customFonts'] if f['id']==fid),None)
                    if not s or not f or not any(fid in font_ids(screen.get('content',{}),False) for screen in assigned):raise DeviceError('이 장치에 배정된 글꼴이 아닙니다.',404)
                    return serve_font(self,f)
                if path.startswith('/api/v1/devices/media/') and self.command=='GET':
                    q=query or {};did=q.get('device_id',[''])[0];mid=path.split('/')[-1];expires=q.get('expires',[''])[0];sig=q.get('sig',[''])[0]
                    with registry.lock:
                        device=registry.read()['devices'].get(did)
                        if not device or device['blocked'] or not device['token_hash'] or not expires.isdigit() or not time.time()<=int(expires)<=time.time()+901:raise DeviceError('장치 미디어 인증이 만료되었습니다.',401)
                        expected=self.device_signature(device,device['screen_id'],mid,expires)
                        if not hmac.compare_digest(sig,expected):raise DeviceError('장치 미디어 인증이 올바르지 않습니다.',401)
                    with self.server.store.lock:data=self.server.store.read()
                    screen,program=self.server.operations.delivery(device,data);assigned=program_screens(program) if program else ([screen] if screen else [])
                    used={e.get('mediaId') for s in assigned for slide in s.get('content',{}).get('slides',[]) for e in slide['elements'] if e['kind'] in ('image','video')}
                    item=next((m for m in data['media'] if m['id']==mid and mid in used),None)
                    if not screen or not item:raise DeviceError('이 장치에 배정된 미디어가 아닙니다.',404)
                    return self.media_file('/media/'+item['file'],data)
                if path=='/api/v1/devices/heartbeat' and self.command=='POST':
                    body=self.device_json();device=registry.heartbeat(token,body,self.client_address[0]);self.server.operations.heartbeat_event(device,body.get('report'));return self.reply(200,dict(device=device,server_id=registry.server_id))
                if path not in ('/api/v1/devices/me','/api/v1/devices/me/screen') or self.command!='GET':raise DeviceError('장치 API를 찾을 수 없습니다.',404)
                device=registry.authenticate(token,self.headers.get('X-Device-ID'))
                if path.endswith('/me'):return self.reply(200,dict(device=registry.public(device),server_id=registry.server_id))
                with self.server.store.lock:data=self.server.store.read()
                screen,program=self.server.operations.delivery(device,data);assets=[];assigned=program_screens(program) if program else ([screen] if screen else [])
                if screen:
                    ids={e.get('mediaId') for s in assigned for slide in s.get('content',{}).get('slides',[]) for e in slide['elements'] if e['kind'] in ('image','video')};expires=str(int(time.time())+900)
                    for item in data['media']:
                        if item['id'] in ids:assets.append(dict(item,url=f"/api/v1/devices/media/{item['id']}?device_id={device['device_id']}&expires={expires}&sig={self.device_signature(device,device['screen_id'],item['id'],expires)}"))
                custom=[]
                if screen:
                    custom=[dict(f,url=f"/api/v1/devices/fonts/{f['id']}?device_id={device['device_id']}&expires={expires}&sig={self.device_signature(device,device['screen_id'],f['id'],expires)}") for f in data['customFonts'] if any(f['id'] in font_ids(s.get('content',{}),False) for s in assigned)]
                public={k:v for k,v in (screen or {}).items() if not k.startswith('_') and k not in ('orders','queueHistory','lastCalledNumber','callSequence','queueSettings','queueNumber')}
                if 'content' in public:public['content']={k:v for k,v in public['content'].items() if k!='modeDrafts'}
                if program:program.pop('device_ids',None)
                return self.reply(200,dict(server_id=registry.server_id,device=registry.public(device),screen=public or None,program=program,media=assets,customFonts=custom,message='' if screen else '관리자가 출력 화면을 배정하면 자동으로 표시됩니다.'))
            raise DeviceError('API를 찾을 수 없습니다.',404)
        except DeviceError as error:
            if path=='/api/v1/devices/register' and error.status in (400,413,415,426):
                try:registry.record_failure(self.client_address[0],{400:'요청 형식 오류',413:'요청 크기 초과',415:'요청 데이터 형식 오류',426:'HTTPS 연결 필요'}[error.status])
                except OSError:pass
            return self.reply(error.status,{'error':str(error)})
        except (OSError,ValueError):return self.reply(500,{'error':'장치 정보를 저장하거나 읽지 못했습니다. 파일 권한과 디스크 공간을 확인해 주세요.'})
