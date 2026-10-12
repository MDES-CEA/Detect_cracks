"""Compare browser raster and SVG coordinates to the native TIFF across zooms."""
import base64
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import numpy as np
from PIL import Image
from validate_analysis_ui import MOSAIC, ROOT, OUT, DevTools, wait_for
from annotation_app.tile_service import PyramidTileService

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    drawer=sys.argv[1] if len(sys.argv)>1 else 'canvas'
    tiles=PyramidTileService(MOSAIC)
    snapshot=OUT/'zoom-annotations.sqlite3'
    source=sqlite3.connect(f'file:{ROOT / "annotation_app/data/annotations.sqlite3"}?mode=ro',uri=True)
    target=sqlite3.connect(snapshot);source.backup(target);target.close();source.close()
    log=(OUT/'zoom-server.log').open('w')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','annotation_app.main:app','--host','127.0.0.1','--port','8019'],cwd=ROOT,
        env={**os.environ,'CRACK_DATABASE_PATH':str(snapshot),'CRACK_CACHE_DIR':str(OUT/'cache'),'CRACK_IMAGE_PATH':str(MOSAIC)},stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    browser=None
    try:
        wait_for('http://127.0.0.1:8019/api/health')
        browser=subprocess.Popen([r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new','--no-first-run',
          '--remote-debugging-port=9239','--use-angle=swiftshader','--enable-unsafe-swiftshader',
          f'--user-data-dir={OUT / ("chrome-zoom-"+drawer)}','--window-size=1600,1000','about:blank'],
          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        pages=wait_for('http://127.0.0.1:9239/json');page=next(p for p in pages if p['type']=='page')
        dev=DevTools(page['webSocketDebuggerUrl']);dev.call('Runtime.enable');dev.call('Page.enable')
        # Test-only constructor capture. No debug hooks in production code.
        dev.call('Page.addScriptToEvaluateOnNewDocument',{'source':f"""
          document.addEventListener('load',event=>{{
            if(event.target.tagName!=='SCRIPT'||!event.target.src.includes('openseadragon'))return;
            const value=window.OpenSeadragon;
            value.Viewer=new Proxy(value.Viewer,{{construct(target,args){{
              if(args[0].id==='viewer') args[0].drawer='{drawer}';
              const viewer=Reflect.construct(target,args);
              if(args[0].id==='viewer') window.zoomTestViewer=viewer;
              return viewer;
            }}}});
          }},true);
        """})
        dev.call('Page.navigate',{'url':'http://127.0.0.1:8019?zone=185'})
        end=time.monotonic()+45
        while time.monotonic()<end:
            if dev.evaluate("window.zoomTestViewer?.world.getItemCount()>0 && !!document.querySelector('.crack-overlay svg')"):break
            time.sleep(.2)
        else:raise AssertionError(dev.errors)
        dev.evaluate("document.getElementById('toggle-all-cracks').click()")
        time.sleep(2)
        print('Renderer:',dev.evaluate('zoomTestViewer.drawer.getType()'),flush=True)
        records=[]
        for index,zoom in enumerate([.25,.45,.9,1.8,.3,.6,.45]):
            dev.evaluate(f"""(()=>{{const v=zoomTestViewer,i=v.world.getItemAt(0);
              v.viewport.zoomTo(i.imageToViewportZoom({zoom}),null,true);
              v.viewport.panTo(i.imageToViewportCoordinates(1100,{46800+(index%2)*300}),true);
              v.viewport.applyConstraints(true);v.forceRedraw();}})()""")
            time.sleep(2)
            alignment=dev.evaluate("""(()=>{const v=zoomTestViewer,i=v.world.getItemAt(0),r=v.element.getBoundingClientRect();let errors=[];
              for(const wrapper of document.querySelectorAll('.crack-overlay,.all-cracks-overlay')) {
                const local=wrapper.classList.contains('crack-overlay');const svg=wrapper.querySelector('svg');
                for(const line of [...svg.querySelectorAll('polyline')].slice(0,25)) {
                  const p=line.points[0];if(!p)continue;
                  const actual=new DOMPoint(p.x,p.y).matrixTransform(svg.getScreenCTM());
                  const expected=v.viewport.pixelFromPoint(i.imageToViewportCoordinates(p.x,p.y+(local?46000:0)),true);
                  errors.push(Math.hypot(actual.x-r.x-expected.x,actual.y-r.y-expected.y));
                }
              }return Math.max(...errors);})()""")
            dev.evaluate("document.querySelectorAll('.crack-overlay,.all-cracks-overlay,.work-zone').forEach(e=>e.style.visibility='hidden')")
            samples=dev.evaluate("""(()=>{const v=zoomTestViewer,i=v.world.getItemAt(0),r=v.element.getBoundingClientRect(),points=[];
              for(let y=60;y<r.height-190;y+=13)for(let x=60;x<r.width-210;x+=13){
                const p=i.viewportToImageCoordinates(v.viewport.pointFromPixel(new OpenSeadragon.Point(x+.5,y+.5),true));
                if(p.x>=5&&p.x<14000&&p.y>=5&&p.y<51690)points.push([Math.round(r.x+x),Math.round(r.y+y),p.x,p.y]);
              }return points;})()""")
            screenshot=dev.call('Page.captureScreenshot',{'format':'png'})
            data=base64.b64decode(screenshot['data'])
            (OUT/f'zoom-{drawer}-{index}.png').write_bytes(data)
            rendered=np.asarray(Image.open(io.BytesIO(data)).convert('L'))
            pts=np.asarray(samples)
            actual=rendered[pts[:,1].astype(int),pts[:,0].astype(int)].astype(float)
            expected=tiles.source._memmap[np.floor(pts[:,3]).astype(int),np.floor(pts[:,2]).astype(int)]
            if tiles.source._lut is not None:expected=tiles.source._lut[expected]
            error=np.abs(actual-expected.astype(float))
            record={'zoom':zoom,'svg_error_px':alignment,'mean_pixel_error':float(error.mean()),
                    'correlation':float(np.corrcoef(actual,expected)[0,1])}
            records.append(record);print(record,flush=True)
            dev.evaluate("document.querySelectorAll('.crack-overlay,.all-cracks-overlay,.work-zone').forEach(e=>e.style.visibility='visible')")
        (OUT/f'zoom-{drawer}.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        assert not dev.errors,dev.errors
    finally:
        if browser is not None:browser.terminate();browser.wait(timeout=15)
        server.terminate();server.wait(timeout=15);log.close()
