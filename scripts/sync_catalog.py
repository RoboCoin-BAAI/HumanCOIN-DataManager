#!/usr/bin/env python3
"""Incrementally sync public HumanCOIN metadata and atomically publish a validated static snapshot."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    from .catalog_store import publish, read_records, encoded, valid_number, camera_resolution, scene_fields
except ImportError:
    from catalog_store import publish, read_records, encoded, valid_number, camera_resolution, scene_fields

HF = 'https://huggingface.co'
MS = 'https://www.modelscope.cn'
ROOT = Path(__file__).resolve().parents[1]
_NETWORK_LOCK = threading.Lock()
_THROTTLE_UNTIL = 0.0
_NETWORK_CONDITION = threading.Condition()
_NETWORK_LIMIT = 4
_NETWORK_ACTIVE = 0

def retry_delay(value, attempt):
    try:
        return max(0.0, min(120, float(value)))
    except (ValueError, TypeError):
        try:
            return max(0.0, min(120, parsedate_to_datetime(value).timestamp() - time.time()))
        except (ValueError, TypeError, AttributeError):
            return min(30, 2 ** attempt) + random.random()

def fetch(url):
    global _THROTTLE_UNTIL, _NETWORK_LIMIT, _NETWORK_ACTIVE
    for attempt in range(4):
        try:
            delay = _THROTTLE_UNTIL - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            with _NETWORK_CONDITION:
                _NETWORK_CONDITION.wait_for(lambda: _NETWORK_ACTIVE < _NETWORK_LIMIT)
                _NETWORK_ACTIVE += 1
            try:
                with urlopen(Request(url, headers={'User-Agent': 'HumanCOIN-DataManager/3.0'}), timeout=30) as response:
                    return json.load(response), response.headers.get('Link', '')
            finally:
                with _NETWORK_CONDITION:
                    _NETWORK_ACTIVE -= 1
                    _NETWORK_CONDITION.notify_all()
        except (HTTPError, URLError, TimeoutError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (408, 429, 500, 502, 503, 504)
            if not retryable or attempt == 3:
                raise
            delay = retry_delay((exc.headers or {}).get('Retry-After') if isinstance(exc, HTTPError) else None, attempt)
            if isinstance(exc, HTTPError) and exc.code == 429:
                with _NETWORK_CONDITION:
                    _NETWORK_LIMIT = max(1, _NETWORK_LIMIT // 2)
                with _NETWORK_LOCK:
                    _THROTTLE_UNTIL = max(_THROTTLE_UNTIL, time.monotonic() + delay)
            time.sleep(delay)

def hf_catalog():
    url = HF + '/api/datasets?author=HumanCOIN&limit=100&full=true'
    result, seen = [], set()
    while url:
        if url in seen:
            raise ValueError('Repeated Hugging Face pagination URL')
        seen.add(url)
        data, link = fetch(url)
        if not isinstance(data, list):
            raise ValueError('Unexpected Hugging Face catalog response')
        result.extend(data)
        match = re.search(r'<([^>]+)>; rel="next"', link)
        url = match[1] if match else None
        if url and not url.startswith(HF + '/api/datasets?'):
            raise ValueError('Unexpected pagination URL')
    ids = [row['id'] for row in result]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate records across Hugging Face pages; retry a stable scan')
    return result

def ms_catalog():
    result, page, expected, seen = [], 1, None, set()
    while True:
        data, _ = fetch(MS + '/api/v1/datasets?' + urlencode({'Owner': 'HumanCOIN', 'PageNumber': page, 'PageSize': 100}))
        if data.get('Code') != 200 or not isinstance(data.get('Data'), list):
            raise ValueError('Unexpected ModelScope catalog response')
        if expected is None:
            expected = data['TotalCount']
        if data['TotalCount'] != expected:
            raise ValueError('ModelScope inventory changed during pagination')
        for row in data['Data']:
            key = (row.get('Namespace'), row['Name'])
            if key in seen:
                raise ValueError('Repeated ModelScope page')
            seen.add(key)
        result.extend(data['Data'])
        if len(result) == expected:
            return result
        if not data['Data'] or len(result) > expected:
            raise ValueError('Incomplete ModelScope inventory')
        page += 1

def ms_file(repo, path):
    return f'{MS}/api/v1/datasets/{repo}/repo?' + urlencode({'Revision': 'master', 'FilePath': path})

def normalize(repo, hf, ms, info, readme):
    features = info.get('features', {})
    keys = ' '.join(features).lower()
    mods = []
    for name, present in [
        ('RGB', any(v.get('dtype') == 'video' and 'depth' not in k for k,v in features.items())),
        ('Depth', 'depth' in keys), ('Hand Pose', 'hand_' in keys), ('Gaze', 'gaze' in keys),
        ('Eye Camera', 'eye_rgb' in keys), ('EMG', 'emg' in keys), ('EEG', 'eeg' in keys),
        ('Manus', readme.get('hand_capture_type') == 'glove' or 'hand_skeleton' in keys),
        ('Audio', any(v.get('dtype') == 'audio' for v in features.values())), ('IMU', 'imu' in keys)]:
        if present:
            mods.append(name)
    level = re.match(r'(l[123])(?:_|-)', repo.split('/')[-1], re.I)
    tags = hf.get('tags', []) + (ms.get('UserDefineTags') or '').split(',')
    explicit = readme.get('level') or next((x.upper() for x in tags if x.upper() in ('L1','L2','L3')), None)
    level_conflict = bool(explicit in ('L1','L2','L3') and level and explicit != level[1].upper())
    level = explicit if explicit in ('L1','L2','L3') else level[1].upper() if level else 'Unknown'
    seconds = readme.get('duration_s')
    if seconds is None and valid_number(info.get('fps')) and info['fps'] > 0 and valid_number(info.get('total_frames'), True):
        seconds = info['total_frames'] / info['fps']
    scene = readme.get('scene') or {}
    scene, scene_category = scene_fields(scene)
    revision = hf.get('sha') or 'main'
    resolution, primary_camera, resolution_source = camera_resolution(repo, features, readme.get('cameras'))
    videos = []
    # Only build URLs from the dataset's declared video template, never assumed files.
    template = info.get('video_path')
    if (hf or ms) and template and info.get('total_episodes', 0) > 0:
        primary = primary_camera
        ordered = sorted(features.items(), key=lambda item: item[0] != primary)
        for key, value in ordered:
            if value.get('dtype') != 'video' or 'depth' in key:
                continue  # Depth HEVC streams are not browser RGB previews.
            try:
                path = template.format(episode_chunk=0, episode_index=0, video_key=key)
                url = f'{HF}/datasets/{repo}/resolve/{revision}/{quote(path, safe="/")}' if hf else ms_file(repo, path)
                videos.append({'key': key, 'url': url})
            except (ValueError, KeyError):
                continue
    return {
        'id': repo, 'repo': repo, 'name': repo.split('/')[-1].replace('_', ' '),
        'level': level, 'scene': scene or '', 'sceneCategory': scene_category, 'task': readme.get('task_name') or '',
        'description': readme.get('task_description') or '', 'mods': mods,
        'resolution': resolution, 'primaryCamera': primary_camera, 'resolutionSource': resolution_source,
        'episodes': info.get('total_episodes'), 'durationSeconds': seconds,
        'sizeBytes': readme.get('size_bytes'), 'downloads': hf.get('downloads'),
        'updated': hf.get('lastModified') or (datetime.fromtimestamp(ms['GmtModified'], timezone.utc).isoformat() if ms.get('GmtModified') else ''),
        'public': not hf.get('private', False), 'gated': hf.get('gated', False),
        'license': next((t.split(':', 1)[1] for t in tags if t.startswith('license:')), ms.get('License')),
        'hubs': {**({'huggingface': {'repo': repo, 'revision': revision, 'url': f'{HF}/datasets/{repo}'}} if hf else {}),
                 **({'modelscope': {'repo': repo, 'revision': 'master', 'url': f'{MS}/datasets/{repo}'}} if ms else {})},
        'videos': videos,
        'streams': [{'key': k, 'dtype': v.get('dtype'), 'shape': v.get('shape'), 'rate': v.get('fps', v.get('sample_rate'))} for k,v in features.items() if k.startswith('observation.')],
        'levelConflict': level_conflict,
        'derivedMetrics': ['durationSeconds'] if readme.get('duration_s') is None and seconds is not None else [],
        'metadataSources': [f'{HF}/datasets/{repo}/raw/{revision}/meta/{name}.json' for name in ('info','readme')] if hf else [ms_file(repo, f'meta/{name}.json') for name in ('info','readme')] if ms else [],
    }

def source_record(repo, hub, listing, cache_root, now, warnings, force=False):
    cache_path = cache_root / (hashlib.sha256((hub + '/' + repo).encode()).hexdigest() + '.json')
    try:
        cached = json.loads(cache_path.read_text()) if cache_path.exists() else None
        if cached and not all(key in cached for key in ('fingerprint', 'checkedAt', 'record')):
            cached = None
    except (ValueError, OSError):
        cached = None
    fingerprint = listing.get('sha') if hub == 'huggingface' else str(listing.get('GmtModified') or '')
    if cached and 'sceneCategory' in cached['record'] and 'resolution' in cached['record'] and not force and cached['fingerprint'] == fingerprint:
        # Commit-addressed HF data can be reused indefinitely. Branch-based sources are rechecked daily.
        age = (now - datetime.fromisoformat(cached['checkedAt'])).total_seconds()
        if (hub == 'huggingface' and fingerprint) or age < 86400:
            return cached['record'], 'ok', cached['checkedAt']
    base = f"{HF}/datasets/{repo}/raw/{listing.get('sha') or 'main'}/meta/"
    values, errors = {}, []
    for name in ('info', 'readme'):
        url = base + name + '.json' if hub == 'huggingface' else ms_file(repo, f'meta/{name}.json')
        try:
            value = fetch(url)[0]
            if not isinstance(value, dict) or 'Code' in value or 'Message' in value and 'Data' in value:
                raise ValueError('Unexpected metadata response')
            values[name] = value
        except Exception as exc:
            errors.append(f'{hub}/{repo}/meta/{name}.json: {exc}')
    warnings.extend(errors)
    if errors and cached:
        return cached['record'], 'stale', cached['checkedAt']
    record = normalize(repo, listing if hub == 'huggingface' else {}, listing if hub == 'modelscope' else {}, values.get('info', {}), values.get('readme', {}))
    record['metadataFingerprint'] = fingerprint
    record['metadataRevision'] = listing.get('sha') or 'master' if hub == 'modelscope' else listing.get('sha') or 'main'
    if not errors:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_suffix('.tmp')
        temp.write_bytes(encoded({'fingerprint': fingerprint, 'checkedAt': now.isoformat(), 'record': record}))
        temp.replace(cache_path)
    return record, 'missing' if errors else 'ok', now.isoformat()

def synchronize(output, state_root, *, workers=4, force=False, now=None, preview_limit=50):
    global _NETWORK_LIMIT
    _NETWORK_LIMIT = workers
    now = now or datetime.now(timezone.utc)
    warnings, inventories, sources = [], {}, {}
    # Do not mutate removal state or publish anything until both inventories are complete.
    for hub, loader in [('huggingface', hf_catalog), ('modelscope', ms_catalog)]:
        inventories[hub] = loader()
        sources[hub] = {'status': 'ok', 'count': len(inventories[hub]), 'checkedAt': now.isoformat()}
    hf = {d['id']: d for d in inventories['huggingface'] if d.get('author') == 'HumanCOIN' and not d.get('private') and not d.get('disabled')}
    ms = {f"{d['Namespace']}/{d['Name']}": d for d in inventories['modelscope'] if d.get('Namespace') == 'HumanCOIN'}
    sources['huggingface']['count'] = len(hf)
    sources['modelscope']['count'] = len(ms)
    state_root = Path(state_root)
    state_file = state_root / 'inventory.json'
    old_state = json.loads(state_file.read_text()) if state_file.exists() else {'missing': {}}
    previous = {d['id']: d for d in read_records(Path(output).parent)} if Path(output).exists() else {}
    missing = {}
    def build(repo):
        records, statuses, checks = {}, {}, {}
        for hub, listing in [('huggingface', hf.get(repo)), ('modelscope', ms.get(repo))]:
            if listing is not None:
                records[hub], statuses[hub], checks[hub] = source_record(repo, hub, listing, state_root / 'sources', now, warnings, force)
            elif hub in previous.get(repo, {}).get('hubs', {}):
                key = hub + '/' + repo
                scans = old_state.get('missing', {}).get(key, 0) + 1
                missing[key] = scans
                if scans < 2:
                    statuses[hub] = 'removal_candidate'
        available = sorted(records, key=lambda hub: (statuses[hub] != 'ok', hub != 'huggingface'))
        if not available:
            if not statuses:
                return None
            d = dict(previous[repo])
            d['staleMetrics'] = ['episodes', 'durationSeconds', 'sizeBytes', 'downloads']
        else:
            canonical = available[0]
            d = dict(records[canonical])
            d['metadataSource'] = canonical
            d['sourceChecks'] = checks
            if statuses[canonical] != 'ok':
                d['staleMetrics'] = ['episodes', 'durationSeconds', 'sizeBytes'] if statuses[canonical] == 'stale' else []
            if all(statuses.get(h) == 'ok' for h in ('huggingface', 'modelscope')):
                conflicts = [key for key in ('episodes', 'durationSeconds', 'sizeBytes', 'level') if records['huggingface'].get(key) is not None and records['modelscope'].get(key) is not None and records['huggingface'].get(key) != records['modelscope'].get(key)]
                if conflicts:
                    warnings.append(repo + ': source metadata conflict: ' + ', '.join(conflicts))
        if d.get('levelConflict'):
            warnings.append(repo + ': explicit tier conflicts with repository name; explicit tier retained')
        d['sourceStatus'] = statuses
        hubs = {}
        for hub in statuses:
            old = previous.get(repo, {}).get('hubs', {}).get(hub, {})
            revision = hf[repo].get('sha') or 'main' if hub == 'huggingface' and repo in hf else 'master' if hub == 'modelscope' and repo in ms else old.get('revision', 'main')
            hubs[hub] = {'repo': repo, 'revision': revision, 'url': f'{HF}/datasets/{repo}' if hub == 'huggingface' else f'{MS}/datasets/{repo}', 'mutableRevision': revision in ('main', 'master')}
        d['hubs'] = hubs
        d['downloads'] = hf[repo].get('downloads') if repo in hf else d.get('downloads') if statuses.get('huggingface') == 'removal_candidate' else None
        d['updated'] = hf[repo].get('lastModified', '') if repo in hf else datetime.fromtimestamp(ms[repo]['GmtModified'], timezone.utc).isoformat() if repo in ms and ms[repo].get('GmtModified') else d.get('updated', '')
        if any(status == 'removal_candidate' for status in statuses.values()):
            warnings.append(repo + ': source missing from first complete inventory; pending confirmation')
            d['staleMetrics'] = list(set(d.get('staleMetrics', []) + ['downloads']))
        return d
    with ThreadPoolExecutor(max_workers=workers) as pool:
        datasets = [d for d in pool.map(build, sorted(hf.keys() | ms.keys() | previous.keys())) if d is not None]
    try:
        from .preview_assets import attach_previews
    except ImportError:
        from preview_assets import attach_previews
    attach_previews(datasets, Path(output).parent, state_root, warnings, max_new=preview_limit)
    result = publish(output, datasets, generated_at=now.isoformat(), sources=sources, warnings=warnings)
    state_root.mkdir(parents=True, exist_ok=True)
    temp = state_file.with_suffix('.tmp')
    temp.write_bytes(encoded({'missing': missing, 'checkedAt': now.isoformat()}))
    temp.replace(state_file)
    return result

def write_catalog(output, datasets, **kwargs):
    return publish(output, datasets, **kwargs)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/data/catalog.json')
    parser.add_argument('--state-dir', type=Path, default=ROOT / 'sync-state')
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--preview-limit', type=int, default=50, help='Maximum new video previews per sync; cached previews are always reused')
    parser.add_argument('--force', action='store_true', help='Re-read unchanged source metadata')
    parser.add_argument('--validate', action='store_true', help='Validate the published snapshot without network access')
    args = parser.parse_args()
    if args.preview_limit < 0:
        parser.error('--preview-limit must be nonnegative')
    try:
        if args.validate:
            try:
                from .catalog_store import validate
            except ImportError:
                from catalog_store import validate
            result = validate(args.output.parent)
        else:
            result = synchronize(args.output, args.state_dir, workers=args.workers, force=args.force, preview_limit=args.preview_limit)
        print(f"Snapshot {result['snapshotId'][:12]}: {result['stats']['datasets']} datasets")
        return 0
    except Exception as exc:
        print(f'Catalog unchanged: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
