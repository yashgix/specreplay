"""SpecReplay on a small synthetic upstream and spec: every outcome kind, the mutation order, the request checks."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import specreplay
from specreplay import score
from specreplay.scan import scan_dir

ROOT = Path(specreplay.__file__).resolve().parents[1]
ZOD = ROOT / "upstream" / "zod" / "4.6.7" / "index.js"
FLAGS = ["--experimental-transform-types", "--disable-warning=ExperimentalWarning"]

SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/v1/things": {
            "get": {"parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 50,
                                                                              "default": 10}}],
                    "responses": {"200": {"content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/ThingList"}}}}}},
            "post": {"requestBody": {"content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/CreateThing"}}}},
                "responses": {"200": {"content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/Thing"}}}}}},
        },
        "/v1/things/{id}": {
            "get": {"parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/Thing"}}}}}},
            "delete": {"responses": {"204": {"description": "Deleted"}}},
        },
        "/v1/things/special": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
            "$ref": "#/components/schemas/Thing"}}}}}}},
        "/v1/blob": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"title": "Blob"}}}}}}},
    },
    "components": {"schemas": {
        "Thing": {"type": "object", "required": ["id", "label", "kind", "tags"], "properties": {
            "id": {"type": "string"},
            "label": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "kind": {"type": "string", "enum": ["a", "b"]},
            "size": {"type": "integer", "default": 3},
            "note": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        }},
        "ThingList": {"type": "object", "required": ["data", "total"], "properties": {
            "data": {"type": "array", "items": {"$ref": "#/components/schemas/Thing"}},
            "total": {"type": "integer"},
        }},
        "CreateThing": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string", "maxLength": 10},
            "color": {"anyOf": [{"type": "string"}, {"type": "null"}], "enum": ["red", "blue"]},
        }},
    }},
}

API_TS = """
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export class AgentPhoneAPI {
  private baseUrl: string;
  constructor(baseUrl: string, apiKey: string) {
    this.baseUrl = baseUrl;
    void apiKey;
  }
  private async request(method: string, path: string, body?: unknown): Promise<any> {
    const res = await fetch(this.baseUrl + path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    const text = await res.text();
    return text ? JSON.parse(text) : {};
  }
  getThing(id: string) { return this.request("GET", `/v1/things/${id}`); }
  listThings(limit: number) { return this.request("GET", `/v1/things?limit=${limit}&verbose=1`); }
  createThing(name: string, color?: string) { return this.request("POST", "/v1/things", { name, color, shade: "x" }); }
  deleteThing(id: string) { return this.request("DELETE", `/v1/things/${id}`); }
  getSpecial() { return this.request("GET", "/v1/things/special"); }
  getBlob() { return this.request("GET", "/v1/blob"); }
  getMissing() { return this.request("GET", "/v1/missing"); }
}
"""

TOOLS_TS = """
import { z } from "zod";
import { AgentPhoneAPI } from "./api.js";

const ok = (text: string, structuredContent?: Record<string, unknown>) =>
  structuredContent ? { content: [{ type: "text", text }], structuredContent } : { content: [{ type: "text", text }] };
const err = (e: unknown) => ({ content: [{ type: "text", text: `Error: ${e instanceof Error ? e.message : e}` }], isError: true });

export function registerTools(server: any, api: AgentPhoneAPI): void {
  server.tool("get_thing", "Read one.", { id: z.string() }, { readOnlyHint: true }, async ({ id }: any) => {
    const t = await api.getThing(id);
    return ok(`Thing ${t.id}: ${t.label.toUpperCase()}`, t);
  });
  server.tool("safe_get_thing", "Read one.", { id: z.string() }, async ({ id }: any) => {
    try {
      const t = await api.getThing(id);
      return ok(`Thing ${t.id}: ${t.label.toUpperCase()}`, t);
    } catch (e) {
      return err(e);
    }
  });
  server.tool("list_things", "List.", { limit: z.number().int().min(1) }, {}, async ({ limit }: any) => {
    const page = await api.listThings(limit);
    return ok(`${page.data.length} things`, page);
  });
  server.tool("create_thing", "Create.", { name: z.string().max(10), color: z.string().optional() }, {},
    async ({ name, color }: any) => ok("created", await api.createThing(name, color)));
  server.tool("delete_thing", "Delete.", { id: z.string() }, {}, async ({ id }: any) => ok(`Deleted ${id}`, await api.deleteThing(id)));
  server.tool("note_thing", "Note.", {}, {}, async () => {
    const t = await api.getSpecial();
    return ok(`Note: ${t.note}`, t);
  });
  server.tool("blob", "Blob.", {}, {}, async () => {
    const b = await api.getBlob();
    return ok(`Size: ${b.size}`, b);
  });
  server.tool("refuse", "Never calls.", { why: z.string() }, {}, async () => err(new Error("not allowed")));
  server.tool("loop", "Loops.", {}, {}, async () => {
    for (let i = 0; i < 11; i++) await api.getThing(`t${i}`);
    return ok("done");
  });
  server.tool("no_struct", "No structure.", { id: z.string() }, {}, async ({ id }: any) => {
    await api.getThing(id);
    return ok("thing");
  });
  server.tool("ghost", "Calls an undocumented path.", {}, {}, async () => {
    try {
      return ok("found", await api.getMissing());
    } catch (e) {
      return err(e);
    }
  });
  server.tool("unlisted", "Not in the inputs.", {}, {}, async () => ok("unused"));
}
"""

SCHEMAS_TS = """
import { z } from "zod";

const thing = z.object({ id: z.string(), label: z.string().nullable(), kind: z.enum(["a"]), tags: z.array(z.string()) }).passthrough();

export const OUTPUT_SCHEMAS: Record<string, z.ZodTypeAny> = {
  get_thing: thing,
  safe_get_thing: thing,
  list_things: z.object({ data: z.array(thing), total: z.number() }).passthrough(),
  create_thing: thing,
  delete_thing: z.object({ success: z.boolean() }),
  note_thing: thing,
  no_struct: thing,
};
"""

INPUTS = {"tools": {
    "get_thing": [{"variant": "default", "args": {"id": "t1"}}],
    "safe_get_thing": [{"variant": "default", "args": {"id": "t1"}}],
    "list_things": [{"variant": "default", "args": {"limit": 5}}],
    "create_thing": [{"variant": "default", "args": {"name": "box", "color": "red"}}],
    "delete_thing": [{"variant": "default", "args": {"id": "t1"}}],
    "note_thing": [{"variant": "default", "args": {}}],
    "blob": [{"variant": "default", "args": {}}],
    "refuse": [{"variant": "default", "args": {"why": "x"}}],
    "loop": [{"variant": "default", "args": {}}],
    "no_struct": [{"variant": "default", "args": {"id": "t1"}}],
    "ghost": [{"variant": "default", "args": {}}],
    "not_registered": [{"variant": "default", "args": {}}],
}}

GET_ONE = "GET /v1/things/{id}"
NULL_LABEL = "Cannot read properties of null (reading 'toUpperCase')"
EXPECTED = [
    ("blob", "default", "GET /v1/blob", "baseline", "text_defect", "undefined", False),
    ("create_thing", "default", "POST /v1/things", "baseline", "undocumented_field", "$.shade", True),
    ("create_thing", "default", "POST /v1/things", "enum:$.kind=b", "output_invalid", "kind", True),
    ("create_thing", "default", "POST /v1/things", "input:color=enum", "input_not_enforced", "color:enum", True),
    ("delete_thing", "default", "DELETE /v1/things/{id}", "baseline", "output_invalid", "success", True),
    ("get_thing", "default", GET_ONE, "enum:$.kind=b", "output_invalid", "kind", True),
    ("get_thing", "default", GET_ONE, "null:$.label", "crash", NULL_LABEL, True),
    ("ghost", "default", "(none)", "baseline", "error_result", 'Error: {"detail":"Not Found"}', False),
    ("ghost", "default", "GET /v1/missing", "baseline", "undocumented_operation", "", True),
    ("list_things", "default", "GET /v1/things", "baseline", "undocumented_param", "verbose", True),
    ("list_things", "default", "GET /v1/things", "enum:$.data[0].kind=b", "output_invalid", "data.0.kind", True),
    ("list_things", "default", "GET /v1/things", "input:limit=maximum", "input_not_enforced", "limit:maximum", True),
    ("loop", "default", GET_ONE, "baseline", "request_limit", "", True),
    ("no_struct", "default", GET_ONE, "baseline", "missing_structured", "", True),
    ("note_thing", "default", "GET /v1/things/special", "enum:$.kind=b", "output_invalid", "kind", True),
    ("note_thing", "default", "GET /v1/things/special", "omit:$.note", "text_defect", "undefined", True),
    ("safe_get_thing", "default", GET_ONE, "enum:$.kind=b", "output_invalid", "kind", True),
    ("safe_get_thing", "default", GET_ONE, "null:$.label", "error_result", f"Error: {NULL_LABEL}", True),
]
FIELDS = ("tool", "variant", "operation", "mutation", "outcome", "detail", "documented")


def node_eval(code):
    """Run an ES module snippet with web/openapi.ts imported as oa; returns its JSON output."""
    url = (ROOT / "web" / "openapi.ts").as_uri()
    source = f"import * as oa from {json.dumps(url)};\nconst spec = {json.dumps(SPEC)};\n{code}"
    done = subprocess.run([os.environ["ARCTURUS_NODE"], *FLAGS, "--input-type=module", "-e", source],
                          capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


def schema(name):
    return json.dumps({"$ref": f"#/components/schemas/{name}"})


class Scanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        src = base / "synthetic" / "src"
        src.mkdir(parents=True)
        for name, text in (("api.ts", API_TS), ("tools.ts", TOOLS_TS), ("output-schemas.ts", SCHEMAS_TS)):
            (src / name).write_text(text)
        (base / "spec.json").write_text(json.dumps(SPEC))
        (base / "inputs.json").write_text(json.dumps(INPUTS))
        cls.report = scan_dir(base / "synthetic", ZOD, base / "spec.json", base / "inputs.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_report_fields(self):
        self.assertEqual(set(self.report), {"commit", "tools", "untested_tools", "rejected", "runs", "requests",
                                            "findings"})
        self.assertEqual(self.report["commit"], "synthetic")

    def test_tools_are_sorted_and_untested_listed(self):
        self.assertEqual(self.report["tools"], sorted(self.report["tools"]))
        self.assertEqual(len(self.report["tools"]), 12)
        self.assertEqual(self.report["untested_tools"], ["unlisted"])

    def test_exact_findings(self):
        got = [tuple(f[k] for k in FIELDS) for f in self.report["findings"]]
        self.assertEqual(got, EXPECTED)

    def test_findings_are_sorted(self):
        keys = [tuple(f[k] for k in FIELDS[:6]) for f in self.report["findings"]]
        self.assertEqual(keys, sorted(keys))

    def test_refusal_is_rejected_not_a_finding(self):
        self.assertEqual(self.report["rejected"],
                         [{"tool": "refuse", "variant": "default", "detail": "refused: Error: not allowed"}])

    def test_run_and_request_counts(self):
        self.assertEqual((self.report["runs"], self.report["requests"]), (43, 86))

    def test_a_crash_and_an_error_result_are_told_apart(self):
        outcomes = {(f["tool"], f["outcome"]) for f in self.report["findings"] if f["mutation"] == "null:$.label"}
        self.assertEqual(outcomes, {("get_thing", "crash"), ("safe_get_thing", "error_result")})

    def test_defaulted_field_is_never_omitted(self):
        self.assertFalse([f for f in self.report["findings"] if f["mutation"] == "omit:$.size"])

    def test_input_rejected_by_the_tool_is_enforced(self):
        self.assertFalse([f for f in self.report["findings"] if f["mutation"].startswith("input:name")])

    def test_cli_fails_on_a_missing_folder(self):
        with self.assertRaises(RuntimeError):
            scan_dir(Path(self.tmp.name) / "nowhere", ZOD, Path(self.tmp.name) / "spec.json",
                     Path(self.tmp.name) / "inputs.json")


class OpenApi(unittest.TestCase):
    def test_match_prefers_literal_segments(self):
        got = node_eval(
            'console.log(JSON.stringify([["GET", "/v1/things/special"], ["GET", "/v1/things/abc"], '
            '["DELETE", "/v1/things/abc"], ["GET", "/v1/nothing"], ["POST", "/v1/things/abc"]]'
            ".map(([m, p]) => oa.matchOperation(spec, m, p))));")
        self.assertEqual(got, ["GET /v1/things/special", "GET /v1/things/{id}", "DELETE /v1/things/{id}", None, None])

    def test_example(self):
        got = node_eval(f"console.log(JSON.stringify(oa.example(spec, {schema('ThingList')})));")
        thing = {"id": "text", "label": "text", "kind": "a", "size": 1, "note": "text", "tags": ["text"]}
        self.assertEqual(got, {"data": [thing], "total": 1})

    def test_example_formats_and_minimum(self):
        got = node_eval('console.log(JSON.stringify([{type: "string", format: "date-time"}, {type: "string", '
                        'format: "date"}, {type: "string", format: "uri"}, {type: "string", format: "email"}, '
                        '{type: "integer", minimum: 7}, {type: "boolean"}, {anyOf: [{type: "null"}, '
                        '{type: "number"}]}, {title: "Any"}].map((s) => oa.example(spec, s))));')
        self.assertEqual(got, ["2026-01-01T00:00:00Z", "2026-01-01", "https://example.com/", "user@example.com", 7,
                               True, 1, {}])

    def test_mutation_order(self):
        got = node_eval(f"console.log(JSON.stringify(oa.mutations(spec, {schema('ThingList')}).map((m) => m.id)));")
        self.assertEqual(got, ["empty_array:$.data", "null:$.data[0].label", "enum:$.data[0].kind=b",
                               "omit:$.data[0].note", "empty_array:$.data[0].tags"])

    def test_anyof_alternatives(self):
        got = node_eval('console.log(JSON.stringify(oa.mutations(spec, {anyOf: [{type: "string"}, '
                        '{type: "integer"}, {type: "null"}]}).map((m) => [m.id, m.value ?? null])));')
        self.assertEqual(got, [["null:$", None], ["alt:$#1", 1]])

    def test_validate_body(self):
        got = node_eval(f"const s = {schema('CreateThing')};\nconsole.log(JSON.stringify(["
                        'oa.validate(spec, s, {name: "abcdefghijkl", color: "green", shade: "x"}), '
                        "oa.validate(spec, s, {color: null}), oa.validate(spec, s, {name: 5})]));")
        self.assertEqual(got, [["$.name:maxLength", "$.color:enum", "$.shade:undocumented"], ["$.name:required"],
                               ["$.name:type"]])


CASE = {"id": "c", "tool": "get_thing", "variant": None, "mutations": ["null:*.label"], "outcomes": ["crash"],
        "detail": None, "buggy": "a", "fixed": "b", "spec_documents": True}


class Scoring(unittest.TestCase):
    CASE = CASE

    def finding(self, **change):
        base = {"tool": "get_thing", "variant": "default", "operation": GET_ONE, "mutation": "null:$.data[0].label",
                "outcome": "crash", "detail": "boom", "documented": True}
        return {**base, **change}

    def test_matches_globs_and_variants(self):
        self.assertTrue(score.matches(self.CASE, self.finding()))
        self.assertFalse(score.matches(self.CASE, self.finding(outcome="output_invalid")))
        self.assertFalse(score.matches(self.CASE, self.finding(tool="other")))
        self.assertFalse(score.matches({**self.CASE, "variant": "agent"}, self.finding()))
        self.assertTrue(score.matches({**self.CASE, "detail": "bo*"}, self.finding()))
        self.assertFalse(score.matches({**self.CASE, "detail": "x"}, self.finding()))

    def test_evaluate(self):
        hit, miss = {"findings": [self.finding()]}, {"findings": []}
        self.assertEqual(score.evaluate(self.CASE, {"a": hit, "b": miss}),
                         {"id": "c", "detected": True, "cleared": True, "caught": True})
        self.assertEqual(score.evaluate(self.CASE, {"a": hit, "b": hit})["caught"], False)
        self.assertEqual(score.evaluate(self.CASE, {"a": miss, "b": miss})["detected"], False)
        open_case = score.evaluate({**self.CASE, "fixed": None}, {"a": hit})
        self.assertEqual((open_case["cleared"], open_case["caught"]), (None, True))

    def test_spec_counts(self):
        self.assertEqual(score.spec_counts(SPEC), {"schema": 4, "no_content": 1, "unconstrained": 1})

    def test_triage_counts(self):
        f = self.finding()
        row = {k: f[k] for k in ("tool", "variant", "operation", "mutation", "outcome", "detail")}
        counts = score.triage_counts([f, self.finding(detail="other")], [{**row, "label": "confirmed"}])
        self.assertEqual(counts, {"latest_new_confirmed": 1, "latest_new_unconfirmed": 0,
                                  "latest_new_false_positive": 0, "latest_new_untriaged": 1})


if __name__ == "__main__":
    unittest.main()
