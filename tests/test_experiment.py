'''Tests for experiment metrics and deterministic result files.'''

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import experiment


def finding(tool, mutation, outcome, detail='', *, variant='default', operation='GET /x', documented=True):
    return {
        'tool': tool,
        'variant': variant,
        'operation': operation,
        'mutation': mutation,
        'outcome': outcome,
        'detail': detail,
        'documented': documented,
    }


def case(case_id, tool, *, mutations, outcomes, detail=None, buggy='c1', fixed='c2', spec_documents=True):
    return {
        'id': case_id,
        'tool': tool,
        'variant': None,
        'mutations': mutations,
        'outcomes': outcomes,
        'detail': detail,
        'buggy': buggy,
        'fixed': fixed,
        'spec_documents': spec_documents,
    }


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.spec = {
            'components': {
                'responses': {
                    'Ok': {'content': {'application/json': {'schema': {'type': 'string'}}}},
                },
            },
            'paths': {
                '/a': {
                    'get': {'responses': {'200': {'content': {'application/json': {'schema': {'type': 'object'}}}}}},
                    'post': {'responses': {'200': {'description': 'done'}}},
                    'delete': {'responses': {'204': {}}},
                },
                '/b': {
                    'get': {'responses': {'200': {'content': {'application/json': {'schema': {'title': 'Thing'}}}}}},
                    'put': {'responses': {'201': {'$ref': '#/components/responses/Ok'}}},
                },
            },
        }
        alpha = finding('alpha', 'input:offset=maximum', 'input_not_enforced', 'offset:maximum', operation='GET /v1/agents')
        gamma = finding('gamma', 'input:offset=maximum', 'input_not_enforced', 'offset:maximum', operation='GET /v1/numbers')
        delta = finding('delta', 'baseline', 'text_defect', 'undefined', operation='POST /v1/numbers', documented=False)
        self.c1 = {
            'commit': 'c1',
            'tools': ['alpha'],
            'untested_tools': [],
            'rejected': [],
            'runs': 2,
            'requests': 3,
            'findings': [alpha],
        }
        self.c2 = {
            'commit': 'c2',
            'tools': ['alpha', 'gamma'],
            'untested_tools': ['beta'],
            'rejected': [{'tool': 'beta', 'variant': 'default', 'detail': 'input: x'}],
            'runs': 1,
            'requests': 1,
            'findings': [gamma, delta],
        }
        self.reports = [self.c1, self.c2]
        self.by_commit = {'c1': self.c1, 'c2': self.c2}
        self.order = ['c1', 'c2']
        self.ledger = [
            case('caught', 'alpha', mutations=['input:*'], outcomes=['input_not_enforced'], buggy='c1', fixed='c2', spec_documents=True),
            case('missed', 'beta', mutations=['input:*'], outcomes=['crash'], buggy='c1', fixed='c2', spec_documents=True),
            case('open', 'alpha', mutations=['input:*'], outcomes=['input_not_enforced'], buggy='c1', fixed=None, spec_documents=False),
        ]
        self.triage = [
            {
                'tool': 'gamma',
                'variant': 'default',
                'operation': 'GET /v1/numbers',
                'mutation': 'input:offset=maximum',
                'outcome': 'input_not_enforced',
                'detail': 'offset:maximum',
                'label': 'confirmed',
            },
        ]

    def test_metrics_are_complete_and_scored(self):
        values = experiment.metrics_for(self.reports, self.order, spec=self.spec, ledger=self.ledger, triage=self.triage)
        self.assertEqual(len(values), 46)
        self.assertEqual(list(values), sorted(values))
        self.assertEqual(values['commits'], 2)
        self.assertEqual(values['spec_operations'], 5)
        self.assertEqual(values['spec_operations_schema'], 2)
        self.assertEqual(values['spec_operations_no_content'], 2)
        self.assertEqual(values['spec_operations_unconstrained'], 1)
        self.assertEqual(values['known_cases'], 3)
        self.assertEqual(values['known_cases_documented'], 2)
        self.assertEqual(values['known_caught'], 2)
        self.assertEqual(values['latest_new_findings'], 1)
        self.assertEqual(values['latest_new_confirmed'], 1)
        self.assertEqual(values['recall'], 0.666667)
        self.assertEqual(values['recall_documented'], 0.5)


class CollectTest(unittest.TestCase):
    def test_collect_scans_in_commit_order(self):
        reports = {
            'c1': {'commit': 'c1', 'findings': []},
            'c2': {'commit': 'c2', 'findings': []},
        }
        rows = [{'commit': 'c1'}, {'commit': 'c2'}]
        with mock.patch.object(experiment.scanner, 'commits', return_value=rows), mock.patch.object(
            experiment.scanner, 'scan', side_effect=lambda commit: reports[commit]
        ) as scan:
            order, collected = experiment.collect()
        self.assertEqual(order, ['c1', 'c2'])
        self.assertEqual(collected, [reports['c1'], reports['c2']])
        self.assertEqual(scan.call_count, 2)


class WriteResultsTest(unittest.TestCase):
    def test_writes_sorted_json_with_trailing_newline(self):
        reports = [{'commit': 'c1', 'findings': []}]
        metrics = {'b': 2, 'a': 1}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'results' / 'metrics.json'
            experiment.write_results(out, reports, metrics)
            reports_path = out.parent / 'reports.json'
            expected_reports = json.dumps(reports, indent=1, sort_keys=True) + chr(10)
            expected_metrics = json.dumps(metrics, indent=1, sort_keys=True) + chr(10)
            self.assertEqual(reports_path.read_text(encoding='utf-8'), expected_reports)
            self.assertEqual(out.read_text(encoding='utf-8'), expected_metrics)
            self.assertEqual(json.loads(reports_path.read_text(encoding='utf-8')), reports)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8')), metrics)


class MainTest(unittest.TestCase):
    def test_main_writes_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'results' / 'metrics.json'
            with mock.patch.object(experiment, 'collect', return_value=(['c1'], [{'commit': 'c1'}])), mock.patch.object(
                experiment, 'metrics_for', return_value={'commits': 1}
            ):
                self.assertEqual(experiment.main(['--out', str(out)]), 0)
            self.assertTrue((out.parent / 'reports.json').is_file())
            self.assertEqual(json.loads(out.read_text(encoding='utf-8')), {'commits': 1})


if __name__ == '__main__':
    unittest.main()
