# SpecReplay

Write-up: https://yashgix.github.io/specreplay/

SpecReplay replays the real tool handlers of `agentphone-mcp` (MIT, TypeScript) at 13 pinned commits against an in-process fake of the AgentPhone API whose responses are built from the published OpenAPI document. It changes one thing at a time (a nullable field set to `null`, an optional field left out, another enum value, an empty array, a 204 with no body) and records every crash, error result, output-schema failure and `undefined` in the text. It also checks each request a tool sends against the spec, and probes each tool argument that reaches a constrained request field with a value just outside the documented limit.

The question it answers: **from the published spec alone, how many of the project's reported contract-drift bugs would an automatic check have caught, and what does it flag today?**

## Why

The ledger used here lists reported contract drift between the project's MCP tools and the documented API. This work does not independently verify the external history or issue statuses; the table below follows the cited sources.

| | reported contract drift |
| --- | --- |
| [#93](https://github.com/AgentPhone-AI/agentphone-mcp/pull/93) | a reported 204 with an empty body failing the tool's output validation |
| [#99](https://github.com/AgentPhone-AI/agentphone-mcp/pull/99) | reported documented `null` values rejected by six tools |
| [#101](https://github.com/AgentPhone-AI/agentphone-mcp/pull/101) | a reported crash on the documented webhook-delivery list shape |
| [#103](https://github.com/AgentPhone-AI/agentphone-mcp/pull/103) | a reported query parameter that has no effect |
| [#105](https://github.com/AgentPhone-AI/agentphone-mcp/pull/105) | a reported `from_` read as `from` |
| [#107](https://github.com/AgentPhone-AI/agentphone-mcp/pull/107) | reported input bounds dropped, then "restored from the public OpenAPI" |
| [#109](https://github.com/AgentPhone-AI/agentphone-mcp/pull/109) | reported wait parameters that no endpoint accepts |
| [#120](https://github.com/AgentPhone-AI/agentphone-mcp/issues/120) | reported open: `language` accepts any string |

The ledger also describes an existing hand-written list of endpoints and field names checked for *presence* against the live spec, outside the unit tests (`scripts/check-openapi-contract.mjs`, #115); this work does not verify that description. SpecReplay checks behaviour instead and takes every expectation from the spec: no hand-written endpoint list, no network, no live API.

## What a scan does

1. **Load the commit's real code**: `src/tools.ts`, `src/api.ts`, `src/output-schemas.ts`, with the zod version its lock file pins (`upstream/zod/4.4.3` or `4.6.7`). The sources are executed, never edited.
2. **Replace `fetch`** with a fake (`web/fakeapi.ts`) that answers from the spec: the documented success status, an example built from the documented schema, an empty body where the spec documents none, and `404 {"detail":"Not Found"}` for a path the spec does not have.
3. **Call each tool variant once** with a valid fixture (`study/tool-inputs.json`: 32 tools, 44 variants). The result is classified the way the MCP SDK would: arguments parsed by the tool's own input schema, `structuredContent` validated against the tool's output schema, `isError` treated as an error result, and `undefined` / `NaN` / `[object Object]` in the text flagged.
4. **Break one thing at a time** in the documented success response, call again with that operation's response overridden, and keep only the outcomes the unmutated call did not already produce.
5. **Check the requests** (undocumented path, query parameter or body field; a body value the spec rejects) and **probe the inputs**: a fixture argument that reached a constrained field is replaced by a violating value, and if the tool still puts it on the wire, the bound is not enforced.
6. **Score** the findings against a 25-case ledger built from the cited issues, PRs and commit messages. A case is caught when it is flagged at its buggy commit and gone at the fix commit.

## Running it

Python 3.14 standard library only (plus `ruff` for linting), Node 22, and TypeScript 7.0.2 (`npm install --no-save typescript@7.0.2`). The experiment, the demo and the tests open no socket. Only the fetch step below uses the network.

```
export SPECREPLAY_NODE=/path/to/node   # must be Node 22, for example /opt/homebrew/opt/node@22/bin/node
python tools/fetch_data.py --accept-spec-drift     # rebuild upstream/ first, see "Data and licenses"

python experiment.py --out results/metrics.json    # all 13 commits, about 15 s
python demo.py                                     # latest commit, one line per documented finding
python demo.py --readme README.md --out README.md  # regenerate the block below
python -m unittest discover -s tests               # Node-backed tests skip without SPECREPLAY_NODE
make lint typecheck test experiment                # the same steps as CI
```

`experiment.py` also writes `results/reports.json` (one report per commit) next to the metrics file, and two runs are byte-identical. The scanner itself is `web/cli.ts`, launched by `specreplay/scan.py` as

```
$SPECREPLAY_NODE --experimental-transform-types --disable-warning=ExperimentalWarning \
  --import <file URL of web/hooks.ts> web/cli.ts SOURCE_DIR SPEC_JSON INPUTS_JSON
```

with `SPECREPLAY_ZOD` pointing at that commit's zod entry. `specreplay/scan.py` is the only code that spawns Node.

## Results

<!-- specreplay:results -->
| name | value |
| --- | --- |
| commits | 13 |
| runs | 6879 |
| known cases | 25 |
| documented cases | 20 |
| caught | 20 |
| caught documented | 19 |
| unconstrained operations | 36 |
| findings not in the ledger | 10 |
| root causes behind them | 4 |

Recall: 20/25 (0.80) overall; 19/20 (0.95) on documented contracts. In-sample: the rules were written knowing these cases.

| root cause | kind | findings | code sites (src/tools.ts at v0.10.0) |
| --- | --- | --- | --- |
| offset has no documented maximum (10000) on five list tools | missing bound | 6 | list_numbers src/tools.ts:561; list_calls src/tools.ts:1237; list_agents src/tools.ts:1601; list_conversations src/tools.ts:2064; list_contacts src/tools.ts:2220 |
| hours has no documented maximum (168) on list_webhook_deliveries | missing bound | 1 | list_webhook_deliveries src/tools.ts:2563 |
| system_prompt has no documented maxLength (20000) on create and update | missing bound | 2 | create_agent src/tools.ts:1643; update_agent src/tools.ts:1778 |
| update_conversation prints Metadata: undefined if the response omits metadata | spec ambiguity | 1 | update_conversation src/tools.ts:2200 |
| language accepts any string | known, open upstream | 2 | create_agent src/tools.ts:1710; update_agent src/tools.ts:1845 |
<!-- /specreplay:results -->

The block is written by `python demo.py --readme README.md --out README.md` from `results/metrics.json`; that command emits the full table, including `runs` (every tool call the experiment made), plus the recall line. Run it after `experiment.py` so the numbers match the metrics file that ships with the results.

## What "documented" means

A finding is documented when the operation it is about has a success response a tool can be judged against: no content (a 2xx without `application/json`), or a JSON schema with at least one key that is not `title`, `description`, `examples`, `example` or `default`. A schema whose keys are all annotations constrains nothing, and a response without a body has nothing to validate. Of the spec's 98 operations, 36 document an unconstrained success response and 62 are documented. Findings on unconstrained operations are kept in the reports with `documented: false`: they may be real, but the spec cannot say so, and they are left out of the findings count and of the documented recall.

## What it flags at v0.10.0

Twelve documented findings at `46c8fe8` (`study/triage.json`) come down to five root causes. The table above lists each with its code sites. None is shown to break a user. The maintainers report in #88 that the API answers 422 to out-of-range values, so a missing client-side bound likely means a late 422. Nothing here was run against the live API.

- Three causes are missing client-side bounds that the spec documents: `offset` (maximum 10000) on five list tools, `hours` (maximum 168) on `list_webhook_deliveries`, and `system_prompt` (maximum length 20000) on `create_agent` and `update_agent`. They are the remainder of the bounds restored in #107. The maintainers dropped these bounds on purpose in #88 and restored most in #107, so they may judge these not worth a change.
- One is a spec ambiguity: `update_conversation` prints `Metadata: undefined` if the response omits `metadata`. The spec allows the omission and documents no default. Whether the live API ever omits it is unknown.
- One is already known: `create_agent` and `update_agent` accept any `language`. It is open upstream as issue #120 with fix PR #121. It is counted as known, not as a finding of this work.

In hosted mode the tool also wraps `system_prompt` in identity text before sending it. Wide mode measures this (see below): the wrapped value can go out over the documented length even when the input is under it.

## Scoring on the bug history

The ledger has 25 cases, 20 of them about contracts the spec documents. A case is caught when a finding matching it exists at its buggy commit and none exists at its fix commit. Recall is 20/25 (0.80) overall and 19/20 (0.95) on documented contracts. This is in-sample: the rules were written knowing these cases, so it measures that the rules reproduce the history, not how they would do on unseen drift. `study/known-bugs.json` also lists the items that were considered and excluded, each with a reason.

## Wide mode and hold-out

`python wide.py` (`make wide`) repeats the latest-commit scan with two additions. First, every argument a fixture leaves out is set to a sentinel value, and if it reaches a constrained request field it is probed like the fixture arguments, so a bound is checked wherever the tool can send it. One extra variant (`list_calls` scoped by number) comes from `study/tool-inputs-extra.json`. Second, in hosted mode it sends a one-character prompt to measure how much text the tool adds, then an accepted prompt of the longest spec-legal length plus one, and checks whether the wire value exceeds the documented maximum. The v1 scan and its metrics are unchanged. The measured threshold holds for plain ASCII prompts that need no trimming and are not already wrapped, and lengths are counted in characters as the spec does (zod counts UTF-16 units).

The hold-out is a small set of cases from the repository's own history that are not in the 25-case ledger (`study/holdout.json`). The scanner rules were tagged `rules-frozen` first and the expected result of each case was written down before the run. `python holdout.py DIR` scores them on sources fetched by `tools/holdout_sources.sh`. A case counts only when its bug is shown to be exercised: each case has a frozen fixture, a detection predicate that ignores wording, and a trigger check, and a case whose trigger is not seen is reported as not exercised. Three cases is too few for a rate. They show a documented response shape caught, and two other classes missed with their bugs exercised: a tool that refuses an input the API accepts, and filters dropped with no wrong request or response.

<!-- specreplay:wide -->
| name | value |
| --- | --- |
| arguments probed from the fixtures | 40 (57 probes) |
| further arguments probed in wide mode | 2 (4 probes) |
| findings added by wide mode (not counting the prompt check) | 3 |
| prompt wrapper | systemPrompt:maxLength added=528 threshold=19472 |
| hold-out cases | 3 |
| hold-out caught | 1 |
| hold-out missed (bug exercised) | 2 |
| hold-out not exercised | 0 |
<!-- /specreplay:wide -->

## Limits

- 36 of the 98 operations document an unconstrained success response; nothing can be judged there, and the study says so rather than guessing.
- The handlers run against a stubbed `fetch` and an emulation of the SDK's three checks (argument parsing, output-schema validation of `structuredContent`, error-result handling), not the SDK itself.
- The checking rules were designed with knowledge of this bug class, so the recall figure is in-sample. The hold-out above has 3 cases, enough to show which classes are covered but not to give a rate. The v0.10.0 list is a first look, not a measure of recall.
- Omitted-field findings depend on whether the live API ever omits the field. An omission the spec allows is only a finding when the tool mishandles it.
- One example per response shape and single-fault mutations: combinations of faults and unusual payloads are out of scope.
- The spec is treated as correct. A spec error surfaces as a tool bug.

## Data and licenses

Our code is MIT (`LICENSE`). Nothing from the projects studied is committed. `upstream/` is rebuilt by `tools/fetch_data.py` and is git-ignored. Only `upstream/MANIFEST.json` (paths and sha256 values) is committed, and the script checks every fetched file against it.

- `upstream/agentphone-mcp/`: `src/` of 13 commits of `github.com/AgentPhone-AI/agentphone-mcp`. MIT, Copyright (c) 2025 AgentPhone (its `LICENSE` at the pinned commits). It is fetched rather than copied, and its `LICENSE` comes with the fetch.
- `upstream/zod/4.4.3/` and `upstream/zod/4.6.7/`: ESM files of the zod package from the npm registry, MIT (zod's own copyright notice is in the `LICENSE` fetched alongside), checked against the registry's integrity hash.
- `upstream/openapi.json`: `https://api.agentphone.ai/openapi.json`. It carries no license, so it is never republished. It is a live document: the copy used for the committed results (14 Nov 2026) is not retrievable, and by 15 Nov one endpoint description (`/v1/contacts/capabilities`) had changed. The fetch script reports the hash mismatch and stops unless given `--accept-spec-drift`. `tests/acceptance` pins the original spec hash, so `tools/run_acceptance.py` (used by `make test` and CI) skips exactly two of its checks when the fetched spec differs from the manifest, `test_spec_is_the_pinned_one` and `test_every_pinned_file_matches_the_manifest`, and prints why. The fetch script has already verified every other file's hash. The experiment rerun on the changed spec still reproduces `results/` byte for byte.
- `study/*.json`: written for this project. The ledger quotes the public issues, PRs and commits it cites.

The hold-out sources are not stored either: `sh tools/holdout_sources.sh DIR` clones the public repository, then `python holdout.py DIR` scores them.

## Layout

```
tools/                fetch_data.py rebuilds upstream/, holdout_sources.sh the hold-out sources
specreplay/scan.py    run the TypeScript scanner on one pinned commit
specreplay/score.py   ledger matching, spec counts, triage, metrics
experiment.py         all 13 commits -> results/reports.json and metrics
demo.py               latest findings; regenerate the results block
web/openapi.ts        reading the spec: examples, mutations, validation
web/fakeapi.ts        the in-process API
web/harness.ts        load a commit's tools, make one call
web/cli.ts            scan one commit, print the report
web/hooks.ts          module resolution for zod, the SDK stub, .js -> .ts
study/                fixtures, the ledger, the hand triage, the hold-out cases
wide.py               wide mode: every argument, prompt wrapper
holdout.py            score the frozen rules on the hold-out cases
tests/                Python unittest; tests/acceptance pins the headline numbers and is run by tools/run_acceptance.py; Node tests live under web/
docs/                 DESIGN.md (how it works), V2-CHANGES.md (what changed after v1)
```
