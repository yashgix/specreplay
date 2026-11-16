"""Run the TypeScript scanner against one pinned commit of agentphone-mcp."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / 'upstream'
WEB = ROOT / 'web'
SPEC = UPSTREAM / 'openapi.json'
INPUTS = ROOT / 'study' / 'tool-inputs.json'
TIMEOUT = 300


def commits(upstream=UPSTREAM):
    """The pinned commit rows, in history order."""
    return json.loads((Path(upstream) / 'commits.json').read_text(encoding='utf-8'))


def scan_dir(source, zod_entry, spec=SPEC, inputs=INPUTS):
    """Run the scanner on one source folder and return its parsed report."""
    node = os.environ.get('ARCTURUS_NODE')
    if not node:
        raise RuntimeError('ARCTURUS_NODE is not set')
    command = [
        node,
        '--experimental-transform-types',
        '--disable-warning=ExperimentalWarning',
        '--import',
        (WEB / 'hooks.ts').as_uri(),
        str(WEB / 'cli.ts'),
        str(Path(source)),
        str(Path(spec)),
        str(Path(inputs)),
    ]
    env = {
        **os.environ,
        'SPECREPLAY_ZOD': str(Path(zod_entry)),
        'PATH': '/usr/bin:/bin',
    }
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f'scanner timed out after {TIMEOUT} s') from error
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f'scanner exited with {result.returncode}')
    return json.loads(result.stdout)


def scan(commit, spec=SPEC, inputs=INPUTS, upstream=UPSTREAM):
    """Scan one pinned commit, with the zod version its row pins."""
    upstream = Path(upstream)
    row = next((row for row in commits(upstream) if row['commit'] == commit), None)
    if row is None:
        raise ValueError(f'unknown commit: {commit}')
    source = upstream / 'agentphone-mcp' / commit
    zod_entry = upstream / 'zod' / row['zod'] / 'index.js'
    return scan_dir(source, zod_entry, spec, inputs)
