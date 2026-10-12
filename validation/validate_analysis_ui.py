"""Local browser smoke test against a SQLite snapshot, using Chrome DevTools."""
import base64
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import sys
import time
from urllib.request import urlopen, Request
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding='utf-8')

ROOT=Path(__file__).resolve().parent.parent
OUT=Path(__file__).resolve().parent/'sorties'
sys.path.insert(0,str(ROOT))
OUT.mkdir(exist_ok=True)
from annotation_app.paths import reference_image
# Les scenarios visent des tuiles et des coordonnees de la mosaique de
# reference : on l'impose, plutot que la derniere image ouverte.
MOSAIC=reference_image()
if MOSAIC is None:
    sys.exit('Aucune mosaique de reference : ecrire son chemin dans '
             'annotation_app/data/image_reference.txt')


class DevTools:
    def __init__(self,url):
        parsed=urlparse(url)
        self.socket=socket.create_connection((parsed.hostname,parsed.port),timeout=30)
        key=base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f'GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        data=b''
        while b'\r\n\r\n' not in data:
            data+=self.socket.recv(1)
        if b'101' not in data:
            raise RuntimeError(data)
        self.counter=0
        self.errors=[]

    def read(self,n):
        data=b''
        while len(data)<n:
            chunk=self.socket.recv(n-len(data))
            if not chunk:
                raise RuntimeError('Browser socket closed')
            data+=chunk
        return data

    def call(self,method,params=None):
        self.counter+=1
        payload=json.dumps({'id':self.counter,'method':method,'params':params or {}}).encode()
        mask=os.urandom(4)
        header=bytes([0x81,0x80|len(payload)]) if len(payload)<126 else bytes([0x81,0x80|126])+struct.pack('!H',len(payload))
        self.socket.sendall(header+mask+bytes(value^mask[i%4] for i,value in enumerate(payload)))
        fragments=b''
        while True:
            first,second=self.read(2)
            size=second&127
            if size==126: size=struct.unpack('!H',self.read(2))[0]
            elif size==127: size=struct.unpack('!Q',self.read(8))[0]
            content=self.read(size)
            fragments+=content
            if not first&128:
                continue
            message=json.loads(fragments); fragments=b''
            if message.get('method')=='Runtime.exceptionThrown':
                self.errors.append(message)
            if message.get('id')==self.counter:
                if 'error' in message: raise RuntimeError(message)
                return message.get('result',{})

    def evaluate(self,expression):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result: raise RuntimeError(result)
        return result.get('result',{}).get('value')


def wait_for(url,seconds=40):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            with urlopen(url,timeout=2) as response: return json.load(response)
        except Exception: time.sleep(.3)
    raise RuntimeError(f'Timeout: {url}')


if __name__=='__main__':
    snapshot=OUT/'ui-annotations.sqlite3'
    source=sqlite3.connect(f'file:{ROOT / "annotation_app/data/annotations.sqlite3"}?mode=ro',uri=True)
    target=sqlite3.connect(snapshot); source.backup(target); target.close(); source.close()
    env={**os.environ,'CRACK_DATABASE_PATH':str(snapshot),'CRACK_CACHE_DIR':str(OUT/'cache'),'CRACK_IMAGE_PATH':str(MOSAIC)}
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    log=(OUT/'server.log').open('w')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','annotation_app.main:app','--host','127.0.0.1','--port','8017'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=flags)
    browser=None
    try:
        wait_for('http://127.0.0.1:8017/api/health')
        browser=subprocess.Popen([r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9237',f'--user-data-dir={OUT / "chrome-analysis"}','--window-size=1500,1000','http://127.0.0.1:8017'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
        pages=wait_for('http://127.0.0.1:9237/json')
        page=next(p for p in pages if p['type']=='page')
        dev=DevTools(page['webSocketDebuggerUrl']); dev.call('Runtime.enable'); dev.call('Page.enable')
        dev.call('Page.navigate',{'url':'http://127.0.0.1:8017?zone=6'})
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if dev.evaluate("!!document.querySelector('.science-panel')"): break
            time.sleep(.5)
        else:
            raise RuntimeError({'url':dev.evaluate('location.href'),'body':dev.evaluate('document.body.innerText'),'errors':dev.errors})
        dev.evaluate("document.querySelector('.science-panel').open=true")
        dev.evaluate("document.querySelector('[data-tab=lengths]').click()")
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if dev.evaluate("document.getElementById('science-results')?.textContent.includes('Longueur cumulée')"): break
            time.sleep(.5)
        else: raise RuntimeError('Length panel failed to load')
        dev.evaluate("document.getElementById('science-axes').click();document.getElementById('science-preview').click()")
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if dev.evaluate("document.getElementById('science-preview-image').naturalWidth>0"): break
            time.sleep(.5)
        else: raise RuntimeError('Figure preview failed')
        screenshot=dev.call('Page.captureScreenshot',{'format':'png'})
        (OUT/'interface-analysis.png').write_bytes(base64.b64decode(screenshot['data']))
        text=dev.evaluate("document.getElementById('science-results').textContent")
        print(text[:1800])
        # Prepare a single diagnostic tile, then verify global and local layers.
        request=Request('http://127.0.0.1:8017/api/analysis/layers/prepare?zone_id=6',method='POST')
        urlopen(request,timeout=30).close()
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            status=wait_for('http://127.0.0.1:8017/api/analysis/layers/status')
            if not status['running']: break
            time.sleep(.5)
        assert 6 in status['cached_zone_ids'],status
        dev.evaluate("document.getElementById('science-layer').value='centerline';document.getElementById('science-layer').dispatchEvent(new Event('change'))")
        time.sleep(3)
        error=dev.evaluate("document.getElementById('science-error').textContent")
        assert not error,error
        assert not dev.errors,dev.errors
        for kind in ['lengths','orientation','map','spatial']:
            with urlopen(f'http://127.0.0.1:8017/api/analysis/figure.png?kind={kind}',timeout=60) as response:
                (OUT/f'{kind}.png').write_bytes(response.read())
        with urlopen('http://127.0.0.1:8017/api/analysis/masks.zip?zone_id=6',timeout=30) as response:
            (OUT/'zone-6-masks.zip').write_bytes(response.read())
        print('Browser, four figures, background mask preparation and ZIP export: OK')
    finally:
        if browser is not None:
            browser.terminate()
            browser.wait(timeout=15)
        server.terminate(); server.wait(timeout=15); log.close()

