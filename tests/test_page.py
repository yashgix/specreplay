"""The committed write-up page is exactly what the generator renders from the committed results."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import build_page


class PageTest(unittest.TestCase):
    def test_page_matches_generator(self):
        self.assertEqual((ROOT / 'docs' / 'index.html').read_text(encoding='utf-8'), build_page.page())


if __name__ == '__main__':
    unittest.main()
