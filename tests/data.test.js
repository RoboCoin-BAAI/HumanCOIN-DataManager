import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash, webcrypto} from 'node:crypto';
import {LEVELS, matches, manifest, command, parseSelection, shellQuote, duration, formatBytes, paginate, aggregate, initialLevels} from '../docs/js/data.js';
import {CatalogEngine, createDetailLoader, validateManifest, WorkerClient} from '../docs/js/catalog-client.js';
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const catalog=JSON.parse(readFileSync(new URL('../docs/data/catalog.json',import.meta.url)));
const diskRows=Object.values(catalog.tiers).flatMap(t=>t.files.flatMap(f=>JSON.parse(readFileSync(new URL('../docs/data/'+f.path,import.meta.url))).datasets));
const filters={query:'',levels:[],mods:[],scene:'',task:'',resolution:'',sort:'featured',publicOnly:true};
const row=(i,level='L3')=>({id:`HumanCOIN/${level.toLowerCase()}_${String(i).padStart(6,'0')}`,level,summary:'Object manipulation',scene:i%2?'kitchen':'desk',task:'assemble',mods:['RGB','EMG'],resolution:i%2?'1280x720':'1920x1184',episodes:i%4,durationSeconds:i,sizeBytes:1024,downloads:i,updated:'2026-11-13',public:true,revisions:{huggingface:'a'.repeat(40)},staleMetrics:[],derivedMetrics:[],sourceStatus:{huggingface:'ok'}});
function fixture(rows,chunk=700){
 const files=new Map();
 function store(dir,value){const data=Buffer.from(JSON.stringify(value)+'\n');const hash=createHash('sha256').update(data).digest('hex');const path=`${dir}/${hash}.json`;files.set('data/'+path,data);return {path,sha256:hash,bytes:data.length};}
 for(const d of rows){const ref=store('details',{schemaVersion:3,dataset:{id:d.id,hubs:{},streams:[],videos:[],description:'Full details'}});d.detailPath=ref.path;d.detailHash=ref.sha256;}
 const tiers={};for(const l of LEVELS){const group=rows.filter(d=>d.level===l),parts=[];for(let i=0;i<group.length;i+=chunk){const piece=group.slice(i,i+chunk);parts.push({...store('indexes/'+l.toLowerCase(),{schemaVersion:3,datasets:piece}),count:piece.length});}tiers[l]={count:group.length,stats:aggregate(group),files:parts};}
 const manifest={schemaVersion:3,snapshotId:'f'.repeat(64),stats:aggregate(rows),sources:{},tiers};const calls=[];
 const fetcher=async path=>{path='data/'+String(path).split('/data/').at(-1);calls.push(path);const data=files.get(path);return {ok:!!data,status:data?200:404,arrayBuffer:async()=>data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength)};};
 return {manifest,fetcher,calls,files};
}
test('published root is compact and every tier count is consistent',()=>{
 validateManifest(catalog);assert.ok(!('datasets' in catalog));assert.ok(readFileSync(new URL('../docs/data/catalog.json',import.meta.url)).length<50*1024);
 assert.equal(new Set(diskRows.map(d=>d.id)).size,catalog.stats.datasets);
 for(const d of diskRows){assert.ok(!('videos' in d));assert.ok(!('streams' in d));assert.ok(!('previewUrl' in d));assert.match(d.detailPath,/^details\/[a-f0-9]{64}\.json$/);}
});
test('stable sorting, missing values last, and AND modality matching',()=>{
 const ds=[{...row(2),episodes:null},{...row(1),episodes:3},{...row(0),episodes:3}];
 assert.deepEqual(matches(ds,{...filters,sort:'largest'}).map(d=>d.id),[row(0).id,row(1).id,row(2).id]);
 assert.equal(matches(ds,{...filters,mods:['RGB','EEG']}).length,0);assert.equal(matches(ds,{...filters,query:'HUMANCOIN'}).length,3);
 assert.equal(matches(ds,{...filters,scene:'kitchen'}).length,1);
});
test('pagination covers every record exactly once and clamps invalid/empty pages',()=>{
 for(const n of [0,1,20,21,10001]){const rows=Array.from({length:n},(_,i)=>row(i));let ids=[];for(let p=1;p<=Math.max(1,Math.ceil(n/20));p++){const result=paginate(rows,p,20);assert.ok(result.items.length<=20);ids.push(...result.items.map(d=>d.id));}assert.equal(new Set(ids).size,n);assert.equal(paginate(rows,99999,20).page,Math.max(1,Math.ceil(n/20)));}
 assert.equal(paginate([],1,20).start,0);assert.throws(()=>paginate([],1,10000));
});
test('tier scope loads only required shards, exact counts across pages, and cached requests deduplicate',async()=>{
 const rows=Array.from({length:10001},(_,i)=>row(i,i<9000?'L1':'L3'));const f=fixture(rows),engine=new CatalogEngine(f.fetcher);
 assert.equal(f.calls.length,0);const payload={manifest:f.manifest,levels:['L3'],filters,page:2,pageSize:20};
 const [a,b]=await Promise.all([engine.query(payload),engine.query(payload)]);assert.equal(a.total,1001);assert.equal(a.items.length,20);assert.deepEqual(a,b);
 assert.ok(f.calls.every(path=>path.includes('/indexes/l3/')));assert.equal(f.calls.length,2);
 const all=await engine.query({...payload,selectAll:true});assert.equal(all.selected.length,1001);assert.equal(f.calls.length,2);assert.equal(all.stats.datasets,1001);
});
test('required shard failure cannot produce a partial successful query and retry works',async()=>{
 const f=fixture(Array.from({length:25},(_,i)=>row(i)),10);let fail=true;const engine=new CatalogEngine(async path=>fail&&path.includes(f.manifest.tiers.L3.files[1].path)?{ok:false,status:503}:f.fetcher(path));
 const payload={manifest:f.manifest,levels:['L3'],filters,page:1,pageSize:20};await assert.rejects(engine.query(payload),/503/);fail=false;assert.equal((await engine.query(payload)).total,25);
});
test('content integrity failure rejects corrupted index data',async()=>{
 const f=fixture([row(0)]),ref=f.manifest.tiers.L3.files[0];f.files.set('data/'+ref.path,Buffer.from('{}'));
 await assert.rejects(new CatalogEngine(f.fetcher).query({manifest:f.manifest,levels:['L3'],filters,page:1,pageSize:20}),/integrity/);
});
test('detail is requested on demand, deduplicated, and index freshness overlays cached static data',async()=>{
 const d=row(0),f=fixture([d]);const load=createDetailLoader(f.fetcher,1);assert.equal(f.calls.length,0);
 const [a,b]=await Promise.all([load(d),load(d)]);assert.equal(a.id,b.id);assert.equal(f.calls.length,1);assert.equal((await load({...d,downloads:42})).downloads,42);assert.equal(f.calls.length,1);
});
test('cross-tier selection resolution uses tier hints and legacy files check every tier',async()=>{
 const f=fixture([row(0,'L1'),row(1,'L3')]),engine=new CatalogEngine(f.fetcher);
 const selection={schema_version:'1.0',datasets:[{repo_id:row(1).id,level:'L3'}]};assert.equal((await engine.resolve({manifest:f.manifest,selection})).length,1);assert.equal(f.calls.length,1);
 assert.equal((await engine.resolve({manifest:f.manifest,selection:{schema_version:'1.0',datasets:[{repo_id:row(0,'L1').id}]}})).length,1);
 await assert.rejects(engine.resolve({manifest:f.manifest,selection:{schema_version:'1.0',datasets:[{repo_id:'HumanCOIN/missing'}]}}));
});
test('commands and selection JSON preserve source versions without requesting details',()=>{
 const ds=[row(1),row(2)];const data=manifest(ds,'huggingface','snapshot');assert.equal(data.snapshot_id,'snapshot');assert.deepEqual(parseSelection(data,ds),ds.map(d=>d.id));
 const cmd=command(ds,'huggingface');assert.equal((cmd.match(/humancoin-download/g)||[]).length,2);assert.ok(cmd.includes('--revision'));assert.ok(!cmd.includes('--manifest'));
 assert.throws(()=>command(ds,'modelscope'),/unavailable/);assert.throws(()=>command([],'huggingface'),/Select at least/);assert.throws(()=>manifest(ds,'evil'),/Unknown/);
 assert.throws(()=>command([{...row(0),sourceStatus:{huggingface:'removal_candidate'}}],'huggingface'),/unavailable/);
});
test('aggregate distinguishes unknown, partial and zero; shell quoting remains safe',()=>{
 const stats=aggregate([{...row(0),episodes:null},{...row(1),episodes:0}]);assert.equal(stats.episodes.sumKnown,0);assert.equal(stats.episodes.missingCount,1);assert.equal(aggregate([]).episodes.sumKnown,0);assert.equal(aggregate([{episodes:null}]).episodes.sumKnown,null);
 assert.equal(shellQuote("a'b"),"'a'\"'\"'b'");assert.equal(duration(null),'—');assert.equal(formatBytes(null),'—');assert.equal(formatBytes(0),'0 B');
});

test('initial tier honors shared links, restores valid scopes, and falls back from empty tiers',()=>{
 const catalog={tiers:{L1:{count:0},L2:{count:0},L3:{count:2},Unknown:{count:0}}};
 assert.deepEqual(initialLevels(catalog),['L3']);
 assert.deepEqual(initialLevels(catalog,{urlLevels:['L2'],savedLevels:['L3']}),['L2']);
 assert.deepEqual(initialLevels(catalog,{savedLevels:['L1']}),['L3']);
 assert.deepEqual(initialLevels(catalog,{savedLevels:['L3','L1','L3']}),['L3','L1']);
 assert.deepEqual(initialLevels(catalog,{savedLevels:'bad',urlLevels:['invalid']}),['L3']);
 const multiple={tiers:{...catalog.tiers,L1:{count:10}}};
 assert.deepEqual(initialLevels(multiple),['L1']);
 assert.deepEqual(initialLevels(multiple,{defaultLevel:'L3'}),['L3']);
 assert.deepEqual(initialLevels(multiple,{savedLevels:['L3'],defaultLevel:'L1'}),['L3']);
 assert.deepEqual(initialLevels({tiers:{}}),[]);
});

test('failed workers reject pending and future requests instead of leaving Retry hanging',async()=>{
 const original=globalThis.Worker;let instance;
 globalThis.Worker=class{constructor(){instance=this;}postMessage(){}terminate(){this.terminated=true;}};
 try{const client=new WorkerClient(),pending=client.request('query',{});instance.onerror();await assert.rejects(pending,/worker failed/);assert.ok(instance.terminated);await assert.rejects(client.request('query',{}),/worker failed/);}finally{globalThis.Worker=original;}
});

test('main-camera resolution filters match exactly and facets sort numeric dimensions',async()=>{
 const rows=[row(0),row(1),{...row(2),resolution:null}];
 assert.deepEqual(matches(rows,{...filters,resolution:'1920x1184'}).map(d=>d.id),[row(0).id]);
 assert.equal(matches(rows,{...filters,resolution:'640x480'}).length,0);
 const f=fixture(rows),engine=new CatalogEngine(f.fetcher);
 const result=await engine.query({manifest:f.manifest,levels:['L3'],filters:{...filters,resolution:'1280x720'},page:1,pageSize:20});
 assert.equal(result.total,1);assert.equal(result.items[0].id,row(1).id);
 assert.deepEqual(result.facets.resolutions,['1280x720','1920x1184']);assert.ok(!('devices' in result.facets));
});


test('scene hierarchy includes descendants and task candidates remain bounded',async()=>{
 const rows=Array.from({length:250},(_,i)=>({...row(i),scene:i%2?'kitchen':'dining_area',task:`task_${String(i).padStart(3,'0')}`}));
 rows.push({...row(999),scene:'office',task:'office_task'});
 assert.equal(matches(rows,{...filters,sceneCategory:'household'}).length,250);
 assert.equal(matches(rows,{...filters,sceneCategory:'household',scene:'kitchen'}).length,125);
 const f=fixture(rows),engine=new CatalogEngine(f.fetcher);
 const result=await engine.query({manifest:f.manifest,levels:['L3'],filters:{...filters,sceneCategory:'household'},page:1,pageSize:20});
 assert.equal(result.total,250);assert.equal(result.facets.tasks.length,100);assert.equal(result.facets.taskCount,250);
 assert.deepEqual(result.facets.scenes,['dining_area','kitchen']);
 const searched=await engine.query({manifest:f.manifest,levels:['L3'],filters:{...filters,taskSearch:'task 249'},page:1,pageSize:20});
 assert.deepEqual(searched.facets.tasks,['task_249']);assert.equal(searched.total,251);
});
