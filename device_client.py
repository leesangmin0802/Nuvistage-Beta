"""Trusted HTTPS device client and adapter for the existing Playback renderer."""
import copy
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import time
import uuid
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
from devices import atomic_private

ROOT=Path(__file__).resolve().parent
VERSION='0.2.0'
class ClientError(ValueError):
    def __init__(self,message,status=0):super().__init__(message);self.status=status
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def server_url(value):
    if '://' not in value:value='https://'+value
    parsed=urlparse(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:raise ClientError('https://서버이름:포트 형식의 주소를 입력해 주세요.')
    try:parsed.port
    except ValueError:raise ClientError('서버 포트 번호를 확인해 주세요.')
    return value.rstrip('/')

class DeviceClient:
    def __init__(self,directory,ca_file=None):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True);os.chmod(self.directory,0o700)
        self.file=self.directory/'credentials.json';self.config=json.loads(self.file.read_text()) if self.file.exists() else dict(device_id=str(uuid.uuid4()),registration_nonce=secrets.token_urlsafe(32))
        if not self.file.exists():self.save()
        self.started=time.monotonic()
        self.ca_file=str(Path(ca_file).resolve()) if ca_file else self.config.get('ca_file')
        context=ssl.create_default_context(cafile=self.ca_file);context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect())
    def save(self):atomic_private(self.file,self.config)
    def request(self,url,path,body=None,token=None,binary=False):
        url=server_url(url)
        if not path.startswith('/') or path.startswith('//'):raise ClientError('서버 응답 경로가 올바르지 않습니다.')
        headers={'Content-Type':'application/json'}
        if token:headers.update(Authorization='Bearer '+token,**{'X-Device-ID':self.config['device_id']})
        request=Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with self.opener.open(request,timeout=8) as response:
                limit=512*1024*1024 if binary else 32*1024*1024
                raw=response.read(limit+1)
                if len(raw)>limit:raise ClientError('서버 응답 크기가 허용 범위를 초과했습니다.')
                return raw if binary else json.loads(raw)
        except HTTPError as error:
            with error:
                try:message=json.loads(error.read(8192)).get('error','서버 요청을 처리하지 못했습니다.')
                except ValueError:message='서버 요청을 처리하지 못했습니다.'
                raise ClientError(message,error.code) from None
        except (URLError,ssl.SSLError,TimeoutError,OSError):raise ClientError('서버 연결 또는 인증서 검증에 실패했습니다. 네트워크·주소·신뢰한 CA를 확인해 주세요.') from None
        except (ValueError,UnicodeError):raise ClientError('서버 응답 형식이 올바르지 않습니다.') from None
    def verify(self,url,expected=None):
        info=self.request(url,'/api/v1/server-info')
        from devices import valid_id
        if not valid_id(info.get('server_id')) or info.get('api_version')!=1:raise ClientError('지원하는 Nuvistage 서버가 아닙니다.')
        if expected and info['server_id']!=expected:raise ClientError('저장된 서버 ID와 다릅니다. 다른 서버에는 인증정보를 보내지 않습니다.',409)
        return info
    def register(self,url,name,password,expected=None):
        url=server_url(url);info=self.verify(url,self.config.get('server_id') if self.config.get('device_token') else expected)
        self.config.update(server_url=url,server_id=info['server_id'],ca_file=self.ca_file,device_name=name)
        # A private nonce allows safe recovery when the first response was lost, without storing the password.
        self.config.setdefault('registration_nonce',secrets.token_urlsafe(32));self.save()
        response=self.request(url,'/api/v1/devices/register',dict(device_id=self.config['device_id'],device_name=name,registration_password=password,player_version=VERSION,registration_nonce=self.config['registration_nonce']))
        self.config.update(device_token=response['device_token'],server_id=response['server_id'],player_version=VERSION)
        self.config.pop('registration_nonce',None);self.save();return response['device']
    @property
    def pairing_code(self):
        if not self.config.get('pairing_code'):
            self.config['pairing_code']=''.join(str(secrets.randbelow(10)) for _ in range(16));self.save()
        return self.config['pairing_code']
    def begin_pairing(self,url,name='새 Player',expected=None):
        url=server_url(url);info=self.verify(url,expected or self.config.get('server_id'))
        self.config.setdefault('pairing_secret',secrets.token_urlsafe(32));self.config.update(server_url=url,server_id=info['server_id'],device_name=name,ca_file=self.ca_file);self.save()
        return self.request(url,'/api/v1/pairing/announce',dict(device_id=self.config['device_id'],device_name=name,code=self.pairing_code,pairing_secret=self.config['pairing_secret'],player_version=VERSION))
    def poll_pairing(self):
        response=self.request(self.config['server_url'],'/api/v1/pairing/poll',dict(device_id=self.config['device_id'],pairing_secret=self.config['pairing_secret']))
        if response['status']=='registered':
            self.config.update(device_token=response['device_token'],server_id=response['server_id'],device_name=response['device']['device_name'],player_version=VERSION);self.config.pop('pairing_secret',None);self.save()
        return response
    def reconnect(self,discover_fn=None):
        if not self.config.get('device_token'):raise ClientError('장치 최초 설정이 필요합니다.',401)
        candidates=[self.config.get('server_url','')];last=None
        def connect(url):
            self.verify(url,self.config['server_id']);token=self.config['device_token']
            import shutil
            previous=json.loads((self.directory/'cache/snapshot.json').read_text()) if self.cached else {};program=previous.get('program') or {}
            report=dict(program_id=program.get('id',''),program_revision=program.get('revision',0),screen_id=(previous.get('screen') or {}).get('id',''),uptime=int(time.monotonic()-self.started),free_bytes=shutil.disk_usage(self.directory).free)
            self.request(url,'/api/v1/devices/heartbeat',dict(device_id=self.config['device_id'],player_version=VERSION,report=report),token)
            snapshot=self.request(url,'/api/v1/devices/me/screen',token=token)
            self.cache(snapshot,url)
            if url!=self.config['server_url']:self.config['server_url']=url;self.save()
            return snapshot
        try:return connect(candidates[0])
        except ClientError as error:
            if error.status in (401,403):self.cache_denied(error);raise
            last=error
        if discover_fn is None:
            from discovery import discover
            discover_fn=discover
        try:found=discover_fn()
        except ValueError:found=[]
        for item in found:
            if item.get('server_id')!=self.config['server_id'] or item.get('url') in candidates:continue
            try:return connect(item['url'])
            except ClientError as error:
                if error.status in (401,403):self.cache_denied(error);raise
                last=error
        raise last or ClientError('서버를 찾지 못했습니다. 저장된 콘텐츠가 있으면 계속 재생합니다.')
    def cache_denied(self,error):
        self.prepare_renderer();self.publish(dict(screen=None,media=[],message=str(error),authorization_denied=True))
    def cache(self,snapshot,url):
        if snapshot.get('server_id')!=self.config['server_id']:raise ClientError('출력 데이터의 서버 ID가 다릅니다.',409)
        result=copy.deepcopy(snapshot);custom=result.get('customFonts',[]);font_files=self.directory/'cache/custom-font-files';font_files.mkdir(parents=True,exist_ok=True)
        for font in custom:
            if not re.fullmatch(r'custom-[0-9a-f]{32}',font.get('id','')) or font.get('extension') not in ('ttf','otf','woff','woff2'):raise ClientError('외부 글꼴 응답 형식을 확인해 주세요.')
            target=font_files/(font['id']+'.'+font['extension'])
            if not target.exists() or target.stat().st_size!=font['size']:self.download(url,font['url'],target,font['size'])
            font['url']=''
        font_screen=copy.deepcopy(result.get('screen') or {});font_screen.setdefault('content',{}).setdefault('slides',[])
        for screen in (result.get('program') or {}).get('playlists',{}).values():
            c=screen.get('content',{})
            for slide in c.get('slides',[]):
                item=copy.deepcopy(slide);item.setdefault('fontFamily',c.get('fontFamily','pretendard'));font_screen['content']['slides'].append(item)
        result['fonts']=self.cache_fonts(font_screen,custom);self.prepare_renderer()
        assets=self.directory/'cache/media';assets.mkdir(exist_ok=True)
        for item in result['media']:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',item.get('id','')):raise ClientError('미디어 식별자가 올바르지 않습니다.')
            suffix={ 'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','video/mp4':'.mp4','video/webm':'.webm'}.get(item.get('mime'))
            if not suffix:raise ClientError('지원하지 않는 미디어 형식입니다.')
            target=assets/(item['id']+suffix)
            if not target.exists() or target.stat().st_size!=item['size']:
                self.download(url,item['url'],target,item['size'])
            item['url']='media/'+target.name
        self.publish(result)
    def download(self,url,path,target,expected):
        if not path.startswith('/') or path.startswith('//') or type(expected) is not int or expected<0:raise ClientError('미디어 응답 정보를 확인해 주세요.')
        temporary=target.with_suffix('.tmp');count=0
        request=Request(server_url(url)+path,headers={'Authorization':'Bearer '+self.config['device_token'],'X-Device-ID':self.config['device_id']})
        try:
            with self.opener.open(request,timeout=15) as response,open(temporary,'wb',opener=lambda p,f:os.open(p,f,0o600)) as stream:
                while True:
                    chunk=response.read(65536)
                    if not chunk:break
                    count+=len(chunk)
                    if count>expected:raise ClientError('미디어 크기가 서버 정보와 다릅니다.')
                    stream.write(chunk)
                stream.flush();os.fsync(stream.fileno())
            if count!=expected:raise ClientError('미디어 다운로드가 완료되지 않았습니다. 이전 콘텐츠를 유지합니다.')
            temporary.replace(target)
        except HTTPError as error:
            status=error.code;error.close();raise ClientError('미디어 접근 권한 또는 배정 상태를 확인해 주세요.',status) from None
        except (OSError,URLError,ssl.SSLError):raise ClientError('미디어 다운로드 연결에 실패했습니다. 기존 캐시를 유지합니다.') from None
        finally:temporary.unlink(missing_ok=True)
    def publish(self,snapshot):
        cache=self.directory/'cache';cache.mkdir(exist_ok=True);view={k:snapshot[k] for k in ('screen','media','message','authorization_denied','fonts','customFonts','program') if k in snapshot};raw=json.dumps(view,ensure_ascii=False)
        target=cache/'snapshot.js';temporary=cache/'snapshot.tmp';temporary.write_text('window.PISIGNAGE_SNAPSHOT='+raw+';');os.chmod(temporary,0o600);temporary.replace(target)
        atomic_private(cache/'snapshot.json',snapshot)
    def cache_fonts(self,screen,custom_fonts=None):
        content=(screen or {}).get('content',{});ids={'pretendard',content.get('fontFamily','pretendard')}
        for slide in content.get('slides',[]):
            ids.add(slide.get('fontFamily',content.get('fontFamily','pretendard')))
            ids.update(e.get('fontFamily',slide.get('fontFamily',content.get('fontFamily','pretendard'))) for e in slide['elements'] if e['kind']=='text')
        aliases={'sans':'pretendard','serif':'nanum-myeongjo','mono':'pretendard'};ids={aliases.get(value,value) for value in ids}
        folder=self.directory/'cache/fonts';folder.mkdir(parents=True,exist_ok=True);faces=re.findall(r'@font-face\{[^}]+\}',(ROOT/'fonts.css').read_text());result=[]
        for font_id in sorted(ids):
            if not re.fullmatch(r'[a-z0-9-]{1,40}',font_id):continue
            target=folder/(font_id+'.css')
            if target.exists():result.append(font_id);continue
            chunks=[]
            custom=next((f for f in custom_fonts or [] if f['id']==font_id),None)
            if custom:
                binary=self.directory/'cache/custom-font-files'/(font_id+'.'+custom['extension']);encoded=base64.b64encode(binary.read_bytes()).decode('ascii');chunks.append('@font-face{font-family:"Pi '+font_id+'";src:url("data:font/'+custom['extension']+';base64,'+encoded+'");font-weight:400;}')
            for face in faces:
                match=re.search(r'/fonts/([a-z-]+)\.(ttf|woff2)',face)
                if not match or match[1].removesuffix('-bold')!=font_id:continue
                file=ROOT/'fonts'/(match[1]+'.'+match[2])
                encoded=base64.b64encode(file.read_bytes()).decode('ascii');uri='data:font/'+('woff2' if match[2]=='woff2' else 'ttf')+';base64,'+encoded
                chunks.append(face.replace('/fonts/'+file.name,uri))
            if chunks:
                target=folder/(font_id+'.css')
                if not target.exists():target.write_text('\n'.join(chunks));os.chmod(target,0o600)
                result.append(font_id)
        return result
    def prepare_renderer(self):
        cache=self.directory/'cache';cache.mkdir(exist_ok=True);fonts=cache/'fonts';fonts.mkdir(exist_ok=True)
        # Reuse the existing renderer. No HTTP server or new playback engine runs on the Player.
        # CSS data fonts avoid file-origin CORS without weakening Chromium security settings.
        styles=(ROOT/'studio.css').read_text()+re.sub(r'@font-face\{[^}]+\}','',(ROOT/'fonts.css').read_text())
        fonts_js=(ROOT/'fonts.js').read_text().replace('export ','');shapes_js=(ROOT/'shapes.js').read_text().replace('export ','');canvas=(ROOT/'canvas.js').read_text();canvas='\n'.join(line for line in canvas.splitlines() if not line.startswith('import ')).replace('export ','')
        scheduled='\n'.join(line for line in (ROOT/'scheduled-player.js').read_text().splitlines() if not line.startswith('import ')).replace('export ','')
        runtime="""const sheets=new Map();function loadSheet(name){if(!sheets.has(name))sheets.set(name,new Promise(resolve=>{const link=document.createElement('link');link.rel='stylesheet';link.href='fonts/'+name+'.css';link.onload=resolve;link.onerror=resolve;document.head.append(link)}));return sheets.get(name)}let playback,signature='';async function update(){const data=window.PISIGNAGE_SNAPSHOT;if(!data)return;const next=JSON.stringify(data);if(next===signature)return;signature=next;playback?.destroy();const host=document.getElementById('player');if(data.screen){host.className='stage';installCustomFonts(data.customFonts,{load:false});await Promise.all((data.fonts||[]).map(loadSheet));await preloadFonts(fontsFor(data.screen));playback=new ScheduledPlayback(host,data.screen,data.media,{program:data.program})}else{host.className='waiting';host.textContent=data.message||'관리자가 출력 화면을 배정하면 자동으로 표시됩니다.'}}function poll(){const script=document.createElement('script');script.src='snapshot.js?time='+Date.now();script.onload=()=>{script.remove();update()};script.onerror=()=>script.remove();document.body.append(script)}poll();setInterval(poll,3000);"""
        html='<!doctype html><html lang="ko"><meta charset="utf-8"><title>Nuvistage Device Player</title><style>'+styles+'html,body{margin:0;width:100%;height:100%;background:#090e18;overflow:hidden}body{display:grid;place-items:center}#player{width:min(100vw,177.7778vh)}#player.portrait{width:min(100vw,56.25vh)}.waiting{color:#b6c5dc;text-align:center;font-size:30px;padding:40px}</style><div id="player"></div><script type="module">'+fonts_js+shapes_js+canvas+scheduled+runtime+'</script></html>'
        (cache/'index.html').write_text(html);os.chmod(cache/'index.html',0o600)
    @property
    def cached(self):return (self.directory/'cache/snapshot.json').exists()
