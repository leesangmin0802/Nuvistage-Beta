# 배포 안내

[← README](README.md) · [Player 연결](DEVICE_REGISTRATION.md) · [개발 안내](DEVELOPMENT.md)

## 배포 구성

| 장치 | 실행하는 프로그램 |
| --- | --- |
| 메인 Raspberry Pi | Nuvistage 서버, 필요하면 Player도 함께 실행 |
| 추가 Raspberry Pi | Player와 Chromium만 실행 |
| 관리자 PC | 웹 브라우저로 서버에 접속 |

서버 한 대가 데이터를 관리하고, Player마다 별도 상태 폴더를 사용합니다. 여러 서버 프로세스가 같은 데이터 파일을 동시에 사용하면 안 됩니다.

## 1. 설치와 최초 계정

프로젝트 폴더에서 실행합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

메인 서버의 브라우저에서 `http://localhost:8765`를 열어 관리자 계정을 만듭니다. 공용 기본 계정은 없습니다. 최초 계정 생성 이후 서버를 종료합니다.

## 2. HTTPS와 LAN 연결

신규 장치 연결에는 HTTPS와 서버 인증서 검증을 사용합니다. 실제 접속 이름을 인증서에 포함하세요.

```bash
.venv/bin/python scripts/create_tls.py --out .tls --host nuvistage.local
.venv/bin/python server.py --host 0.0.0.0 --port 8765 \
  --tls-cert .tls/server.pem --tls-key .tls/server-key.pem \
  --mdns --advertise-host nuvistage.local
```

`nuvistage.local`이 메인 서버로 연결되도록 OS 호스트 이름 또는 내부 DNS를 설정합니다. 기존 인증서가 있으면 덮어쓰지 말고 그 인증서에 포함된 이름을 사용합니다. DHCP 예약을 사용하면 주소 변경을 줄일 수 있습니다.

서버의 `ca.pem`을 Player의 신뢰 설정에 전달합니다. CA 개인키와 서버 개인키는 Player에 복사하지 않습니다. 자세한 연결 절차는 [DEVICE_REGISTRATION.md](DEVICE_REGISTRATION.md)를 참고하세요.

## 3. Player 실행

```bash
.venv/bin/python scripts/device_player.py \
  --state .device-players/main \
  --ca /path/to/ca.pem \
  --setup-ui --launch
```

Player의 16자리 코드를 관리자 **장치 관리 → 장치 추가**에 입력하고 화면을 배정합니다. 연결 후에는 같은 명령으로 재부팅 후 자동 연결할 수 있습니다.

Raspberry Pi의 그래픽 데스크톱에서 Player 자동 실행을 설치하려면:

```bash
.venv/bin/python scripts/device_player.py \
  --state .device-players/main \
  --ca /path/to/ca.pem \
  --install-autostart
```

자동 실행에는 그래픽 세션이 필요합니다. 데스크톱 자동 로그인과 HDMI 해상도는 OS에서 설정합니다. 스크립트는 OS 설정을 대신 변경하지 않습니다.

## 4. 메인 서버 자동 실행

Linux에서 관리자 계정과 TLS 인증서를 준비한 뒤, 수동으로 실행한 서버를 종료하고 실행합니다.

```bash
.venv/bin/python scripts/install_server_service.py --hostname nuvistage.local
```

현재 서비스 파일 이름은 기존 설치와 호환되는 `pisignage-server.service`입니다.

```bash
systemctl --user status pisignage-server.service
journalctl --user -u pisignage-server.service -f
```

로그인 전부터 사용자 서비스를 실행해야 한다면 시스템 관리자가 다음을 설정합니다.

```bash
sudo loginctl enable-linger "$USER"
```

서비스에는 프로젝트의 절대 경로가 기록됩니다. 프로젝트를 옮긴 경우 서비스를 다시 생성하세요. 이 서비스는 메인 서버에만 설치합니다.

## 백업과 복구

서버를 종료하고 다음 항목을 함께 보관합니다.

| 항목 | 역할 |
| --- | --- |
| `data.json` | 콘텐츠·설정·내 템플릿 |
| `data.auth.json` | 관리자 인증·서명 키 |
| `data.devices.json` | 장치 인증·배정 |
| `data.operations.json` | 그룹·예약·배포 |
| `data.media/`, `data.fonts/` | 업로드한 원본 파일 |
| `.tls/` | 서버 인증서·키 |

Player의 상태 폴더도 재설치 시 연결을 유지하려면 별도로 백업합니다. 백업 파일은 Git 저장소와 분리해 보관합니다.

사용자 지정 `--data`를 사용하면 같은 파일 이름에 `.auth.json`, `.devices.json`, `.operations.json`, `.media/`, `.fonts/`가 대응합니다. 복구할 때는 서버를 종료한 상태에서 일관된 백업 세트를 되돌립니다.

## 관리자 계정 복구

비밀번호를 잊었다면 메인 서버를 종료한 뒤 로컬 터미널에서 실행합니다.

```bash
.venv/bin/python scripts/reset_admin.py
```

터미널에서 새 비밀번호를 직접 입력합니다. 기존 콘텐츠와 Player 연결을 유지하는 계정 복구 도구이며 전체 초기화 명령은 아닙니다.

## 기존 화면 링크 방식

이전 설치에서 사용한 화면별 출력 링크와 `scripts/run_player.py`는 호환용으로 유지합니다. 신규 설치는 코드 연결 방식을 사용하세요. 기존 Player 설정 JSON도 출력 권한을 포함하므로 저장소에 올리지 않습니다.

## 확인 범위

macOS에서 API, HTTPS 가상 Player, 캐시 생성, 관리자 미리보기를 검증했습니다. Raspberry Pi의 부팅 자동 실행·다중 영상·실제 HDMI 출력은 운영 장치에서 별도로 확인해야 합니다.
