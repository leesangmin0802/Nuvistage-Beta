from devices import DeviceError

def handle_operations(handler,path):
    handler.device_admin();ops=handler.server.operations
    if path=='/api/v1/operations' and handler.command=='GET':
        result=ops.snapshot();devices=handler.server.devices.list();reported=result.get('reported',{})
        with handler.server.store.lock:source=handler.server.store.read()
        screens={s['id']:s['revision'] for s in source['screens']};playlists={p['id']:p['revision'] for p in result['playlists']}
        for g in result['groups']:
            published=g.get('published') or {};g['dirty']=not published or g['revision']!=g.get('deployed_draft_revision') or any(playlists.get(pid)!=rev for pid,rev in published.get('source_playlists',{}).items()) or any(screens.get(sid)!=rev for sid,rev in published.get('source_screens',{}).items())
        result['devices']=[dict(d,reported=reported.get(d['device_id'],{})) for d in devices]
        return handler.reply(200,result)
    parts=path.strip('/').split('/');kind=parts[3] if len(parts)>3 else '';iid=parts[4] if len(parts)>4 else '';action=parts[5] if len(parts)>5 else ''
    if len(parts)>6 or kind not in ('groups','playlists'):raise DeviceError('운영 API를 찾을 수 없습니다.',404)
    body=handler.device_json(128*1024);device_ids={d['device_id'] for d in handler.server.devices.list()}
    with handler.server.store.lock:
        source=handler.server.store.read()
        if action:
            if kind!='groups' or handler.command!='POST' or action not in ('deploy','override'):raise DeviceError('지원하지 않는 요청입니다.',405)
            value=ops.deploy(iid,body,source,device_ids) if action=='deploy' else ops.override(iid,body,source)
        else:
            if (handler.command,iid!='') not in (('POST',False),('PATCH',True),('DELETE',True)):raise DeviceError('지원하지 않는 요청입니다.',405)
            value=ops.mutate(kind,iid,handler.command,body,source,device_ids)
    return handler.reply(201 if handler.command=='POST' else 200,value)
