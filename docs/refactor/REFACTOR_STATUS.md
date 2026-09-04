# MAAOS R0-R6 Refactor Status

## Current state

Claude Code harness: **refreshed for post-P0-P4 refactoring**

Current refactor phase: **NOT STARTED**

The completed Symbolic-Twin V1 implementation phases P0-P4 remain the frozen
behavioral baseline.

## Refactor phases

| Phase | Status | Purpose |
|---|---|---|
| R0 | PENDING | Protect and characterize the current baseline |
| R1 | PENDING | Introduce narrow typed contracts without behavior change |
| R2 | PENDING | Extract orchestration policies |
| R3 | PENDING | Correct proposal-comparison lifecycle |
| R4 | PENDING | Make domain composition explicit |
| R5 | PENDING | Prove runtime substitutability with a test-only probe domain |
| R6 | PENDING | Correctness, typing, CI, dependency and legacy hygiene |

## Baseline command

```bash
python -B -m unittest discover -s tests -t .
```

Do not hard-code an expected test count here. Record the actual R0 baseline
when R0 begins.

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
