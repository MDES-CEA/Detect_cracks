"""Real mouse/keyboard regression tests on a copied annotation database."""
import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from validate_analysis_ui import MOSAIC, ROOT, OUT, DevTools, wait_for


def request(path, body=None, method=None):
    req=Request('http://127.0.0.1:8018'+path, data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json'},method=method)
    with urlopen(req,timeout=90) as response:return json.load(response)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    snapshot=OUT/'editing-annotations.sqlite3'
    source=sqlite3.connect(f'file:{ROOT / "annotation_app/data/annotations.sqlite3"}?mode=ro',uri=True)
    target=sqlite3.connect(snapshot);source.backup(target);target.close();source.close()
    flags=subprocess.CREATE_NO_WINDOW
    log=(OUT/'editing-server.log').open('w')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','annotation_app.main:app','--host','127.0.0.1','--port','8018'],cwd=ROOT,
        env={**os.environ,'CRACK_DATABASE_PATH':str(snapshot),'CRACK_CACHE_DIR':str(OUT/'cache'),'CRACK_IMAGE_PATH':str(MOSAIC)},stdout=log,stderr=log,creationflags=flags)
    browser=None
    try:
        wait_for('http://127.0.0.1:8018/api/health')
        browser=subprocess.Popen([r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new','--disable-gpu','--no-first-run',
          '--remote-debugging-port=9238',f'--user-data-dir={OUT / "chrome-editing"}','--window-size=1500,1000','about:blank'],
          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
        pages=wait_for('http://127.0.0.1:9238/json');page=next(p for p in pages if p['type']=='page')
        dev=DevTools(page['webSocketDebuggerUrl']);dev.call('Runtime.enable');dev.call('Page.enable')
        dev.call('Page.navigate',{'url':'http://127.0.0.1:8018?zone=6'})
        def until(expression,timeout=60):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                result=dev.evaluate(expression)
                if result:return result
                time.sleep(.2)
            raise AssertionError((expression,dev.errors,dev.evaluate('document.body.innerText')))
        until("document.querySelector('.work-zone.selected') && !document.getElementById('viewer-message').offsetHeight")
        until("document.getElementById('action-status').textContent.includes('L01')")
        zone=next(z for z in request('/api/zones') if z['id']==6)
        def click(x,y):
            rect=dev.evaluate("(()=>{const r=document.querySelector('.work-zone.selected').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()")
            sx=rect['x']+(x-zone['x'])/zone['width']*rect['width'];sy=rect['y']+(y-zone['y'])/zone['height']*rect['height']
            dev.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':sx,'y':sy,'button':'left','clickCount':1})
            dev.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':sx,'y':sy,'button':'left','clickCount':1})
        def key(value,code,keycode):
            dev.call('Input.dispatchKeyEvent',{'type':'keyDown','key':value,'code':code,'windowsVirtualKeyCode':keycode})
            dev.call('Input.dispatchKeyEvent',{'type':'keyUp','key':value,'code':code,'windowsVirtualKeyCode':keycode})
        def settled():
            until("document.getElementById('busy-indicator').classList.contains('hidden')")
        dev.evaluate("document.getElementById('mode-draw').click()")
        x,y=zone['x'],zone['y']
        click(x+300,y+1400);click(x+650,y+1500);settled()
        created=until("Number(document.getElementById('selection-summary').textContent.match(/Fissure (\\d+)/)?.[1])")
        def crack():return next(c for c in request('/api/zones/6/cracks') if c['id']==created)
        click(x+1050,y+1200);settled();assert len(crack()['anchors'])==3, (crack(),dev.evaluate("document.getElementById('action-status').textContent"))
        before=dev.evaluate("document.querySelector('.work-zone.selected').getBoundingClientRect().y")
        key('z','KeyW',90);settled();assert len(crack()['anchors'])==2
        after=dev.evaluate("document.querySelector('.work-zone.selected').getBoundingClientRect().y")
        assert abs(before-after)<.01,('Z moved viewport',before,after)
        key('Escape','Escape',27)
        assert dev.evaluate("document.getElementById('mode-select').classList.contains('active')")
        assert crack()['category']=='unclassified'
        before_count=len(request('/api/zones/6/cracks'))
        click(x+1400,y+1700)
        assert len(request('/api/zones/6/cracks'))==before_count
        assert 'premier point' not in dev.evaluate("document.getElementById('selection-summary').textContent").lower()
        geometry=crack()['geometry'];point=geometry[len(geometry)//2]
        click(*point)
        assert not dev.evaluate("document.getElementById('insert-node').disabled")
        dev.evaluate("document.getElementById('insert-node').click()")
        click(*point);settled();assert len(crack()['anchors'])==3
        assert crack()['category']=='unclassified'
        key('Escape','Escape',27)
        dev.evaluate("document.querySelector('.categories button[data-category=filled]').click()")
        until("document.getElementById('selection-summary').textContent.includes('Colmatée')")
        dev.evaluate("document.getElementById('insert-node').click()")
        click(x+1100,y+1750);settled()
        assert len(crack()['anchors'])==3, 'A click away from the selected line must not extend it'
        geometry=crack()['geometry'];point=geometry[(3*len(geometry))//4]
        click(*point);settled()
        assert len(crack()['anchors'])==4
        assert crack()['category']=='filled'
        key('Escape','Escape',27)
        dev.evaluate("document.getElementById('open-analysis').click();document.querySelector('[data-tab=lengths]').click()")
        until("document.getElementById('science-results').textContent.includes('tracés enregistrés')")
        assert not dev.evaluate("!!document.getElementById('length-menu') || !!document.getElementById('analysis-view')")
        dev.evaluate("document.getElementById('science-scope').value='zone';document.getElementById('science-scope').dispatchEvent(new Event('change'))")
        until("document.getElementById('science-results').textContent.includes('1 tuile(s)')")
        a=request('/api/statistics/lengths?zone_id=6')['zone'];b=request('/api/analysis/lengths?zone_id=6')
        assert abs(a['total_px']-b['total_px'])<1e-6
        assert a['trace_count']==b['trace_count']
        # Same path, second annotation: neither length nor corrected count grows.
        before=request('/api/analysis/lengths?zone_id=6')
        request('/api/zones/6/cracks',{'anchors':crack()['anchors'],'annotator':'UI regression'},'POST')
        after=request('/api/analysis/lengths?zone_id=6')
        assert after['raw_trace_count']==before['raw_trace_count']+1
        assert after['trace_count']==before['trace_count']
        assert abs(after['total_px']-before['total_px'])<1e-5
        dev.evaluate("document.getElementById('science-refresh').click();document.getElementById('toggle-zones').click()")
        until("document.getElementById('science-results').textContent.includes('tracés enregistrés')")
        screenshot=dev.call('Page.captureScreenshot',{'format':'png'})
        (OUT/'editing-unified.png').write_bytes(base64.b64decode(screenshot['data']))
        assert not dev.errors,dev.errors
        print('PASS: create, Z without pan, Escape finish, no new draft, insert nodes anywhere on the selected line without endpoint extension, unified controls, shared totals, overlap length/count.')
    finally:
        if browser is not None:browser.terminate();browser.wait(timeout=15)
        server.terminate();server.wait(timeout=15);log.close()
