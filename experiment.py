"""Run the pinned-commit replay experiment and write its reports and metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import specreplay.scan as scanner
from specreplay import score

ROOT = Path(__file__).resolve().parent
TRIAGE = ROOT / 'study' / 'triage.json'
LEDGER = ROOT / 'study' / 'known-bugs.json'


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_triage(path=TRIAGE):
    data = load_json(path)
    rows = data.get('findings') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f'no triage findings in {path}')
    return rows


def collect(order=None):
    rows = scanner.commits()
    commits = [row['commit'] for row in rows] if order is None else list(order)
    reports = [scanner.scan(commit) for commit in commits]
    return commits, reports


def metrics_for(reports, order, spec=None, ledger=None, triage=None):
    spec = load_json(scanner.SPEC) if spec is None else spec
    ledger = score.load_ledger(LEDGER) if ledger is None else ledger
    triage = load_triage() if triage is None else triage
    keyed = {report['commit']: report for report in reports}
    return score.metrics(keyed, order, ledger, spec, triage)


def write_results(out, reports, metrics):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    reports_path = out.parent / 'reports.json'
    reports_path.write_text(json.dumps(reports, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    out.write_text(json.dumps(metrics, indent=1, sort_keys=True) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='metrics JSON path')
    args = parser.parse_args(argv)
    try:
        order, reports = collect()
        metrics = metrics_for(reports, order)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    write_results(args.out, reports, metrics)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
