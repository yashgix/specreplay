"""Score the frozen rules on the hold-out cases, counting a case only when its bug is shown to be exercised."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from specdrift import scan as scanner

ROOT = Path(__file__).resolve().parent
HOLDOUT = ROOT / 'study' / 'holdout.json'
STUB = 'export const OUTPUT_SCHEMAS = {};\n'


def matching(predicate, report):
    """Findings of one report that fit a case's predicate. Wording is never compared."""
    return [
        item
        for item in report['findings']
        if item['tool'] == predicate['tool']
        and ('variant' not in predicate or item['variant'] == predicate['variant'])
        and item['outcome'] in predicate['outcomes']
        and predicate.get('operation_contains', '') in item['operation']
    ]


def refused(case, report):
    variant = case['fixture']['variant']
    return any(item['tool'] == case['tool'] and item['variant'] == variant for item in report['rejected'])


def triggered(case, before, after):
    """Whether the run shows the bug's own behaviour."""
    trigger = case['trigger']
    if trigger['kind'] == 'detected':
        return bool(matching(case['detect'], before))
    at_buggy = refused(case, before)
    at_fixed = refused(case, after)
    return (at_buggy and not at_fixed) if trigger['at'] == 'buggy' else (at_fixed and not at_buggy)


def classify(case, before, after):
    """caught, missed or not_exercised."""
    if not triggered(case, before, after):
        return 'not_exercised'
    caught = bool(matching(case['detect'], before)) and not matching(case['detect'], after)
    return 'caught' if caught else 'missed'


def short(ref, repo):
    out = subprocess.run(
        ['git', '-C', str(repo), 'rev-parse', '--short', ref], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def scan_source(source, case, directory):
    """Scan one old commit with the case's frozen fixture added. Commits without output schemas get an empty table."""
    stub = Path(source) / 'src' / 'output-schemas.ts'
    if not stub.exists():
        stub.write_text(STUB, encoding='utf-8')
    inputs = json.loads(scanner.INPUTS.read_text(encoding='utf-8'))
    if 'fixture' in case:
        inputs['tools'][case['tool']] = [*inputs['tools'].get(case['tool'], []), case['fixture']]
    path = Path(directory) / 'inputs.json'
    path.write_text(json.dumps(inputs), encoding='utf-8')
    return scanner.scan_dir(source, scanner.UPSTREAM / 'zod' / '4.4.3' / 'index.js', inputs=path)


def score_case(case, sources):
    repo = sources / 'repo'
    with tempfile.TemporaryDirectory() as directory:
        before = scan_source(sources / short(case['buggy'], repo), case, directory)
        after = scan_source(sources / short(case['fixed'], repo), case, directory)
    return {
        'id': case['id'],
        'first_run_prediction': case['first_run_prediction'],
        'result': classify(case, before, after),
        'findings_before': len(matching(case['detect'], before)),
        'findings_after': len(matching(case['detect'], after)),
        'refused_at_buggy': refused(case, before) if 'fixture' in case else None,
        'refused_at_fixed': refused(case, after) if 'fixture' in case else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', type=Path, help='folder made by tools/holdout_sources.sh')
    parser.add_argument('--out', type=Path, default=ROOT / 'results' / 'holdout.json')
    args = parser.parse_args(argv)
    cases = json.loads(HOLDOUT.read_text(encoding='utf-8'))['cases']
    scored = [score_case(case, args.sources) for case in cases]
    counts = {
        name: sum(1 for item in scored if item['result'] == name) for name in ('caught', 'missed', 'not_exercised')
    }
    args.out.write_text(
        json.dumps({'cases': len(scored), **counts, 'scored': scored}, indent=1) + '\n', encoding='utf-8'
    )
    print(f'hold-out: {counts}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
