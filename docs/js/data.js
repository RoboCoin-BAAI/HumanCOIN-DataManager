import {sceneCategory} from './scenes.js';
export const HUBS = ['huggingface', 'modelscope'];
export const LEVELS = ['L1', 'L2', 'L3', 'Unknown'];
export function matches(datasets, filters) {
  const query = (filters.query || '').trim().toLowerCase();
  const rows = datasets.filter(d => (!filters.levels.length || filters.levels.includes(d.level)) &&
    filters.mods.every(m => d.mods.includes(m)) && (!filters.sceneCategory || sceneCategory(d) === filters.sceneCategory) && (!filters.scene || d.scene === filters.scene) &&
    (!filters.task || d.task === filters.task) && (!filters.resolution || d.resolution === filters.resolution) &&
    (!filters.publicOnly || d.public) && (!query || (d.searchText || [d.id, d.task, d.scene, d.summary, ...d.mods].join(' ').toLowerCase()).includes(query)));
  const missingLast = (a,b,key) => a[key] == null ? b[key] == null ? 0 : 1 : b[key] == null ? -1 : b[key] - a[key];
  return rows.sort((a,b) => (filters.sort === 'newest' ? (a.updated ? b.updated ? b.updated.localeCompare(a.updated) : -1 : b.updated ? 1 : 0) :
    filters.sort === 'largest' ? missingLast(a,b,'episodes') : filters.sort === 'popular' ? missingLast(a,b,'downloads') : LEVELS.indexOf(a.level)-LEVELS.indexOf(b.level)) || a.id.localeCompare(b.id));
}
export function parseSelection(value, datasets) {
  if (value?.schema_version !== '1.0' || !Array.isArray(value.datasets)) throw Error('Expected a selection.json file with schema_version 1.0.');
  const known = new Set(datasets.map(d => d.id));
  const repos = value.datasets.map(d => d?.repo_id);
  if (repos.some(repo => !known.has(repo))) throw Error('The file contains datasets missing from this snapshot. Your selection has not changed.');
  if (value.hub && !HUBS.includes(value.hub)) throw Error('Unknown download source.');
  return [...new Set(repos)];
}
export function manifest(datasets, hub, snapshotId) {
  if (!HUBS.includes(hub)) throw Error('Unknown download source.');
  if (datasets.some(d => !d.revisions?.[hub] || d.sourceStatus?.[hub] === 'removal_candidate')) throw Error('Some selected datasets are unavailable on this platform. Switch the download source or remove unsupported datasets.');
  return {schema_version: '1.0', selection_name: 'humancoin_selection', hub, ...(snapshotId ? {snapshot_id:snapshotId} : {}),
    datasets: datasets.map(d => ({repo_id:d.id, level:d.level, revision:d.revisions[hub]}))};
}
export const shellQuote = value => "'" + String(value).replaceAll("'", "'\"'\"'") + "'";
export function command(datasets, hub) {
  const selection = manifest(datasets, hub);
  if (!selection.datasets.length) throw Error('Select at least one dataset first.');
  return selection.datasets.map(d => `humancoin-download --hub ${hub} \\\n  --datasets ${shellQuote(d.repo_id)} \\\n  --revision ${shellQuote(d.revision)} \\\n  --target-dir ./data --max-workers 8`).join('\n\n');
}
export function formatBytes(bytes) {
  if (bytes == null) return '—';
  if (!bytes) return '0 B';
  const index = Math.min(4, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(1)} ${['B','KiB','MiB','GiB','TiB'][index]}`;
}
export function duration(seconds) {
  if (seconds == null) return '—';
  const hours = seconds / 3600;
  return hours > 0 && hours < 0.01 ? '<0.01 h' : `${hours.toFixed(2)} h`;
}
export function paginate(items, page = 1, pageSize = 20) {
  if (![20,50,100].includes(pageSize)) throw Error('Invalid page size.');
  const total = items.length, pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(pages, Math.max(1, Math.trunc(page) || 1)), offset=(current-1)*pageSize;
  return {items:items.slice(offset,offset+pageSize),page:current,pages,total,start:total?offset+1:0,end:Math.min(offset+pageSize,total)};
}
export function aggregate(rows) {
  const stats={datasets:rows.length};
  for (const key of ['episodes','durationSeconds','sizeBytes','downloads']) {
    const known=rows.filter(d=>Number.isFinite(d[key])&&d[key]>=0);
    stats[key]={sumKnown:known.length||!rows.length?known.reduce((s,d)=>s+d[key],0):null,knownCount:known.length,missingCount:rows.length-known.length,
      staleCount:rows.filter(d=>d.staleMetrics?.includes(key)).length,derivedCount:rows.filter(d=>d.derivedMetrics?.includes(key)).length};
  }
  return stats;
}

export function initialLevels(catalog, {urlLevels = [], savedLevels = [], defaultLevel = 'L1'} = {}) {
  const valid = values => Array.isArray(values) ? [...new Set(values.filter(level => LEVELS.includes(level)))] : [];
  const explicit = valid(urlLevels);
  // Shared links remain authoritative, including a deliberately chosen empty tier.
  if (explicit.length) return explicit;
  const remembered = valid(savedLevels);
  if (remembered.some(level => catalog.tiers[level]?.count > 0)) return remembered;
  const available = LEVELS.filter(level => catalog.tiers[level]?.count > 0);
  return available.includes(defaultLevel) ? [defaultLevel] : available.slice(0, 1);
}
