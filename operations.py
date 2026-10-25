"""Local playlist/group scheduling with immutable published revisions."""
import copy
from datetime import datetime,timedelta
from pathlib import Path
import re
import secrets
import threading
import time
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from devices import atomic_private,DeviceError,valid_name

def new_id(prefix):return prefix+'-'+secrets.token_hex(12)
def valid_duration(value):return type(value) in (int,float) and 0<=value<=86400

LAYOUTS={
 'full':[(0,0,100,100)],
 'split':[(0,0,50,100),(50,0,50,100)],
 'sidebar':[(0,0,72,100),(72,0,28,100)],
 'three':[(0,0,68,100),(68,0,32,50),(68,50,32,50)],
 'four':[(0,0,50,50),(50,0,50,50),(0,50,50,50),(50,50,50,50)],
 'six':[(x,y,100/3,50) for y in (0,50) for x in (0,100/3,200/3)]
}

def active_rule(rule,timezone,at=None):
    now=datetime.fromtimestamp(time.time() if at is None else at,ZoneInfo(timezone));minutes=now.hour*60+now.minute
    start=int(rule['start'][:2])*60+int(rule['start'][3:]);end=int(rule['end'][:2])*60+int(rule['end'][3:])
    day=now.date()
    if start<end:
        if not start<=minutes<end:return False
    elif start>end:
        if minutes<end:day-=timedelta(days=1)
        elif minutes<start:return False
    if day.weekday() not in rule['days']:return False
    return (not rule.get('date_from') or day.isoformat()>=rule['date_from']) and (not rule.get('date_to') or day.isoformat()<=rule['date_to'])

def choose_screen(program,at=None):
    now=time.time() if at is None else at;override=program.get('override')
    if override and override['until']>now:return copy.deepcopy(override['screen'])
    rule=next((r for r in sorted(program['rules'],key=lambda r:(-r['priority'],r['id'])) if active_rule(r,program['timezone'],now)),None)
    if rule and rule.get('paused'):
        screen=copy.deepcopy(next(iter(program['playlists'].values())));screen['status']='paused';return screen
    key=rule['playlist_id'] if rule else program['default_playlist_id'];return copy.deepcopy(program['playlists'][key])

def program_screens(program):
    if not program:return []
    return list(program['playlists'].values())+([program['override']['screen']] if program.get('override') else [])

class Operations:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock()
        if not self.path.exists():self.write(dict(playlists=[],groups=[],events=[]))
    def read(self):
        import json
        return json.loads(self.path.read_text())
    def write(self,data):atomic_private(self.path,data)
    def event(self,data,action,name,**extra):
        data['events']=(data['events']+[dict(id=new_id('ev'),at=int(time.time()),action=action,name=name,**extra)])[-3000:]
    def snapshot(self):
        with self.lock:return self.read()
    def mutate(self,kind,item_id,method,body,source,device_ids):
        if kind not in ('playlists','groups'):raise DeviceError('운영 항목을 찾을 수 없습니다.',404)
        with self.lock:
            data=self.read();items=data[kind];item=next((x for x in items if x['id']==item_id),None)
            if item_id and not item:raise DeviceError('항목이 없습니다.',404)
            if item and (type(body.get('revision')) is not int or body['revision']!=item['revision']):raise DeviceError('다른 창에서 변경했습니다. 최신 목록을 불러온 뒤 다시 시도해 주세요.',409)
            if method=='DELETE':
                if set(body)!={'revision'}:raise DeviceError('삭제 요청을 확인해 주세요.')
                if kind=='playlists' and any(item_id==g['default_playlist_id'] or item_id in g.get('zone_playlists',[]) or any(r.get('playlist_id')==item_id for r in g['rules']) or (g.get('published') and item_id in g['published']['playlists']) for g in data['groups']):raise DeviceError('그룹에서 사용 중인 재생목록입니다.',409)
                items.remove(item);self.event(data,'delete',item['name'],kind=kind);self.write(data);return dict(ok=True)
            allowed={'name','revision','items'} if kind=='playlists' else {'name','revision','device_ids','default_playlist_id','timezone','rules','ticker','clock','layout','zone_playlists'}
            if set(body)-allowed or not valid_name(body.get('name')):raise DeviceError('이름과 설정을 확인해 주세요.')
            value=copy.deepcopy(body);value.pop('revision',None);value['name']=body['name'].strip()
            if kind=='playlists':
                entries=body.get('items')
                if not isinstance(entries,list) or not 1<=len(entries)<=50:raise DeviceError('재생목록에 콘텐츠를 1~50개 추가해 주세요.')
                ids={s['id'] for s in source['screens'] if s.get('type')!='queue'}
                for entry in entries:
                    if not isinstance(entry,dict) or set(entry)!={'screen_id','duration'} or (not isinstance(entry.get('screen_id'),str) or entry.get('screen_id') not in ids) or not valid_duration(entry.get('duration')):raise DeviceError('콘텐츠와 표시 시간을 확인해 주세요.')
            else:
                members=body.get('device_ids');default=body.get('default_playlist_id');playlists={p['id'] for p in data['playlists']}
                if not isinstance(members,list) or len(members)>500 or any(not isinstance(d,str) or d not in device_ids for d in members) or len(set(members))!=len(members):raise DeviceError('그룹 장치를 확인해 주세요.')
                if any(set(members)&(set(g['device_ids'])|set(g.get('published',{}).get('device_ids',[]))) for g in data['groups'] if g['id']!=item_id):raise DeviceError('다른 그룹에 배정된 장치가 있습니다.',409)
                if not isinstance(default,str) or default not in playlists:raise DeviceError('기본 재생목록을 선택해 주세요.')
                try:ZoneInfo(body.get('timezone',''))
                except (ZoneInfoNotFoundError,ValueError,TypeError):raise DeviceError('시간대를 확인해 주세요.')
                if type(body.get('clock')) is not bool or not isinstance(body.get('ticker'),str) or len(body['ticker'])>500:raise DeviceError('시계·하단 문구를 확인해 주세요.')
                layout=body.get('layout','full');zones=body.get('zone_playlists',[])
                if not isinstance(layout,str) or layout not in LAYOUTS or not isinstance(zones,list) or len(zones)!=len(LAYOUTS[layout])-1 or any(not isinstance(pid,str) or pid not in playlists for pid in zones):raise DeviceError('화면 분할과 영역별 재생목록을 확인해 주세요.')
                value.update(layout=layout,zone_playlists=zones)
                rules=body.get('rules')
                if not isinstance(rules,list) or len(rules)>50:raise DeviceError('시간표는 최대 50개입니다.')
                identifiers=set()
                for r in rules:
                    if not isinstance(r,dict) or set(r)!={'id','playlist_id','paused','days','start','end','date_from','date_to','priority'} or (not isinstance(r.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',r['id'])) or r['id'] in identifiers:raise DeviceError('시간표 형식이 올바르지 않습니다.')
                    identifiers.add(r['id'])
                    if type(r.get('paused')) is not bool or (not isinstance(r.get('playlist_id'),str) or (not r['paused'] and r.get('playlist_id') not in playlists)) or not isinstance(r.get('days'),list) or not r['days'] or any(type(d) is not int or not 0<=d<=6 for d in r['days']) or len(set(r['days']))!=len(r['days']):raise DeviceError('시간표의 요일과 재생목록을 확인해 주세요.')
                    for k in ('start','end'):
                        if not isinstance(r[k],str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',r[k]):raise DeviceError('시작·종료 시간을 확인해 주세요.')
                    for k in ('date_from','date_to'):
                        if not isinstance(r[k],str):raise DeviceError('기간 날짜를 확인해 주세요.')
                        if r[k]:
                            try:datetime.strptime(r[k],'%Y-%m-%d')
                            except (ValueError,TypeError):raise DeviceError('기간 날짜를 확인해 주세요.')
                    if r['date_from'] and r['date_to'] and r['date_from']>r['date_to']:raise DeviceError('종료일은 시작일 이후여야 합니다.')
                    if type(r['priority']) is not int or not 0<=r['priority']<=100:raise DeviceError('우선순위는 0~100으로 지정해 주세요.')
            if not item:
                if len(items)>=100:raise DeviceError('생성 가능한 항목 수를 초과했습니다.',409)
                item=dict(id=new_id('pl' if kind=='playlists' else 'gr'),revision=0,created_at=int(time.time()));items.append(item)
            item.update(value,revision=item['revision']+1,updated_at=int(time.time()));self.event(data,'save',item['name'],kind=kind);self.write(data);return copy.deepcopy(item)
    def compile(self,playlist,source,version):
        lookup={s['id']:s for s in source['screens'] if s.get('type')!='queue'};slides=[]
        for i,entry in enumerate(playlist['items']):
            original=lookup.get(entry['screen_id'])
            if not original:raise DeviceError('재생목록의 콘텐츠가 삭제되었습니다. 먼저 수정해 주세요.',409)
            c=original.get('content',{});parts=copy.deepcopy(c.get('slides',[]))
            if c.get('mode') in ('menu','basic'):
                elements=[dict(id='title',kind='text',text=original.get('title') or original['name'],x=7,y=6,w=86,h=14,fontSize=70,color=original['accent'],fontFamily=c.get('fontFamily','pretendard'),bold=True)]
                if c.get('mode')=='menu':
                    items=c.get('menuItems',[]);columns=2 if len(items)>8 else 1
                    for n,m in enumerate(items):
                        row=n%8;column=n//8;y=24+row*8;x=7+column*47;width=86 if columns==1 else 40
                        name=('추천 · ' if m.get('featured') else '')+m.get('name','');price='품절' if m.get('soldOut') else str(m.get('price',''));color='#8894a8' if m.get('soldOut') else '#ffffff'
                        elements.extend([dict(id='name'+str(n),kind='text',text=name,x=x,y=y,w=width*.7,h=5,fontSize=30,color=color),dict(id='price'+str(n),kind='text',text=price,x=x+width*.72,y=y,w=width*.28,h=5,fontSize=26,color=color,align='right')])
                        if m.get('description'):elements.append(dict(id='description'+str(n),kind='text',text=m['description'],x=x,y=y+4.8,w=width,h=3,fontSize=17,color='#adb8cc'))
                else:elements.append(dict(id='body',kind='text',text=original.get('subtitle',''),x=8,y=35,w=84,h=40,fontSize=42,color='#ffffff'))
                parts=[dict(id='menu',duration=10,transition='fade',elements=elements)]
            if not parts:raise DeviceError('빈 콘텐츠는 재생목록에 배포할 수 없습니다: '+original['name'],409)
            for j,slide in enumerate(parts):
                slide['id']=f'{i}-{j}';slide.setdefault('background',c.get('background','#142039'));slide.setdefault('fontFamily',c.get('fontFamily','pretendard'))
                if entry['duration']:slide['duration']=entry['duration']
                for k,e in enumerate(slide['elements']):
                    e['id']=f'{i}-{j}-{k}'
                    if e['kind']=='video':e.setdefault('playbackRate',c.get('playbackRate',1))
                slides.append(slide)
            if len(slides)>500:raise DeviceError('배포할 슬라이드는 최대 500개입니다.',409)
        first=lookup[playlist['items'][0]['screen_id']]
        return dict(id=playlist['id'],revision=version,name=playlist['name'],type='ads',title=playlist['name'],subtitle='',accent=first['accent'],status='active',content=dict(mode='slides',aspect=first['content'].get('aspect','landscape'),background='#142039',playbackRate=1,menuItems=[],slides=slides))
    def deploy(self,gid,body,source,device_ids):
        with self.lock:
            data=self.read();g=next((g for g in data['groups'] if g['id']==gid),None)
            if not g:raise DeviceError('그룹을 찾을 수 없습니다.',404)
            if set(body)!={'revision'} or body['revision']!=g['revision']:raise DeviceError('최신 그룹 설정으로 다시 배포해 주세요.',409)
            if any(d not in device_ids for d in g['device_ids']):raise DeviceError('삭제된 장치를 그룹에서 먼저 제거해 주세요.',409)
            ids={g['default_playlist_id'],*g.get('zone_playlists',[]),*(r['playlist_id'] for r in g['rules'] if not r['paused'])};lookup={p['id']:p for p in data['playlists']};version=g.get('published',{}).get('revision',0)+1
            if not ids<=lookup.keys():raise DeviceError('재생목록을 찾을 수 없습니다.',409)
            # Each deployed playlist uses one aspect; mixing orientations is rejected.
            for pid in ids:
                aspects={s.get('content',{}).get('aspect','landscape') for s in source['screens'] if any(e['screen_id']==s['id'] for e in lookup[pid]['items'])}
                if len(aspects)>1:raise DeviceError('같은 재생목록의 화면 방향을 통일해 주세요.',409)
            program=dict(id=gid,revision=version,name=g['name'],timezone=g['timezone'],default_playlist_id=g['default_playlist_id'],rules=copy.deepcopy(g['rules']),ticker=g['ticker'],clock=g['clock'],device_ids=list(g['device_ids']),playlists={pid:self.compile(lookup[pid],source,version) for pid in sorted(ids)},deployed_at=int(time.time()))
            program['source_playlists']={pid:lookup[pid]['revision'] for pid in ids}
            used={e['screen_id'] for pid in ids for e in lookup[pid]['items']};program['source_screens']={s['id']:s['revision'] for s in source['screens'] if s['id'] in used}
            program['zones']=[dict(x=x,y=y,w=w,h=h,playlist_id=g['zone_playlists'][i-1] if i else '') for i,(x,y,w,h) in enumerate(LAYOUTS[g.get('layout','full')])]
            g.update(published=program,revision=g['revision']+1,deployed_draft_revision=g['revision']+1);self.event(data,'deploy',g['name'],group_id=gid,version=version,devices=len(g['device_ids']));self.write(data);return copy.deepcopy(g)
    def override(self,gid,body,source):
        with self.lock:
            data=self.read();g=next((g for g in data['groups'] if g['id']==gid),None)
            if not g or not g.get('published'):raise DeviceError('그룹을 먼저 배포해 주세요.',409)
            if type(body.get('revision')) is not int or body['revision']!=g['revision']:raise DeviceError('그룹 목록을 새로 불러와 주세요.',409)
            if set(body)=={'revision','clear'} and body['clear'] is True:g['published'].pop('override',None)
            else:
                if set(body)-{'revision','message','minutes','playlist_id'} or type(body.get('minutes')) is not int or not 1<=body['minutes']<=1440:raise DeviceError('임시 출력 시간은 1~1440분으로 지정해 주세요.')
                playlist=next((p for p in data['playlists'] if p['id']==body.get('playlist_id')),None)
                if body.get('playlist_id') and not playlist:raise DeviceError('재생목록을 찾을 수 없습니다.',404)
                if playlist:screen=self.compile(playlist,source,g['published']['revision']+1)
                else:
                    message=body.get('message','')
                    if not isinstance(message,str) or not 1<=len(message.strip())<=500:raise DeviceError('임시 출력 문구를 입력해 주세요.')
                    screen=dict(id=gid+'-override',revision=int(time.time()*1000),name='임시 안내',type='notice',title='안내',subtitle='',accent='#85a5ff',status='active',content=dict(mode='slides',aspect=next(iter(g['published']['playlists'].values()))['content']['aspect'],background='#101827',playbackRate=1,menuItems=[],slides=[dict(id='override',duration=10,transition='fade',elements=[dict(id='message',kind='text',text=message.strip(),x=8,y=15,w=84,h=70,color='#ffffff',fontSize=70,bold=True,align='center',fontFamily='pretendard')])]))
                g['published']['override']=dict(until=int(time.time())+body['minutes']*60,screen=screen)
            clean=g['revision']==g.get('deployed_draft_revision');g['published']['revision']+=1;g['revision']+=1;
            if clean:g['deployed_draft_revision']=g['revision']
            self.event(data,'override',g['name'],group_id=gid,cleared=not bool(g['published'].get('override')));self.write(data);return copy.deepcopy(g)
    def for_device(self,did):
        with self.lock:
            return next((copy.deepcopy(g['published']) for g in self.read()['groups'] if did in g.get('published',{}).get('device_ids',[])),None)
    def delivery(self,device,source):
        program=self.for_device(device['device_id'])
        if program:return choose_screen(program),program
        screen=next((s for s in source['screens'] if s['id']==device['screen_id'] and s.get('type')!='queue'),None)
        return copy.deepcopy(screen),None
    def referenced_contents(self):
        with self.lock:return [s['content'] for g in self.read()['groups'] for s in program_screens(g.get('published'))]
    def heartbeat_event(self,device,report):
        if not report:return
        with self.lock:
            data=self.read();key=device['device_id'];state=data.setdefault('reported',{});value=dict(program_id=report.get('program_id',''),program_revision=report.get('program_revision',0))
            if state.get(key)!=value:
                state[key]=value;self.event(data,'device_received',device['device_name'],device_id=key,**value);self.write(data)
