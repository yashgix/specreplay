"""Tests for the hold-out case file and how a case is classified."""

from __future__ import annotations

import json
import unittest

import holdout

CASES = {case['id']: case for case in json.loads(holdout.HOLDOUT.read_text(encoding='utf-8'))['cases']}
USAGE = CASES['holdout-usage-plan']
MEDIA = CASES['holdout-media-only-send']


def finding(detail, outcome='error_result', operation='GET /v1/agents,GET /v1/usage', tool='account_overview'):
    return {
        'tool': tool,
        'variant': 'default',
        'operation': operation,
        'mutation': 'baseline',
        'outcome': outcome,
        'detail': detail,
    }


def report(*findings, rejected=()):
    return {'findings': list(findings), 'rejected': list(rejected)}


class ClassifyTest(unittest.TestCase):
    def test_the_bug_gone_at_the_fix_is_caught(self):
        self.assertEqual(holdout.classify(USAGE, report(finding('old error')), report()), 'caught')

    def test_a_persistent_failure_with_changed_wording_stays_missed(self):
        before = report(finding('old error'))
        after = report(finding('new error'))
        self.assertEqual(holdout.classify(USAGE, before, after), 'missed')

    def test_an_unrelated_finding_that_disappears_earns_nothing(self):
        other = finding('x', operation='GET /v1/numbers')
        self.assertEqual(holdout.classify(USAGE, report(other), report()), 'not_exercised')

    def test_a_trigger_that_never_fires_is_not_exercised(self):
        self.assertEqual(holdout.classify(MEDIA, report(), report()), 'not_exercised')

    def test_a_triggered_case_without_a_finding_is_missed(self):
        refusal = {'tool': 'send_message', 'variant': 'media_only', 'detail': 'input: body'}
        self.assertEqual(holdout.classify(MEDIA, report(rejected=[refusal]), report()), 'missed')


class CaseFileTest(unittest.TestCase):
    def test_every_case_has_a_source_a_predicate_and_a_trigger(self):
        for case in CASES.values():
            self.assertTrue(case['source'].startswith('https://github.com/'))
            self.assertIn('outcomes', case['detect'])
            self.assertIn('kind', case['trigger'])

    def test_hold_out_cases_are_not_in_the_ledger(self):
        ledger = json.loads((holdout.ROOT / 'study' / 'known-bugs.json').read_text(encoding='utf-8'))['cases']
        self.assertTrue(CASES.keys().isdisjoint({case['id'] for case in ledger}))


if __name__ == '__main__':
    unittest.main()
