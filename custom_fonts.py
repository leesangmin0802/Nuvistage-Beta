"""Validated local font uploads. Uploaded fonts are data, never executable stylesheets."""
from io import BytesIO
from pathlib import Path
import re
import time
from uuid import uuid4

CUSTOM_FONT=re.compile(r'custom-[0-9a-f]{32}')

def font_ids(content,include_drafts=True):
    result={content.get('fontFamily','pretendard')}
    for slide in content.get('slides',[]):
        result.add(slide.get('fontFamily',content.get('fontFamily','pretendard')))
        result.update(e.get('fontFamily',slide.get('fontFamily',content.get('fontFamily','pretendard'))) for e in slide.get('elements',[]) if e.get('kind')=='text')
    if include_drafts:
        for draft in content.get('modeDrafts',{}).values():result.update(font_ids(draft,False))
    return {f for f in result if isinstance(f,str) and CUSTOM_FONT.fullmatch(f)}

def inspect_font(raw):
    if len(raw)<48 or raw[:4] not in (b'\x00\x01\x00\x00',b'OTTO',b'wOFF',b'wOF2'):raise ValueError('TTF·OTF·WOFF·WOFF2 글꼴 파일을 선택해 주세요.')
    if raw[:4] in (b'wOFF',b'wOF2') and int.from_bytes(raw[16:20],'big')>128*1024*1024:raise ValueError('압축 해제 크기가 너무 큰 글꼴입니다.')
    try:
        from fontTools.ttLib import TTFont
    except ImportError:raise ValueError('글꼴 가져오기 의존성을 설치해 주세요: requirements-fonts.txt')
    try:
        with TTFont(BytesIO(raw),lazy=False) as font:
            if not font.getBestCmap() or 'head' not in font or 'hhea' not in font:raise ValueError()
            name=font['name'].getDebugName(16) or font['name'].getDebugName(1) or '가져온 글꼴'
            name=''.join(c for c in name if ord(c)>=32)[:80]
    except Exception:raise ValueError('유효한 글꼴 데이터를 읽을 수 없습니다. 손상되었거나 지원하지 않는 글꼴입니다.') from None
    return name,{b'\x00\x01\x00\x00':'ttf',b'OTTO':'otf',b'wOFF':'woff',b'wOF2':'woff2'}[raw[:4]]

def upload_font(handler):
    from urllib.parse import unquote
    length=int(handler.headers.get('Content-Length','0'))
    if not 0<length<=32*1024*1024:return handler.reply(413,{'error':'글꼴 파일은 32MB 이내로 선택해 주세요.'})
    raw=handler.rfile.read(length)
    if len(raw)!=length:raise ValueError('글꼴 업로드가 완료되지 않았습니다.')
    family,extension=inspect_font(raw);name=unquote(handler.headers.get('X-Filename',''))
    name=Path(name.replace('\\','/')).stem.strip()[:80] or family
    item=dict(id='custom-'+uuid4().hex,name=name,family=family,extension=extension,size=len(raw),createdAt=int(time.time()))
    item['file']=item['id']+'.'+extension;item['url']='/custom-fonts/'+item['file']
    store=handler.server.store;store.font_dir.mkdir(exist_ok=True);path=store.font_dir/item['file']
    with store.lock:
        data=store.read()
        if len(data['customFonts'])>=100:raise ValueError('외부 글꼴은 최대 100종까지 등록할 수 있습니다.')
        try:
            path.write_bytes(raw);data['customFonts'].append(item);store.write(data)
        except Exception:path.unlink(missing_ok=True);raise
    return handler.reply(201,{'font':item})

def delete_font(handler,path,body,data):
    fid=path.removeprefix('/api/fonts/');item=next((f for f in data['customFonts'] if f['id']==fid),None)
    if not item:return handler.reply(404,{'error':'글꼴을 찾을 수 없습니다.'})
    used=[s['name'] for s in data['screens'] if s.get('type')!='queue' and fid in font_ids(s.get('content',{}))]
    used+=['템플릿: '+t['name'] for t in data['templates'] if t.get('type')!='queue' and fid in font_ids(t.get('content',{}))]
    if any(fid in font_ids(c,False) for c in handler.server.operations.referenced_contents()):used.append('배포된 그룹')
    if used:return handler.reply(409,{'error':'사용 중인 글꼴입니다. 먼저 해당 화면이나 템플릿에서 변경해 주세요.','usedBy':used})
    file=handler.server.store.font_dir/item['file'];tombstone=file.with_suffix('.deleting');existed=file.exists()
    if existed:file.replace(tombstone)
    data['customFonts'].remove(item)
    try:handler.server.store.write(data)
    except OSError:
        if existed:tombstone.replace(file)
        raise
    tombstone.unlink(missing_ok=True);return handler.reply(200,{'ok':True})

def serve_font(handler,item):
    file=handler.server.store.font_dir/item['file']
    if not file.is_file():return handler.reply(404,{'error':'글꼴 파일이 없습니다.'})
    return handler.reply(200,file.read_bytes(),'font/'+item['extension'])

def validate_references(content,data):
    available={f['id'] for f in data['customFonts']}
    if font_ids(content)-available:raise ValueError('등록되지 않은 외부 글꼴이 포함되어 있습니다.')
    profiles=[content,*content.get('modeDrafts',{}).values()]
    for profile in profiles:
        for slide in profile.get('slides',[]):
            for e in slide['elements']:
                if e['kind'] in ('image','video') and not any(m['id']==e['mediaId'] and m['mime'].startswith(e['kind']+'/') for m in data['media']):raise ValueError('콘텐츠에 없는 미디어 또는 잘못된 종류가 포함되어 있습니다.')
