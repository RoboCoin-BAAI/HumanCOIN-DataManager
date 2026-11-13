"""Button audit in an isolated Firefox profile and temporary site. Requires geckodriver on :4444."""
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Thread
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from browser_smoke import Browser
from scripts.catalog_store import publish,read_records


def wait_file(path):
    for _ in range(150):
        if path.exists() and path.stat().st_size and not path.with_suffix(path.suffix+'.part').exists():
            try:return json.loads(path.read_text())
            except (ValueError,OSError):pass
        time.sleep(.05)
    raise AssertionError('JSON export was not downloaded: '+str(path))


def main():
    checks=[]
    with tempfile.TemporaryDirectory(prefix='humancoin-buttons-',dir=ROOT) as tmp:
        tmp=Path(tmp);site=tmp/'docs';shutil.copytree(ROOT/'docs',site);data=site/'data';shutil.rmtree(data);data.mkdir()
        download=tmp/'downloads';download.mkdir()
        actual=read_records(ROOT/'docs/data');preview=next(d['preview'] for d in actual if d.get('preview'))
        for asset in preview.values():
            target=data/asset['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'docs/data'/asset['path'],target)
        (site/'test-media').mkdir()
        shutil.copy2(ROOT/'docs/data'/preview['clip']['path'],site/'test-media/preview.mp4')
        flags={'root':True,'index':False};requests=[]
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path=='/data/catalog.json' and flags['root'] or '/indexes/' in self.path and flags['index']:
                    self.send_error(503);return
                super().do_GET()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=site));Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}/'
        rows=[]
        for i in range(45):
            level=['L1','L2','L3'][i%3];repo=f'HumanCOIN/{level.lower()}_item_{i:03d}'
            hubs={'huggingface':{'repo':repo,'revision':'a'*40,'url':'https://huggingface.co/datasets/'+repo}}
            if i%2==0:hubs['modelscope']={'repo':repo,'revision':'master','url':'https://www.modelscope.cn/datasets/'+repo}
            rows.append({'id':repo,'repo':repo,'level':level,'scene':'office' if i%2==0 else 'kitchen',
                         'task':'assemble' if i%4<2 else 'clean','description':f'Manipulation example {i}',
                         'resolution':'1280x720' if i%5==0 else '1920x1184','mods':['RGB']+(['EMG'] if i%2 else [])+(['EEG'] if i%5==0 else []),
                         'episodes':i+1,'durationSeconds':i+10,'downloads':1000-i,'sizeBytes':1000+i,'updated':f'2026-11-{i%10+1:02d}',
                         'public':True,'hubs':hubs,'streams':[{'key':'observation.eeg','dtype':'float32','shape':[32],'rate':250}],
                         'videos':[{'key':'bad_camera','url':base+'missing.mp4'},{'key':'good_camera','url':base+'test-media/preview.mp4'}],
                         'sourceStatus':{hub:'ok' for hub in hubs}})
        publish(data/'catalog.json',rows,generated_at=datetime.now(timezone.utc).isoformat(),sources={},warnings=[])
        browser=None
        try:
            browser=Browser('http://127.0.0.1:4444',desktop_pointer=False,download_dir=download);b=browser
            b.call('/session/'+b.session+'/url',{'url':base})
            b.wait("return document.getElementById('catalogStatus').textContent==='Catalog loading failed'")
            assert b.js("return document.getElementById('importJson').disabled")
            flags['root']=False;b.click('#retryScope')
            b.wait("return document.getElementById('datasetList').dataset.levels==='L1'&&document.getElementById('shown').textContent==='15'")
            assert not b.js("return document.getElementById('importJson').disabled")
            assert b.js("return document.getElementById('selectPage').hidden")
            assert b.js("return document.getElementById('clearSelected').disabled&&document.getElementById('exportJson').disabled&&document.getElementById('generate').disabled")
            checks.append('initial failure/retry and loading/empty-selection controls')
            flags['index']=True;b.click('.levelfilter[value="L2"]')
            b.wait("return !document.getElementById('retryScope').hidden&&document.getElementById('loadStatus').textContent.includes('503')")
            roots=requests.count('/data/catalog.json');flags['index']=False;b.click('#retryScope')
            b.wait("return document.getElementById('shown').textContent==='30'&&document.getElementById('scopeStatus').textContent===''")
            assert requests.count('/data/catalog.json')==roots
            checks.append('scope retry after initial retry without unintended root reload')
            b.js("window.__errors=[];window.addEventListener('error',e=>__errors.push(e.message));window.addEventListener('unhandledrejection',e=>__errors.push(String(e.reason)))")
            for nav,title in [('home','Overview'),('explore','Explore Datasets'),('selection','My Selection')]:
                b.click(f'[data-nav="{nav}"]');assert b.js("return document.getElementById('crumb').textContent")==title
            b.click('button[onclick^="jump"]');assert b.js("return document.getElementById('crumb').textContent")=='Explore Datasets'
            b.click('[data-nav="docs"]');b.wait("return document.getElementById('modalTitle').textContent==='HumanCOIN · Quick Start'");b.click('#modal .close')
            b.click('[data-nav="about"]');b.wait("return document.getElementById('modalTitle').textContent==='About HumanCOIN'")
            b.call('/session/'+b.session+'/actions',{'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue00c'},{'type':'keyUp','value':'\ue00c'}]}]})
            assert not b.js("return document.getElementById('modal').classList.contains('show')")
            b.click('button[onclick="openDocs()"]');b.call('/session/'+b.session+'/actions',{'actions':[{'type':'pointer','id':'mouse','parameters':{'pointerType':'mouse'},'actions':[{'type':'pointerMove','duration':0,'x':10,'y':100},{'type':'pointerDown','button':0},{'type':'pointerUp','button':0}]}]})
            assert not b.js("return document.getElementById('modal').classList.contains('show')")
            checks.append('navigation, documentation, About, close button, Escape and overlay close')
            b.click('#browseAll');b.wait("return document.getElementById('shown').textContent==='45'")
            def select(control,value):b.js(f"document.getElementById({json.dumps(control)}).value={json.dumps(value)};document.getElementById({json.dumps(control)}).dispatchEvent(new Event('change'))")
            def shown(n):b.wait(f"return document.getElementById('shown').textContent==='{n}'&&document.getElementById('scopeStatus').textContent===''")
            select('scene','office');shown(sum(d['scene']=='office' for d in rows))
            select('task','clean');shown(sum(d['scene']=='office' and d['task']=='clean' for d in rows))
            select('resolution','1920x1184');shown(sum(d['scene']=='office' and d['task']=='clean' and d['resolution']=='1920x1184' for d in rows))
            assert b.js("return new URL(location.href).searchParams.get('resolution')")=='1920x1184'
            assert b.js("return document.querySelector('#resolution option:checked').textContent")=='1920 × 1184'
            b.click('#reset');shown(45);assert b.js("return document.querySelectorAll('.levelfilter:checked').length")==3
            b.click('.modfilter[value="EMG"]');shown(sum('EMG' in d['mods'] for d in rows))
            b.click('.modfilter[value="EEG"]');shown(sum('EMG' in d['mods'] and 'EEG' in d['mods'] for d in rows))
            b.click('#reset');shown(45)
            b.js("document.getElementById('search').value='item_007';document.getElementById('search').dispatchEvent(new Event('input'))");shown(1)
            assert b.js("return document.querySelector('.dataset-id').textContent")==rows[7]['id']
            b.click('#reset');shown(45)
            for order,key in [('largest','episodes'),('popular','downloads'),('newest','updated')]:
                select('sort',order);shown(45)
                maximum=max(d[key] for d in rows);first=b.js("return document.querySelector('.dataset-id').textContent")
                assert next(d for d in rows if d['id']==first)[key]==maximum
            select('sort','featured');shown(45)
            assert b.js("return document.querySelector('#sort option[value=featured]').textContent")=='Default order'
            select('pageSize','50');shown(45);assert b.js("return document.querySelectorAll('.dataset').length")==45
            assert b.js("return document.getElementById('nextPage').disabled&&document.getElementById('selectPage').hidden")
            select('pageSize','100');shown(45);assert b.js("return document.querySelectorAll('.dataset').length")==45
            select('pageSize','20');shown(45);b.click('#nextPage');b.wait("return document.getElementById('pageNumber').textContent==='Page 2 of 3'")
            b.click('#prevPage');b.wait("return document.getElementById('pageNumber').textContent==='Page 1 of 3'")
            checks.append('combined filters, reset, search, all sort modes, page size and previous/next')
            b.click('#selectPage');b.wait("return document.getElementById('selectCount').textContent==='20 datasets'")
            b.click('#selectAll');b.wait("return document.getElementById('selectCount').textContent==='45 datasets'")
            b.click('#selectionItems button:last-child');assert '21–40' in b.js("return document.getElementById('selectionItems').textContent")
            b.click('#selectionItems button:nth-last-child(2)');assert '1–20' in b.js("return document.getElementById('selectionItems').textContent")
            b.click('#exportJson');exported=wait_file(download/'selection.json');assert len(exported['datasets'])==45;assert exported['hub']=='huggingface'
            b.click('#clearSelected');assert b.js("return document.getElementById('selectCount').textContent")=='0 datasets'
            b.js("window.__pick=0;document.getElementById('importFile').click=()=>window.__pick++")
            b.click('#importJson');assert b.js('return window.__pick')==1,b.js("return {count:window.__pick,disabled:document.getElementById('importJson').disabled,click:document.getElementById('importFile').click.toString()}");b.js("delete document.getElementById('importFile').click")
            b.upload('#importFile',download/'selection.json');b.wait("return document.getElementById('selectCount').textContent==='45 datasets'")
            bad=tmp/'invalid.json';bad.write_text('{bad json');b.upload('#importFile',bad);b.wait("return document.getElementById('toast').textContent.includes('JSON')")
            assert b.js("return document.getElementById('selectCount').textContent")=='45 datasets'
            unknown=tmp/'unknown.json';unknown.write_text(json.dumps({'schema_version':'1.0','datasets':[{'repo_id':'HumanCOIN/missing','level':'L3'}]}));b.upload('#importFile',unknown)
            b.wait("return document.getElementById('toast').textContent.includes('missing from this snapshot')");assert b.js("return document.getElementById('selectCount').textContent")=='45 datasets'
            changed=tmp/'changed.json';changed.write_text(json.dumps({'schema_version':'1.0','hub':'huggingface','datasets':[{'repo_id':d['id'],'level':d['level'],'revision':'old-version'} for d in rows[:2]]}))
            b.upload('#importFile',changed);b.wait("return !!document.getElementById('acceptImport')");b.click('#acceptImport')
            assert b.js("return document.getElementById('selectCount').textContent")=='2 datasets'
            b.click('#selectionItems button:first-child');assert b.js("return document.getElementById('selectCount').textContent")=='1 dataset'
            checks.append('page/all selection, selection paging/removal, actual JSON download, import picker/round trip, invalid/missing imports and revision review')
            b.upload('#importFile',changed);b.wait("return !!document.getElementById('acceptImport')&&document.getElementById('modal').classList.contains('show')");b.click('#acceptImport')
            select('hub','modelscope');b.click('#generate');b.wait("return document.getElementById('toast').textContent.includes('unavailable on this platform')")
            assert not b.js("return document.getElementById('modal').classList.contains('show')")
            select('hub','huggingface');b.click('#generate');b.wait("return !!document.getElementById('downloadCode')")
            code=b.js("return document.getElementById('downloadCode').textContent");assert code.count('humancoin-download')==2;assert 'old-version' not in code
            b.js("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__copied=text}}})")
            b.click('#copyCommand');b.wait("return typeof window.__copied==='string'");assert b.js('return __copied')==code
            b.js("navigator.clipboard.writeText=async()=>{throw new Error('denied')};window.__oldExec=document.execCommand;document.execCommand=()=>{throw new Error('denied')}")
            b.click('#copyCommand');b.wait("return document.getElementById('toast').textContent.startsWith('Copy failed')");b.js('document.execCommand=__oldExec');b.click('#modal .close')
            select('hub','modelscope');b.click('[data-action="download"]');b.wait("return !!document.getElementById('downloadCode')&&document.getElementById('modal').classList.contains('show')")
            assert '--hub modelscope' in b.js("return document.getElementById('downloadCode').textContent");b.click('#modal .close')
            checks.append('single/batch commands, platform availability, source switching, copy payload and denied-clipboard fallback')
            b.js("document.querySelector('.thumb').focus()")
            b.call('/session/'+b.session+'/actions',{'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue007'},{'type':'keyUp','value':'\ue007'}]}]})
            b.wait("return document.getElementById('modal').classList.contains('show')&&!!document.getElementById('camera')");b.click('#modal .close')
            b.click('.thumb[data-action="preview"]');b.wait("return !!document.getElementById('camera')")
            b.wait("return document.getElementById('videoStatus').textContent.includes('failed')")
            select('camera','1');b.wait("return document.getElementById('videoStatus').textContent==='Ready to play.'")
            assert b.js("return document.getElementById('previewVideo').src").endswith('test-media/preview.mp4')
            b.click('#previewDownload');b.wait("return document.getElementById('modalTitle').textContent==='Download dataset'");b.click('#modal .close')
            checks.append('clickable cover, camera switching/error recovery and preview-to-download action')
            b.click('#checkUpdates');b.wait("return document.getElementById('updateStatus').textContent.includes('Catalog is current')");assert b.js("return document.getElementById('applyUpdate').hidden")
            flags['root']=True;b.click('#checkUpdates');b.wait("return document.getElementById('updateStatus').textContent.startsWith('Update check failed')")
            assert b.js("return document.getElementById('selectCount').textContent")=='2 datasets';flags['root']=False
            b.click('#checkUpdates');b.wait("return document.getElementById('updateStatus').textContent.includes('Catalog is current')")
            checks.append('manual update/no-update/failure recovery without selection loss')
            # An in-flight bulk-select must not undo a newer Clear action.
            b.click('#clearSelected');b.js("window.__nativePost=Worker.prototype.postMessage;Worker.prototype.postMessage=function(message){if(message.payload?.selectAll){window.__delayed={worker:this,message};return;}return __nativePost.call(this,message)}")
            b.click('#selectAll');b.wait('return !!window.__delayed');b.click('[data-id]');b.click('#clearSelected')
            b.js("Worker.prototype.postMessage=__nativePost;__nativePost.call(__delayed.worker,__delayed.message)")
            b.wait("return !document.getElementById('selectAll').disabled")
            assert b.js("return document.getElementById('selectCount').textContent")=='0 datasets'
            checks.append('late Select all cannot overwrite a newer Clear action')
            assert b.js('return __errors')==[],b.js('return __errors')
            assert not b.js("return !!document.getElementById('publishedOnly')||document.querySelectorAll('.progress').length>0")
            assert b.js("return document.querySelectorAll('.dataset button[data-action=preview]').length")==20
            print('BUTTON AUDIT PASSED:')
            for check in checks:print('- '+check)
        finally:
            if browser:browser.close()
            server.shutdown();server.server_close()

if __name__=='__main__':main()
