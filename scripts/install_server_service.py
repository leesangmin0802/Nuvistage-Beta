#!/usr/bin/env python3
"""Install the main server as a Linux systemd user service. Main Pi only."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys


def quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def main():
    if sys.platform!='linux' or not shutil.which('systemctl'):
        raise SystemExit('메인 Raspberry Pi OS/Linux에서 실행해 주세요.')
    root=Path(__file__).resolve().parents[1]
    if not root.joinpath('data.auth.json').exists():
        raise SystemExit('먼저 python3 server.py를 실행하고 localhost:8765에서 관리자 계정을 설정해 주세요.')
    import json
    if not json.loads(root.joinpath('data.auth.json').read_text()).get('passwordHash'):
        raise SystemExit('최초 관리자 계정을 설정한 후 서비스를 설치해 주세요.')
    parser=argparse.ArgumentParser();parser.add_argument('--hostname',required=True,help='인증서 SAN에 포함된 .local 호스트 이름');parser.add_argument('--port',type=int,default=8765);parser.add_argument('--cert',type=Path,default=root/'.tls/server.pem');parser.add_argument('--key',type=Path,default=root/'.tls/server-key.pem');args=parser.parse_args()
    if not args.cert.is_file() or not args.key.is_file():raise SystemExit('먼저 서버 TLS 인증서를 생성해 주세요. DEVICE_REGISTRATION.md를 참고하세요.')
    if not importlib.util.find_spec('zeroconf'):raise SystemExit('requirements-device.txt를 설치한 Python 환경으로 실행해 주세요.')
    directory=Path.home()/'.config/systemd/user';directory.mkdir(parents=True,exist_ok=True)
    command=' '.join(quote(x) for x in (sys.executable,root/'server.py','--host','0.0.0.0','--data',root/'data.json','--port',args.port,'--tls-cert',args.cert.resolve(),'--tls-key',args.key.resolve(),'--mdns','--advertise-host',args.hostname))
    unit='[Unit]\nDescription=Nuvistage Main Server\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory='+quote(root)+'\nExecStart='+command+'\nRestart=on-failure\nRestartSec=3\nUMask=0077\n\n[Install]\nWantedBy=default.target\n'
    (directory/'pisignage-server.service').write_text(unit)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','pisignage-server.service'],check=True)
    print('메인 서버 사용자 서비스를 설치했습니다. 부팅 직후 실행은 loginctl enable-linger 사용자명 설정을 확인하세요.')


if __name__=='__main__': main()
