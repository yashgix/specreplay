"""Tests that run the TypeScript spec helpers under Node."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = os.environ.get('ARCTURUS_NODE')
TESTS = sorted((ROOT / 'web').glob('*.test.cjs'))
TIMEOUT = 120


@unittest.skipUnless(NODE, 'ARCTURUS_NODE is not set')
class OpenAPINodeTest(unittest.TestCase):
    def test_node_suite_passes(self):
        command = [
            NODE,
            '--experimental-transform-types',
            '--disable-warning=ExperimentalWarning',
            '--test',
            *map(str, TESTS),
        ]
        env = {**os.environ, 'PATH': '/usr/bin:/bin'}
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        self.assertEqual(result.returncode, 0, output)


if __name__ == '__main__':
    unittest.main()
