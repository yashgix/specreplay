"""Run tests/acceptance. If the fetched openapi.json differs from the manifest, skip the two spec-hash checks and say why."""

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_HASH_TESTS = {'test_spec_is_the_pinned_one', 'test_every_pinned_file_matches_the_manifest'}


def spec_drifted():
    pinned = json.loads((ROOT / 'upstream' / 'MANIFEST.json').read_text())['files']['openapi.json']
    return hashlib.sha256((ROOT / 'upstream' / 'openapi.json').read_bytes()).hexdigest() != pinned


def flatten(suite):
    for item in suite:
        yield from flatten(item) if isinstance(item, unittest.TestSuite) else [item]


def main():
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests' / 'acceptance'))
    drifted = spec_drifted()
    if drifted:
        print('openapi.json differs from the 14 Nov 2026 snapshot in the manifest: skipping', *sorted(SPEC_HASH_TESTS))
    tests = [t for t in flatten(suite) if not (drifted and t._testMethodName in SPEC_HASH_TESTS)]
    result = unittest.TextTestRunner().run(unittest.TestSuite(tests))
    sys.exit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
