"""Show the latest SpecDrift findings and regenerate the README results block."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import specdrift.scan as scanner

ROOT = Path(__file__).resolve().parent
METRICS = ROOT / 'results' / 'metrics.json'
START = '<!-- specdrift:results -->'
END = '<!-- /specdrift:results -->'
ROWS = (
    ('commits', 'commits'),
    ('runs', 'runs_total'),
    ('known cases', 'known_cases'),
    ('documented cases', 'known_cases_documented'),
    ('caught', 'known_caught'),
    ('caught documented', 'known_caught_documented'),
    ('unconstrained operations', 'spec_operations_unconstrained'),
    ('new findings', 'latest_new_findings'),
    ('confirmed', 'latest_new_confirmed'),
    ('false positives', 'latest_new_false_positive'),
)


def _number(metrics, key):
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'metric {key} is not a number')
    return value


def _plain(metrics, key):
    value = _number(metrics, key)
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _recall_line(metrics):
    caught = _plain(metrics, 'known_caught')
    cases = _plain(metrics, 'known_cases')
    caught_documented = _plain(metrics, 'known_caught_documented')
    documented_cases = _plain(metrics, 'known_cases_documented')
    recall = float(_number(metrics, 'recall'))
    recall_documented = float(_number(metrics, 'recall_documented'))
    return (
        f'Recall: {caught}/{cases} ({recall:.2f}) overall; '
        f'{caught_documented}/{documented_cases} ({recall_documented:.2f}) on documented contracts.'
    )


def render(readme_text, metrics):
    if readme_text.count(START) != 1 or readme_text.count(END) != 1:
        raise ValueError('README needs exactly one SpecDrift results block')
    start = readme_text.index(START)
    end = readme_text.index(END)
    if end < start:
        raise ValueError('SpecDrift results markers are out of order')
    lines = ['| name | value |', '| --- | --- |']
    for label, key in ROWS:
        lines.append(f'| {label} | {_plain(metrics, key)} |')
    body = '\n'.join(lines + ['', _recall_line(metrics)])
    return readme_text[:start] + f'{START}\n{body}\n{END}' + readme_text[end + len(END) :]


def show(report):
    findings = report.get('findings', [])
    documented = [item for item in findings if item.get('documented')]
    commit = report.get('commit', '?')
    tools = len(report.get('tools', []))
    runs = report.get('runs', 0)
    requests = report.get('requests', 0)
    print(f'{commit}: {tools} tools, {runs} calls, {requests} requests, {len(documented)} documented findings')
    for item in documented:
        print(item['tool'], item['outcome'], item['mutation'], item['detail'])


def latest_report():
    commit = scanner.commits()[-1]['commit']
    return scanner.scan(commit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--readme', type=Path, help='README to update')
    parser.add_argument('--out', type=Path, help='where to write the updated README')
    args = parser.parse_args(argv)
    if (args.readme is None) != (args.out is None):
        parser.error('--readme and --out must be used together')
    if args.readme is not None and args.out is not None:
        metrics = json.loads(METRICS.read_text(encoding='utf-8'))
        text = args.readme.read_text(encoding='utf-8')
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render(text, metrics), encoding='utf-8')
        return 0
    try:
        report = latest_report()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    show(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
