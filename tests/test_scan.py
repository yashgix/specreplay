"""Tests for the Node-backed scanner wrapper."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from specdrift import scan as scanner

NODE = os.environ.get("ARCTURUS_NODE")


class CommitsTest(unittest.TestCase):
    def test_pinned_rows_are_in_history_order(self):
        rows = scanner.commits()
        self.assertEqual(len(rows), 13)
        self.assertEqual(rows[0]["commit"], "d3d3209")
        self.assertEqual(rows[-1]["commit"], "46c8fe8")
        for row in rows:
            self.assertEqual(set(row), {"commit", "sha", "date", "subject", "zod"})
            self.assertEqual(len(row["sha"]), 40)
            self.assertIn(row["zod"], {"4.4.3", "4.6.7"})

    def test_default_inputs_exist(self):
        self.assertTrue(scanner.SPEC.is_file())
        self.assertTrue(scanner.INPUTS.is_file())


class ScanDirTest(unittest.TestCase):
    def test_requires_arcturus_node(self):
        with mock.patch.dict(os.environ, {"ARCTURUS_NODE": ""}):
            with self.assertRaises(RuntimeError) as caught:
                scanner.scan_dir(
                    scanner.UPSTREAM / "agentphone-mcp" / "46c8fe8",
                    scanner.UPSTREAM / "zod" / "4.6.7" / "index.js",
                )
        self.assertEqual(str(caught.exception), "ARCTURUS_NODE is not set")


class ScanTest(unittest.TestCase):
    def test_unknown_commit_raises(self):
        with self.assertRaises(ValueError) as caught:
            scanner.scan("not-a-commit")
        self.assertIn("unknown commit", str(caught.exception))


@unittest.skipUnless(NODE, "ARCTURUS_NODE is not set")
class LatestCommitScanTest(unittest.TestCase):
    def test_report_shape(self):
        report = scanner.scan("46c8fe8")
        self.assertEqual(report["commit"], "46c8fe8")
        self.assertEqual(report["tools"], sorted(report["tools"]))
        self.assertGreaterEqual(len(report["tools"]), 30)
        self.assertIsInstance(report["untested_tools"], list)
        self.assertIsInstance(report["rejected"], list)
        self.assertGreater(report["runs"], 0)
        self.assertGreaterEqual(report["requests"], 0)
        keys = []
        for item in report["findings"]:
            self.assertEqual(
                set(item),
                {"tool", "variant", "operation", "mutation", "outcome", "detail", "documented"},
            )
            self.assertIsInstance(item["documented"], bool)
            keys.append(
                (
                    item["tool"],
                    item["variant"],
                    item["operation"],
                    item["mutation"],
                    item["outcome"],
                    item["detail"],
                )
            )
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
