"""Re-fetch the pinned upstream data into a folder and compare it with upstream/MANIFEST.json.

    python tools/fetch_data.py OUT_DIR            # fetch into OUT_DIR/upstream, then compare
    python tools/fetch_data.py OUT_DIR --write    # also write OUT_DIR/upstream/MANIFEST.json

Needs network and git. Never run by tests or the experiment.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = 'https://github.com/AgentPhone-AI/agentphone-mcp.git'
SPEC_URL = 'https://api.agentphone.ai/openapi.json'
REGISTRY = 'https://registry.npmjs.org/zod'
# Each pinned commit: the parent of a known fix, the fix itself, and v0.10.0.
COMMITS = [
    'd3d3209',
    'caece3a',
    '6dc7e97',
    '397ae03',
    '5841776',
    '50639a3',
    'd11dfd4',
    '92f68fb',
    '56c36b3',
    'af4501f',
    '183bafd',
    '1921eba',
    '46c8fe8',
]
IMPORT = re.compile(r"""(?:from|import)\s*["'](\.[^"']+)["']""")


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def git(*args, cwd=None):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True).stdout


def export_commits(out):
    """src/ of every pinned commit, plus the repo's MIT license and each commit's zod version."""
    with tempfile.TemporaryDirectory() as tmp:
        git('clone', '--quiet', REPO, tmp)
        shutil.copy(Path(tmp) / 'LICENSE', out / 'agentphone-mcp' / 'LICENSE')
        rows = []
        for short in COMMITS:
            sha = git('rev-parse', short, cwd=tmp).decode().strip()
            dest = out / 'agentphone-mcp' / short
            dest.mkdir(parents=True)
            with tarfile.open(fileobj=io.BytesIO(git('archive', sha, 'src', cwd=tmp))) as archive:
                archive.extractall(dest, filter='data')
            lock = json.loads(git('show', f'{sha}:package-lock.json', cwd=tmp))
            date, subject = git('log', '-1', '--format=%cs%x00%s', sha, cwd=tmp).decode().strip().split('\0')
            rows.append(
                {
                    'commit': short,
                    'sha': sha,
                    'date': date,
                    'subject': subject,
                    'zod': lock['packages']['node_modules/zod']['version'],
                }
            )
    return rows


def reachable(files, entry):
    """The relative-import closure of entry inside one package's files."""
    seen, todo = set(), [entry]
    while todo:
        name = todo.pop()
        if name in seen or name not in files:
            continue
        seen.add(name)
        base = os.path.dirname(name)
        todo += [os.path.normpath(os.path.join(base, spec)) for spec in IMPORT.findall(files[name].decode())]
    return seen


def export_zod(out, version):
    """The ESM files zod's index.js reaches, its package.json and license, checked against the registry hash."""
    meta = json.loads(fetch(f'{REGISTRY}/{version}'))
    data = fetch(meta['dist']['tarball'])
    algo, digest = meta['dist']['integrity'].split('-', 1)
    if hashlib.new(algo, data).digest() != base64.b64decode(digest):
        raise SystemExit(f'zod {version}: tarball integrity mismatch')
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        files = {
            os.path.normpath(m.name.removeprefix('package/')): archive.extractfile(m).read()
            for m in archive.getmembers()
            if m.isfile()
        }
    keep = reachable(files, 'index.js') | {'package.json', 'LICENSE'}
    for name in sorted(keep):
        dest = out / 'zod' / version / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(files[name])


def manifest(root):
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'MANIFEST.json')
    return {'files': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    out = args.out / 'upstream'
    if out.exists():
        raise SystemExit(f'{out} exists')
    (out / 'agentphone-mcp').mkdir(parents=True)
    rows = export_commits(out)
    (out / 'commits.json').write_text(json.dumps(rows, indent=1) + '\n')
    for version in sorted({r['zod'] for r in rows}):
        export_zod(out, version)
    (out / 'openapi.json').write_bytes(fetch(SPEC_URL))
    fresh = manifest(out)
    pinned_path = Path(__file__).resolve().parents[1] / 'upstream' / 'MANIFEST.json'
    if args.write:
        (out / 'MANIFEST.json').write_text(json.dumps(fresh, indent=1, sort_keys=True) + '\n')
        return
    pinned = json.loads(pinned_path.read_text())['files']
    changed = sorted(k for k in pinned.keys() | fresh['files'].keys() if pinned.get(k) != fresh['files'].get(k))
    print(f'{len(fresh["files"])} files fetched; {len(changed)} differ from the pinned manifest')
    for name in changed:
        print('  differs:', name)
    sys.exit(1 if changed else 0)


if __name__ == '__main__':
    main()
