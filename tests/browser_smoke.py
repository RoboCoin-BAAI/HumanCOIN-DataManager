"""Optional real Firefox regression: start geckodriver, then run python tests/browser_smoke.py.
Uses an isolated temporary copy and synthetic metadata. Does not edit the real catalog or access hubs.
"""
import argparse
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.catalog_store import publish

class Browser:
    def __init__(self,url,desktop_pointer=True,download_dir=None):
        self.opener=build_opener(ProxyHandler({}));self.url=url.rstrip('/')
        prefs={'ui.primaryPointerCapabilities':6,'ui.allPointerCapabilities':6} if desktop_pointer else {}
        if download_dir:prefs.update({'browser.download.folderList':2,'browser.download.dir':str(download_dir),'browser.download.useDownloadDir':True,'browser.helperApps.neverAsk.saveToDisk':'application/json'})
        self.session=self.call('/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless'],'prefs':prefs}}}})['sessionId']
    def call(self,path,payload=None,method=None):
        req=Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'},method=method or ('POST' if payload is not None else 'GET'))
        try:
            with self.opener.open(req,timeout=45) as response:return json.load(response)['value']
        except HTTPError as exc:raise AssertionError(exc.read().decode()) from exc
    def js(self,code):return self.call('/session/'+self.session+'/execute/sync',{'script':code,'args':[]})
    def wait(self,code,timeout=15):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if value:=self.js(code):return value
            time.sleep(.05)
        raise AssertionError('Browser wait timed out: '+code+'\n'+str(self.js("return {load:document.getElementById('loadStatus').textContent,update:document.getElementById('updateStatus').textContent,scope:document.getElementById('scopeStatus').textContent,modalVideo:{status:document.getElementById('videoStatus')?.textContent,src:document.getElementById('previewVideo')?.getAttribute('src'),ready:document.getElementById('previewVideo')?.readyState,error:document.getElementById('previewVideo')?.error?.code},hover:matchMedia('(hover: hover) and (pointer: fine)').matches,reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,video:[...document.querySelectorAll('.thumb video')].slice(0,2).map(v=>({src:v.getAttribute('src'),paused:v.paused,time:v.currentTime,error:v.error?.code,ready:v.readyState}))}")))
    def element(self,selector):
        return self.call('/session/'+self.session+'/element',{'using':'css selector','value':selector})['element-6066-11e4-a52e-4f735466cecf']
    def click(self,selector):
        self.call('/session/'+self.session+'/element/'+self.element(selector)+'/click',{})
    def upload(self,selector,path):
        self.call('/session/'+self.session+'/element/'+self.element(selector)+'/value',{'text':str(path)})
    def move(self,x,y):
        self.call('/session/'+self.session+'/actions',{'actions':[{'type':'pointer','id':'mouse','parameters':{'pointerType':'mouse'},'actions':[{'type':'pointerMove','duration':80,'x':x,'y':y}]}]})
    def close(self):self.call('/session/'+self.session,method='DELETE')

def rows():
    return [{'id':f'HumanCOIN/{"l3" if i<85 else "l1"}_demo_{i:04d}','repo':f'HumanCOIN/demo_{i:04d}',
             'level':'L3' if i<85 else 'L1','scene':'kitchen','task':'assemble','description':'Test manipulation',
             'mods':['RGB','EMG'],'resolution':'1920x1184','episodes':1,'durationSeconds':30,'sizeBytes':1000,'downloads':i,
             'updated':'2026-11-13','public':True,'hubs':{'huggingface':{'revision':'a'*40,'repo':f'HumanCOIN/demo_{i:04d}','url':'https://huggingface.co/HumanCOIN'}},
             'sourceStatus':{'huggingface':'ok'},'streams':[],'videos':[]} for i in range(125)]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--webdriver-url',default='http://127.0.0.1:4444');args=parser.parse_args()
    now=datetime(2026,11,13,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix='humancoin-browser-') as tmp:
        site=Path(tmp)/'docs';shutil.copytree(ROOT/'docs',site);data=site/'data';shutil.rmtree(data)
        current=rows()
        actual=json.loads((ROOT/'docs/data/catalog.json').read_text())
        source_rows=[d for tier in actual['tiers'].values() for ref in tier['files'] for d in json.loads((ROOT/'docs/data'/ref['path']).read_text())['datasets']]
        preview=next((d['preview'] for d in source_rows if d.get('preview')),None)
        if preview:
            (data/'media').mkdir(parents=True)
            for ref in preview.values():shutil.copy2(ROOT/'docs/data'/ref['path'],data/ref['path'])
            for d in current:d['preview']=preview
        publish(data/'catalog.json',current,generated_at=now.isoformat(),sources={},warnings=[],shard_limit=18000)
        requests=[];failure={'index':False}
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if failure['index'] and '/indexes/' in self.path:self.send_error(503);return
                super().do_GET()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=site));Thread(target=server.serve_forever,daemon=True).start()
        browser=None
        try:
            browser=Browser(args.webdriver_url,desktop_pointer=False);b=browser
            b.call('/session/'+b.session+'/url',{'url':f'http://127.0.0.1:{server.server_port}/'})
            b.wait("return document.getElementById('datasetList').dataset.levels==='L1'&&document.getElementById('scopeStatus').textContent===''")
            assert b.js("return document.querySelectorAll('.dataset').length")==20
            assert b.js("return document.getElementById('shown').textContent")=='40'
            assert '/data/catalog.json' in requests
            assert not any('/indexes/l3/' in path or '/details/' in path for path in requests)
            assert b.js("return new URL(location.href).searchParams.get('levels')")=='L1'
            assert b.js("return getComputedStyle(document.querySelector('.dataset')).backdropFilter")=='none'
            assert b.js("return getComputedStyle(document.querySelector('.sidebar')).backdropFilter")=='none'
            if preview:
                assert not any(path.endswith('.mp4') for path in requests)
                b.js("document.querySelector('.thumb').scrollIntoView({behavior:'instant',block:'center'})")
                b.wait("return document.querySelector('.thumb img').complete&&document.querySelector('.thumb img').naturalWidth>0")
                # A real mouse over card text must play the thumbnail, even when CSS reports hover:none.
                b.js("window.__hoverEvents=[];document.querySelector('.dataset').addEventListener('pointerenter',e=>__hoverEvents.push({type:e.pointerType,trusted:e.isTrusted}))")
                rect=b.js("const r=document.querySelector('.dataset-body').getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}")
                b.move(rect['x'],rect['y'])
                assert b.js("return document.querySelector('.thumb video').getAttribute('src')")==None
                b.wait("return document.querySelector('.thumb').classList.contains('is-playing')&&document.querySelector('.thumb video').currentTime>0")
                assert b.js("return __hoverEvents.some(e=>e.type==='mouse'&&e.trusted)")
                b.move(3,3)
                # Playback rejection must be visible instead of silently restoring the idle hint.
                b.js("window.__nativePlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){return Promise.reject(new DOMException('Blocked for test','NotAllowedError'))};document.querySelector('.dataset').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))")
                b.wait("return document.querySelector('.thumb').dataset.previewState==='error'")
                assert b.js("return document.querySelector('.thumb .hover-hint').textContent")=='CLICK PREVIEW'
                assert 'blocked' in b.js("return document.querySelector('.thumb').dataset.previewError")
                b.js("HTMLMediaElement.prototype.play=__nativePlay;document.querySelector('.dataset').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))")
                b.wait("return document.querySelector('.thumb').classList.contains('is-playing')")
                b.js("document.querySelectorAll('.thumb')[1].scrollIntoView({behavior:'instant',block:'center'});document.querySelectorAll('.dataset')[1].dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))")
                b.wait("return document.querySelectorAll('.thumb')[1].classList.contains('is-playing')")
                assert b.js("return [...document.querySelectorAll('.thumb video')].filter(v=>!v.paused).length")==1
                assert b.js("return document.querySelector('.thumb video').getAttribute('src')")==None
                b.js("document.querySelectorAll('.dataset')[1].dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'}))")
                assert b.js("return [...document.querySelectorAll('.thumb video')].every(v=>v.paused&&!v.getAttribute('src'))")
                b.js("document.querySelector('.thumb').scrollIntoView({behavior:'instant',block:'center'});document.querySelector('.dataset').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))")
                b.wait("return document.querySelector('.thumb').classList.contains('is-playing')")
                # Scrolling must stop decoding immediately and suppress playback until idle.
                b.js("window.dispatchEvent(new Event('scroll'))")
                assert b.js("return [...document.querySelectorAll('.thumb video')].every(v=>v.paused&&!v.getAttribute('src'))")
                blocked=b.call('/session/'+b.session+'/execute/async',{'script':"const done=arguments[arguments.length-1];let ticks=0;function tick(){window.dispatchEvent(new Event('scroll'));if(++ticks<4)setTimeout(tick,80);else done([...document.querySelectorAll('.thumb video')].every(v=>v.paused&&!v.getAttribute('src')))}tick()",'args':[]})
                assert blocked
                b.wait("return document.querySelector('.thumb').classList.contains('is-playing')")
                b.js("window.scrollTo({top:0,behavior:'instant'})")
                b.wait("return [...document.querySelectorAll('.thumb video')].every(v=>v.paused&&!v.getAttribute('src'))")
            assert b.js("return getComputedStyle(document.getElementById('applyUpdate')).display")== 'none'
            assert b.js("return getComputedStyle(document.getElementById('retryScope')).display")== 'none'
            b.js("document.querySelectorAll('.level-card')[2].click()")
            b.wait("return document.getElementById('datasetList').dataset.levels==='L3'&&document.getElementById('scopeStatus').textContent===''")
            # Plain visits restore the last scope; an explicit shared empty tier takes priority.
            b.call('/session/'+b.session+'/url',{'url':f'http://127.0.0.1:{server.server_port}/'})
            b.wait("return document.getElementById('datasetList').dataset.levels==='L3'&&document.getElementById('scopeStatus').textContent===''")
            b.call('/session/'+b.session+'/url',{'url':f'http://127.0.0.1:{server.server_port}/?levels=L2'})
            b.wait("return document.getElementById('datasetList').dataset.levels==='L2'&&document.getElementById('scopeStatus').textContent===''")
            assert b.js("return document.getElementById('shown').textContent")=='0'
            # Remembered empty tiers fall back to a populated preferred tier.
            b.call('/session/'+b.session+'/url',{'url':f'http://127.0.0.1:{server.server_port}/'})
            b.wait("return document.getElementById('datasetList').dataset.levels==='L1'&&document.getElementById('scopeStatus').textContent===''")
            requests.clear()
            b.call('/session/'+b.session+'/url',{'url':f'http://127.0.0.1:{server.server_port}/?levels=L3'})
            b.wait("return document.getElementById('datasetList').dataset.levels==='L3'&&document.getElementById('scopeStatus').textContent===''")
            assert b.js("return document.querySelectorAll('.dataset').length")==20
            assert b.js("return document.getElementById('shown').textContent")=='85'
            assert all('/indexes/l1/' not in p for p in requests)
            assert not any('/details/' in p for p in requests)
            b.js("document.getElementById('nextPage').click()")
            b.wait("return document.getElementById('pageNumber').textContent==='Page 2 of 5'")
            first=b.js("return document.querySelector('.dataset-id').textContent")
            b.js("document.getElementById('selectAll').click()")
            b.wait("return document.getElementById('selectCount').textContent==='85 datasets'")
            assert b.js("return document.querySelectorAll('#selectionItems button').length")<=22
            assert not any('/details/' in p for p in requests)
            b.js("document.querySelector('[data-action=download]').click()")
            b.wait("return document.getElementById('downloadCode')")
            assert 'humancoin-download' in b.js("return document.getElementById('downloadCode').textContent")
            assert not any('/details/' in p for p in requests)
            b.js("closeModal();document.querySelector('[data-action=preview]').click()")
            b.wait("return document.querySelector('#modalBody .sensorpanel')")
            assert len([p for p in requests if '/details/' in p])==1
            b.js("closeModal();document.querySelector('[data-action=preview]').click()")
            b.wait("return document.querySelector('#modalBody .sensorpanel')")
            assert len([p for p in requests if '/details/' in p])==1
            b.js("closeModal();document.querySelectorAll('.level-card')[0].click()")
            b.wait("return document.getElementById('datasetList').dataset.levels==='L1'&&document.getElementById('scopeStatus').textContent===''")
            assert b.js("return document.getElementById('selectCount').textContent")=='85 datasets'
            b.js("history.back()")
            b.wait("return document.getElementById('pageNumber').textContent==='Page 2 of 5'&&document.getElementById('datasetList').dataset.levels==='L3'&&document.getElementById('scopeStatus').textContent===''")
            assert b.js("return document.querySelector('.dataset-id').textContent")==first
            # A new snapshot changes metadata, removes a selection and changes versions.
            current=current[1:]
            for d in current:d['hubs']['huggingface']['revision']='b'*40;d['downloads']+=1
            publish(data/'catalog.json',current,generated_at=(now+timedelta(hours=1)).isoformat(),sources={},warnings=[],shard_limit=18000)
            b.js("document.getElementById('checkUpdates').click()")
            b.wait("return !document.getElementById('applyUpdate').hidden")
            old_status=b.js("return document.getElementById('datasetList').dataset.snapshot")
            failure['index']=True;b.js("document.getElementById('applyUpdate').click()")
            b.wait("return document.getElementById('updateStatus').textContent.startsWith('Refresh failed')&&!document.getElementById('applyUpdate').disabled")
            assert b.js("return document.getElementById('shown').textContent")=='85'
            assert b.js("return document.getElementById('datasetList').dataset.snapshot")==old_status
            failure['index']=False;b.js("document.getElementById('applyUpdate').click()")
            b.wait("return document.getElementById('updateStatus').textContent==='Catalog refreshed.'")
            assert b.js("return document.getElementById('shown').textContent")=='84'
            assert b.js("return document.getElementById('selectCount').textContent")=='84 datasets'
            assert b.js("return document.querySelectorAll('.dataset').length")==20
            b.js("document.getElementById('generate').click()")
            assert "'"+'b'*40+"'" in b.js("return document.getElementById('downloadCode').textContent")
            b.js("closeModal();document.getElementById('search').value='missing-task';document.getElementById('search').dispatchEvent(new Event('input'))")
            b.wait("return document.getElementById('shown').textContent==='0'")
            assert b.js("return document.getElementById('nextPage').disabled")
            print('Firefox passed: trusted mouse hover over card body with native pointer capabilities, lightweight scroll surfaces, scroll-time playback suppression and idle resume, static posters, delayed hover, one active clip, leave/scroll cleanup, initial default, saved scope, shared link priority, empty-tier fallback, lazy scope, 20-row pages, cross-page selection, lazy details/cache, URL history, failed refresh rollback, atomic successful refresh, removed/versioned selections, empty search.')
        finally:
            if browser:browser.close()
            server.shutdown();server.server_close()

if __name__=='__main__':main()
