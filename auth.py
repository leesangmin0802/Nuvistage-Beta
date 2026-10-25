"""Single-admin authentication and read-only player credentials."""
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.cookies import SimpleCookie

ITERATIONS = 600_000
SESSION_SECONDS = 12 * 60 * 60


class Auth:
    def __init__(self, path, secure_cookie=False):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.secure_cookie = secure_cookie
        self.sessions = {}
        self.failures = {}
        if self.path.exists():
            self.config = json.loads(self.path.read_text())
        else:
            self.config = {'secret': secrets.token_hex(32)}
            self.save()

    @property
    def configured(self):
        return 'passwordHash' in self.config

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        with open(temporary, 'w', encoding='utf-8', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
            os.chmod(temporary, 0o600)
            json.dump(self.config, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    @staticmethod
    def loopback(address):
        try:
            return ipaddress.ip_address(address).is_loopback
        except ValueError:
            return False

    def setup(self, username, password):
        with self.lock:
            if self.configured:
                raise ValueError('관리자 계정이 이미 설정되어 있습니다.')
            if not isinstance(username, str) or not 2 <= len(username.strip()) <= 60:
                raise ValueError('관리자 아이디는 2~60자로 입력해 주세요.')
            if not isinstance(password, str) or not 12 <= len(password) <= 256:
                raise ValueError('비밀번호는 12~256자로 설정해 주세요.')
            salt = secrets.token_hex(16)
            config = dict(self.config, username=username.strip(), salt=salt,
                          passwordHash=hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex())
            old = self.config
            self.config = config
            try:
                self.save()
            except OSError:
                self.config = old
                raise

    def login(self, username, password, address):
        with self.lock:
            now = time.time()
            self.failures = {k:v for k,v in self.failures.items() if v[1] > now}
            failed = self.failures.get(address, (0, now + 60))
            if failed[0] >= 5:
                return None, 429
            if not self.configured:
                return None, 409
            if not isinstance(password, str) or len(password) > 256 or not isinstance(username, str):
                return None, 400
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(self.config['salt']), ITERATIONS).hex()
            if not (hmac.compare_digest(digest, self.config['passwordHash']) and hmac.compare_digest(username.encode(), self.config['username'].encode())):
                self.failures[address] = (failed[0]+1, failed[1])
                return None, 401
            self.failures.pop(address, None)
            self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
            if len(self.sessions) >= 128:
                self.sessions.pop(next(iter(self.sessions)))
            token = secrets.token_urlsafe(32)
            session = {'expires': now + SESSION_SECONDS, 'csrf': secrets.token_urlsafe(32)}
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = session
            return (token, session), 200

    def session(self, header):
        try:
            cookie = SimpleCookie(header or '')
            token = cookie['pisignage_session'].value
        except (KeyError, ValueError):
            return None
        with self.lock:
            session = self.sessions.get(hashlib.sha256(token.encode()).hexdigest())
            if not session or session['expires'] <= time.time():
                return None
            return session

    def logout(self, header):
        try:
            token = SimpleCookie(header)['pisignage_session'].value
            with self.lock:
                self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        except (KeyError, ValueError):
            pass

    def cookie(self, token='', logout=False):
        return f'pisignage_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if logout else SESSION_SECONDS}' + ('; Secure' if self.secure_cookie else '')

    def player_token(self, screen):
        value = f"player:{screen['id']}:{screen.get('_playerVersion', 0)}"
        return hmac.new(bytes.fromhex(self.config['secret']), value.encode(), hashlib.sha256).hexdigest()

    def check_player(self, token, screen):
        return bool(token) and hmac.compare_digest(str(token), self.player_token(screen))

    def sign_media(self, screen, item):
        expires = (int(time.time()) // 3600 + 25) * 3600
        message = f"media:{screen['id']}:{screen.get('_playerVersion',0)}:{item['id']}:{expires}"
        sig = hmac.new(bytes.fromhex(self.config['secret']), message.encode(), hashlib.sha256).hexdigest()
        return f"{item['url']}?screen={screen['id']}&expires={expires}&sig={sig}"

    def check_media(self, screen, item, expires, signature):
        try:
            expiry = int(expires)
        except (TypeError, ValueError):
            return False
        if expiry < time.time() or expiry > time.time() + 26 * 3600:
            return False
        message = f"media:{screen['id']}:{screen.get('_playerVersion',0)}:{item['id']}:{expiry}"
        expected = hmac.new(bytes.fromhex(self.config['secret']), message.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(str(signature), expected)


