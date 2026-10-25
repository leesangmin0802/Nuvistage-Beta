#!/usr/bin/env python3
"""Create a private local CA and a SAN-validated LAN server certificate using OpenSSL."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def create_certificates(directory,hosts):
    directory=Path(directory)
    if directory.exists() and any(directory.iterdir()):raise ValueError('인증서를 덮어쓰지 않습니다. 비어 있는 새 폴더를 지정해 주세요.')
    if not shutil.which('openssl'):raise ValueError('OpenSSL 실행 파일이 필요합니다.')
    names=[]
    for value in dict.fromkeys(['localhost','127.0.0.1']+hosts):
        try:ipaddress.ip_address(value);names.append('IP:'+value)
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?',value):raise ValueError('인증서 호스트 이름을 확인해 주세요.')
            names.append('DNS:'+value)
    directory.mkdir(parents=True,exist_ok=True);os.chmod(directory,0o700)
    def run(*args):subprocess.run(['openssl',*map(str,args)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    run('req','-x509','-newkey','rsa:3072','-nodes','-sha256','-days','3650','-keyout',directory/'ca-key.pem','-out',directory/'ca.pem','-subj','/CN=Nuvistage Local CA','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign','-addext','subjectKeyIdentifier=hash','-addext','authorityKeyIdentifier=keyid:always')
    run('req','-new','-newkey','rsa:3072','-nodes','-keyout',directory/'server-key.pem','-out',directory/'server.csr','-subj','/CN=Nuvistage Server')
    extension=directory/'server.ext';extension.write_text('subjectAltName='+','.join(names)+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always,issuer\n')
    run('x509','-req','-in',directory/'server.csr','-CA',directory/'ca.pem','-CAkey',directory/'ca-key.pem','-CAcreateserial','-out',directory/'server.pem','-days','365','-sha256','-extfile',extension)
    for path in directory.iterdir():os.chmod(path,0o600 if 'key' in path.name else 0o644)
    (directory/'server.csr').unlink();extension.unlink()
    return directory

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=Path(__file__).resolve().parents[1]/'.tls');p.add_argument('--host',action='append',default=[],help='접속에 사용할 DNS 이름 또는 IP (반복 가능)');args=p.parse_args()
    try:
        directory=create_certificates(args.out,args.host);print('인증서 생성 완료: '+str(directory));print('Player에 안전하게 전달할 파일: ca.pem (개인키는 전달하지 마세요.)')
    except (ValueError,OSError,subprocess.CalledProcessError):raise SystemExit('인증서를 생성하지 못했습니다. 호스트 이름·OpenSSL·폴더 권한을 확인해 주세요.')
