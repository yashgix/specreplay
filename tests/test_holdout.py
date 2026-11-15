"""Tests for the hold-out case file and its scorer."""

from __future__ import annotations

import json
import unittest

import holdout


class HoldoutTest(unittest.TestCase):
    def test_cases_carry_a_prediction_and_a_source(self):
        data = json.loads(holdout.HOLDOUT.read_text(encoding='utf-8'))
        self.assertEqual(data['frozen_tag'], 'rules-frozen')
        for case in data['cases']:
            self.assertIn(case['predicted'], ('caught', 'missed'))
            self.assertTrue(case['source'].startswith('https://github.com/'))

    def test_hold_out_cases_are_not_in_the_ledger(self):
        ledger = json.loads((holdout.ROOT / 'study' / 'known-bugs.json').read_text(encoding='utf-8'))['cases']
        known = {case['source'] for case in ledger}
        cases = json.loads(holdout.HOLDOUT.read_text(encoding='utf-8'))['cases']
        self.assertTrue(all(case['source'] not in known for case in cases))


if __name__ == '__main__':
    unittest.main()
