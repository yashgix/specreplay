"""SpecDrift on the pinned agentphone-mcp history and the pinned AgentPhone OpenAPI spec."""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import specdrift
from specdrift import score
from specdrift.scan import commits, scan

ROOT = Path(specdrift.__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream"
ORDER = ["d3d3209", "caece3a", "6dc7e97", "397ae03", "5841776", "50639a3", "d11dfd4", "92f68fb", "56c36b3", "af4501f",
         "183bafd", "1921eba", "46c8fe8"]
SPEC_SHA = "498274d9db6a9798c6ea76b5245c65d531c9115afdbc2f1a51a87133e437b97b"
OUTCOMES = ("output_invalid", "missing_structured", "error_result", "crash", "text_defect", "request_limit",
            "undocumented_operation", "undocumented_param", "undocumented_field", "request_invalid",
            "input_not_enforced")
METRICS = sorted([
    "commits", "documented_findings_per_commit", "findings_per_commit", "findings_total", "known_cases",
    "known_cases_documented", "known_caught", "known_caught_documented", "known_caught_undocumented",
    "known_detected", "known_flagged_after_fix", "latest_finding_operations", "latest_findings",
    "latest_findings_documented", "latest_findings_known", "latest_findings_undocumented", "latest_new_confirmed",
    "latest_new_false_positive", "latest_new_findings", "latest_new_tools", "latest_new_unconfirmed",
    "latest_new_untriaged", "latest_rejected", "latest_runs", "latest_tools", "latest_untested_tools", "recall",
    "recall_documented", "rejected_total", "requests_total", "runs_total", "spec_operations",
    "spec_operations_no_content", "spec_operations_schema", "spec_operations_unconstrained",
    *(f"latest_{o}" for o in OUTCOMES),
])
VALUES = {
    "commits": 13, "known_cases": 25, "known_cases_documented": 20, "known_detected": 22, "known_caught": 20,
    "known_caught_documented": 19, "known_caught_undocumented": 1, "known_flagged_after_fix": 2, "recall": 0.8,
    "recall_documented": 0.95, "spec_operations": 98, "spec_operations_schema": 59, "spec_operations_no_content": 3,
    "spec_operations_unconstrained": 36, "latest_tools": 32, "latest_untested_tools": 0, "latest_rejected": 1,
    "latest_findings": 22, "latest_findings_documented": 12, "latest_findings_undocumented": 10,
    "latest_findings_known": 2, "latest_new_findings": 10, "latest_new_tools": 9, "latest_new_confirmed": 9,
    "latest_new_unconfirmed": 1, "latest_new_false_positive": 0, "latest_new_untriaged": 0,
    "latest_input_not_enforced": 11, "latest_output_invalid": 5, "latest_error_result": 2, "latest_text_defect": 4,
    "latest_crash": 0, "latest_finding_operations": 16, "rejected_total": 7,
}
CAUGHT = {
    "detach-empty-body": True, "contact-delete-empty-body": False, "get-agent-null-numbers": True,
    "list-agents-null-numbers": True, "create-agent-null-numbers": True, "overview-null-numbers": True,
    "update-agent-null-numbers": True, "list-calls-null-phone-number-id": True,
    "get-call-null-phone-number-id": False, "project-deliveries-shape": True, "agent-deliveries-shape": True,
    "agent-deliveries-hours": True, "voices-null-gender-accent": False, "message-sender-from_": True,
    "project-test-webhook-shape": False, "agent-test-webhook-shape": False, "list-agents-limit-bound": True,
    "create-agent-voice-speed-bound": True, "usage-days-bound": True, "messages-limit-bound": True,
    "deliveries-limit-bound": True, "get-call-timeout-param": True, "conversation-call-wait-fields": True,
    "create-agent-language-enum": True, "update-agent-language-enum": True,
}
LATEST_DOCUMENTED = sorted([
    ("create_agent", "default", "input:language=enum", "input_not_enforced", "language:enum"),
    ("create_agent", "default", "input:system_prompt=maxLength", "input_not_enforced", "systemPrompt:maxLength"),
    ("list_agents", "default", "input:offset=maximum", "input_not_enforced", "offset:maximum"),
    ("list_calls", "agent", "input:offset=maximum", "input_not_enforced", "offset:maximum"),
    ("list_contacts", "default", "input:offset=maximum", "input_not_enforced", "offset:maximum"),
    ("list_conversations", "agent", "input:offset=maximum", "input_not_enforced", "offset:maximum"),
    ("list_conversations", "default", "input:offset=maximum", "input_not_enforced", "offset:maximum"),
    ("list_numbers", "default", "input:offset=maximum", "input_not_enforced", "offset:maximum"),
    ("list_webhook_deliveries", "project", "input:hours=maximum", "input_not_enforced", "hours:maximum"),
    ("update_agent", "default", "input:language=enum", "input_not_enforced", "language:enum"),
    ("update_agent", "default", "input:system_prompt=maxLength", "input_not_enforced", "systemPrompt:maxLength"),
    ("update_conversation", "default", "omit:$.metadata", "text_defect", "undefined"),
])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keys(findings, *, documented=None):
    return sorted((f["tool"], f["variant"], f["mutation"], f["outcome"], f["detail"]) for f in findings
                  if documented is None or f["documented"] == documented)


class Data(unittest.TestCase):
    def test_every_pinned_file_matches_the_manifest(self):
        listed = json.loads((UPSTREAM / "MANIFEST.json").read_text())["files"]
        present = {p.relative_to(UPSTREAM).as_posix() for p in UPSTREAM.rglob("*") if p.is_file()}
        self.assertEqual(present - {"MANIFEST.json"}, set(listed))
        bad = [name for name, digest in listed.items() if sha256(UPSTREAM / name) != digest]
        self.assertEqual(bad, [])

    def test_spec_is_the_pinned_one(self):
        self.assertEqual(sha256(UPSTREAM / "openapi.json"), SPEC_SHA)

    def test_commits_in_history_order(self):
        rows = commits()
        self.assertEqual([r["commit"] for r in rows], ORDER)
        self.assertEqual({r["zod"] for r in rows[:-1]}, {"4.4.3"})
        self.assertEqual(rows[-1]["zod"], "4.6.7")

    def test_licenses_are_kept(self):
        self.assertTrue((UPSTREAM / "agentphone-mcp" / "LICENSE").read_text().startswith("MIT License"))
        for version in ("4.4.3", "4.6.7"):
            self.assertIn("MIT", (UPSTREAM / "zod" / version / "LICENSE").read_text())

    def test_spec_counts(self):
        spec = json.loads((UPSTREAM / "openapi.json").read_text())
        self.assertEqual(score.spec_counts(spec), {"schema": 59, "no_content": 3, "unconstrained": 36})

    def test_ledger_and_triage(self):
        ledger = score.load_ledger(ROOT / "study" / "known-bugs.json")
        self.assertEqual(sorted(c["id"] for c in ledger), sorted(CAUGHT))
        self.assertTrue(all(c["buggy"] in ORDER and c["fixed"] in (None, *ORDER) for c in ledger))
        triage = json.loads((ROOT / "study" / "triage.json").read_text())["findings"]
        self.assertEqual(len(triage), 12)

    def test_typescript_type_checks(self):
        tsc = Path(os.environ["ARCTURUS_NODE_MODULES"]) / "typescript" / "bin" / "tsc"
        done = subprocess.run([os.environ["ARCTURUS_NODE"], str(tsc), "-p", str(ROOT / "web" / "tsconfig.json")],
                              capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:])


class Experiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        for run in ("run1", "run2"):
            subprocess.run([sys.executable, str(ROOT / "experiment.py"), "--out", str(base / run / "metrics.json")],
                           cwd=ROOT, check=True, timeout=600, capture_output=True)
        cls.raw = {run: (base / run / "metrics.json").read_bytes() for run in ("run1", "run2")}
        cls.metrics = json.loads(cls.raw["run1"])
        reports = json.loads((base / "run1" / "reports.json").read_text())
        cls.reports = {r["commit"]: r for r in reports}
        cls.order = [r["commit"] for r in reports]
        cls.reports_raw = {run: (base / run / "reports.json").read_bytes() for run in ("run1", "run2")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_two_runs_are_byte_identical(self):
        self.assertEqual(self.raw["run1"], self.raw["run2"])
        self.assertEqual(self.reports_raw["run1"], self.reports_raw["run2"])

    def test_metric_names(self):
        self.assertEqual(sorted(self.metrics), METRICS)
        self.assertEqual(list(self.metrics), METRICS)

    def test_metrics_are_finite_numbers(self):
        for name, value in self.metrics.items():
            values = value if isinstance(value, list) else [value]
            self.assertTrue(all(isinstance(v, (int, float)) and math.isfinite(v) for v in values), name)

    def test_headline_values(self):
        self.assertEqual({k: self.metrics[k] for k in VALUES}, VALUES)

    def test_per_commit_counts(self):
        self.assertEqual(self.metrics["findings_per_commit"], [72, 71, 71, 71, 65, 62, 61, 61, 60, 58, 24, 21, 22])
        self.assertEqual(self.metrics["documented_findings_per_commit"],
                         [59, 59, 59, 59, 53, 50, 49, 49, 48, 48, 14, 11, 12])
        self.assertEqual(self.metrics["findings_total"], 719)

    def test_run_counts(self):
        self.assertEqual((self.metrics["runs_total"], self.metrics["requests_total"]), (6879, 9324))
        self.assertEqual([r["runs"] for r in self.reports.values()],
                         [525] * 6 + [516] * 6 + [633])

    def test_reports_in_history_order(self):
        self.assertEqual(self.order, ORDER)
        self.assertEqual([len(self.reports[c]["tools"]) for c in ORDER], [28] * 12 + [32])

    def test_each_known_case(self):
        ledger = score.load_ledger(ROOT / "study" / "known-bugs.json")
        got = {c["id"]: score.evaluate(c, self.reports)["caught"] for c in ledger}
        self.assertEqual(got, CAUGHT)

    def test_latest_documented_findings(self):
        self.assertEqual(keys(self.reports["46c8fe8"]["findings"], documented=True), LATEST_DOCUMENTED)

    def test_empty_body_before_and_after_the_detach_fix(self):
        before = keys(self.reports["d3d3209"]["findings"])
        self.assertIn(("detach_number", "default", "baseline", "output_invalid", "success"), before)
        self.assertNotIn("detach_number", {k[0] for k in keys(self.reports["caece3a"]["findings"])})

    def test_null_numbers_before_and_after_the_fix(self):
        for tool in ("get_agent", "list_agents", "create_agent", "update_agent"):
            before = [k for k in keys(self.reports["397ae03"]["findings"]) if k[0] == tool and "numbers" in k[2]]
            after = [k for k in keys(self.reports["5841776"]["findings"]) if k[0] == tool and "numbers" in k[2]]
            self.assertTrue(before and all(k[3] == "output_invalid" for k in before), tool)
            self.assertEqual(after, [], tool)

    def test_delivery_shape_crash(self):
        found = keys(self.reports["5841776"]["findings"])
        message = "Cannot read properties of undefined (reading 'length')"
        for variant in ("project", "agent"):
            self.assertIn(("list_webhook_deliveries", variant, "baseline", "error_result", message), found)

    def test_dead_wait_parameters(self):
        found = keys(self.reports["183bafd"]["findings"])
        self.assertIn(("get_call", "default", "baseline", "undocumented_param", "timeout"), found)
        for field in ("$.maxWaitSeconds", "$.waitForCompletion"):
            self.assertIn(("make_conversation_call", "default", "baseline", "undocumented_field", field), found)
        self.assertFalse([k for k in keys(self.reports["1921eba"]["findings"]) if "undocumented" in k[3]])

    def test_unconstrained_responses_are_marked(self):
        latest = {(f["tool"], f["documented"]) for f in self.reports["46c8fe8"]["findings"] if f["tool"] == "list_voices"}
        self.assertEqual(latest, {("list_voices", False)})

    def test_refused_combination_is_rejected(self):
        rejected = self.reports["46c8fe8"]["rejected"]
        self.assertEqual([(r["tool"], r["variant"]) for r in rejected], [("list_webhook_deliveries", "agent_hours")])
        self.assertTrue(rejected[0]["detail"].startswith("refused: "))

    def test_scan_function_matches_the_experiment(self):
        self.assertEqual(scan("af4501f"), self.reports["af4501f"])

    def test_readme_block(self):
        import demo

        text = demo.render("# T\n\nbefore\n<!-- specdrift:results -->\nold\n<!-- /specdrift:results -->\nafter\n",
                           self.metrics)
        self.assertTrue(text.startswith("# T\n\nbefore\n<!-- specdrift:results -->"))
        self.assertTrue(text.endswith("<!-- /specdrift:results -->\nafter\n"))
        self.assertNotIn("old", text)
        self.assertIn("| 20 |", text)
        with self.assertRaises(ValueError):
            demo.render("no block", self.metrics)


if __name__ == "__main__":
    unittest.main()
