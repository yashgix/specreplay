'''Tests for the demo renderer and its command line.'''

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import demo

METRICS = {
    'commits': 13,
    'runs_total': 109,
    'known_cases': 25,
    'known_cases_documented': 20,
    'known_caught': 20,
    'known_caught_documented': 19,
    'spec_operations_unconstrained': 36,
    'latest_new_findings': 10,
    'latest_new_confirmed': 9,
    'latest_new_false_positive': 0,
    'recall': 0.8,
    'recall_documented': 0.95,
}


class RenderTest(unittest.TestCase):
    def test_replaces_one_block_and_keeps_markers(self):
        text = 'intro' + chr(10) + demo.START + chr(10) + 'old' + chr(10) + demo.END + chr(10) + 'outro' + chr(10)
        rendered = demo.render(text, METRICS)
        self.assertEqual(rendered.count(demo.START), 1)
        self.assertEqual(rendered.count(demo.END), 1)
        self.assertTrue(rendered.startswith('intro' + chr(10) + demo.START + chr(10)))
        self.assertIn('| commits | 13 |', rendered)
        self.assertIn('| caught documented | 19 |', rendered)
        self.assertIn('Recall: 20/25 (0.80) overall; 19/20 (0.95) on documented contracts.', rendered)
        self.assertTrue(rendered.endswith(chr(10) + demo.END + chr(10) + 'outro' + chr(10)))

    def test_render_rejects_missing_marker(self):
        with self.assertRaises(ValueError):
            demo.render(demo.START + chr(10), METRICS)

    def test_render_rejects_duplicate_marker(self):
        text = demo.START + chr(10) + demo.START + chr(10) + demo.END + chr(10)
        with self.assertRaises(ValueError):
            demo.render(text, METRICS)

    def test_render_rejects_reversed_markers(self):
        text = demo.END + chr(10) + demo.START + chr(10)
        with self.assertRaises(ValueError):
            demo.render(text, METRICS)


class MainTest(unittest.TestCase):
    def test_main_writes_rendered_readme(self):
        readme = 'before' + chr(10) + demo.START + chr(10) + demo.END + chr(10) + 'after' + chr(10)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics_path = root / 'metrics.json'
            metrics_path.write_text(json.dumps(METRICS), encoding='utf-8')
            readme_path = root / 'README.md'
            readme_path.write_text(readme, encoding='utf-8')
            out_path = root / 'out' / 'README.md'
            with mock.patch.object(demo, 'METRICS', metrics_path):
                self.assertEqual(demo.main(['--readme', str(readme_path), '--out', str(out_path)]), 0)
            self.assertEqual(out_path.read_text(encoding='utf-8'), demo.render(readme, METRICS))


if __name__ == '__main__':
    unittest.main()
