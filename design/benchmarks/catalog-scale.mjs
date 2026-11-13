import {readFileSync,writeFileSync} from 'node:fs';
import {gzipSync} from 'node:zlib';
import {performance} from 'node:perf_hooks';
const fixtures=JSON.parse(readFileSync(new URL('./fixtures.json',import.meta.url)));
function median(values){return values.sort((a,b)=>a-b)[Math.floor(values.length/2)];}
const results=[];
for(const n of [10000,50000,100000]){
 const index=[];
 let fullBytes=2;
 for(let i=0;i<n;i++){
  const sample=fixtures[i%fixtures.length];
  const level=['L1','L2','L3'][i%3];
  const id=`HumanCOIN/${level.toLowerCase()}_scene_${i%18}_task_${i%500}_${String(i).padStart(6,'0')}`;
  fullBytes+=Buffer.byteLength(JSON.stringify({...sample.detail,id,repo:id,level}))+1;
  const row={...sample.index,id,level,task:`task_${i%500}`,scene:`scene_${i%18}`};
  delete row.previewUrl;
  index.push(row);
 }
 const light=JSON.stringify(index);
 const parse=[],query=[];
 for(let run=0;run<7;run++){
  let t=performance.now();const rows=JSON.parse(light);parse.push(performance.now()-t);
  t=performance.now();const found=rows.filter(d=>d.level==='L3'&&d.mods.includes('EMG')&&[d.id,d.summary,d.task,d.scene].join(' ').toLowerCase().includes('task_')).sort((a,b)=>(b.episodes??-1)-(a.episodes??-1)||a.id.localeCompare(b.id));
  found.slice(20,40);query.push(performance.now()-t);
 }
 const l1=JSON.stringify(index.filter(d=>d.level==='L1'));
 results.push({rows:n,fullBytes,indexBytes:Buffer.byteLength(light),indexGzipBytes:gzipSync(light).length,oneTierBytes:Buffer.byteLength(l1),oneTierGzipBytes:gzipSync(l1).length,medianParseMs:median(parse),medianFilterSortPageMs:median(query)});
}
if (process.argv[2]) writeFileSync(process.argv[2],JSON.stringify(results,null,2)+'\n');
console.log(JSON.stringify(results,null,2));
