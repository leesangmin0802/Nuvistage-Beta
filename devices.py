"""Persistent device identities. This file never stores cleartext credentials."""
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import uuid
from auth import ITERATIONS

class DeviceError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


def atomic_private(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    try:
        with open(temporary,'w',encoding='utf-8',opener=lambda p,f:os.open(p,f,0o600)) as stream:
            os.chmod(temporary,0o600);json.dump(value,stream,ensure_ascii=False,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path);os.chmod(path,0o600)
    finally:temporary.unlink(missing_ok=True)


def valid_id(value):
    try:return isinstance(value,str) and str(uuid.UUID(value))==value
    except ValueError:return False


def digest(token):return hashlib.sha256(token.encode()).hexdigest()

def valid_name(value):return isinstance(value,str) and 1<=len(value.strip())<=100 and not any(ord(c)<32 for c in value)

class DeviceRegistry:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.attempts={}
        if not self.path.exists():atomic_private(self.path,dict(server_id=str(uuid.uuid4()),revision=1,registration_allowed=False,password=None,devices={},failures=[]))
        self.read()
        os.chmod(self.path,0o600)
    def read(self):
        data=json.loads(self.path.read_text())
        if not isinstance(data,dict) or not valid_id(data.get('server_id')) or not isinstance(data.get('devices'),dict):raise ValueError('장치 저장 파일 형식을 확인해 주세요.')
        return data
    def write(self,data):atomic_private(self.path,data)
    @property
    def server_id(self):
        with self.lock:return self.read()['server_id']
    def settings(self):
        with self.lock:
            data=self.read();return dict(server_id=data['server_id'],revision=data['revision'],registration_allowed=data['registration_allowed'],password_configured=bool(data['password']),device_count=len(data['devices']),failures=data['failures'][-100:][::-1])
    def configure(self,body):
        if not isinstance(body,dict) or set(body)-{'revision','registration_allowed','registration_password'}:raise DeviceError('장치 등록 설정을 확인해 주세요.')
        with self.lock:
            data=self.read()
            if type(body.get('revision')) is not int or body['revision']!=data['revision']:raise DeviceError('다른 창에서 설정을 변경했습니다. 새로고침해 주세요.',409)
            if 'registration_allowed' in body and type(body['registration_allowed']) is not bool:raise DeviceError('등록 허용 여부를 확인해 주세요.')
            if 'registration_password' in body:
                password=body['registration_password']
                if not isinstance(password,str) or not 12<=len(password)<=256:raise DeviceError('장치 등록 비밀번호는 12~256자로 설정해 주세요.')
                salt=secrets.token_hex(16);data['password']=dict(salt=salt,iterations=ITERATIONS,hash=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex())
            data['registration_allowed']=body.get('registration_allowed',data['registration_allowed'])
            # Code-based claims need no shared registration password.
            data['revision']+=1;self.write(data)
        return self.settings()
    def failure(self,data,address,reason):
        data['failures']=(data['failures']+[dict(at=int(time.time()),address=address,reason=reason)])[-200:];self.write(data)
    def record_failure(self,address,reason):
        with self.lock:self.failure(self.read(),address,reason)
    def register(self,body,address):
        if not isinstance(body,dict) or set(body)-{'device_id','device_name','registration_password','player_version','registration_nonce'} or not valid_id(body.get('device_id')) or not valid_name(body.get('device_name')) or not isinstance(body.get('player_version'),str) or not re.fullmatch(r'[A-Za-z0-9._+-]{1,40}',body['player_version']) or not isinstance(body.get('registration_password'),str) or len(body['registration_password'])>256:raise DeviceError('장치 ID·이름·Player 버전·등록 비밀번호를 확인해 주세요.')
        nonce=body.get('registration_nonce')
        if nonce is not None and (not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',nonce)):raise DeviceError('등록 재시도 정보를 확인해 주세요.')
        with self.lock:
            data=self.read();now=int(time.time())
            self.attempts={k:[v for v in times if v>now-60] for k,times in self.attempts.items() if any(v>now-60 for v in times)}
            recent=self.attempts.get(address,[]);total=sum(len(v) for v in self.attempts.values())
            if len(recent)>=8 or total>=60:
                self.failure(data,address,'요청 제한');raise DeviceError('등록 시도가 많습니다. 1분 후 다시 시도해 주세요.',429)
            self.attempts[address]=recent+[now]
            if not data['registration_allowed'] or not data['password']:
                self.failure(data,address,'등록 잠금');raise DeviceError('신규 장치 등록이 잠겨 있습니다. 관리자에게 문의해 주세요.',423)
            p=data['password'];actual=hashlib.pbkdf2_hmac('sha256',body['registration_password'].encode(),bytes.fromhex(p['salt']),p['iterations']).hex()
            if not hmac.compare_digest(actual,p['hash']):
                self.failure(data,address,'비밀번호 불일치');raise DeviceError('서버 등록 비밀번호가 올바르지 않습니다.',401)
            existing=data['devices'].get(body['device_id']);retry=False
            if existing:
                retry=bool(nonce and existing.get('registration_nonce_hash') and hmac.compare_digest(existing['registration_nonce_hash'],digest(nonce)) and now-existing['registered_at']<=600 and not existing['last_seen'] and not existing['blocked'])
                if not retry and not existing.get('enrollment_required'):
                    self.failure(data,address,'장치 ID 충돌');raise DeviceError('이미 등록된 장치 ID입니다. 기존 토큰으로 연결하거나 관리자가 등록을 초기화해 주세요.',409)
                if existing['blocked']:raise DeviceError('차단된 장치는 등록할 수 없습니다.',403)
            if len(data['devices'])>=500 and not existing:raise DeviceError('등록 가능한 장치 수를 초과했습니다.',409)
            token=secrets.token_urlsafe(32)
            device=dict(device_id=body['device_id'],device_name=body['device_name'].strip(),player_version=body['player_version'],screen_id=existing.get('screen_id','') if existing else '',blocked=False,enrollment_required=False,token_hash=digest(token),registered_at=now,last_seen=0,last_ip=address,revision=existing['revision']+1 if existing else 1,registration_nonce_hash=digest(nonce) if nonce else '')
            data['devices'][device['device_id']]=device;self.write(data)
            return dict(server_id=data['server_id'],device=self.public(device),device_token=token,recovered=retry)
    def public(self,device):
        keys=('device_id','device_name','player_version','screen_id','blocked','enrollment_required','registered_at','last_seen','last_ip','revision')
        value={k:device[k] for k in keys};value['pairing_code']=device.get('pairing_code','');value['report']=device.get('report',{});value['token_revoked']=not bool(device['token_hash']);value['online']=bool(device['last_seen'] and time.time()-device['last_seen']<35 and not device['blocked'] and device['token_hash']);return value
    def authenticate(self,token,device_id=None):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise DeviceError('장치 인증 토큰이 없거나 만료되었습니다. 최초 설정을 다시 진행해 주세요.',401)
        hashed=digest(token)
        with self.lock:
            data=self.read();device=next((d for d in data['devices'].values() if d['token_hash'] and hmac.compare_digest(d['token_hash'],hashed)),None)
            if not device or (device_id and device['device_id']!=device_id):raise DeviceError('장치 인증이 해제되었습니다. 관리자에게 문의해 주세요.',401)
            if device['blocked']:raise DeviceError('관리자가 이 장치를 차단했습니다.',403)
            return copy.deepcopy(device)
    def heartbeat(self,token,body,address):
        if not isinstance(body,dict) or set(body)-{'device_id','player_version','report'} or not valid_id(body.get('device_id')) or not isinstance(body.get('player_version'),str) or not re.fullmatch(r'[A-Za-z0-9._+-]{1,40}',body['player_version']):raise DeviceError('장치 상태 보고 형식을 확인해 주세요.')
        report=body.get('report')
        if report is not None:
            if not isinstance(report,dict) or set(report)-{'program_id','program_revision','screen_id','uptime','free_bytes'} or not isinstance(report.get('program_id',''),str) or len(report.get('program_id',''))>80 or not isinstance(report.get('screen_id',''),str) or len(report.get('screen_id',''))>80 or any(type(report.get(k,0)) is not int or not 0<=report.get(k,0)<=10**18 for k in ('program_revision','uptime','free_bytes')):raise DeviceError('장치 진단 정보를 확인해 주세요.')
        with self.lock:
            auth=self.authenticate(token,body['device_id']);data=self.read();d=data['devices'][auth['device_id']];d.update(last_seen=int(time.time()),last_ip=address,player_version=body['player_version'],registration_nonce_hash='');
            if report is not None:d['report']=report
            self.write(data);return self.public(d)
    def list(self):
        with self.lock:return [self.public(d) for d in self.read()['devices'].values()]
    def change(self,device_id,action,body):
        with self.lock:
            data=self.read();device=data['devices'].get(device_id)
            if not device:raise DeviceError('등록된 장치를 찾을 수 없습니다.',404)
            if type(body.get('revision')) is not int or body['revision']!=device['revision']:raise DeviceError('다른 창에서 장치 설정을 변경했습니다. 새로고침해 주세요.',409)
            allowed={'update':{'revision','device_name','blocked'},'assign':{'revision','screen_id'},'delete':{'revision'},'revoke':{'revision'},'reset':{'revision'}}[action]
            if set(body)-allowed:raise DeviceError('지원하지 않는 장치 설정입니다.')
            if action=='update':
                if 'device_name' in body:
                    if not valid_name(body['device_name']):raise DeviceError('장치 이름은 1~100자로 입력해 주세요.')
                    device['device_name']=body['device_name'].strip()
                if 'blocked' in body:
                    if type(body['blocked']) is not bool:raise DeviceError('차단 여부를 확인해 주세요.')
                    device['blocked']=body['blocked']
            elif action=='assign':device['screen_id']=body['screen_id']
            elif action=='delete':del data['devices'][device_id]
            elif action in ('revoke','reset'):
                device['token_hash']='';device['registration_nonce_hash']='';device['enrollment_required']=action=='reset'
            if action in ('delete','revoke','reset'):data.get('pairing',{}).pop(device_id,None)
            device['revision']+=1;self.write(data);return self.public(device)
