"""Tests for scoring scanner reports against the ledger and the spec."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from specdrift import score


def finding(
    tool,
    mutation,
    outcome,
    detail='',
    *,
    variant='default',
    operation='GET /x',
    documented=True,
):
    return {
        'tool': tool,
        'variant': variant,
        'operation': operation,
        'mutation': mutation,
        'outcome': outcome,
        'detail': detail,
        'documented': documented,
    }


def case(
    case_id,
    tool,
    *,
    mutations,
    outcomes,
    detail=None,
    buggy='bug',
    fixed='fix',
    spec_documents=True,
):
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


class LoadLedgerTest(unittest.TestCase):
    def test_reads_a_bare_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.json'
            path.write_text(json.dumps([{'id': 'x'}]), encoding='utf-8')
            self.assertEqual(score.load_ledger(path), [{'id': 'x'}])

    def test_reads_cases_under_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.json'
            path.write_text(json.dumps({'cases': [{'tool': 't'}]}), encoding='utf-8')
            self.assertEqual(score.load_ledger(path), [{'tool': 't'}])

    def test_raises_without_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.json'
            path.write_text(json.dumps({'about': 'x', 'rows': [{'id': 1}]}), encoding='utf-8')
            with self.assertRaises(ValueError):
                score.load_ledger(path)


class MatchesTest(unittest.TestCase):
    def setUp(self):
        self.case = case(
            'one',
            'list_agents',
            mutations=['input:offset=*'],
            outcomes=['input_not_enforced'],
            detail='offset:*',
        )

    def test_matches_any_variant_with_globs(self):
        item = finding('list_agents', 'input:offset=maximum', 'input_not_enforced', 'offset:maximum')
        self.assertTrue(score.matches(self.case, item))

    def test_rejects_a_different_tool(self):
        item = finding('list_numbers', 'input:offset=maximum', 'input_not_enforced', 'offset:maximum')
        self.assertFalse(score.matches(self.case, item))

    def test_rejects_a_variant_the_case_names(self):
        named = {**self.case, 'variant': 'agent'}
        item = finding('list_agents', 'input:offset=maximum', 'input_not_enforced', 'offset:maximum')
        self.assertFalse(score.matches(named, item))
        self.assertTrue(score.matches(named, {**item, 'variant': 'agent'}))

    def test_rejects_unlisted_mutation_and_outcome(self):
        mutation = finding('list_agents', 'baseline', 'input_not_enforced', 'offset:maximum')
        outcome = finding('list_agents', 'input:offset=maximum', 'crash', 'offset:maximum')
        self.assertFalse(score.matches(self.case, mutation))
        self.assertFalse(score.matches(self.case, outcome))

    def test_null_detail_accepts_any_detail(self):
        loose = {**self.case, 'detail': None}
        item = finding('list_agents', 'input:offset=maximum', 'input_not_enforced', 'anything')
        self.assertTrue(score.matches(loose, item))


class EvaluateTest(unittest.TestCase):
    def _case(self, fixed='fix'):
        return case('c1', 'alpha', mutations=['*'], outcomes=['crash'], buggy='bug', fixed=fixed)

    def test_caught_when_detected_then_cleared(self):
        item = finding('alpha', 'baseline', 'crash', 'boom')
        result = score.evaluate(self._case(), {'bug': [item], 'fix': []})
        self.assertEqual(result, {'id': 'c1', 'detected': True, 'cleared': True, 'caught': True})

    def test_still_flagged_after_fix_is_not_caught(self):
        item = finding('alpha', 'baseline', 'crash', 'boom')
        result = score.evaluate(self._case(), {'bug': [item], 'fix': [item]})
        self.assertEqual(result['cleared'], False)
        self.assertEqual(result['caught'], False)

    def test_open_case_is_caught_on_detection_alone(self):
        item = finding('alpha', 'baseline', 'crash', 'boom')
        result = score.evaluate(self._case(fixed=None), {'bug': [item]})
        self.assertEqual(result, {'id': 'c1', 'detected': True, 'cleared': None, 'caught': True})

    def test_missing_reports_mean_unevaluated(self):
        result = score.evaluate(self._case(), {})
        self.assertEqual(result, {'id': 'c1', 'detected': False, 'cleared': None, 'caught': False, 'unevaluated': True})

    def test_a_missing_fix_report_is_not_a_clean_fix(self):
        item = finding('alpha', 'baseline', 'crash', 'boom')
        result = score.evaluate(self._case(), {'bug': [item]})
        self.assertEqual((result['detected'], result['cleared'], result['caught']), (True, None, False))
        self.assertTrue(result['unevaluated'])


class SpecCountsTest(unittest.TestCase):
    def test_counts_schema_no_content_and_unconstrained(self):
        spec = {
            'components': {
                'responses': {
                    'Ok': {'content': {'application/json': {'schema': {'type': 'string'}}}},
                },
            },
            'paths': {
                '/a': {
                    'get': {
                        'responses': {
                            '200': {'content': {'application/json': {'schema': {'type': 'object'}}}},
                        },
                    },
                    'post': {'responses': {'200': {'description': 'done'}}},
                    'delete': {'responses': {'204': {}}},
                },
                '/b': {
                    'get': {
                        'responses': {
                            '200': {'content': {'application/json': {'schema': {'title': 'Thing'}}}},
                        },
                    },
                    'put': {'responses': {'201': {'$ref': '#/components/responses/Ok'}}},
                },
                '/c': {'patch': {'responses': {'404': {'description': 'missing'}}}},
                '/d': {
                    'head': {
                        'responses': {
                            '200': {'content': {'application/json': {'schema': {'type': 'string'}}}},
                        },
                    },
                },
            },
        }
        self.assertEqual(
            score.spec_counts(spec),
            {'schema': 2, 'no_content': 2, 'unconstrained': 1},
        )


class TriageCountsTest(unittest.TestCase):
    def test_labels_by_exact_tuple_and_counts_untriaged(self):
        rows = [
            finding('a', 'input:x=maximum', 'input_not_enforced', 'x:maximum'),
            finding('b', 'baseline', 'crash', 'boom'),
            finding('c', 'baseline', 'text_defect', 'undefined'),
            finding('d', 'baseline', 'error_result', 'nope'),
        ]
        triage = [
            {**rows[0], 'label': 'confirmed'},
            {**rows[1], 'label': 'false_positive'},
            {**rows[2], 'label': 'unknown'},
        ]
        counts = score.triage_counts(rows, triage)
        self.assertEqual(
            counts,
            {
                'latest_new_confirmed': 1,
                'latest_new_unconfirmed': 0,
                'latest_new_false_positive': 1,
                'latest_new_untriaged': 2,
            },
        )


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
                    'get': {
                        'responses': {
                            '200': {'content': {'application/json': {'schema': {'type': 'object'}}}},
                        },
                    },
                    'post': {'responses': {'200': {'description': 'done'}}},
                    'delete': {'responses': {'204': {}}},
                },
                '/b': {
                    'get': {
                        'responses': {
                            '200': {'content': {'application/json': {'schema': {'title': 'Thing'}}}},
                        },
                    },
                    'put': {'responses': {'201': {'$ref': '#/components/responses/Ok'}}},
                },
            },
        }
        alpha = finding(
            'alpha',
            'input:offset=maximum',
            'input_not_enforced',
            'offset:maximum',
            operation='GET /v1/agents',
        )
        gamma = finding(
            'gamma',
            'input:offset=maximum',
            'input_not_enforced',
            'offset:maximum',
            operation='GET /v1/numbers',
        )
        delta = finding(
            'delta',
            'baseline',
            'text_defect',
            'undefined',
            operation='POST /v1/numbers',
            documented=False,
        )
        self.reports = {
            'c1': {
                'commit': 'c1',
                'tools': ['alpha'],
                'untested_tools': [],
                'rejected': [],
                'runs': 2,
                'requests': 3,
                'findings': [alpha],
            },
            'c2': {
                'commit': 'c2',
                'tools': ['alpha', 'gamma'],
                'untested_tools': ['beta'],
                'rejected': [{'tool': 'beta', 'variant': 'default', 'detail': 'input: x'}],
                'runs': 1,
                'requests': 1,
                'findings': [gamma, delta],
            },
        }
        self.ledger = [
            case(
                'caught',
                'alpha',
                mutations=['input:*'],
                outcomes=['input_not_enforced'],
                buggy='c1',
                fixed='c2',
                spec_documents=True,
            ),
            case(
                'missed',
                'beta',
                mutations=['input:*'],
                outcomes=['crash'],
                buggy='c1',
                fixed='c2',
                spec_documents=True,
            ),
            case(
                'open',
                'alpha',
                mutations=['input:*'],
                outcomes=['input_not_enforced'],
                buggy='c1',
                fixed=None,
                spec_documents=False,
            ),
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
        values = score.metrics(self.reports, ['c1', 'c2'], self.ledger, self.spec, self.triage)
        self.assertEqual(len(values), 46)
        self.assertEqual(list(values), sorted(values))
        expected = {
            'commits': 2,
            'runs_total': 3,
            'requests_total': 4,
            'rejected_total': 1,
            'findings_total': 3,
            'findings_per_commit': [1, 2],
            'documented_findings_per_commit': [1, 1],
            'spec_operations': 5,
            'spec_operations_schema': 2,
            'spec_operations_no_content': 2,
            'spec_operations_unconstrained': 1,
            'known_cases': 3,
            'known_cases_documented': 2,
            'known_detected': 2,
            'known_flagged_after_fix': 0,
            'known_caught': 2,
            'known_caught_documented': 1,
            'known_caught_undocumented': 1,
            'recall': 0.666667,
            'recall_documented': 0.5,
            'latest_tools': 2,
            'latest_untested_tools': 1,
            'latest_rejected': 1,
            'latest_runs': 1,
            'latest_findings': 2,
            'latest_findings_documented': 1,
            'latest_findings_undocumented': 1,
            'latest_findings_known': 0,
            'latest_new_findings': 1,
            'latest_new_tools': 1,
            'latest_finding_operations': 2,
            'latest_new_confirmed': 1,
            'latest_new_unconfirmed': 0,
            'latest_new_false_positive': 0,
            'latest_new_untriaged': 0,
            'latest_input_not_enforced': 1,
            'latest_text_defect': 1,
        }
        for key, value in expected.items():
            self.assertEqual(values[key], value, key)
        for outcome in score.OUTCOMES:
            self.assertIn(f'latest_{outcome}', values)
            if outcome not in ('input_not_enforced', 'text_defect'):
                self.assertEqual(values[f'latest_{outcome}'], 0, outcome)


if __name__ == '__main__':
    unittest.main()
