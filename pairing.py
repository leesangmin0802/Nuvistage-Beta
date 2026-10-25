"""Administrator claims a Player's stable display code; only its private nonce receives a token."""
import hashlib
import hmac
import re
import secrets
import time
from devices import DeviceError,valid_id,valid_name,digest

def normalize_code(value):
    code=re.sub(r'[\s-]','',value) if isinstance(value,str) else ''
    if not re.fullmatch(r'[0-9]{16}',code):raise DeviceError('Player에 표시된 16자리 코드를 입력해 주세요.')
    return code

def pending_public(registry):
    with registry.lock:
        data=registry.read();now=time.time()
        return [dict(device_id=p['device_id'],device_name=p['device_name'],last_ip=p['last_ip'],last_seen=p['last_seen'],player_version=p['player_version']) for p in data.get('pairing',{}).values() if now-p['last_seen']<120 and not p.get('claimed')]

def rate(registry,address):
    now=time.time();key='pair:'+address
    registry.attempts={k:[v for v in values if v>now-60] for k,values in registry.attempts.items() if any(v>now-60 for v in values)}
    values=registry.attempts.get(key,[])
    if len(values)>=40 or sum(map(len,registry.attempts.values()))>=2000:raise DeviceError('연결 요청이 많습니다. 잠시 후 다시 시도해 주세요.',429)
    registry.attempts[key]=values+[now]

def announce(registry,body,address):
    if set(body)-{'device_id','device_name','code','pairing_secret','player_version'} or not valid_id(body.get('device_id')) or not valid_name(body.get('device_name')) or (not isinstance(body.get('player_version'),str) or not re.fullmatch(r'[A-Za-z0-9._+-]{1,40}',body['player_version'])) or (not isinstance(body.get('pairing_secret'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',body['pairing_secret'])):raise DeviceError('Player 연결 정보가 올바르지 않습니다.')
    code=normalize_code(body.get('code'));hashed=digest(body['pairing_secret']);did=body['device_id'];now=int(time.time())
    with registry.lock:
        rate(registry,address);data=registry.read();items=data.setdefault('pairing',{});items={k:p for k,p in items.items() if now-p['last_seen']<600};data['pairing']=items
        existing=data['devices'].get(did)
        if existing and not existing.get('enrollment_required'):raise DeviceError('이미 등록된 장치입니다. 기존 인증으로 연결하거나 관리자에서 재등록을 허용해 주세요.',409)
        if existing and existing['blocked']:raise DeviceError('차단된 장치입니다.',403)
        prior=items.get(did)
        if prior and not hmac.compare_digest(prior['secret_hash'],hashed):raise DeviceError('동일 장치 ID로 다른 연결 요청이 있습니다.',409)
        if any(p['code']==code and p['device_id']!=did for p in items.values()):raise DeviceError('코드가 중복되었습니다. Player 연결 코드를 다시 생성해 주세요.',409)
        if len(items)>=500 and did not in items:raise DeviceError('연결 대기 장치가 너무 많습니다.',429)
        if not prior:items[did]=dict(device_id=did,code=code,secret_hash=hashed,device_name=body['device_name'].strip(),player_version=body['player_version'],claimed=False,created_at=now)
        items[did].update(last_seen=now,last_ip=address);registry.write(data)
    return dict(server_id=data['server_id'],status='waiting')

def token_for(secret,pending):
    return hmac.new(bytes.fromhex(secret),('pairing:'+pending['device_id']+':'+pending['secret_hash']+':'+pending['claim_nonce']).encode(),hashlib.sha256).hexdigest()

def device_token(secret,pending):
    import base64
    return base64.urlsafe_b64encode(bytes.fromhex(token_for(secret,pending))).decode().rstrip('=')

def claim(registry,body,secret):
    if set(body)-{'code','device_name','screen_id'}:raise DeviceError('등록할 장치 정보를 확인해 주세요.')
    code=normalize_code(body.get('code'));now=int(time.time())
    with registry.lock:
        data=registry.read()
        if not data['registration_allowed']:raise DeviceError('신규 장치 등록이 잠겨 있습니다. 등록 설정에서 허용해 주세요.',423)
        p=next((p for p in data.get('pairing',{}).values() if p['code']==code and now-p['last_seen']<120 and not p.get('claimed')),None)
        if not p:raise DeviceError('연결 대기 중인 Player를 찾지 못했습니다. 코드와 네트워크 연결을 확인해 주세요.',404)
        existing=data['devices'].get(p['device_id'])
        if existing and (existing['blocked'] or not existing.get('enrollment_required')):raise DeviceError('등록할 수 없는 장치입니다.',409)
        if len(data['devices'])>=500 and not existing:raise DeviceError('등록 가능한 장치 수를 초과했습니다.',409)
        name=body.get('device_name') or p['device_name']
        if not valid_name(name):raise DeviceError('장치 이름은 1~100자로 입력해 주세요.')
        p.update(claimed=True,claimed_at=now,claim_nonce=secrets.token_hex(24))
        d=dict(device_id=p['device_id'],device_name=name.strip(),player_version=p['player_version'],screen_id=body.get('screen_id',''),blocked=False,enrollment_required=False,token_hash=digest(device_token(secret,p)),registered_at=now,last_seen=0,last_ip=p['last_ip'],revision=existing['revision']+1 if existing else 1,registration_nonce_hash='',pairing_code=code)
        data['devices'][d['device_id']]=d;registry.write(data)
        return dict(device=registry.public(d),server_id=data['server_id'])

def poll(registry,body,address,secret):
    if set(body)-{'device_id','pairing_secret'} or not valid_id(body.get('device_id')) or (not isinstance(body.get('pairing_secret'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',body['pairing_secret'])):raise DeviceError('연결 확인 정보가 올바르지 않습니다.')
    with registry.lock:
        rate(registry,address);data=registry.read();p=data.get('pairing',{}).get(body['device_id'])
        if not p or not hmac.compare_digest(p['secret_hash'],digest(body['pairing_secret'])):raise DeviceError('연결 대기 정보가 없습니다. Player를 다시 연결해 주세요.',401)
        p['last_seen']=int(time.time());p['last_ip']=address
        if not p['claimed']:registry.write(data);return dict(status='waiting',server_id=data['server_id'])
        d=data['devices'].get(p['device_id'])
        if not d or d['blocked'] or not d['token_hash'] or d['last_seen'] or time.time()-p['claimed_at']>600 or not hmac.compare_digest(d['token_hash'],digest(device_token(secret,p))):raise DeviceError('연결 승인이 만료되었거나 해제되었습니다.',401)
        registry.write(data);return dict(status='registered',device_token=device_token(secret,p),device=registry.public(d),server_id=data['server_id'])
