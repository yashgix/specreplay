"""Show the latest SpecDrift findings and regenerate the README results block."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import specdrift.scan as scanner

ROOT = Path(__file__).resolve().parent
METRICS = ROOT / 'results' / 'metrics.json'
TRIAGE = ROOT / 'study' / 'triage.json'
WIDE = ROOT / 'results' / 'wide.json'
HOLDOUT = ROOT / 'results' / 'holdout.json'
WIDE_START = '<!-- specdrift:wide -->'
WIDE_END = '<!-- /specdrift:wide -->'
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
    ('findings not in the ledger', 'latest_new_findings'),
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
        f'{caught_documented}/{documented_cases} ({recall_documented:.2f}) on documented contracts. '
        'In-sample: the rules were written knowing these cases.'
    )


def _causes_table(root_causes):
    lines = ['', '| root cause | kind | findings | code sites (src/tools.ts at v0.10.0) |', '| --- | --- | --- | --- |']
    for cause in root_causes:
        status = 'known, open upstream' if cause['known'] else cause['kind'].replace('_', ' ')
        sites = '; '.join(cause['sites'])
        lines.append(f'| {cause["title"]} | {status} | {cause["findings"]} | {sites} |')
    return lines


def render(readme_text, metrics, root_causes=()):
    if readme_text.count(START) != 1 or readme_text.count(END) != 1:
        raise ValueError('README needs exactly one SpecDrift results block')
    start = readme_text.index(START)
    end = readme_text.index(END)
    if end < start:
        raise ValueError('SpecDrift results markers are out of order')
    lines = ['| name | value |', '| --- | --- |']
    for label, key in ROWS:
        lines.append(f'| {label} | {_plain(metrics, key)} |')
    unknown = [cause for cause in root_causes if not cause['known']]
    if root_causes:
        lines.append(f'| root causes behind them | {len(unknown)} |')
    lines += ['', _recall_line(metrics)]
    if root_causes:
        lines += _causes_table(root_causes)
    body = '\n'.join(lines)
    return readme_text[:start] + f'{START}\n{body}\n{END}' + readme_text[end + len(END) :]


def render_extra(readme_text, wide, holdout):
    """Fill the wide-mode and hold-out block from results/wide.json and results/holdout.json."""
    start = readme_text.index(WIDE_START)
    end = readme_text.index(WIDE_END)
    wrapped = wide['wrapped'][0]['detail'] if wide['wrapped'] else ''
    added = len(wide['added_findings']) - len(wide['wrapped'])
    lines = [
        '| name | value |',
        '| --- | --- |',
        f'| arguments probed from the fixtures | {wide["v1_args"]} ({wide["v1_probes"]} probes) |',
        f'| further arguments probed in wide mode | {wide["wide_args"]} ({wide["wide_probes"]} probes) |',
        f'| findings added by wide mode (not counting the prompt check) | {added} |',
        f'| prompt wrapper | {wrapped} |',
        f'| hold-out cases | {holdout["cases"]} |',
        f'| hold-out caught | {holdout["caught"]} |',
    ]
    body = '\n'.join(lines)
    return readme_text[:start] + f'{WIDE_START}\n{body}\n{WIDE_END}' + readme_text[end + len(WIDE_END) :]


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


def root_causes():
    triage = json.loads(TRIAGE.read_text(encoding='utf-8'))
    counts = Counter(row['root_cause'] for row in triage['findings'])
    return [{**cause, 'findings': counts[cause['id']]} for cause in triage['root_causes']]


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
        text = render(text, metrics, root_causes())
        if WIDE_START in text:
            text = render_extra(text, json.loads(WIDE.read_text()), json.loads(HOLDOUT.read_text()))
        args.out.write_text(text, encoding='utf-8')
        return 0
    try:
        report = latest_report()
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    show(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
