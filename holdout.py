"""Score the frozen rules on the hold-out cases: a case is caught when a finding on its tool at the buggy commit is gone at the fix."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from specdrift import scan as scanner

ROOT = Path(__file__).resolve().parent
HOLDOUT = ROOT / 'study' / 'holdout.json'
STUB = 'export const OUTPUT_SCHEMAS = {};\n'


def short(ref, repo):
    out = subprocess.run(
        ['git', '-C', str(repo), 'rev-parse', '--short', ref], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def findings_for(source, tool):
    """Findings on one tool, as comparable tuples. Old commits without output schemas get an empty table."""
    stub = Path(source) / 'src' / 'output-schemas.ts'
    if not stub.exists():
        stub.write_text(STUB, encoding='utf-8')
    zod = scanner.UPSTREAM / 'zod' / '4.4.3' / 'index.js'
    report = scanner.scan_dir(source, zod)
    return {tuple(item.values()) for item in report['findings'] if item['tool'] == tool}, report['rejected']


def score_case(case, sources):
    repo = sources / 'repo'
    before, rejected = findings_for(sources / short(case['buggy'], repo), case['tool'])
    after, _ = findings_for(sources / short(case['fixed'], repo), case['tool'])
    gone = sorted(before - after)
    return {
        'id': case['id'],
        'predicted': case['predicted'],
        'result': 'caught' if gone else 'missed',
        'findings_before': len(before),
        'findings_after': len(after),
        'gone_at_fix': [list(item) for item in gone],
        'rejected_at_buggy': [item for item in rejected if item['tool'] == case['tool']],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', type=Path, help='folder made by tools/holdout_sources.sh')
    parser.add_argument('--out', type=Path, default=ROOT / 'results' / 'holdout.json')
    args = parser.parse_args(argv)
    cases = json.loads(HOLDOUT.read_text(encoding='utf-8'))['cases']
    scored = [score_case(case, args.sources) for case in cases]
    caught = sum(1 for item in scored if item['result'] == 'caught')
    summary = {'cases': len(scored), 'caught': caught, 'recall': round(caught / len(scored), 2), 'scored': scored}
    args.out.write_text(json.dumps(summary, indent=1) + '\n', encoding='utf-8')
    print(f'hold-out recall {caught}/{len(scored)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
