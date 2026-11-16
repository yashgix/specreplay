# Design

## The premise under test

The premise is that a contract check can be derived from the published spec alone, run against the project's real handlers, and find the bugs in a ledger of reported contract drift. This build verifies the mechanism and the local artifacts, not the external history. Everything here exists to make that premise cheap to check and cheap to attack: pinned inputs, one fake API, single-fault changes, a fixed report shape, and a score computed from a ledger written by hand before the run.

## Pipeline

```
upstream/agentphone-mcp/<commit>/src --+
upstream/openapi.json                --+--> web/cli.ts --> report --+
study/tool-inputs.json               --+                          +--> specreplay/score.py --> metrics
study/known-bugs.json                ------------------------------+
study/triage.json                    ------------------------------+
```

One scan covers one commit: the commit is a folder, its `src/` is loaded, and every tool gets one valid fixture call before anything is mutated. The report for that commit is a plain JSON object, so scoring is a pure function over reports and never re-runs a tool.

## Reading the spec (`web/openapi.ts`)

- `deref` follows `$ref` chains with a seen-set, so a cyclic reference yields `{}` instead of a loop.
- `effective` picks the shape a value is built from: the first non-null `anyOf` branch, else the first `allOf` part, keeping a sibling `enum`. The spec writes nullable fields as `anyOf: [{...}, {type: "null"}]`; one representative non-null shape is enough to build an example and to enumerate mutations, and the null branch is not lost, it becomes an explicit `null:` mutation. A merge would hide which branch was chosen.
- `matchOperation` compares segment for segment, where `{name}` matches any non-empty segment; of several candidates the template with the most literal segments wins, ties go to the spec's order. That reproduces the routing a server does when two templates can match the same concrete path, and it keeps the result independent of key order in the JSON.
- The success response is the lowest 2xx. A response without `application/json` is *no content*; a JSON schema whose keys are all annotations is *unconstrained*. Those are the only three states a tool's output check can be judged against: validate something, validate nothing because there is no body, or nothing to validate.
- `example` is built from the schema, never sampled: `enum[0]`, `const`, the `format` table, `minimum` for numbers, one array item. Nothing random means two runs produce the same bytes.
- `mutations` enumerates single faults in a fixed order, with ids that name where the fault is (`omit:$.metadata`, `null:$.items[0].phone_number`). Combining faults would multiply calls and lose attribution: which of the two changes caused the crash?
- `omit` is only emitted for a key that is neither required nor documented with a `default`. A documented default means the server always fills it in, so removing it tests nothing.
- `apply` works on a deep copy and replaces the whole body for the root path. `null` becomes `null` and `empty_array` becomes `[]`; only `alt` and `enum` carry a replacement value.
- `validate` picks the first `anyOf` branch whose type fits and then checks `enum`, `maxLength`, `minLength`, `maximum`, `minimum`, `maxItems`, `minItems`, array items and required keys, flagging an unknown object key as `undocumented` unless `additionalProperties` allows it. Unknown-key detection is the mirror image of the kind of drift the ledger cites in #107: a tool sending what the spec does not declare.
- Every recursion stops below depth 12, so a pathological schema costs nothing.

## The fake API (`web/fakeapi.ts`)

It answers from the spec, not from recorded traffic. Recorded responses would encode what the server did on one day, bug included; the spec is the contract under test. An unmatched path gets `404 {"detail":"Not Found"}` so a tool that builds the wrong URL fails the way it would against the real service. Unconstrained successes return `{}`, no-content successes return an empty body at the documented status. Each call gets its own request log and its own override map, keyed by operation name, which is how a mutation reaches the handler. The 11th request in one call is neither recorded nor answered: it throws and marks the call, so a retry loop surfaces as `request_limit` instead of a hung scan. Query parameters are recorded as ordered entries rather than a map, because the param check and the probes need name and value together.

## Calling a tool (`web/harness.ts`)

Module loading happens once per commit: `src/tools.ts`, `src/api.ts`, `src/output-schemas.ts` and zod are imported by URL. Each call is fresh: a new fake installed as `globalThis.fetch`, a new `AgentPhoneAPI`, a fresh `registerTools(server, api)`, where the shim records name, input shape and the last argument as handler (annotations are optional, so the last argument is always the handler).

The SDK's three checks are emulated, because the SDK is not in the environment and these three decide the outcome:

1. arguments go through `z.object(shape).safeParse`; a failure rejects the call before any request, recorded as `input: <issue paths>`;
2. `structuredContent` is validated against `OUTPUT_SCHEMAS[name]`: absent gives `missing_structured`, a failed parse gives `output_invalid` with sorted unique issue paths;
3. `isError` marks an error result, and the joined text is scanned for `undefined`, `NaN` and `[object Object]`.

The classification order is deliberate: a refusal (an error result with no request sent) is not a finding; the request limit shadows everything else, since anything after it is an artefact; a crash reports the first line of the message, cut at 120 characters, so reports stay byte-stable and diffs stay readable.

`web/hooks.ts` exists because upstream files import `./api.js` from `.ts` sources and pull in `zod` and `@wakeshift/sdk`; the resolve hooks point those at the pinned zod entry, a small SDK stub, and the neighbouring `.ts` file. Upstream needs `--experimental-transform-types` for its constructor parameter properties, which is why `web/tsconfig.json` can still say `erasableSyntaxOnly` for the scanner's own files while the upstream sources are only ever stripped at run time.

## One scan (`web/cli.ts`)

1. **Baseline.** One call with the fixture. A rejection is recorded in `rejected` and the variant stops. Each outcome becomes a finding with mutation `baseline` and the distinct operations the call touched.
2. **Request checks.** Every request is matched to an operation; an unmatched one is `undocumented_operation`. A query name outside the operation's parameters is `undocumented_param`; a body problem from `validate` is `undocumented_field` or `request_invalid`. These are the checks that need no mutation at all, and they catch the direction the supplied issue history shows: the tool sending something the contract does not allow.
3. **Response mutations.** For each distinct baseline operation with a constrained success schema, one call per mutation. An outcome identical (outcome and detail) to a baseline outcome is dropped. Without that skip, a tool that already prints `undefined` or already crashes files the same finding once per mutation, drowning the one change that mattered; it also keeps the new-finding count honest when a tool is broken independently of its responses.
4. **Input probes.** For each constrained field of each baseline request, and each fixture argument whose string form equals the field's value, one violating value chosen by the argument's type (`zz-invalid` for an enum and a string, max + 1, min - 1, or `"a"` repeated max + 1 times). The call only proves drift when the value reaches the wire at that operation: a tool that rejects the argument, or accepts it and drops it, has enforced the bound, and counting that as a finding would invert the meaning of the probe.

Findings are deduplicated on `(tool, variant, operation, mutation, outcome, detail)` and sorted by the same tuple with plain code-unit comparison. Two probes can reach the same field through different arguments, and stable order is what makes reports diffable and metrics byte-identical. The report's `commit` is the source folder's name, because the folder is what was actually scanned.

A scan of one commit costs roughly 34 variants times a few dozen calls; the whole 13-commit run takes about 15 s, well inside the 300 s timeout the Python side enforces.

## Scoring (`specreplay/score.py`)

- `matches` requires the same tool, a case variant that is null or equal (a case that names no variant applies to every variant, which is how the issue texts read), a mutation matching one of the case's `fnmatchcase` globs, an outcome in the case's set, and a `detail` that is null or a glob. Globs keep 25 cases readable: one case often covers several tools, and details are path fragments such as `offset:maximum`.
- `evaluate` reports `detected` at the buggy commit, `cleared` at the fix commit, and `caught = detected and cleared is not False`. Requiring cleared is what makes the score mean something: a rule that fires identically before and after the fix is measuring something else, and a case with no fix (`fixed: null`) is judged on detection alone because the ledger marks it open.
- `spec_counts` counts the three response states over the five HTTP methods.
- `triage_counts` matches the hand-checked rows on the exact six-tuple, so a label can never land on a different finding.
- `metrics` derives all 46 numbers from the reports, the ledger, the spec and the triage, and returns them with sorted keys. Recall is rounded to six places. `latest_new_*` counts only documented findings that match no case at all, which is why the two `language` findings at v0.10.0 are reported as known (the #120 ledger case, marked open in the ledger) rather than new.

## The experiment and the demo

`experiment.py` scans the commits in `commits.json` order and writes `reports.json` and the metrics with `indent=1`, `sort_keys=True` and a trailing newline. There are no timestamps and no randomness, so the runner's two runs can be diffed byte for byte. `demo.py` either prints the latest documented findings or replaces the guarded README block: `render` refuses a README in which either marker is missing or repeated, so the generated block cannot silently overwrite the wrong section.

## Triage method

At `46c8fe8`, each documented finding was read against the pinned `src/tools.ts` and the spec by hand and labelled:

- **confirmed**: the source shows the mismatch and the spec states the opposite (for example an input declared `z.number().int().min(0)` where the spec documents `maximum` 10000);
- **unconfirmed**: the mismatch is real only if the live API behaves in a way the spec allows but does not require (the `Metadata: undefined` text when `metadata` is absent);
- **false positive**: the two are not actually in conflict.

Each row carries its evidence in words, and none was labelled from scanner output alone. Of the twelve rows, eleven are confirmed and one unconfirmed; two confirmed rows (the `language` pair) match the #120 ledger case and are therefore known, not new, leaving 10 findings that are not in the ledger. They sit in 4 root causes (see `study/triage.json`). A label says the code and spec visibly differ, not that a user is hurt: the maintainers report in #88 that the API answers 422 to out-of-range values, so a missing limit likely costs a late 422. Nothing was run against the live API.

## Determinism

No clock, no randomness, no network, no environment-dependent ordering: schema properties keep their JSON order, findings are sorted, metrics keys are sorted, commits follow `commits.json`, and every example comes from the schema itself. The fake seeds nothing and the harness keeps no state between calls. That is what lets the experiment be required to produce identical bytes twice.

## What this design cannot see

- Operations whose success response is unconstrained (36 of 98): a wrong value cannot be called wrong.
- Combinations of faults, and payloads the spec permits but the example never produces.
- Anything the spec gets wrong: a spec error looks like a tool bug, and the ledger's citations are the only defence.
- Whether the live API omits an optional field: the findings that depend on it are labelled unconfirmed.
- The checking rules were written knowing this bug class, so the recall figure is in-sample. There is no large unseen set: the ten v0.10.0 findings are an exploratory first look and the hold-out has three cases, and the README says so plainly.

## Alternatives considered

- **Recording live traffic**: needs credentials and a network, and it records the server's behaviour including the bug, so it cannot serve as the contract.
- **Running the MCP SDK**: not in the environment; the three checks that decide a call's outcome are a handful of lines, and emulating them is stated as emulation rather than hidden.
- **Fuzzing the spec**: too many findings that no one can judge, and the triage would dominate the work.
- **Diffing spec versions**: a different question, and the bug ledger is about tools against one spec, not the spec against itself.
- **Multi-fault mutations**: a combinatorial blow-up with poor attribution for a single-fault bug class.
