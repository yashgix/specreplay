"""Tests for wide mode: extra arguments are probed and the prompt wrapper is measured."""

from __future__ import annotations

import os
import unittest

import wide
from specdrift import scan as scanner

NODE = os.environ.get('ARCTURUS_NODE')


@unittest.skipUnless(NODE, 'ARCTURUS_NODE is not set')
class WideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        commit = scanner.commits()[-1]['commit']
        cls.summary = wide.summarise(scanner.scan(commit), wide.run_wide(commit))

    def test_wide_mode_keeps_every_v1_finding(self):
        self.assertEqual(self.summary['v1_not_enforced'], 11)

    def test_arguments_the_fixture_leaves_out_are_probed(self):
        added = {(item['tool'], item['variant'], item['detail']) for item in self.summary['added_findings']}
        self.assertIn(('list_calls', 'default', 'offset:maximum'), added)
        self.assertIn(('list_calls', 'number', 'offset:maximum'), added)

    def test_wrapper_adds_a_fixed_length(self):
        details = {item['detail'] for item in self.summary['wrapped']}
        self.assertEqual(details, {'systemPrompt:maxLength added=528 threshold=19472'})


if __name__ == '__main__':
    unittest.main()
