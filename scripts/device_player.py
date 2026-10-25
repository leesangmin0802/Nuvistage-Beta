#!/usr/bin/env python3
"""Initial setup and auto-reconnect of a registered Player. Use --once for virtual tests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from device_client import DeviceClient,ClientError,VERSION
from discovery import discover


def choose_server():
    try:servers=discover()
    except ValueError as error:print(str(error));servers=[]
    if len(servers)==1:
        print('서버를 찾았습니다: '+servers[0]['url']);return servers[0]['url'],servers[0]['server_id']
    if servers:
        print('검색된 서버:')
        for i,item in enumerate(servers,1):print(f"{i}. {item['name']} — {item['url']}")
        answer=input('서버 번호 선택 (직접 입력하려면 Enter): ').strip()
        if answer:
            try:return servers[int(answer)-1]['url'],servers[int(answer)-1]['server_id']
            except (ValueError,IndexError):raise ClientError('서버 번호를 확인해 주세요.')
    return input('HTTPS 서버 주소: ').strip(),None


def setup_gui(client):
    import tkinter as tk
    from tkinter import ttk,filedialog
    import threading
    app=tk.Tk();app.title('Nuvistage Player');app.geometry('720x560');app.configure(bg='#101827')
    frame=ttk.Frame(app,padding=30);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Nuvistage',font=('',26,'bold')).pack(anchor='w')
    ttk.Label(frame,text='관리자 페이지의 장치 추가에서 아래 코드를 입력하세요.').pack(anchor='w',pady=(12,8))
    code=client.pairing_code;ttk.Label(frame,text='  '.join(code[i:i+4] for i in range(0,16,4)),font=('',30,'bold')).pack(pady=18)
    variables={k:tk.StringVar(value=client.config.get('device_name','새 Player') if k=='name' else client.config.get('server_url','') if k=='server' else client.ca_file or '') for k in ('name','server','ca')}
    for key,title in [('name','장치 이름'),('server','서버 주소'),('ca','CA 인증서 (미리 설정되어 있으면 비워두세요)')]:
        ttk.Label(frame,text=title).pack(anchor='w',pady=(8,4));ttk.Entry(frame,textvariable=variables[key]).pack(fill='x')
    row=ttk.Frame(frame);row.pack(fill='x',pady=12);chooser=ttk.Combobox(row,state='readonly',width=40);chooser.pack(side='right');found=[];done=[];stopped=threading.Event();busy=False
    status=tk.StringVar(value='서버를 검색하는 중…');ttk.Label(frame,textvariable=status,wraplength=650).pack(anchor='w',pady=10)
    def selected(event):
        if chooser.current()>=0:variables['server'].set(found[chooser.current()]['url'])
    chooser.bind('<<ComboboxSelected>>',selected)
    ttk.Button(row,text='인증서 선택',command=lambda:variables['ca'].set(filedialog.askopenfilename(filetypes=[('인증서','*.pem *.crt')]))).pack(side='left')
    def close():stopped.set();app.destroy()
    app.protocol('WM_DELETE_WINDOW',close)
    def connect():
        nonlocal busy
        if busy:return
        busy=True;values={k:v.get().strip() for k,v in variables.items()};button.state(['disabled']);status.set('서버에 연결하는 중…')
        def worker():
            try:
                candidate=DeviceClient(client.directory,values['ca'] or None);expected=next((x['server_id'] for x in found if x['url']==values['server']),None)
                candidate.begin_pairing(values['server'],values['name'],expected)
                app.after(0,lambda:status.set('연결 대기 중 · 관리자에서 코드를 입력하면 화면이 자동으로 열립니다.'))
                while not stopped.wait(3):
                    if candidate.poll_pairing()['status']=='registered':
                        done.append(True);app.after(0,close);return
            except (ClientError,OSError,ValueError) as error:
                message=str(error) if isinstance(error,ClientError) else '서버 주소와 인증서 설정을 확인해 주세요.'
                def fail():
                    nonlocal busy
                    busy=False;status.set(message);button.state(['!disabled'])
                if not stopped.is_set():app.after(0,fail)
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(frame,text='서버에 연결',command=connect);button.pack(fill='x')
    def search():
        try:result=discover()
        except ValueError:result=[]
        def finish():
            if stopped.is_set():return
            found[:]=result;chooser['values']=[x['name']+' · '+x['url'] for x in result]
            if len(result)==1 and not variables['server'].get():variables['server'].set(result[0]['url'])
            if variables['server'].get():connect()
            else:status.set('서버를 선택하거나 주소를 입력하세요.')
        if not stopped.is_set():app.after(0,finish)
    threading.Thread(target=search,daemon=True).start();app.mainloop()
    if not done:raise ClientError('Player 연결이 완료되지 않았습니다.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--state',type=Path,default=Path.home()/'.local/share/pisignage-device');parser.add_argument('--ca',type=Path);parser.add_argument('--server');parser.add_argument('--name');parser.add_argument('--install-autostart',action='store_true');parser.add_argument('--setup',action='store_true');parser.add_argument('--setup-ui',action='store_true');parser.add_argument('--discover',action='store_true');parser.add_argument('--once',action='store_true');parser.add_argument('--headless',action='store_true');parser.add_argument('--browser-binary',help='Chromium 또는 Chrome 실행 파일 경로');parser.add_argument('--launch',action='store_true',help='기존 재생 엔진을 사용하는 로컬 캐시 화면을 Chromium으로 열기');args=parser.parse_args()
    try:
        if args.install_autostart:
            if sys.platform!='linux':raise ClientError('데스크톱 자동 실행 설치는 Raspberry Pi OS/Linux에서 지원합니다.')
            from scripts.run_player import desktop_quote
            folder=Path.home()/'.config/autostart';folder.mkdir(parents=True,exist_ok=True)
            command=[sys.executable,str(Path(__file__).resolve()),'--state',str(args.state.expanduser().resolve()),'--setup-ui','--launch']
            if args.ca:command+=['--ca',str(args.ca.resolve())]
            if args.browser_binary:command+=['--browser-binary',args.browser_binary]
            target=folder/'pisignage-device.desktop';target.write_text('[Desktop Entry]\nType=Application\nName=Nuvistage Device Player\nExec='+' '.join(desktop_quote(v) for v in command)+'\nTerminal=false\nX-GNOME-Autostart-enabled=true\n');os.chmod(target,0o600);print('다음 데스크톱 로그인부터 장치 Player가 자동 연결됩니다. 미등록 상태이면 최초 설정 창을 표시합니다.');return
        if args.discover:
            print(json.dumps(discover(),ensure_ascii=False,indent=2));return
        client=DeviceClient(args.state,args.ca)
        if args.setup_ui and (args.setup or not client.config.get('device_token')):setup_gui(client);client=DeviceClient(args.state,args.ca)
        elif args.setup or not client.config.get('device_token'):
            code=client.pairing_code;print('Player 코드: '+'-'.join(code[i:i+4] for i in range(0,16,4)),flush=True)
            if args.server:url,expected=args.server,None
            else:
                found=discover()
                if len(found)==1:url,expected=found[0]['url'],found[0]['server_id']
                elif sys.stdin.isatty():url,expected=choose_server()
                else:raise ClientError('서버를 선택할 수 없습니다. --server로 서버 주소를 지정해 주세요.')
            client.begin_pairing(url,args.name or client.config.get('device_name','새 Player'),expected)
            print('관리자에서 이 코드를 입력하면 자동으로 연결됩니다.',flush=True)
            while client.poll_pairing()['status']!='registered':time.sleep(3)
            print('장치 연결을 완료했습니다.',flush=True)
        process=None;delay=3
        while True:
            try:
                result=client.reconnect();print('연결됨 · '+result['device']['device_name']+' · '+('화면 배정됨' if result['screen'] else '화면 배정 대기'));delay=3
            except ClientError as error:
                print(str(error)+(' · 기존 캐시를 유지합니다.' if client.cached and error.status not in (401,403) else ''))
                if args.once:raise
                if error.status in (401,403):
                    if args.once:raise
                    # Do not re-register automatically: the registration password is never persisted.
                    time.sleep(15);continue
                delay=min(delay*2,30)
            if process is not None and process.poll() is not None:process=None
            if args.launch and not args.headless and process is None and (client.directory/'cache/index.html').exists():
                from scripts.run_player import chromium_command
                command=chromium_command((client.directory/'cache/index.html').resolve().as_uri(),args.browser_binary);command=[v for v in command if not v.startswith('--user-data-dir=')]+['--user-data-dir='+str((client.directory/'browser').resolve())];process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if args.once:return
            time.sleep(delay if delay>3 else 10)
    except KeyboardInterrupt:pass
    except (ClientError,ValueError,OSError) as error:raise SystemExit('Player: '+(str(error) if isinstance(error,ClientError) else '인증서·저장 폴더·자동 검색 설정을 확인해 주세요.'))

if __name__=='__main__':main()
