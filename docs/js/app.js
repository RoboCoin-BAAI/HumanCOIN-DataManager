import {setupLanguage} from './i18n.js';
import {LEVELS, initialLevels, manifest, command, formatBytes, duration} from './data.js';
import {CardPreviews, mediaUrl} from './card-previews.js';
import {DEFAULT_LEVEL} from './config.js';
import {WorkerClient, fetchManifest, createDetailLoader} from './catalog-client.js';
const el=id=>document.getElementById(id);
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const count=value=>value==null?'—':value.toLocaleString('en-US');
const STORAGE='humancoin.selection.v1',SCOPE_STORAGE='humancoin.scope.v1',MODS=['RGB','Depth','Hand Pose','Gaze','Eye Camera','EMG','EEG','Manus','Audio','IMU'];
let catalog,candidate,worker,levels=[],page=1,pageSize=20,lastResult,queryVersion=0,modalVersion=0,lastFocus,selectionPage=1,lastCheck=0,checking=false;
let selected=new Map(),selectionRevision=0;
const loadDetail=createDetailLoader();
const cardPreviews=new CardPreviews();
function toast(message){let box=el('toast');if(!box){box=document.createElement('div');box.id='toast';box.setAttribute('role','status');box.style.cssText='position:fixed;right:24px;bottom:24px;padding:16px;background:#265d55;color:white;z-index:100;border-radius:10px;max-width:80vw';document.body.append(box);}box.textContent=message;box.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>box.hidden=true,6000);}
function filters(){return {query:el('search').value,levels:[...levels],mods:[...document.querySelectorAll('.modfilter:checked')].map(i=>i.value),sceneCategory:el('sceneCategory').value,taskSearch:el('taskSearch').value,scene:el('scene').value,task:el('task').value,resolution:el('resolution').value,sort:el('sort').value,publicOnly:true};}
function chosen(){return [...selected.values()];}
function save(){selectionRevision++;try{localStorage.setItem(STORAGE,JSON.stringify({repos:chosen().map(d=>({id:d.id,level:d.level,revisions:d.revisions})),hub:el('hub').value}));}catch{toast('Browser storage is unavailable or full. Export JSON to save your selection.');}}
function syncSelected(){
 el('navCount').textContent=`(${selected.size})`;el('selectCount').textContent=`${count(selected.size)} dataset${selected.size===1?'':'s'}`;
 el('exportJson').disabled=el('generate').disabled=el('clearSelected').disabled=!selected.size;
 const rows=chosen(),pages=Math.max(1,Math.ceil(rows.length/20));selectionPage=Math.min(selectionPage,pages);
 const offset=(selectionPage-1)*20;el('selectionItems').replaceChildren();
 for(const d of rows.slice(offset,offset+20)){const b=document.createElement('button');b.className='btn small ghost';b.textContent=`${d.id.split('/')[1]} ×`;b.title=`Remove ${d.id}`;b.onclick=()=>{selected.delete(d.id);save();syncSelected();syncChecks();};el('selectionItems').append(b);}
 if(rows.length>20){const label=document.createElement('span');label.textContent=`Selected ${offset+1}–${Math.min(offset+20,rows.length)} of ${count(rows.length)}`;el('selectionItems').append(label);for(const [text,step] of [['Previous selections',-1],['Next selections',1]]){const b=document.createElement('button');b.className='btn small secondary';b.textContent=text;b.disabled=step<0?selectionPage===1:selectionPage===pages;b.onclick=()=>{selectionPage+=step;syncSelected();};el('selectionItems').append(b);}}
}
function syncChecks(){el('datasetList').querySelectorAll('input[data-id]').forEach(i=>i.checked=selected.has(i.dataset.id));}
function pageControls(ready){el('selectPage').hidden=!ready||lastResult.pages<=1;el('prevPage').disabled=!ready||lastResult.page<=1;el('nextPage').disabled=!ready||lastResult.page>=lastResult.pages;el('selectAll').disabled=el('selectPage').disabled=!ready||!lastResult.total;}
function statsLabel(metric){return (metric.missingCount?` · Partial (${metric.knownCount}/${metric.knownCount+metric.missingCount})`:'')+(metric.staleCount?` · ${metric.staleCount} stale`:'')+(metric.derivedCount?` · ${metric.derivedCount} derived`:'');}
function renderMetrics(){const s=catalog.stats;const values=[count(s.datasets),count(s.episodes.sumKnown),duration(s.durationSeconds.sumKnown),count(s.downloads.sumKnown)];document.querySelectorAll('.metricval').forEach((n,i)=>n.textContent=values[i]);const notes=['Published dataset repositories','Across dataset repositories'+statsLabel(s.episodes),'Repository duration; may overlap'+statsLabel(s.durationSeconds),'Hugging Face statistics'+statsLabel(s.downloads)];document.querySelectorAll('.metricsmall').forEach((n,i)=>n.textContent=notes[i]);el('catalogStatus').textContent=`Snapshot ${new Date(catalog.generatedAt).toLocaleString('en-US')} · ${count(s.datasets)} datasets`;}
function populateOptions(id,values,label){const current=el(id).value;el(id).replaceChildren(new Option(label,''));for(const v of values)el(id).add(new Option(id==='resolution'?v.replace('x',' × '):v.replaceAll('_',' '),v));if(current&&!values.includes(current))el(id).add(new Option(current.replaceAll('_',' '),current));el(id).value=current;}
function renderResult(result){
 lastResult=result;page=result.page;
 el('shown').textContent=count(result.total);el('pageStatus').textContent=`Showing ${result.start}–${result.end} of ${count(result.total)}`;el('pageNumber').textContent=`Page ${result.page} of ${result.pages}`;
 el('scopeStatus').textContent='';
 el('datasetList').dataset.levels=result.levels.join(',');
 el('datasetList').dataset.snapshot=result.snapshotId;
 const s=result.stats;el('scopeStats').textContent=`Episodes: ${count(s.episodes.sumKnown)}${statsLabel(s.episodes)} · Duration: ${duration(s.durationSeconds.sumKnown)}${statsLabel(s.durationSeconds)}`;
 const f=filters();el('filterTip').textContent=f.mods.length?`${f.mods.length} modality filters`:'All modalities in selected levels';
 el('empty').classList.toggle('hidden',!!result.total);cardPreviews.clear();el('datasetList').replaceChildren();
 for(const d of result.items){const poster=mediaUrl(d.preview?.poster,'jpg');const article=document.createElement('article');article.className='dataset';article.innerHTML=`<div class="thumb${poster?' has-image':''}" data-action="preview" role="button" tabindex="0" aria-label="Preview ${escapeHtml(d.task||d.id)}">${poster?`<img src="${escapeHtml(poster)}" alt="${escapeHtml(d.task||d.id)} recording preview" loading="lazy" decoding="async">`:''}<div class="visual-title">${escapeHtml(d.level)} · ${d.preview?.clip?'<span class="hover-hint">HOVER TO PLAY</span><span class="touch-hint">TAP TO PREVIEW</span>':'VIDEO PREVIEW'}</div></div><div class="dataset-body"><div class="dataset-title">${escapeHtml(d.task||d.id.split('/')[1].replaceAll('_',' '))} <span class="badge ${escapeHtml(d.level.toLowerCase())}">${escapeHtml(d.level)}</span></div><div class="dataset-id">${escapeHtml(d.id)}</div><div class="desc">${escapeHtml(d.summary||'No task description available.')}</div><div class="tags">${d.mods.map(m=>`<span class="tag">${escapeHtml(m)}</span>`).join('')}${Object.keys(d.revisions).map(h=>`<span class="tag">${h==='huggingface'?'Hugging Face':'ModelScope'}</span>`).join('')}${d.staleMetrics?.length?'<span class="tag">Cached metadata</span>':''}</div><div class="dataset-stats"><span>▤ <b>${count(d.episodes)}</b> episodes</span><span>◷ <b>${duration(d.durationSeconds)}</b></span><span>⇩ <b>${count(d.downloads)}</b> HF</span><span>◈ <b>${formatBytes(d.sizeBytes)}</b></span></div></div><div class="dataset-actions"><label class="cartcheck"><input type="checkbox" data-id="${escapeHtml(d.id)}" ${selected.has(d.id)?'checked':''}> Select Dataset</label><div class="actions-bottom"><button class="btn small secondary" data-action="preview">◉ Preview</button><button class="btn small ghost" data-action="download">↓ Download</button></div></div>`;
  const cover=article.querySelector('.thumb');
  cover.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showPreview(d);}};
  cardPreviews.bind(cover,d);
  article.querySelector('input').onchange=e=>{e.target.checked?selected.set(d.id,d):selected.delete(d.id);save();syncSelected();};article.querySelectorAll('[data-action="preview"]').forEach(b=>b.onclick=()=>showPreview(d));article.querySelector('[data-action="download"]').onclick=()=>downloadBody([d],'Download dataset');el('datasetList').append(article);
 }
 populateOptions('sceneCategory',result.facets.sceneCategories,'All categories');populateOptions('scene',result.facets.scenes,'All areas');populateOptions('task',result.facets.tasks,'All tasks');el('taskHint').textContent=result.facets.taskCount>100?`Showing 100 of ${count(result.facets.taskCount)} tasks. Refine your search.`:'';populateOptions('resolution',result.facets.resolutions,'All resolutions');
 document.querySelectorAll('.modfilter').forEach(i=>i.parentElement.querySelector('.count').textContent=result.facets.modalities[i.value]||0);
 el('loadStatus').textContent=catalog.quality.warningCount?`Catalog includes ${catalog.quality.warningCount} catalog warnings. Missing statistics appear as —.`:'';
 if(catalog.quality.warningCount){const link=document.createElement('a');link.href='data/'+catalog.quality.report.path;link.textContent=' View report';link.target='_blank';link.rel='noopener noreferrer';el('loadStatus').append(link);}
 el('retryScope').hidden=true;pageControls(true);syncSelected();
}
async function render({history=false}={}){
 cardPreviews.stop();const version=++queryVersion;pageControls(false);el('retryScope').hidden=true;el('shown').textContent='—';el('pageStatus').textContent='';el('scopeStats').textContent='';
 if(!catalog||!levels.length){lastResult=null;el('datasetList').replaceChildren();el('shown').textContent='—';el('empty').classList.add('hidden');el('scopeStats').textContent='';el('pageStatus').textContent='';el('pageNumber').textContent='';el('loadStatus').textContent='';el('scopeStatus').textContent=catalog?.stats.datasets===0?'No published datasets are available yet.':'Choose a data level to browse, or select All levels.';if(history)writeUrl();return;}
 el('scopeStatus').textContent=lastResult?`Loading ${levels.join(' + ')}. The list below belongs to the previous completed query.`:`Loading ${levels.join(' + ')}…`;
 try{const result=await worker.request('query',{manifest:catalog,levels,filters:filters(),page,pageSize},(done,total)=>{if(version===queryVersion)el('loadStatus').textContent=`Loading selected indexes: ${done} of ${total} files`;});if(version!==queryVersion)return;renderResult(result);if(history)writeUrl();}
 catch(error){if(version!==queryVersion)return;el('loadStatus').textContent=error.message;el('scopeStatus').textContent='Scope loading failed. Any list below belongs to the previous completed query.';el('retryScope').hidden=false;if(worker?.failed)el('retryScope').onclick=init;}
}
function writeUrl({replace=false}={}){const url=new URL(location.href);const f=filters();for(const k of ['levels','query','sort','sceneCategory','scene','task','resolution','device','mods','public','page','pageSize'])url.searchParams.delete(k);if(levels.length)url.searchParams.set('levels',levels.join(','));for(const key of ['query','sceneCategory','scene','task','resolution'])if(f[key])url.searchParams.set(key,f[key]);if(f.mods.length)url.searchParams.set('mods',f.mods.join(','));if(f.sort!=='featured')url.searchParams.set('sort',f.sort);if(page>1)url.searchParams.set('page',page);if(pageSize!==20)url.searchParams.set('pageSize',pageSize);if(url.href!==location.href)history[replace?'replaceState':'pushState'](null,'',url);}
function readUrl({initial=false}={}){const p=new URL(location.href).searchParams;levels=[...new Set((p.get('levels')||'').split(',').filter(l=>LEVELS.includes(l)))];if(initial){let savedLevels=[];try{savedLevels=JSON.parse(localStorage.getItem(SCOPE_STORAGE));}catch{/* Scope memory is optional. */}levels=initialLevels(catalog,{urlLevels:levels,savedLevels,defaultLevel:DEFAULT_LEVEL});}page=Math.max(1,parseInt(p.get('page'))||1);pageSize=[20,50,100].includes(Number(p.get('pageSize')))?Number(p.get('pageSize')):20;el('pageSize').value=pageSize;for(const id of ['search','sceneCategory','scene','task','resolution']){const value=p.get(id==='search'?'query':id)||'';if(id!=='search'&&value&&!Array.from(el(id).options).some(o=>o.value===value))el(id).add(new Option(value,value));el(id).value=value;}el('sort').value=['featured','newest','largest','popular'].includes(p.get('sort'))?p.get('sort'):'featured';document.querySelectorAll('.modfilter').forEach(i=>i.checked=(p.get('mods')||'').split(',').includes(i.value));syncLevelChecks();}
function rememberScope(){if(!levels.length)return;try{localStorage.setItem(SCOPE_STORAGE,JSON.stringify(levels));}catch{/* Browsing does not require storage. */}}
function syncLevelChecks(){document.querySelectorAll('.levelfilter').forEach(i=>i.checked=levels.includes(i.value));}
function changeScope(next){el('taskSearch').value='';levels=next;rememberScope();page=1;syncLevelChecks();for(const id of ['sceneCategory','scene','task','resolution'])el(id).value='';render({history:true});}
function filterLevel(level){changeScope([level]);jump('explore');}
function jump(id){if(id==='docs')return openDocs();if(id==='about')return openAbout();el(id)?.scrollIntoView({behavior:'smooth',block:'start'});document.querySelectorAll('.navitem').forEach(n=>n.classList.toggle('active',n.dataset.nav===id));el('crumb').textContent={home:'Overview',explore:'Explore Datasets',selection:'My Selection'}[id]||'Overview';}
function closeModal(){modalVersion++;el('modal').classList.remove('show');document.body.style.overflow='';el('modalBody').querySelectorAll('video').forEach(v=>{v.pause();v.removeAttribute('src');v.load();});lastFocus?.focus();}
function openModal(title,body){cardPreviews.stop();modalVersion++;if(!el('modal').classList.contains('show'))lastFocus=document.activeElement;el('modalBody').querySelectorAll('video').forEach(v=>v.pause());el('modalTitle').removeAttribute('data-content-language');el('modalTitle').textContent=title;el('modalBody').innerHTML=body;el('modal').classList.add('show');document.body.style.overflow='hidden';el('modal').querySelector('.close').focus();return modalVersion;}
function hubLinks(d){return Object.entries(d.hubs).map(([key,h])=>`<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener noreferrer">${key==='huggingface'?'Hugging Face':'ModelScope'} ↗</a>`).join(' · ');}
async function showPreview(entry){
 const token=openModal(entry.task||entry.id,'<p class="modaldesc" role="status">Loading dataset details…</p>');el('modalTitle').setAttribute('data-content-language','en');
 let d;try{d=await loadDetail(entry);}catch(error){if(token!==modalVersion)return;openModal('Dataset details',`<p class="notice">${escapeHtml(error.message)}</p><button class="btn secondary" id="retryDetail">Retry</button>`);el('retryDetail').onclick=()=>showPreview(entry);return;}
 if(token!==modalVersion)return;
  openModal(d.task || d.id, `<span class="previewtag">${escapeHtml(d.level)} · ${escapeHtml(d.scene || 'Unknown scene')}</span><p class="modaldesc"><span data-content-language="en">${escapeHtml(d.description)}</span><br>First episode from the dataset. Sensor streams retain their independent sampling rates.</p><div class="viewer-grid"><div>${d.videos.length?'<video id="previewVideo" class="sample-main" controls playsinline preload="metadata"></video><select id="camera" class="filterselect" aria-label="Preview camera"></select><p id="videoStatus" class="sectionhint" role="status">Video loads on demand. If access is restricted or the codec is unsupported, open the dataset on its source platform.</p>':'<p class="notice">No browser video preview is available for this dataset.</p>'}</div><div class="sensorpanel"><div class="sensorline">Sensor metadata <b>${d.streams.length} streams</b></div>${d.streams.map(s=>`<div class="stream"><div>${escapeHtml(s.key)}</div><small>${escapeHtml(s.dtype)} · [${escapeHtml((s.shape||[]).join(' × '))}] · ${s.rate==null?'Unknown sampling rate':escapeHtml(s.rate)+' Hz'}</small></div>`).join('')||'No sensor metadata available.'}</div></div><div class="detailtable">${[['Episodes',count(d.episodes)],['Duration',duration(d.durationSeconds)],['Size (metadata)',formatBytes(d.sizeBytes)],['Main camera resolution',d.resolution?d.resolution.replace('x',' × '):'—'],['License',d.license||'—'],['Updated',d.updated.slice(0,10)||'—']].map(([k,v])=>`<div class="detailcell"><span>${k}</span><b>${escapeHtml(v)}</b></div>`).join('')}</div><div class="downloadbar"><span>${hubLinks(d)}</span><button class="btn primary" id="previewDownload">Get Download Command →</button></div>`);
  el('previewDownload').onclick=()=>downloadBody([entry], 'Download dataset');
  el('modalTitle').setAttribute('data-content-language','en');
  if (d.videos.length) {
    const camera=el('camera'), video=el('previewVideo'),status=el('videoStatus');
    d.videos.forEach((v,i)=>camera.add(new Option(v.key,String(i))));
    camera.onchange=()=>{status.textContent='Video loads on demand. If access is restricted or the codec is unsupported, open the dataset on its source platform.';video.src=d.videos[Number(camera.value)].url;video.load();}; camera.onchange();
    video.onloadeddata=()=>status.textContent='Ready to play.';
    video.onerror=()=>status.textContent='Video failed to load. Check your connection and access permissions, or open the dataset on its source platform.';
  }
}
function accessReminder(){return '<p class="notice">Before downloading, visit the <a href="https://huggingface.co/HumanCOIN" target="_blank" rel="noopener noreferrer">HumanCOIN Hugging Face page ↗</a>, open the datasets you need and request download access where required. For gated datasets, wait for approval and authenticate with the approved account before downloading.</p>';}
function showWelcome(){
 openModal('Welcome to HumanCOIN', `<p class="modaldesc">Please make sure you can access <a href="https://huggingface.co/HumanCOIN" target="_blank" rel="noopener noreferrer">Hugging Face ↗</a>. Full video previews currently load from Hugging Face.</p>${accessReminder()}<div class="downloadbar"><span></span><button class="btn primary" id="dismissWelcome">Continue to portal</button></div>`);
 el('dismissWelcome').onclick=closeModal;
}
function downloadBody(items, title) {
  let cmd, data;
  try { cmd=command(items,el('hub').value); data=manifest(items,el('hub').value,catalog.snapshotId); }
  catch(error) { toast(error.message); return; }
  openModal(title, `${accessReminder()}<p class="modaldesc">${items.length} complete dataset(s) · ${el('hub').value}<br>Commands use the HumanCOIN-LeRobot download tool. JSON saves your selection for import into this portal.</p><div class="flabel">INSTALL (ONCE)</div><pre class="cmd">pip install ${el('hub').value==='modelscope'?'"humancoin-lerobot[modelscope]"':'humancoin-lerobot'}</pre><div class="flabel">DOWNLOAD COMMAND</div><pre class="cmd" id="downloadCode">${escapeHtml(cmd)}</pre><div class="downloadbar"><span class="sectionhint">Download to ./data/HumanCOIN/ with the selected revision for each repository.</span><button class="btn primary" id="copyCommand">⧉ Copy Command</button></div><details><summary>Selection JSON</summary><pre class="cmd">${escapeHtml(JSON.stringify(data,null,2))}</pre></details><p class="notice">Restricted repositories require platform access and authentication. Commit revisions pin content; main/master are mutable branches. Sizes come from metadata; HF downloads are platform statistics.</p>`);
  el('copyCommand').onclick=()=>copyText(cmd);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text);toast('Copied to clipboard.'); }
  catch { const t=document.createElement('textarea');t.value=text;el('modalBody').append(t);t.select();let ok=false;try{ok=document.execCommand('copy');}catch{/* Manual selection remains available when clipboard access is denied. */}finally{t.remove();}toast(ok?'Copied to clipboard.':'Copy failed. Please select and copy the command manually.'); }
}
function doExport() {
  try {
    const data=manifest(chosen(),el('hub').value,catalog.snapshotId);
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='selection.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error) { toast(error.message); }
}
function openDocs() {
  openModal('HumanCOIN · Quick Start', `<p class="modaldesc">Filter datasets, choose a source, select complete repositories and generate download commands. Your selection is saved in this browser and can be imported or exported as JSON.</p><div class="flabel">INSTALL FROM PYPI</div><pre class="cmd">pip install humancoin-lerobot\n# ModelScope support\npip install "humancoin-lerobot[modelscope]"</pre><p class="modaldesc">The download tool supports --hub, --datasets, --revision, --target-dir, --max-workers and --dry-run. Add --dry-run to check destination paths. Use Python 3.10–3.13. Authenticate with HF_TOKEN for Hugging Face, or MODELSCOPE_TOKEN / MS_TOKEN for ModelScope.</p><p><a href="https://github.com/RoboCoin-BAAI/HumanCOIN-LeRobot" target="_blank" rel="noopener noreferrer">HumanCOIN-LeRobot documentation ↗</a></p><div class="notice">Unavailable statistics appear as —. Repositories with the same ID on both platforms share one catalog entry. Download commands are available only for platforms that host the selected repositories.</div>`);
}
function openAbout() {
  openModal('About HumanCOIN', `<p class="modaldesc">HumanCOIN is an egocentric multimodal dataset for embodied manipulation. It connects visible actions with the operator’s state through multi-view vision, gaze, surface EMG, EEG and glove kinematics under a unified spatiotemporal reference, supporting research into attention, execution and cognition.</p><p class="modaldesc">Three acquisition tiers share a task ontology. L1, visual intention, emphasizes everyday scene coverage. L2, motor intention, adds EMG and wrist views. L3, cognitive intention, adds EEG, measured gaze and detailed kinematic measurements. Deeper tiers focus on more controlled tasks with richer signal measurements.</p><p><a href="https://koorye.github.io/HumanCOIN-dev/" target="_blank" rel="noopener noreferrer">HumanCOIN project · Concept and acquisition architecture ↗</a></p><p class="modaldesc">This portal provides discovery, previews, filters and downloads for published datasets. Available modalities follow each repository’s metadata. Planned project scale is distinct from the published catalog statistics shown here.</p><p><a href="https://huggingface.co/HumanCOIN" target="_blank" rel="noopener noreferrer">Hugging Face ↗</a> · <a href="https://www.modelscope.cn/organization/HumanCOIN" target="_blank" rel="noopener noreferrer">ModelScope ↗</a></p>`);
}
Object.assign(window,{jump,filterLevel,closeModal,openDocs,openAbout});
document.addEventListener('keydown',event=>{
 if(!el('modal').classList.contains('show'))return;if(event.key==='Escape')closeModal();
 if(event.key==='Tab'){const nodes=[...el('modal').querySelectorAll('button,a,input,select,textarea,video,summary,[tabindex="0"]')].filter(x=>!x.disabled);const first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
});
let searchTimer;
for(const id of ['sceneCategory','scene','task','resolution','sort'])el(id).onchange=()=>{page=1;render({history:true});};
el('search').oninput=()=>{clearTimeout(searchTimer);queryVersion++;pageControls(false);searchTimer=setTimeout(()=>{page=1;render({history:true});},200);};
document.querySelectorAll('.levelfilter').forEach(x=>x.onchange=()=>changeScope([...document.querySelectorAll('.levelfilter:checked')].map(i=>i.value)));
el('browseAll').onclick=()=>changeScope([...LEVELS]);
el('reset').onclick=()=>{el('taskSearch').value='';document.querySelectorAll('.modfilter').forEach(i=>i.checked=false);for(const id of ['search','sceneCategory','scene','task','resolution'])el(id).value='';el('sort').value='featured';page=1;render({history:true});};
el('pageSize').onchange=()=>{pageSize=Number(el('pageSize').value);page=1;render({history:true});};
el('prevPage').onclick=()=>{page--;render({history:true});};el('nextPage').onclick=()=>{page++;render({history:true});};
el('retryScope').onclick=()=>render({history:true});
el('clearSelected').onclick=()=>{selected.clear();save();syncSelected();syncChecks();};
el('selectPage').onclick=()=>{for(const d of lastResult?.items||[])selected.set(d.id,d);save();syncSelected();syncChecks();};
el('selectAll').onclick=async()=>{
 if(!lastResult)return;const version=queryVersion,revision=selectionRevision;el('selectAll').disabled=true;
 try{const result=await worker.request('query',{manifest:catalog,levels,filters:filters(),page,pageSize,selectAll:true});if(version!==queryVersion||revision!==selectionRevision)return;for(const d of result.selected)selected.set(d.id,d);save();syncSelected();syncChecks();toast(`Selected ${count(result.total)} matching datasets across all pages.`);}catch(error){toast(error.message);}finally{if(version===queryVersion)pageControls(!!lastResult);}
};
el('hub').onchange=save;el('exportJson').onclick=doExport;el('generate').onclick=()=>downloadBody(chosen(),'Batch download');
el('importJson').onclick=()=>el('importFile').click();
el('importFile').onchange=async event=>{
 try{const revision=selectionRevision;const file=event.target.files[0];if(!file)return;if(file.size>32*1024*1024)throw Error('JSON files must be no larger than 32 MiB.');const value=JSON.parse(await file.text());
  if(value?.schema_version!=='1.0'||!Array.isArray(value.datasets)||value.datasets.some(d=>typeof d?.repo_id!=='string')||(value.hub&&!['huggingface','modelscope'].includes(value.hub)))throw Error('Invalid selection.json.');
  if(value.datasets.some(d=>!LEVELS.includes(d.level)))toast('This older file has no tier hints. Checking all levels to preserve cross-tier selections.');
  const snapshot=catalog.snapshotId;const rows=await worker.request('resolve',{manifest:catalog,selection:value,strict:true});if(snapshot!==catalog.snapshotId)throw Error('Catalog changed during import. Please retry.');if(revision!==selectionRevision)throw Error('Selection changed during import. Please import again.');
  const byId=new Map(rows.map(d=>[d.id,d]));
  const changed=value.datasets.filter(d=>d.revision&&byId.get(d.repo_id)?.revisions[value.hub||el('hub').value]!==d.revision).length;
  const apply=()=>{selected=new Map(rows.map(d=>[d.id,d]));if(value.hub)el('hub').value=value.hub;selectionPage=1;save();syncSelected();syncChecks();toast(`Imported ${count(rows.length)} dataset(s) using this catalog snapshot.`);};
  if(changed){openModal('Review selection versions',`<p class="modaldesc">${count(changed)} selected repository versions differ from the current catalog. The file itself will remain unchanged.</p><button class="btn primary" id="acceptImport">Import using current versions</button>`);el('acceptImport').onclick=()=>{if(snapshot!==catalog.snapshotId||revision!==selectionRevision){toast('Catalog or selection changed. Please import again.');return;}apply();closeModal();};}else apply();
 }catch(error){toast(error.message);}finally{event.target.value='';}
};
document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>jump(b.dataset.nav));
window.addEventListener('popstate',()=>{readUrl();rememberScope();render();});
async function checkUpdates(manual=false){
 if(checking||!catalog||document.hidden||(!manual&&Date.now()-lastCheck<300000))return;
 checking=true;lastCheck=Date.now();el('checkUpdates').disabled=true;
 try{const next=await fetchManifest();if(next.snapshotId!==catalog.snapshotId){candidate=next;el('applyUpdate').hidden=false;el('updateStatus').textContent='A new snapshot is ready.';}else{candidate=null;el('applyUpdate').hidden=true;el('updateStatus').textContent=`Checked ${new Date(next.checkedAt).toLocaleString('en-US')} · Catalog is current.`;}}
 catch(error){el('updateStatus').textContent=`Update check failed. Current snapshot retained. ${error.message}`;}
 finally{checking=false;el('checkUpdates').disabled=false;}
}
async function applyUpdate(){
 if(!candidate)return;const next=candidate,version=++queryVersion,selectionKeys=JSON.stringify([...selected.keys()]);const oldSelected=chosen();pageControls(false);el('applyUpdate').disabled=true;
 el('updateStatus').textContent='Preparing the new snapshot…';
 try{
  const result=levels.length?await worker.request('query',{manifest:next,levels,filters:filters(),page,pageSize}):null;
  // Without trustworthy tier hints from an old snapshot, resolve across all tiers: a repository may have changed tiers.
  const selection={schema_version:'1.0',datasets:oldSelected.map(d=>({repo_id:d.id}))};
  const rows=oldSelected.length?await worker.request('resolve',{manifest:next,selection,strict:false}):[];
  if(version!==queryVersion||selectionKeys!==JSON.stringify([...selected.keys()])){el('updateStatus').textContent='Browsing changed while preparing the update. Click Refresh to retry.';await render();return;}
  const removed=oldSelected.length-rows.length,changed=rows.filter(d=>JSON.stringify(d.revisions)!==JSON.stringify(selected.get(d.id)?.revisions)).length,unavailable=rows.filter(d=>!d.revisions[el('hub').value]||d.sourceStatus?.[el('hub').value]==='removal_candidate').length;
  closeModal();catalog=next;candidate=null;selected=new Map(rows.map(d=>[d.id,d]));save();renderMetrics();
  if(result)renderResult(result);else await render();syncSelected();writeUrl();el('applyUpdate').hidden=true;el('updateStatus').textContent='Catalog refreshed.';
  toast(`Snapshot updated. Selection: ${removed} removed, ${changed} version changes, ${unavailable} unavailable on the selected source.`);
 }catch(error){el('updateStatus').textContent=`Refresh failed. Previous snapshot retained. ${error.message}`;if(version===queryVersion)await render();}
 finally{el('applyUpdate').disabled=false;}
}
el('checkUpdates').onclick=()=>checkUpdates(true);el('applyUpdate').onclick=applyUpdate;
setInterval(()=>checkUpdates(),300000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkUpdates();});
async function restoreSelection(){
 try{const snapshot=catalog.snapshotId,revision=selectionRevision;const value=JSON.parse(localStorage.getItem(STORAGE));if(['huggingface','modelscope'].includes(value?.hub))el('hub').value=value.hub;if(!value?.repos?.length)return;
  const selection={schema_version:'1.0',datasets:value.repos.map(d=>typeof d==='string'?{repo_id:d}:{repo_id:d.id,level:d.level})};
  const rows=await worker.request('resolve',{manifest:catalog,selection,strict:false});if(snapshot!==catalog.snapshotId||revision!==selectionRevision)return;selected=new Map(rows.map(d=>[d.id,d]));
  const savedById=new Map(value.repos.filter(d=>typeof d==='object').map(d=>[d.id,d]));
  const changed=rows.filter(d=>{const old=savedById.get(d.id);return old?.revisions&&JSON.stringify(old.revisions)!==JSON.stringify(d.revisions);}).length;
  const removed=value.repos.length-rows.length;if(removed||changed)toast(`Saved selection revalidated: ${removed} removed, ${changed} version changes.`);save();syncSelected();syncChecks();
 }catch(error){toast(`Saved selection could not be checked. Stored selection retained. ${error.message}`);}
}
async function init(){
 el('loadStatus').textContent='Loading catalog summary…';
 try{
  catalog=await fetchManifest();worker=worker&&!worker.failed?worker:new WorkerClient();el('importJson').disabled=false;el('retryScope').onclick=()=>render({history:true});renderMetrics();
  if(catalog.tiers.Unknown.count&&!document.querySelector('.levelfilter[value="Unknown"]')){const label=document.createElement('label');label.className='check';label.innerHTML='<input class="levelfilter" type="checkbox" value="Unknown"> Unknown';label.querySelector('input').onchange=()=>changeScope([...document.querySelectorAll('.levelfilter:checked')].map(i=>i.value));document.querySelector('.levelfilter').parentElement.parentElement.append(label);}
  el('modalityChecks').innerHTML=MODS.map(m=>`<label class="check"><input class="modfilter" type="checkbox" value="${m}"> ${m} <span class="count">—</span></label>`).join('');document.querySelectorAll('.modfilter').forEach(i=>i.onchange=()=>{page=1;render({history:true});});
  readUrl({initial:true});rememberScope();writeUrl({replace:true});await render();writeUrl({replace:true});await restoreSelection();
 }catch(error){el('catalogStatus').textContent='Catalog loading failed';el('loadStatus').textContent=error.message;el('retryScope').hidden=false;el('retryScope').onclick=init;}
}
el('importJson').disabled=true;syncSelected();pageControls(false);showWelcome();init();

let taskSearchTimer;el('taskSearch').oninput=()=>{clearTimeout(taskSearchTimer);taskSearchTimer=setTimeout(()=>render(),200);};
el('sceneCategory').onchange=()=>{el('scene').value='';el('task').value='';el('taskSearch').value='';page=1;render({history:true});};

el('scene').onchange=()=>{el('task').value='';el('taskSearch').value='';page=1;render({history:true});};

setupLanguage();
