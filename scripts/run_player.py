#!/usr/bin/env python3
"""Browser-only Raspberry Pi player. Does not start an HTTP server."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse, parse_qs


def load_player_url(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    value = data.get('playerUrl','')
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path != '/display.html':
        raise ValueError('관리자에서 다운로드한 플레이어 설정 JSON이 필요합니다.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', query.get('id',[''])[0]) or not re.fullmatch(r'[0-9a-f]{64}',fragment.get('token',[''])[0]):
        raise ValueError('설정에 올바른 화면 ID와 플레이어 연결 토큰이 없습니다.')
    return value


def chromium_command(url, binary=None):
    executable = binary or shutil.which('chromium') or shutil.which('chromium-browser')
    if not executable:
        raise ValueError('Chromium이 설치되어 있지 않습니다. Raspberry Pi OS에서 Chromium을 설치해 주세요.')
    profile = Path.home()/'.local/share/pisignage-player'
    return [str(executable),'--kiosk','--noerrdialogs','--disable-session-crashed-bubble',
            '--autoplay-policy=no-user-gesture-required','--user-data-dir='+str(profile),url]


def desktop_quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')+'"'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path,help='관리자에서 다운로드한 pisignage-player.json')
    parser.add_argument('--install-autostart',action='store_true',help='현재 사용자의 데스크톱 로그인 시 자동 실행')
    parser.add_argument('--check',action='store_true',help='설정만 검증하고 실행하지 않음')
    args=parser.parse_args()
    try:
        url=load_player_url(args.config)
        if args.check:
            print('플레이어 설정 형식 정상. 연결 토큰은 표시하지 않습니다.')
            return
        if args.install_autostart:
            if sys.platform!='linux': raise ValueError('자동 실행 설치는 Raspberry Pi OS/Linux에서만 지원합니다.')
            directory=Path.home()/'.config/autostart';directory.mkdir(parents=True,exist_ok=True)
            command=' '.join(desktop_quote(x) for x in (sys.executable,Path(__file__).resolve(),args.config.resolve()))
            (directory/'pisignage-player.desktop').write_text('[Desktop Entry]\nType=Application\nName=Nuvistage Player\nExec='+command+'\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
            os.chmod(args.config,0o600)
            print('다음 데스크톱 로그인부터 플레이어만 자동 실행합니다.')
            return
        subprocess.run(chromium_command(url),check=True)
    except (OSError,ValueError,subprocess.CalledProcessError) as error:
        raise SystemExit('플레이어를 시작하지 못했습니다: '+str(error))


if __name__=='__main__': main()
