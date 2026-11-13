import {sceneCategory} from './scenes.js';
import {LEVELS, matches, paginate, aggregate, parseSelection} from './data.js';
export function validateManifest(value) {
  if (value?.schemaVersion !== 3 || !/^[a-f0-9]{64}$/.test(value.snapshotId || '') || !value.stats || !value.tiers || !value.sources) throw Error('Unsupported catalog. Refresh the page to update the application.');
  for (const level of LEVELS) {
    const tier=value.tiers[level];
    if (!tier || !Array.isArray(tier.files) || tier.files.reduce((s,f)=>s+f.count,0)!==tier.count) throw Error('Invalid tier manifest.');
    for (const f of tier.files) if (!new RegExp(`^indexes/${level.toLowerCase()}/[a-f0-9]{64}\\.json$`).test(f.path)) throw Error('Invalid index path.');
  }
  if (LEVELS.reduce((s,l)=>s+value.tiers[l].count,0)!==value.stats.datasets) throw Error('Invalid catalog counts.');
  return value;
}
export async function fetchManifest(fetcher=fetch) {
  const response=await fetcher(new URL('../data/catalog.json',import.meta.url).href,{cache:'no-cache',signal:AbortSignal.timeout(20000)});
  if(!response.ok)throw Error(`Catalog request failed (HTTP ${response.status}).`);
  return validateManifest(await response.json());
}
export async function readVerified(path,hash,fetcher=fetch) {
  if (!/^(indexes\/(l1|l2|l3|unknown)|details)\/[a-f0-9]{64}\.json$/.test(path)) throw Error('Invalid catalog reference.');
  const response=await fetcher(new URL(`../data/${path}`,import.meta.url).href,{signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw Error(`Catalog file unavailable (HTTP ${response.status}). Check for a new catalog or retry.`);
  const data=await response.arrayBuffer();
  const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(v=>v.toString(16).padStart(2,'0')).join('');
  if(actual!==hash)throw Error('Catalog integrity check failed. Retry or check for updates.');
  return {value:JSON.parse(new TextDecoder().decode(data)),bytes:data.byteLength};
}
export function createDetailLoader(fetcher=fetch,limit=100) {
  const cached=new Map(),pending=new Map();
  return function load(entry) {
    const path=entry.detailPath;
    if(cached.has(path)){const d=cached.get(path);cached.delete(path);cached.set(path,d);return Promise.resolve({...d,...entry});}
    if(pending.has(path))return pending.get(path).then(d=>({...d,...entry}));
    const promise=(async()=>{
      const {value}=await readVerified(path,entry.detailHash,fetcher);
      if(value.schemaVersion!==3||value.dataset?.id!==entry.id||!Array.isArray(value.dataset.streams)||!Array.isArray(value.dataset.videos))throw Error('Invalid dataset details.');
      cached.set(path,value.dataset);if(cached.size>limit)cached.delete(cached.keys().next().value);
      return value.dataset;
    })();
    pending.set(path,promise);promise.finally(()=>pending.delete(path)).catch(()=>{});
    return promise.then(d=>({...d,...entry}));
  };
}
export class CatalogEngine {
  constructor(fetcher=fetch){this.fetcher=fetcher;this.files=new Map();this.bytes=0;this.pending=new Map();}
  async file(ref) {
    if(this.files.has(ref.path)){const v=this.files.get(ref.path);this.files.delete(ref.path);this.files.set(ref.path,v);return v.rows;}
    if(this.pending.has(ref.path))return this.pending.get(ref.path);
    const promise=(async()=>{
      const {value,bytes}=await readVerified(ref.path,ref.sha256,this.fetcher);
      if(value.schemaVersion!==3||!Array.isArray(value.datasets)||value.datasets.length!==ref.count||bytes!==ref.bytes)throw Error('Invalid index shard.');
      const rows=value.datasets.map(d=>({...d,searchText:[d.id,d.task,d.scene,d.summary,...d.mods].join(' ').toLowerCase()}));
      this.files.set(ref.path,{rows,bytes});this.bytes+=bytes;
      // Bound reusable cached indexes. A running query holds only its own scope separately.
      while(this.bytes>80*1024*1024&&this.files.size>1){const key=this.files.keys().next().value;this.bytes-=this.files.get(key).bytes;this.files.delete(key);}
      return rows;
    })();
    this.pending.set(ref.path,promise);promise.finally(()=>this.pending.delete(ref.path)).catch(()=>{});
    return promise;
  }
  async scope(manifest,levels,onProgress=()=>{}) {
    validateManifest(manifest);
    if(levels.some(l=>!LEVELS.includes(l)))throw Error('Invalid browsing scope.');
    const files=[...new Set(levels)].flatMap(l=>manifest.tiers[l].files.map(ref=>({level:l,ref})));
    let next=0,completed=0;const pieces=new Array(files.length);
    const worker=async()=>{while(next<files.length){const index=next++,{level,ref}=files[index];const rows=await this.file(ref);if(rows.some(d=>d.level!==level))throw Error('Index tier mismatch.');pieces[index]=rows;onProgress(++completed,files.length);}};
    await Promise.all(Array.from({length:Math.min(4,files.length)},worker));
    const rows=pieces.flat();
    if(new Set(rows.map(d=>d.id)).size!==rows.length)throw Error('Duplicate dataset IDs in scope.');
    return rows;
  }
  async query({manifest,levels,filters,page,pageSize,selectAll=false},progress) {
    const rows=await this.scope(manifest,levels,progress),found=matches(rows,{...filters,levels});
    const sceneRows=rows.filter(d=>!filters.sceneCategory||sceneCategory(d)===filters.sceneCategory);
    const taskRows=matches(rows,{...filters,levels,task:'',query:''});
    const allTasks=[...new Set(taskRows.map(d=>d.task).filter(Boolean))].sort();
    const taskMatches=allTasks.filter(t=>t.toLowerCase().replaceAll('_',' ').includes((filters.taskSearch||'').trim().toLowerCase().replaceAll('_',' ')));
    const facets={sceneCategories:[...new Set(rows.map(sceneCategory).filter(Boolean))],taskCount:taskMatches.length,scenes:[...new Set(sceneRows.map(d=>d.scene).filter(Boolean))].sort(),tasks:taskMatches.slice(0,100),resolutions:[...new Set(rows.map(d=>d.resolution).filter(Boolean))].sort((a,b)=>{const [aw,ah]=a.split('x').map(Number),[bw,bh]=b.split('x').map(Number);return aw-bw||ah-bh;}),
      modalities:Object.fromEntries([...new Set(rows.flatMap(d=>d.mods))].map(m=>[m,rows.filter(d=>d.mods.includes(m)).length]))};
    return {snapshotId:manifest.snapshotId,levels,...paginate(found,page,pageSize),stats:aggregate(found),facets,
      ...(selectAll?{selected:found.map(({searchText,...d})=>d)}:{})};
  }
  async resolve({manifest,selection,strict=true},progress) {
    const hints=selection.datasets.map(d=>d.level);
    const levels=hints.every(l=>LEVELS.includes(l))?[...new Set(hints)]:LEVELS;
    const rows=await this.scope(manifest,levels,progress);
    if(strict)parseSelection(selection,rows);
    const wanted=new Set(selection.datasets.map(d=>d.repo_id));
    return rows.filter(d=>wanted.has(d.id)).map(({searchText,...d})=>d);
  }
}
export class WorkerClient {
  constructor(){
    this.worker=new Worker(new URL('./catalog-worker.js',import.meta.url),{type:'module'});this.next=0;this.pending=new Map();this.failed=false;
    this.worker.onmessage=({data})=>{const p=this.pending.get(data.id);if(!p)return;if(data.progress){p.progress?.(...data.progress);return;}this.pending.delete(data.id);data.error?p.reject(Error(data.error)):p.resolve(data.result);};
    this.worker.onerror=()=>{this.failed=true;this.worker.terminate();for(const p of this.pending.values())p.reject(Error('Catalog worker failed. Reload the page to retry.'));this.pending.clear();};
  }
  request(type,payload,progress){if(this.failed)return Promise.reject(Error('Catalog worker failed. Reload the page to retry.'));const id=++this.next;return new Promise((resolve,reject)=>{this.pending.set(id,{resolve,reject,progress});this.worker.postMessage({id,type,payload});});}
}
