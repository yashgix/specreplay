# SpecDrift, v2 changes (batch 1)

`SPEC.md` is the v1 spec and stays as written. This file lists what changed after v1, why, and what v1 behaviour it touches.

## Changes

1. **Findings are reported as root causes.** v1 counted 10 "new" findings and labelled 9 "confirmed" and 0 "false positives". Those 10 rows are 4 root causes at 8 code sites, and "confirmed" only meant the code and spec visibly differ. `study/triage.json` now carries a `root_causes` list (kind, code sites, note) and a `root_cause` key on each row. The README results block renders a root-cause table from it.
2. **Wording.** No "new bugs", "9 confirmed" or "0 false positives". Missing client-side bounds are described as plausible risks: the server also validates and answers 422. `update_conversation` printing `Metadata: undefined` is a spec ambiguity. The `language` finding is already open upstream (#120, fix PR #121) and is shown as known.
3. **Recall is stated as in-sample.** The rules were written knowing the 25 ledger cases. The README says so in the results block and in the limits. A held-out check is planned for a later batch.
4. **Housekeeping.** `pyproject.toml` (ruff), `Makefile` (`make lint`, `make typecheck`, `make test`, `make experiment`, `make readme`) and `.github/workflows/ci.yml`. The v1 acceptance tests are copied unchanged to `tests/acceptance/` (hashes in the sprint notes) and run by `make test`.

## What v1 behaviour changes

None in the metrics. `results/metrics.json` keeps the v1 keys and values, because the acceptance tests pin them (including `latest_new_confirmed` 9). Only the rendered README block and the triage file's extra keys changed. The README table drops the `confirmed` and `false positives` rows.

## Not in this batch

Probing every branch of a tool (not only the fixture's arguments), a wrapped-prompt length check, a held-out set, and replacing `upstream/` with a fetch script before any publication (`upstream/` holds code and a spec without a licence, so it is analysis only and is never republished).
