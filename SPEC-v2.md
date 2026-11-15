# SpecDrift, v2 changes (batch 1)

`SPEC.md` is the v1 spec and stays as written. This file lists what changed after v1, why, and what v1 behaviour it touches.

## Changes

1. **Findings are reported as root causes.** v1 counted 10 "new" findings and labelled 9 "confirmed" and 0 "false positives". Those 10 rows are 4 root causes at 8 code sites, and "confirmed" only meant the code and spec visibly differ. `study/triage.json` now carries a `root_causes` list (kind, code sites, note) and a `root_cause` key on each row. The README results block renders a root-cause table from it.
2. **Wording.** No "new bugs", "9 confirmed" or "0 false positives". Missing client-side bounds are described as plausible risks: the server also validates and answers 422. `update_conversation` printing `Metadata: undefined` is a spec ambiguity. The `language` finding is already open upstream (#120, fix PR #121) and is shown as known.
3. **Recall is stated as in-sample.** The rules were written knowing the 25 ledger cases. The README says so in the results block and in the limits. A held-out check is planned for a later batch.
4. **Housekeeping.** `pyproject.toml` (ruff), `Makefile` (`make lint`, `make typecheck`, `make test`, `make experiment`, `make readme`) and `.github/workflows/ci.yml`. The v1 acceptance tests are copied unchanged to `tests/acceptance/` (hashes in the sprint notes) and run by `make test`.

## What v1 behaviour changes

None in the metrics. `results/metrics.json` keeps the v1 keys and values, because the acceptance tests pin them (including `latest_new_confirmed` 9). Only the rendered README block and the triage file's extra keys changed. The README table drops the `confirmed` and `false positives` rows.

## Batch 2

5. **Wide mode** (`wide.py`, `SPECDRIFT_WIDE=1`): arguments a fixture leaves out are set to a sentinel and probed if they reach a constrained field, and one extra fixture variant (`list_calls` by number) is added. It runs beside the v1 scan and writes `results/wide.json`. The v1 scan, `results/metrics.json` and `results/reports.json` are unchanged. The probe code moved from `web/cli.ts` to `web/probes.ts` with no change in behaviour (reports byte-identical).
6. **Wrapped-prompt check** (`web/wrapped.ts`, wide mode only): measures what the tool adds to `system_prompt` in hosted mode by calling the real handler, and flags an accepted prompt that goes out over the documented maximum. Measured: 528 characters added, so the longest safe hosted prompt is 19472 characters.
7. **Hold-out** (`study/holdout.json`, `holdout.py`, `results/holdout.json`): 3 cases from repository history outside the 25-case ledger, written down with predictions after the scanner was tagged `rules-frozen` and before it was run on them. Sources are fetched by `tools/holdout_sources.sh` into a scratch folder and are not stored in this repository. Old commits that lack `src/output-schemas.ts` get an empty schema table so the loader runs, which also means output-schema checks do not apply to them.

## Not in this batch

Replacing `upstream/` with a fetch script before any publication (`upstream/` holds code and a spec without a licence, so it is analysis only and is never republished).
