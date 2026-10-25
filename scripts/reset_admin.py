#!/usr/bin/env python3
"""Local account recovery. Stop the server before running this command."""
import argparse
import getpass
import hashlib
from pathlib import Path
import secrets
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from auth import Auth, ITERATIONS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[1]/'data.json')
    args=parser.parse_args()
    path=args.data.with_suffix('.auth.json')
    if not path.exists(): raise SystemExit('기존 관리자 설정이 없습니다. 웹에서 최초 설정을 진행해 주세요.')
    auth=Auth(path)
    if not auth.configured: raise SystemExit('웹에서 최초 설정을 진행해 주세요.')
    password=getpass.getpass('새 관리자 비밀번호 (12자 이상): ')
    if not 12<=len(password)<=256 or password!=getpass.getpass('새 비밀번호 확인: '):
        raise SystemExit('비밀번호 길이 또는 확인이 일치하지 않습니다. 변경하지 않았습니다.')
    salt=secrets.token_hex(16)
    auth.config.update(salt=salt,passwordHash=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex())
    auth.save()
    print('비밀번호를 변경했습니다. 서버를 다시 시작하세요. 기존 플레이어 링크는 유지됩니다.')


if __name__=='__main__':main()
