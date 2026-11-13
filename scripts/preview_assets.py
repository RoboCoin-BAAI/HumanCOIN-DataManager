"""Build small real-video posters/clips once per source URL; never put hub videos on list cards."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

try:
    from .catalog_store import encoded
except ImportError:
    from catalog_store import encoded

VERSION = 'preview-480p-12fps-4s-v1'

def asset(root, data, extension):
    sha = hashlib.sha256(data).hexdigest()
    path = f'media/{sha}.{extension}'
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temp = target.with_suffix('.tmp')
        temp.write_bytes(data)
        temp.replace(target)
    return {'path': path, 'sha256': sha, 'bytes': len(data)}

def existing(root, preview):
    if not preview:
        return False
    for name in ('poster', 'clip'):
        ref = preview.get(name, {})
        path = root / ref.get('path', '')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ref.get('sha256'):
            return False
    return True

def generate(url, root, runner=subprocess.run):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('huggingface.co', 'www.modelscope.cn'):
        raise ValueError('Unsupported preview source')
    with tempfile.TemporaryDirectory(prefix='humancoin-preview-') as directory:
        clip, poster = Path(directory) / 'clip.mp4', Path(directory) / 'poster.jpg'
        options = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
        # FFmpeg uses a lowercase HTTP proxy variable/option rather than urllib's proxy behavior.
        proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
        network = ['-http_proxy', proxy] if proxy else []
        result = runner([*options, '-rw_timeout', '15000000', *network, '-i', url,
                         '-t', '4', '-an', '-vf', 'fps=12,scale=480:-2', '-c:v', 'libx264',
                         '-pix_fmt', 'yuv420p', '-preset', 'veryfast', '-crf', '28', '-threads', '1',
                         '-movflags', '+faststart', str(clip)], capture_output=True, timeout=90)
        if result.returncode or not clip.exists():
            raise RuntimeError('Video preview extraction failed')
        result = runner([*options, '-i', str(clip), '-frames:v', '1', '-q:v', '4', str(poster)], capture_output=True, timeout=20)
        if result.returncode or not poster.exists():
            raise RuntimeError('Poster extraction failed')
        if clip.stat().st_size > 2 * 1024 * 1024 or poster.stat().st_size > 200 * 1024:
            raise ValueError('Preview asset exceeds size budget')
        return {'poster': asset(root, poster.read_bytes(), 'jpg'), 'clip': asset(root, clip.read_bytes(), 'mp4')}

def attach_previews(datasets, root, state_dir, warnings, runner=subprocess.run, max_new=50):
    root, state_dir = Path(root), Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    cache_path = state_dir / 'previews.json'
    try:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except (ValueError, OSError):
        cache = {}
    attempted, deferred = 0, 0
    for d in datasets:
        videos = d.get('videos', [])
        if not videos:
            continue
        url = videos[0]['url']
        fingerprint = '' if re.search(r'/resolve/[a-f0-9]{40}/', url) else str(d.get('metadataFingerprint') or d.get('updated') or '')
        key = hashlib.sha256((VERSION + url + fingerprint).encode()).hexdigest()
        preview = cache.get(key)
        if not existing(root, preview):
            if attempted >= max_new:
                deferred += 1
                continue
            attempted += 1
            if not shutil.which('ffmpeg'):
                warnings.append(d['id'] + ': ffmpeg is unavailable; preview assets could not be generated')
                continue
            try:
                preview = generate(url, root, runner)
                cache[key] = preview
            except Exception as exc:
                # Do not expose remote redirect query strings or proxy credentials in reports.
                warnings.append(d['id'] + ': ' + type(exc).__name__ + ' generating preview assets')
                continue
        d['preview'] = preview
    if deferred:
        warnings.append(f'Preview generation deferred for {deferred} datasets; increase --preview-limit or run sync again')
    state_dir.mkdir(parents=True, exist_ok=True)
    temp = cache_path.with_suffix('.tmp')
    temp.write_bytes(encoded(cache))
    temp.replace(cache_path)
