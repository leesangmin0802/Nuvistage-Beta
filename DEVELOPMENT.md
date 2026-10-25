# 개발 안내

[← README](README.md) · [구조 안내](docs/ARCHITECTURE.md) · [업데이트 기록](CHANGELOG.md)

## 개발 환경

Nuvistage는 Python HTTP 서버와 브라우저의 JavaScript 모듈로 구성됩니다. 프런트엔드 빌드 과정 없이 소스 파일을 바로 제공합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

관리 페이지는 `http://localhost:8765`에서 열립니다. 기본 바인딩은 localhost이며 LAN 배포 절차는 [DEPLOYMENT.md](DEPLOYMENT.md)에 있습니다.

## 테스트

Python 테스트는 임시 폴더와 별도 서버를 사용합니다. 실제 운영 데이터를 수정하지 않습니다. HTTPS 테스트에는 OpenSSL, mDNS 테스트에는 `requirements-device.txt`의 패키지가 필요합니다. JavaScript 테스트에는 Node.js 22 이상을 사용합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
node --import ./tests/register_modules.mjs --test tests/test_design.mjs
```

| 범위 | 검증 항목 |
| --- | --- |
| 서버 | 로그인·CSRF·권한 분리, 저장 충돌, 미디어·글꼴 참조 보호, 템플릿, 재시작 |
| 장치 | HTTPS, 코드 등록, 응답 유실 복구, 재부팅, 차단·토큰 폐기, 가상 프로세스 |
| 운영 | 초안·배포본 분리, 그룹 중복 방지, 저장 실패, 콘텐츠 컴파일 |
| 시간표 | 요일·기간·시간대, 자정 통과, 우선순위, 기본 재생, 임시 출력 만료 |
| 편집기 | 모드 복원, 독립 슬라이드, 정렬·간격·복제, 도형, 한국어 템플릿 |

현재 기준 테스트는 Python 40개, JavaScript 13개입니다. 테스트에 포함된 계정·비밀번호·인증서는 임시 환경에서 사용하는 가짜 값이며 설치용 기본 계정이 아닙니다.

## 브라우저 검증

운영 데이터와 분리된 임시 관리 화면을 실행할 수 있습니다.

```bash
.venv/bin/python tests/browser_harness.py --ui-session
```

`http://localhost:8878/test/start`에서 임시 세션을 시작합니다. 서버를 종료하면 이 테스트 환경의 계정과 데이터가 제거됩니다. 이 경로는 운영 서버에 존재하지 않습니다.

모바일 레이아웃은 `http://localhost:8878/test/mobile?route=/dashboard`에서 확인할 수 있습니다. 테스트 스크린샷은 `docs/screenshots/`에 저장하며 Git에서 제외합니다.

## 소스 구성

```text
.
├── server.py                 # HTTP 라우팅·화면·미디어·저장
├── auth.py                   # 관리자 인증과 출력 서명
├── devices.py                # 장치 레지스트리
├── pairing.py                # 코드 기반 최초 연결
├── device_api.py             # 장치 API
├── operations.py             # 재생목록·그룹·예약·배포
├── operations_api.py         # 운영 관리 API
├── device_client.py          # Player 연결·다운로드·캐시
├── admin.js                  # 단일 페이지 관리자
├── canvas.js                 # 공통 콘텐츠 렌더러
├── scheduled-player.js       # 예약·분할 재생
├── *-admin.js / *-tools.js    # 관리·편집 도구
├── scripts/                  # 실행·배포·계정 복구 도구
├── tests/                    # 자동 테스트
├── fonts/                    # 내장 글꼴과 라이선스
└── docs/                     # 설계 문서와 공용 이미지
```

## 변경 시 점검

- 저장 포맷을 변경하면 기존 데이터 읽기와 재시작을 확인합니다.
- 편집기와 Player는 같은 렌더러를 사용합니다. 새 속성은 서버 검증과 캐시에도 반영합니다.
- 관리자 API는 로그인과 CSRF, Player API는 장치 토큰으로 보호합니다.
- 미디어·글꼴 삭제 시 비활성 편집 모드와 배포 스냅샷의 참조도 확인합니다.
- 장치 토큰·등록 비밀값·관리자 비밀번호를 로그에 남기지 않습니다.
- 기능이 실제 출력인지 관리자 미리보기인지, 수신 기록인지 재생 증명인지 구분합니다.

## GitHub에 올리기 전

```bash
git status --short
git status --short --ignored
```

`data*.json`, 업로드 폴더, `credentials.json`, 인증서, Player 설정 JSON, `.env`, 로컬 로그는 커밋하지 않습니다. 빈 구조가 필요하면 `data.example.json`을 사용하세요. `.gitignore`는 이미 추적 중인 파일을 제거하지 않으므로, 기존 저장소에서는 추적 목록도 확인해야 합니다.
