# SpecDrift

SpecDrift replays the real tool handlers of `agentphone-mcp` (MIT, TypeScript) at 13 pinned commits against an in-process fake of the AgentPhone API whose responses are built from the published OpenAPI document. It changes one thing at a time (a nullable field set to `null`, an optional field left out, another enum value, an empty array, a 204 with no body) and records every crash, error result, output-schema failure and `undefined` in the text. It also checks each request a tool sends against the spec, and probes each tool argument that reaches a constrained request field with a value just outside the documented limit.

The question it answers: **from the published spec alone, how many of the project's reported contract-drift bugs would an automatic check have caught, and what does it find today?**

## Why

The assignment supplies a ledger of reported contract drift between the project's MCP tools and the documented API. This build does not independently verify the external history or issue statuses; the table below follows the ledger's cited sources.

| | reported contract drift |
| --- | --- |
| [#93](https://github.com/AgentPhone-AI/agentphone-mcp/pull/93) | a reported 204 with an empty body failing the tool's output validation |
| [#99](https://github.com/AgentPhone-AI/agentphone-mcp/pull/99) | reported documented `null` values rejected by six tools |
| [#101](https://github.com/AgentPhone-AI/agentphone-mcp/pull/101) | a reported crash on the documented webhook-delivery list shape |
| [#103](https://github.com/AgentPhone-AI/agentphone-mcp/pull/103) | a reported query parameter that the supplied ledger says has no effect |
| [#105](https://github.com/AgentPhone-AI/agentphone-mcp/pull/105) | a reported `from_` read as `from` |
| [#107](https://github.com/AgentPhone-AI/agentphone-mcp/pull/107) | reported input bounds dropped, then "restored from the public OpenAPI" |
| [#109](https://github.com/AgentPhone-AI/agentphone-mcp/pull/109) | reported wait parameters that no endpoint accepts |
| [#120](https://github.com/AgentPhone-AI/agentphone-mcp/issues/120) | reported open: `language` accepts any string |

The assignment also describes an existing hand-written list of endpoints and field names checked for *presence* against the live spec, outside the unit tests (`scripts/check-openapi-contract.mjs`, #115); this build does not verify that description. SpecDrift checks behaviour instead and takes every expectation from the spec: no hand-written endpoint list, no network, no live API.

## What a scan does

1. **Load the commit's real code**: `src/tools.ts`, `src/api.ts`, `src/output-schemas.ts`, with the zod version its lock file pins (`upstream/zod/4.4.3` or `4.6.7`). The sources are executed, never edited.
2. **Replace `fetch`** with a fake (`web/fakeapi.ts`) that answers from the spec: the documented success status, an example built from the documented schema, an empty body where the spec documents none, and `404 {"detail":"Not Found"}` for a path the spec does not have.
3. **Call each tool variant once** with a valid fixture (`study/tool-inputs.json`: 32 tools, 44 variants). The result is classified the way the MCP SDK would: arguments parsed by the tool's own input schema, `structuredContent` validated against the tool's output schema, `isError` treated as an error result, and `undefined` / `NaN` / `[object Object]` in the text flagged.
4. **Break one thing at a time** in the documented success response, call again with that operation's response overridden, and keep only the outcomes the unmutated call did not already produce.
5. **Check the requests** (undocumented path, query parameter or body field; a body value the spec rejects) and **probe the inputs**: a fixture argument that reached a constrained field is replaced by a violating value, and if the tool still puts it on the wire, the bound is not enforced.
6. **Score** the findings against a 25-case ledger built from the cited issues, PRs and commit messages. A case is caught when it is flagged at its buggy commit and gone at the fix commit.

## Running it

Python 3.14 standard library only; Node 22 and TypeScript 7.0.2 come from the environment's read-only `node_modules`. Nothing is installed, and the experiment, the demo and the tests open no socket.

```
export ARCTURUS_NODE=/path/to/node

python experiment.py --out results/metrics.json    # all 13 commits, about 15 s
python demo.py                                     # latest commit, one line per documented finding
python demo.py --readme README.md --out README.md  # regenerate the block below
python -m unittest discover -s tests               # Node-backed tests skip without ARCTURUS_NODE
tsc -p web/tsconfig.json                           # scanner types
```

`experiment.py` also writes `results/reports.json` (one report per commit) next to the metrics file, and two runs are byte-identical. The scanner itself is `web/cli.ts`, launched by `specdrift/scan.py` as

```
$ARCTURUS_NODE --experimental-transform-types --disable-warning=ExperimentalWarning \
  --import <file URL of web/hooks.ts> web/cli.ts SOURCE_DIR SPEC_JSON INPUTS_JSON
```

with `SPECDRIFT_ZOD` pointing at that commit's zod entry. `specdrift/scan.py` is the only code that spawns Node.

## Results

<!-- specdrift:results -->
| name | value |
| --- | --- |
| commits | 13 |
| known cases | 25 |
| documented cases | 20 |
| caught | 20 |
| caught documented | 19 |
| unconstrained operations | 36 |
| new findings | 10 |
| confirmed | 9 |
| false positives | 0 |

Recall: 20/25 (0.80) overall; 19/20 (0.95) on documented contracts.
<!-- /specdrift:results -->

The block is written by `python demo.py --readme README.md --out README.md` from `results/metrics.json`; that command emits the full ten-row table, including `runs` (every tool call the experiment made), plus the recall line. Run it after `experiment.py` so the numbers match the metrics file that ships with the results.

## What "documented" means

A finding is documented when the operation it is about has a success response a tool can be judged against: no content (a 2xx without `application/json`), or a JSON schema with at least one key that is not `title`, `description`, `examples`, `example` or `default`. A schema whose keys are all annotations constrains nothing, and a response without a body has nothing to validate. Of the spec's 98 operations, 36 document an unconstrained success response and 62 are documented. Findings on unconstrained operations are kept in the reports with `documented: false`: they may be real, but the spec cannot say so, and they are left out of the new-finding list and of the documented recall.

## What it finds at v0.10.0

Twelve documented findings were hand-checked by this build at `46c8fe8` (`study/triage.json`). Ten are new, meaning they match no ledger case: 9 confirmed, 1 unconfirmed, 0 false positives. The other two, `create_agent` and `update_agent` accepting any `language`, match the #120 case marked open in the supplied ledger, so they are reported as known rather than new.

Confirmed and new:

- `system_prompt` has no maximum length on `create_agent` and `update_agent`; the spec documents `systemPrompt` with `maxLength` 20000.
- `offset` has no maximum on `list_agents`, `list_calls` (agent variant), `list_contacts`, `list_conversations` (both variants) and `list_numbers`; the spec documents `maximum` 10000.
- `hours` has no maximum on `list_webhook_deliveries`; the spec documents `maximum` 168.

Unconfirmed: `update_conversation` prints `Metadata: undefined` when the optional `metadata` is absent. The spec allows the omission and documents no default, so whether the live API ever omits it is unknown.

Every label comes from reading the pinned `src/tools.ts` against the spec, and each row of `study/triage.json` carries the evidence in its own words.

## Scoring on the bug history

The supplied ledger has 25 cases, 20 of them about contracts the spec documents. A case is caught when a finding matching it exists at its buggy commit and none exists at its fix commit. Recall is 20/25 (0.80) overall and 19/20 (0.95) on documented contracts. `study/known-bugs.json` also lists the items that were considered and excluded, each with a reason.

## Limits

- 36 of the 98 operations document an unconstrained success response; nothing can be judged there, and the study says so rather than guessing.
- The handlers run against a stubbed `fetch` and an emulation of the SDK's three checks (argument parsing, output-schema validation of `structuredContent`, error-result handling), not the SDK itself.
- The checking rules were designed with knowledge of this bug class, so the recall figure is in-sample. The out-of-sample part is the v0.10.0 finding list and its hand triage.
- Omitted-field findings depend on whether the live API ever omits the field. An omission the spec allows is only a finding when the tool mishandles it.
- One example per response shape and single-fault mutations: combinations of faults and unusual payloads are out of scope.
- The spec is treated as correct. A spec error surfaces as a tool bug.

## Data and licenses

- `upstream/agentphone-mcp/`: `src/` of 13 commits of `github.com/AgentPhone-AI/agentphone-mcp`, MIT, with the license copied at `upstream/agentphone-mcp/LICENSE`.
- `upstream/zod/4.4.3/` and `upstream/zod/4.6.7/`: the ESM files of the zod package from the npm registry, MIT, licenses copied alongside.
- `upstream/openapi.json`: `https://api.agentphone.ai/openapi.json`, fetched 14 Nov 2026. It carries no license, so it is used for analysis only and is never republished: the code, docs and tests here name its paths, fields and counts but do not reproduce it. A public copy of this repository would hold only code, `tools/fetch_data.py`, the manifest and the derived findings.
- `study/tool-inputs.json`, `study/known-bugs.json`, `study/triage.json`: written for this project; the ledger quotes the public issues, PRs and commits it cites.
- `upstream/MANIFEST.json` lists every file under `upstream/` with its sha256.

## Re-fetching the data

```
python tools/fetch_data.py
```

That script is the only code here that uses the network. Neither the tests nor the experiment run it: they read the pinned files, so a scan never depends on the live API or on a spec that moves.

## Layout

```
specdrift/scan.py     run the TypeScript scanner on one pinned commit
specdrift/score.py    ledger matching, spec counts, triage, metrics
experiment.py         all 13 commits -> results/reports.json and metrics
demo.py               latest findings; regenerate the results block
web/openapi.ts        reading the spec: examples, mutations, validation
web/fakeapi.ts        the in-process API
web/harness.ts        load a commit's tools, make one call
web/cli.ts            scan one commit, print the report
web/hooks.ts          module resolution for zod, the SDK stub, .js -> .ts
study/                fixtures, the ledger, the hand triage
tests/                Python unittest; the Node test lives under web/
```
