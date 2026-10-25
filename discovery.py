"""mDNS locates candidates; HTTPS trust and the persisted server UUID authenticate them."""
import socket
import threading
import time
SERVICE='_nuvistage._tcp.local.'


def dependency():
    try:
        from zeroconf import Zeroconf,ServiceInfo,ServiceBrowser,IPVersion
        return Zeroconf,ServiceInfo,ServiceBrowser,IPVersion
    except ImportError:raise ValueError('자동 검색에는 zeroconf가 필요합니다. requirements-device.txt를 설치하거나 서버 주소를 직접 입력해 주세요.')

class Advertisement:
    def __init__(self,zc,info):self.zc=zc;self.info=info
    def close(self):
        self.zc.unregister_service(self.info);self.zc.close()


def advertise(server,hostname=None,addresses=None,interfaces=None):
    Zeroconf,ServiceInfo,_,IPVersion=dependency()
    hostname=hostname or socket.gethostname().split('.')[0]+'.local'
    if not hostname.endswith('.local') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.' for c in hostname):raise ValueError('자동 검색 호스트 이름은 인증서에 포함된 .local 이름을 사용해 주세요.')
    if addresses is None:
        import ifaddr
        addresses=list({ip.ip for adapter in ifaddr.get_adapters() for ip in adapter.ips if isinstance(ip.ip,str) and not ip.ip.startswith('127.')})
        if not addresses or all(ip.startswith('127.') for ip in addresses):raise ValueError('LAN IPv4 주소를 찾을 수 없습니다. 네트워크 연결을 확인해 주세요.')
    kwargs=dict(ip_version=IPVersion.V4Only)
    if interfaces:kwargs['interfaces']=interfaces
    zc=Zeroconf(**kwargs)
    info=ServiceInfo(SERVICE,'Nuvistage-'+server.devices.server_id[:8]+'.'+SERVICE,addresses=[socket.inet_aton(ip) for ip in addresses],port=server.server_port,properties={'server_id':server.devices.server_id,'scheme':'https','api':'1','tls_host':hostname},server=hostname+'.')
    try:zc.register_service(info)
    except Exception:zc.close();raise
    return Advertisement(zc,info)


def discover(timeout=3,interfaces=None):
    Zeroconf,_,ServiceBrowser,IPVersion=dependency();found={};lock=threading.Lock()
    class Listener:
        def add_service(self,zc,type_,name):self.update_service(zc,type_,name)
        def update_service(self,zc,type_,name):
            info=zc.get_service_info(type_,name,timeout=1200)
            if not info:return
            props={k.decode('utf-8','replace'):v.decode('utf-8','replace') for k,v in info.properties.items() if v is not None}
            host=props.get('tls_host',info.server.rstrip('.'))
            if props.get('scheme')!='https' or not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.' for c in host):return
            from devices import valid_id
            if not valid_id(props.get('server_id')):return
            with lock:found[name]=dict(name=name.split('._nuvistage')[0],server_id=props['server_id'],url=f'https://{host}:{info.port}',addresses=info.parsed_addresses())
        def remove_service(self,zc,type_,name):
            with lock:found.pop(name,None)
    kwargs=dict(ip_version=IPVersion.V4Only)
    if interfaces:kwargs['interfaces']=interfaces
    zc=Zeroconf(**kwargs);browser=ServiceBrowser(zc,SERVICE,Listener())
    try:time.sleep(max(.1,min(timeout,15)))
    finally:browser.cancel();zc.close()
    with lock:return sorted(found.values(),key=lambda item:(item['name'],item['server_id']))
