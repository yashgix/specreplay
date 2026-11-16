"""Tests for the Node-backed scanner wrapper."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specreplay import scan as scanner

NODE = os.environ.get('ARCTURUS_NODE')

SYNTHETIC_TOOLS = """
export function registerTools(server, api) {
  server.tool('defects', 'text defects', {}, () => ({
    content: [{ type: 'text', text: 'undefined NaN [object Object] undefined' }],
  }));
  server.tool('schema', 'output schema', {}, () => ({
    content: [{ type: 'text', text: 'ok' }],
    structuredContent: { x: 'abc', y: 'abc' },
  }));
}
"""

SYNTHETIC_API = 'export class AgentPhoneAPI { constructor(baseUrl, apiKey) {} }\n'

SYNTHETIC_SCHEMAS = """
import { z } from 'zod';

export const OUTPUT_SCHEMAS = {
  schema: z.object({
    x: z.string().min(5).max(1),
    y: z.string().min(5),
  }),
};
"""


class CommitsTest(unittest.TestCase):
    def test_pinned_rows_are_in_history_order(self):
        rows = scanner.commits()
        self.assertEqual(len(rows), 13)
        self.assertEqual(rows[0]['commit'], 'd3d3209')
        self.assertEqual(rows[-1]['commit'], '46c8fe8')
        for row in rows:
            self.assertEqual(set(row), {'commit', 'sha', 'date', 'subject', 'zod'})
            self.assertEqual(len(row['sha']), 40)
            self.assertIn(row['zod'], {'4.4.3', '4.6.7'})

    def test_default_inputs_exist(self):
        self.assertTrue(scanner.SPEC.is_file())
        self.assertTrue(scanner.INPUTS.is_file())


class ScanDirTest(unittest.TestCase):
    def test_requires_arcturus_node(self):
        with mock.patch.dict(os.environ, {'ARCTURUS_NODE': ''}), self.assertRaises(RuntimeError) as caught:
            scanner.scan_dir(
                scanner.UPSTREAM / 'agentphone-mcp' / '46c8fe8',
                scanner.UPSTREAM / 'zod' / '4.6.7' / 'index.js',
            )
        self.assertEqual(str(caught.exception), 'ARCTURUS_NODE is not set')


class ScanTest(unittest.TestCase):
    def test_unknown_commit_raises(self):
        with self.assertRaises(ValueError) as caught:
            scanner.scan('not-a-commit')
        self.assertIn('unknown commit', str(caught.exception))


@unittest.skipUnless(NODE, 'ARCTURUS_NODE is not set')
class LatestCommitScanTest(unittest.TestCase):
    def test_report_shape(self):
        report = scanner.scan('46c8fe8')
        self.assertEqual(report['commit'], '46c8fe8')
        self.assertEqual(report['tools'], sorted(report['tools']))
        self.assertGreaterEqual(len(report['tools']), 30)
        self.assertIsInstance(report['untested_tools'], list)
        self.assertIsInstance(report['rejected'], list)
        self.assertGreater(report['runs'], 0)
        self.assertGreaterEqual(report['requests'], 0)
        keys = []
        for item in report['findings']:
            self.assertEqual(
                set(item),
                {'tool', 'variant', 'operation', 'mutation', 'outcome', 'detail', 'documented'},
            )
            self.assertIsInstance(item['documented'], bool)
            keys.append(
                (
                    item['tool'],
                    item['variant'],
                    item['operation'],
                    item['mutation'],
                    item['outcome'],
                    item['detail'],
                )
            )
        self.assertEqual(len(keys), len(set(keys)))


@unittest.skipUnless(NODE, 'ARCTURUS_NODE is not set')
class SyntheticScanTest(unittest.TestCase):
    def test_text_defects_and_sorted_output_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / 'src'
            src.mkdir()
            (src / 'tools.ts').write_text(SYNTHETIC_TOOLS, encoding='utf-8')
            (src / 'api.ts').write_text(SYNTHETIC_API, encoding='utf-8')
            (src / 'output-schemas.ts').write_text(SYNTHETIC_SCHEMAS, encoding='utf-8')
            spec = root / 'openapi.json'
            spec.write_text('{"paths": {}}', encoding='utf-8')
            inputs = root / 'inputs.json'
            inputs.write_text(
                json.dumps(
                    {
                        'tools': {
                            'defects': [{'variant': 'default', 'args': {}}],
                            'schema': [{'variant': 'default', 'args': {}}],
                        }
                    }
                ),
                encoding='utf-8',
            )
            report = scanner.scan_dir(
                root,
                scanner.UPSTREAM / 'zod' / '4.6.7' / 'index.js',
                spec,
                inputs,
            )
        by_tool = {}
        for item in report['findings']:
            by_tool.setdefault(item['tool'], []).append((item['mutation'], item['outcome'], item['detail']))
        self.assertEqual(
            by_tool['defects'],
            [('baseline', 'text_defect', 'NaN;[object Object];undefined')],
        )
        self.assertEqual(by_tool['schema'], [('baseline', 'output_invalid', 'x;y')])


if __name__ == '__main__':
    unittest.main()
