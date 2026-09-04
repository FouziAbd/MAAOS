# MAAOS R0-R6 Refactor Status

## Current state

Claude Code harness: **refreshed for post-P0-P4 refactoring**

Current refactor phase: **R4 COMPLETE** (next: R5)

The completed Symbolic-Twin V1 implementation phases P0-P4 remain the frozen
behavioral baseline.

## Refactor phases

| Phase | Status | Purpose |
|---|---|---|
| R0 | COMPLETE | Protect and characterize the current baseline |
| R1 | COMPLETE | Introduce narrow typed contracts without behavior change |
| R2 | COMPLETE | Extract orchestration policies |
| R3 | COMPLETE | Correct proposal-comparison lifecycle |
| R4 | COMPLETE | Make domain composition explicit |
| R5 | PENDING | Prove runtime substitutability with a test-only probe domain |
| R6 | PENDING | Correctness, typing, CI, dependency and legacy hygiene |

## Baseline command

```bash
python -B -m unittest discover -s tests -t .
```

The live suite-count pin is the single line in `## Baseline evidence` below;
`tests/test_domain_freeze.py::TestHandoffCountsAreMechanical` asserts it
equals unittest discovery. Update that line in the same change set whenever a
phase adds or removes tests.

## Baseline evidence

Current offline suite: 744 tests, deterministic and offline

Frozen pristine baseline: commit
`116d1fdde7b54f5e2f44f98f9f36304c92569162`, captured 2026-09-04 in
`docs/refactor/baseline/` (suite tail, both headless demo transcripts, and
`BASELINE.md`).

## R6 tooling decisions

Decided at pre-flight so R1+ static checks have a fixed target; R6 owns the
actual enforcement work.

| Tool | Decision | Baseline |
|---|---|---|
| mypy | Adopt, scoped to `shared/` + `runtime/` first, `--ignore-missing-imports`; widen later only if R6 calls for it | mypy 2.3.1, captured 2026-09-04: `python -m mypy shared runtime --ignore-missing-imports` → **49 errors in 7 files** (25 source files checked), saved in `docs/refactor/baseline/mypy_pristine.txt`. 49 is the "must not increase" baseline; R6 owns driving it down |
| ruff | Adopt for lint (no autoformat rewrite of frozen code) | NOT INSTALLED at pre-flight |
| uv lock | Adopt `uv` lockfile for dependency reproducibility in R6 | `uv` not on PATH at pre-flight |
| GitHub Actions | Offline suite only — `.github/workflows/offline-tests.yml` added at pre-flight; no live-LM or network-dependent job | In place |
| Import boundaries | Enforce as plain `unittest` tests (no extra tool) as R1-R4 introduce the boundaries | Owned by R1-R4/R6 |

## Active V1 runner

```bash
cd functional_layer/custom_env/box_push/env
python box_push_v1_run.py
```

## Refactor authority

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

## Update discipline

Only update a phase to `IN PROGRESS` or `COMPLETE` from actual implementation
and verification evidence.

Do not mark later phases complete because an earlier change happens to satisfy
part of a later criterion.
