"""Wide mode on the latest commit: probe every argument a tool can send, and check prompt wrapping."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from specreplay import scan as scanner

ROOT = Path(__file__).resolve().parent
EXTRA = ROOT / 'study' / 'tool-inputs-extra.json'


def merged_inputs(directory):
    """The v1 fixtures plus the extra variants, written to a file the scanner can read."""
    inputs = json.loads(scanner.INPUTS.read_text(encoding='utf-8'))
    for tool, variants in json.loads(EXTRA.read_text(encoding='utf-8'))['tools'].items():
        inputs['tools'][tool] = inputs['tools'].get(tool, []) + variants
    path = Path(directory) / 'inputs.json'
    path.write_text(json.dumps(inputs), encoding='utf-8')
    return path


def run_wide(commit):
    with tempfile.TemporaryDirectory() as directory:
        os.environ['SPECREPLAY_WIDE'] = '1'
        try:
            return scanner.scan(commit, inputs=merged_inputs(directory))
        finally:
            del os.environ['SPECREPLAY_WIDE']


def _probes(report, mode):
    return [probe for probe in report['probes'] if mode is None or probe['mode'] == mode]


def _pairs(probes):
    return {(probe['tool'], probe['variant'], probe['arg']) for probe in probes}


def summarise(v1, wide):
    """What wide mode adds to the v1 scan of the same commit."""
    v1_keys = {tuple(item.values()) for item in v1['findings']}
    added = [item for item in wide['findings'] if tuple(item.values()) not in v1_keys]
    fixture = _probes(wide, 'input')
    discovered = _probes(wide, 'wide')
    return {
        'commit': wide['commit'],
        'v1_probes': len(fixture),
        'wide_probes': len(discovered),
        'v1_args': len(_pairs(fixture)),
        'wide_args': len(_pairs(discovered)),
        'v1_not_enforced': sum(1 for probe in fixture if not probe['enforced']),
        'wide_not_enforced': sum(1 for probe in discovered if not probe['enforced']),
        'added_findings': added,
        'wrapped': [item for item in added if item['outcome'] == 'wrapped_over_limit'],
        'probes': wide['probes'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'results' / 'wide.json')
    args = parser.parse_args(argv)
    commit = scanner.commits()[-1]['commit']
    result = summarise(scanner.scan(commit), run_wide(commit))
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(
        f'{commit}: fixture probes {result["v1_probes"]} on {result["v1_args"]} arguments, '
        f'wide probes {result["wide_probes"]} on {result["wide_args"]} more arguments, '
        f'{len(result["added_findings"])} added findings'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
