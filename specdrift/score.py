"""Score scanner reports against the pinned spec and the known-bug ledger."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

ANNOTATIONS = frozenset({'title', 'description', 'examples', 'example', 'default'})
METHODS = ('get', 'post', 'put', 'patch', 'delete')
OUTCOMES = (
    'output_invalid',
    'missing_structured',
    'error_result',
    'crash',
    'text_defect',
    'request_limit',
    'undocumented_operation',
    'undocumented_param',
    'undocumented_field',
    'request_invalid',
    'input_not_enforced',
)
FIELDS = ('tool', 'variant', 'operation', 'mutation', 'outcome', 'detail')
LABELS = ('confirmed', 'unconfirmed', 'false_positive', 'untriaged')


def load_ledger(path):
    """The ledger cases, whether the file holds them directly or under a key."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('cases', 'ledger', 'bugs'):
            cases = data.get(key)
            if isinstance(cases, list):
                return cases
        for value in data.values():
            if isinstance(value, list) and value and all(isinstance(item, dict) and 'tool' in item for item in value):
                return value
    raise ValueError(f'no ledger cases in {path}')


def matches(case, finding):
    """Whether one finding is the bug a ledger case describes."""
    if case.get('tool') != finding.get('tool'):
        return False
    variant = case.get('variant')
    if variant is not None and variant != finding.get('variant'):
        return False
    mutation = str(finding.get('mutation', ''))
    if not any(fnmatch.fnmatchcase(mutation, pattern) for pattern in case.get('mutations') or []):
        return False
    if finding.get('outcome') not in (case.get('outcomes') or []):
        return False
    detail = case.get('detail')
    if detail is None:
        return True
    return fnmatch.fnmatchcase(str(finding.get('detail', '')), detail)


def _findings(report):
    if isinstance(report, dict):
        findings = report.get('findings')
        return findings if isinstance(findings, list) else []
    return report if isinstance(report, list) else []


def _found(case, report):
    return any(matches(case, finding) for finding in _findings(report))


def evaluate(case, reports):
    """Whether one case is detected at its buggy commit and clear at its fix."""
    detected = _found(case, reports.get(case['buggy']))
    fixed = case.get('fixed')
    cleared = None if fixed is None else not _found(case, reports.get(fixed))
    return {'id': case['id'], 'detected': detected, 'cleared': cleared, 'caught': detected and cleared is not False}


def _resolve(spec, ref):
    if not isinstance(ref, str) or not ref.startswith('#/'):
        return None
    current = spec
    for raw in ref[2:].split('/'):
        part = raw.replace('~1', '/').replace('~0', '~')
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _deref(spec, schema):
    current = schema
    seen = set()
    while isinstance(current, dict) and isinstance(current.get('$ref'), str):
        ref = current['$ref']
        if ref in seen:
            return {}
        seen.add(ref)
        current = _resolve(spec, ref)
    return current if isinstance(current, dict) else {}


def _success_kind(spec, operation):
    """How a success response is documented: schema, no_content or unconstrained."""
    responses = operation.get('responses')
    if not isinstance(responses, dict):
        return None
    codes = sorted(int(code) for code in responses if len(code) == 3 and code.startswith('2') and code.isdigit())
    if not codes:
        return None
    response = _deref(spec, responses[str(codes[0])])
    content = response.get('content')
    media = content.get('application/json') if isinstance(content, dict) else None
    if not isinstance(media, dict):
        return 'no_content'
    schema = _deref(spec, media.get('schema', {}))
    return 'schema' if any(key not in ANNOTATIONS for key in schema) else 'unconstrained'


def spec_counts(spec):
    """How many operations document a schema, no content or an unconstrained body."""
    counts = {'schema': 0, 'no_content': 0, 'unconstrained': 0}
    paths = spec.get('paths') if isinstance(spec, dict) else None
    for item in (paths or {}).values():
        if not isinstance(item, dict):
            continue
        for method in METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            kind = _success_kind(spec, operation)
            if kind is not None:
                counts[kind] += 1
    return counts


def _key(finding):
    return tuple(finding.get(field) for field in FIELDS)


def triage_counts(new, triage):
    """The new findings tallied by their hand-check label, untriaged included."""
    labels = {_key(row): row.get('label') for row in triage}
    counts = {f'latest_new_{label}': 0 for label in LABELS}
    for finding in new:
        label = labels.get(_key(finding))
        counts[f'latest_new_{label if label in LABELS else "untriaged"}'] += 1
    return counts


def _operation_names(findings):
    names = set()
    for finding in findings:
        for name in str(finding.get('operation', '')).split(','):
            name = name.strip()
            if name[:1].isupper():
                names.add(name)
    return names


def metrics(reports, order, ledger, spec, triage):
    """Every experiment metric, from the reports, the ledger, the spec and the triage."""
    counts = spec_counts(spec)
    evaluated = [evaluate(case, reports) for case in ledger]
    cases = {case['id']: case for case in ledger}
    documented_cases = [case for case in ledger if case.get('spec_documents')]
    caught = [item for item in evaluated if item['caught']]
    caught_documented = sum(1 for item in caught if cases[item['id']].get('spec_documents'))

    per_commit = [reports[commit] for commit in order if commit in reports]
    latest = per_commit[-1] if per_commit else {}
    findings = latest.get('findings', [])
    documented = [finding for finding in findings if finding.get('documented')]
    open_cases = [case for case in ledger if case.get('fixed') is None]
    new = [finding for finding in documented if not any(matches(case, finding) for case in ledger)]

    values = {
        'commits': len(order),
        'runs_total': sum(report.get('runs', 0) for report in per_commit),
        'requests_total': sum(report.get('requests', 0) for report in per_commit),
        'rejected_total': sum(len(report.get('rejected', [])) for report in per_commit),
        'findings_total': sum(len(report.get('findings', [])) for report in per_commit),
        'findings_per_commit': [len(report.get('findings', [])) for report in per_commit],
        'documented_findings_per_commit': [
            sum(1 for finding in report.get('findings', []) if finding.get('documented')) for report in per_commit
        ],
        'spec_operations': sum(counts.values()),
        'spec_operations_schema': counts['schema'],
        'spec_operations_no_content': counts['no_content'],
        'spec_operations_unconstrained': counts['unconstrained'],
        'known_cases': len(ledger),
        'known_cases_documented': len(documented_cases),
        'known_detected': sum(1 for item in evaluated if item['detected']),
        'known_flagged_after_fix': sum(1 for item in evaluated if item['cleared'] is False),
        'known_caught': len(caught),
        'known_caught_documented': caught_documented,
        'known_caught_undocumented': len(caught) - caught_documented,
        'recall': round(len(caught) / len(ledger), 6) if ledger else 0.0,
        'recall_documented': (round(caught_documented / len(documented_cases), 6) if documented_cases else 0.0),
        'latest_tools': len(latest.get('tools', [])),
        'latest_untested_tools': len(latest.get('untested_tools', [])),
        'latest_rejected': len(latest.get('rejected', [])),
        'latest_runs': latest.get('runs', 0),
        'latest_findings': len(findings),
        'latest_findings_documented': len(documented),
        'latest_findings_undocumented': len(findings) - len(documented),
        'latest_findings_known': sum(1 for finding in documented if any(matches(case, finding) for case in open_cases)),
        'latest_new_findings': len(new),
        'latest_new_tools': len({finding.get('tool') for finding in new}),
        'latest_finding_operations': len(_operation_names(findings)),
    }
    values.update(triage_counts(new, triage))
    for outcome in OUTCOMES:
        values[f'latest_{outcome}'] = sum(1 for finding in findings if finding.get('outcome') == outcome)
    return dict(sorted(values.items()))
