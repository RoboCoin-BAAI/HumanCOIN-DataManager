"""Versioned static catalog storage. No network access; all published references are immutable."""
import hashlib
import json
import math
import re
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

SCHEMA = 3
LEVELS = ('L1', 'L2', 'L3', 'Unknown')
METRICS = ('episodes', 'durationSeconds', 'sizeBytes', 'downloads')
SCENES = json.loads((Path(__file__).resolve().parents[1] / 'humancoin_scenes_v1.json').read_text())

def scene_fields(value):
    if isinstance(value, dict):
        area = value.get('area') or value.get('name') or ''
        category = value.get('category') or ''
    else:
        area, category = value or '', ''
    known = next((key for key, areas in SCENES.items() if area in areas), '')
    category = known or (category if category in SCENES else '')
    if category in ('other', 'unknown'):
        area = category
    return area, category

MAX_SHARD = 2 * 1024 * 1024

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def valid_number(value, integer=False):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 and (not integer or int(value) == value)

def camera_resolution(repo, features=None, cameras=None):
    """Read width x height for the declared primary RGB camera; never use the master clock camera."""
    features, cameras = features or {}, cameras or {}
    primary = cameras.get('primary_camera')
    def dimensions(width, height):
        if valid_number(width, True) and valid_number(height, True) and width > 0 and height > 0:
            return f'{int(width)}x{int(height)}'
        return None
    if primary:
        feature = features.get(primary, {})
        info = feature.get('info') or {}
        shape = feature.get('shape') or []
        resolution = dimensions(info.get('video.width'), info.get('video.height'))
        if not resolution and len(shape) >= 2:
            resolution = dimensions(shape[1], shape[0])  # Metadata video shapes use HWC.
        if not resolution:
            item = next((item for item in cameras.get('items', []) if item.get('id') == primary), {})
            resolution = dimensions(item.get('width'), item.get('height'))
        if resolution:
            return resolution, primary, 'metadata'
    named = re.search(r'(?:^|_)([1-9]\d*)[xX]([1-9]\d*)(?=_|$)', repo.split('/')[-1])
    return (f'{int(named[1])}x{int(named[2])}', primary, 'repository-name') if named else (None, primary, None)

def with_camera_resolution(original):
    d = dict(original)
    d['scene'], d['sceneCategory'] = scene_fields({'area': d.get('scene'), 'category': d.get('sceneCategory')})
    d.pop('devices', None)
    if not isinstance(d.get('resolution'), str) or not re.fullmatch(r'[1-9]\d*x[1-9]\d*', d['resolution']):
        features = {stream['key']: stream for stream in d.get('streams', [])}
        resolution, primary, source = camera_resolution(d['id'], features, {'primary_camera': d.get('primaryCamera')})
        d.update(resolution=resolution, primaryCamera=primary, resolutionSource=source)
    return d

def aggregate(rows):
    result = {'datasets': len(rows)}
    for metric in METRICS:
        values = [d[metric] for d in rows if valid_number(d.get(metric), metric in ('episodes', 'sizeBytes', 'downloads'))]
        result[metric] = {'sumKnown': sum(values) if values or not rows else None,
                          'knownCount': len(values), 'missingCount': len(rows) - len(values),
                          'staleCount': sum(metric in d.get('staleMetrics', []) for d in rows),
                          'derivedCount': sum(metric in d.get('derivedMetrics', []) for d in rows)}
    return result

def immutable(root, directory, value):
    data = encoded(value)
    hash_value = digest(data)
    path = f'{directory}/{hash_value}.json'
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {'path': path, 'sha256': hash_value, 'bytes': len(data)}

def split_rows(rows, limit, prefix=''):
    payload = {'schemaVersion': SCHEMA, 'datasets': rows}
    if len(encoded(payload)) <= limit:
        return [payload] if rows else []
    if len(rows) < 2 or len(prefix) >= 256:
        raise ValueError('One index record exceeds the shard byte limit')
    buckets = [[], []]
    for row in rows:
        bits = bin(int(hashlib.sha256(row['id'].encode()).hexdigest(), 16))[2:].zfill(256)
        buckets[int(bits[len(prefix)])].append(row)
    return [part for i, bucket in enumerate(buckets) if bucket for part in split_rows(bucket, limit, prefix + str(i))]

def build(root, datasets, *, generated_at, sources, warnings, shard_limit=MAX_SHARD):
    seen, groups = set(), {level: [] for level in LEVELS}
    for original in sorted(datasets, key=lambda d: d['id']):
        d = with_camera_resolution(original)
        if d['id'] in seen:
            raise ValueError('Duplicate dataset ID: ' + d['id'])
        seen.add(d['id'])
        d['level'] = d.get('level') if d.get('level') in LEVELS else 'Unknown'
        for metric in METRICS:
            if not valid_number(d.get(metric), metric in ('episodes', 'sizeBytes', 'downloads')):
                d[metric] = None
        # Dynamic statistics and freshness must not invalidate static sensor/video details.
        detail = {key: value for key, value in d.items() if key not in (*METRICS, 'updated', 'staleMetrics', 'derivedMetrics', 'sourceStatus', 'sourceChecks', 'missingScans', 'revisions', 'detailPath', 'detailHash', 'summary', 'searchText')}
        ref = immutable(root, 'details', {'schemaVersion': SCHEMA, 'dataset': detail})
        keys = ('id', 'level', 'scene', 'sceneCategory', 'task', 'mods', 'resolution', *METRICS, 'updated', 'public')
        entry = {key: d.get(key) for key in keys}
        # Keep the retired field empty for already-open v3 clients; the current UI uses resolution.
        entry['devices'] = []
        entry.update(summary=d.get('description', '')[:240],
                     revisions={hub: source['revision'] for hub, source in d.get('hubs', {}).items()},
                     sourceStatus=d.get('sourceStatus', {}), staleMetrics=d.get('staleMetrics', []),
                     derivedMetrics=d.get('derivedMetrics', []), detailPath=ref['path'], detailHash=ref['sha256'])
        if d.get('preview'):
            entry['preview'] = d['preview']
        groups[d['level']].append(entry)
    tiers = {}
    for level, rows in groups.items():
        parts = []
        for payload in split_rows(rows, shard_limit):
            ref = immutable(root, 'indexes/' + level.lower(), payload)
            ref['count'] = len(payload['datasets'])
            parts.append(ref)
        tiers[level] = {'count': len(rows), 'stats': aggregate(rows), 'files': parts}
    all_rows = [row for rows in groups.values() for row in rows]
    report = immutable(root, 'reports', {'warnings': sorted(warnings)})
    content = {'schemaVersion': SCHEMA, 'stats': aggregate(all_rows), 'tiers': tiers,
               'sources': {hub: {k: v for k, v in source.items() if k != 'checkedAt'} for hub, source in sources.items()},
               'quality': {'warningCount': len(warnings), 'report': report}}
    snapshot_id = digest(encoded(content))
    old = root / 'manifests' / (snapshot_id + '.json')
    generated = json.loads(old.read_text())['generatedAt'] if old.exists() else generated_at
    manifest = {**content, 'snapshotId': snapshot_id, 'generatedAt': generated,
                'checkedAt': generated_at, 'sources': sources}
    immutable_manifest = root / 'manifests' / (snapshot_id + '.json')
    immutable_manifest.parent.mkdir(exist_ok=True)
    # Keep the first immutable manifest for this content; checkedAt lives in the mutable root.
    if not immutable_manifest.exists():
        immutable_manifest.write_bytes(encoded(manifest))
    (root / 'catalog.json').write_bytes(encoded(manifest))
    return manifest

def references(manifest):
    refs = [manifest['quality']['report']]
    refs.extend(part for tier in manifest['tiers'].values() for part in tier['files'])
    return refs

def validate(root, manifest=None):
    root = Path(root)
    manifest = manifest or json.loads((root / 'catalog.json').read_text())
    if manifest.get('schemaVersion') != SCHEMA:
        raise ValueError('Unsupported catalog schema')
    all_rows, seen = [], set()
    for ref in references(manifest):
        path = root / ref['path']
        if root.resolve() not in path.resolve().parents:
            raise ValueError('Unsafe reference path')
        data = path.read_bytes()
        if len(data) != ref['bytes'] or digest(data) != ref['sha256']:
            raise ValueError('Invalid content hash: ' + str(path))
    for level, tier in manifest['tiers'].items():
        rows = []
        for part in tier['files']:
            payload = json.loads((root / part['path']).read_text())
            if payload.get('schemaVersion') != SCHEMA or len(payload['datasets']) != part['count']:
                raise ValueError('Invalid index shard')
            rows.extend(payload['datasets'])
        for row in rows:
            if row['id'] in seen or row['level'] != level:
                raise ValueError('Duplicate ID or wrong tier')
            seen.add(row['id'])
            for name, ref in row.get('preview', {}).items():
                if name not in ('poster', 'clip') or not ref['path'].startswith('media/') or root.resolve() not in (root / ref['path']).resolve().parents:
                    raise ValueError('Invalid preview reference')
                media = (root / ref['path']).read_bytes()
                if len(media) != ref['bytes'] or digest(media) != ref['sha256']:
                    raise ValueError('Invalid preview hash')
            data = (root / row['detailPath']).read_bytes()
            if digest(data) != row['detailHash']:
                raise ValueError('Invalid detail hash')
            detail = json.loads(data)
            if detail.get('schemaVersion') != SCHEMA or detail['dataset']['id'] != row['id']:
                raise ValueError('Invalid detail ID or schema')
        if len(rows) != tier['count'] or aggregate(rows) != tier['stats']:
            raise ValueError('Tier statistics do not match index')
        all_rows.extend(rows)
    if aggregate(all_rows) != manifest['stats']:
        raise ValueError('Global statistics do not match indexes')
    return manifest

def collect(root, now):
    """Retain seven days and at least the last two content snapshots."""
    sightings_path = root / 'retention.json'
    sightings = json.loads(sightings_path.read_text()) if sightings_path.exists() else {}
    current = json.loads((root / 'catalog.json').read_text())
    sightings[current['snapshotId']] = current['checkedAt']
    manifests = sorted((root / 'manifests').glob('*.json'), key=lambda p: sightings.get(p.stem, json.loads(p.read_text())['checkedAt']), reverse=True)
    cutoff = now - timedelta(days=7)
    keep, used = [], set()
    current_id = json.loads((root / 'catalog.json').read_text())['snapshotId']
    for i, path in enumerate(manifests):
        value = json.loads(path.read_text())
        if i < 2 or path.stem == current_id or datetime.fromisoformat(sightings.get(path.stem, value['checkedAt'])) >= cutoff:
            keep.append(path)
            used.add(path.relative_to(root).as_posix())
            for ref in references(value):
                used.add(ref['path'])
            for tier in value['tiers'].values():
                for part in tier['files']:
                    for row in json.loads((root / part['path']).read_text())['datasets']:
                        used.add(row['detailPath'])
                        used.update(ref['path'] for ref in row.get('preview', {}).values())
    sightings_path.write_bytes(encoded({p.stem: sightings.get(p.stem, json.loads(p.read_text())['checkedAt']) for p in keep}))
    for directory in ('manifests', 'indexes', 'details', 'reports', 'media'):
        for path in (root / directory).rglob('*'):
            if path.is_file() and path.relative_to(root).as_posix() not in used:
                path.unlink()

def publish(output, datasets, *, generated_at, sources, warnings, shard_limit=MAX_SHARD):
    output = Path(output)
    if output.name != 'catalog.json':
        raise ValueError('Output must be named catalog.json')
    root = output.parent
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix='.catalog-build-') as directory:
        stage = Path(directory) / 'data'
        if root.exists():
            shutil.copytree(root, stage)
        else:
            stage.mkdir()
        manifest = build(stage, datasets, generated_at=generated_at, sources=sources, warnings=warnings, shard_limit=shard_limit)
        validate(stage, manifest)
        collect(stage, datetime.fromisoformat(generated_at))
        # New immutable objects become readable before the root pointer changes.
        root.mkdir(exist_ok=True)
        for path in stage.rglob('*'):
            if path.is_file() and path.name != 'catalog.json':
                target = root / path.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or path.name == 'retention.json':
                    shutil.copy2(path, target)
        temp = root / '.catalog.tmp'
        temp.write_bytes((stage / 'catalog.json').read_bytes())
        temp.replace(output)
        for directory in ('manifests', 'indexes', 'details', 'reports', 'media'):
            for path in (root / directory).rglob('*'):
                if path.is_file() and not (stage / path.relative_to(root)).exists():
                    path.unlink()
    return manifest

def read_records(root):
    root = Path(root)
    manifest = json.loads((root / 'catalog.json').read_text())
    if manifest['schemaVersion'] == 2:
        return [{**json.loads((root / row['detailPath']).read_text())['dataset'], **row} for row in manifest['datasets']]
    validate(root, manifest)
    return [{**json.loads((root / row['detailPath']).read_text())['dataset'], **row}
            for tier in manifest['tiers'].values() for part in tier['files']
            for row in json.loads((root / part['path']).read_text())['datasets']]
