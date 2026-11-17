# Changes since v1

The first version is git tag `v1-pipeline-final`. This file lists what changed after it, why, and what v1 behaviour it touches.

## Reporting

1. **Findings are reported as root causes.** v1 counted 10 "new" findings and labelled 9 "confirmed" and 0 "false positives". Those 10 rows are 4 root causes at 9 code sites, and "confirmed" only meant the code and spec visibly differ. `study/triage.json` now carries a `root_causes` list (kind, code sites, note) and a `root_cause` key on each row. The README results block renders a root-cause table from it. Missing client-side bounds are described as plausible risks, since the server also validates and answers 422. `update_conversation` printing `Metadata: undefined` is a spec ambiguity. The `language` finding is already open upstream (#120, fix PR #121) and is shown as known.
2. **Recall is stated as in-sample.** The rules were written knowing the 25 ledger cases. The README says so in the results block and in the limits. A small held-out check was added later (see below).

## What v1 behaviour changes

None in the metrics. `results/metrics.json` keeps the v1 keys and values, because the v1 acceptance tests pin them (including `latest_new_confirmed` 9). Those tests are kept in `tests/acceptance/` with their assertions unchanged and run by `make test`. Only the rendered README block and the triage file's extra keys changed. The README table drops the `confirmed` and `false positives` rows.

## Wide mode and hold-out

3. **Wide mode** (`wide.py`, `SPECREPLAY_WIDE=1`): arguments a fixture leaves out are set to a sentinel and probed if they reach a constrained field, and one extra fixture variant (`list_calls` by number) is added. It runs beside the v1 scan and writes `results/wide.json`. The v1 scan, `results/metrics.json` and `results/reports.json` are unchanged by wide mode itself. The probe code moved from `web/cli.ts` to `web/probes.ts` with no change in behaviour (reports byte-identical).
4. **Wrapped-prompt check** (`web/wrapped.ts`, wide mode only): measures what the tool adds to `system_prompt` in hosted mode by calling the real handler, and flags an accepted prompt that goes out over the documented maximum. Measured: 528 characters added, so the longest safe hosted prompt is 19472 characters.
5. **Hold-out** (`study/holdout.json`, `holdout.py`, `results/holdout.json`): 3 cases from repository history outside the 25-case ledger. Sources, the case list and first-run predictions were written after the tag `rules-frozen` and before the first run. Sources are fetched by `tools/holdout_sources.sh` into a scratch folder and are not stored here. Old commits that lack `src/output-schemas.ts` get an empty schema table so the loader runs, so output-schema checks do not apply to them.

## Fixes after the freeze (code changed after `rules-frozen`)

A review of the wide mode and hold-out code found defects. These are bug fixes, not tuning: none of them was chosen by looking at which hold-out case they would help, and the 25-case results do not move (`results/metrics.json` and `results/reports.json` are byte-identical before and after). The rule code that changed after the freeze:

- `web/openapi.ts`, `validate`: `anyOf` accepts any fully valid branch, `allOf` enforces every branch (the first-branch shortcut remains only in `effective`, which example and mutation generation use). String `minLength` and `maxLength` count characters (code points), as JSON Schema does. Zod counts UTF-16 units, so a client-side `.max()` on an emoji prompt counts differently from the spec. The wrapper finding below uses the spec side. Tests in `web/openapi.test.cjs` that encoded the shortcut were replaced.
- `web/openapi.ts`, `example`: generated values satisfy `minLength`, `maxLength`, `minimum`, `maximum` and `minItems`. `web/cli.ts` now validates every generated success example against its own schema before any replay and stops if one fails. None of the shipped baselines failed.
- `web/wrapped.ts`: lengths are counted in characters, and the call and request counts are measured (the earlier count of three calls and no requests was wrong). The threshold is now stated for plain ASCII prompts that need no trimming and are not already wrapped: the tool trims the prompt and unwraps its own wrapper before wrapping (`src/tools.ts:203-224`), so padded or already-wrapped input sends less.
- `specreplay/score.py`, `evaluate`: a case with no report for its buggy or fixed commit is unevaluated (`unevaluated: true`, not caught). Complete cases return the same fields as before.
- `holdout.py` and `study/holdout.json`: each case has a frozen detection predicate (tool, variant, outcome, operation, never wording), a frozen fixture where the old fixtures could not trigger the bug, and a trigger check. A case is `caught` only if the trigger is seen, the finding is present at the buggy commit and absent at the fix. A case whose trigger is not seen is `not_exercised` and counts neither way. The predicates and fixtures were written after the first run, from the pull request text.
- Results after the corrections: `make wide` gives the same counts as before. The hold-out is 1 caught, 2 missed, 0 not exercised, now with both missed bugs shown to be exercised (the tool refuses a media-only send before the fix, and refuses a scoped call with a filter after it).

## Data

`upstream/` holds code and a spec without a usable license for redistribution, so it is not committed. `tools/fetch_data.py` rebuilds it and checks it against `upstream/MANIFEST.json`.
