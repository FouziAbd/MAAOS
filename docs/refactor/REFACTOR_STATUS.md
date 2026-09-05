# MAAOS R0-R6 Refactor Status

## Current state

Claude Code harness: **refreshed for post-P0-P4 refactoring**

Current refactor phase: **R6 COMPLETE** (2026-09-05). All R0-R6 phases are
complete; the next step is `/refactor-audit`. Commit 4 took the owner's option
(a) for report item 6 — a reference-only quarantine of `middleware_layer/` and
`model_layer/` (README banner, `.claude/rules/legacy-packages.md`,
`tests/test_r6_legacy_boundary.py`) instead of a `git mv`, because the move
would break the runner's `--nl live` import, the opt-in live test, the
auto-discovering import guard, and would move the V1 live seam. Relocating that
seam and moving both trees under `legacy/` is a recorded post-R6 owner task.

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
| R5 | COMPLETE | Prove runtime substitutability with a test-only probe domain |
| R6 | COMPLETE | Correctness, typing, CI, dependency and legacy hygiene |

## Baseline command

```bash
python -B -m unittest discover -s tests -t .
```

The live suite-count pin is the single line in `## Baseline evidence` below;
`tests/test_domain_freeze.py::TestHandoffCountsAreMechanical` asserts it
equals unittest discovery. Update that line in the same change set whenever a
phase adds or removes tests.

## Baseline evidence

Current offline suite: 849 tests, deterministic and offline

Frozen pristine baseline: commit
`116d1fdde7b54f5e2f44f98f9f36304c92569162`, captured 2026-09-04 in
`docs/refactor/baseline/` (suite tail, both headless demo transcripts, and
`BASELINE.md`).

## R6 tooling decisions


Decided at pre-flight so R1+ static checks have a fixed target; R6 owns the
actual enforcement work.

| Tool | Decision | Baseline |
|---|---|---|
| mypy | Adopt, scoped to `shared/` + `runtime/` first, `--ignore-missing-imports`; widen later only if R6 calls for it | mypy 2.3.1, captured 2026-09-04: `python -m mypy shared runtime --ignore-missing-imports` → **49 errors in 7 files** (25 source files checked), saved in `docs/refactor/baseline/mypy_pristine.txt`. 49 is the "must not increase" baseline; R6 owns driving it down. **R6 (2026-09-05): 0 errors** on the gate `shared runtime app tests/contract_conformance.py tests/probe_counter.py` (`[tool.mypy]` in `pyproject.toml`, `follow_imports = silent`; 38 files); enforced by `tests/test_r6_typing.py` and CI |
| ruff | Adopt for lint (no autoformat rewrite of frozen code) | NOT INSTALLED at pre-flight. **R6: ruff 0.16.6**, lint-only `E4,E7,E9,F,W` on `shared runtime app` (`[tool.ruff]` in `pyproject.toml`), clean; enforced by `tests/test_r6_tooling.py` and CI |
| uv lock | Adopt `uv` lockfile for dependency reproducibility in R6 | `uv` not on PATH at pre-flight. **R6: uv 0.12.9**, `uv.lock` (91 packages, sha256 hashes, Python ==3.12.*); `uv lock --check` up to date; the frozen `numpy==2.4.0` pin is yanked upstream (WARN, owner) |
| GitHub Actions | Offline suite only — `.github/workflows/offline-tests.yml` added at pre-flight; no live-LM or network-dependent job | In place. **R6:** `uv sync --locked` → offline suite → `ruff check shared runtime app` → `mypy`; not yet observed running (branch unpushed) |
| Import boundaries | Enforce as plain `unittest` tests (no extra tool) as R1-R4 introduce the boundaries | Owned by R1-R4/R6 — in place (`tests/test_no_backend_imports.py`, `tests/test_r4_composition.py`, `tests/test_r1_contracts.py` scans hardened in R6) |

## R6 owner decisions

- Legacy packages: move `middleware_layer/` and `model_layer/` under `legacy/` as a pure `git mv` with no content edits, in its own commit, last in the phase. If moving would break any existing test or import, stop and ask instead. **Outcome (2026-09-05):** the move would break imports and the import guard; the owner chose option (a) — reference-only quarantine (README banner, `.claude/rules/legacy-packages.md`, `tests/test_r6_legacy_boundary.py` pinning the single exception `model_layer.planner.v1_nl_live`). The relocation + move is a post-R6 owner task.
- Commit structure: R6 may be split into up to four commits, in this order — (1) hygiene: observation copying, malformed-backend faults, `NLProposal` split; (2) typing: generics for the shared channels, probe fixture mypy-clean; (3) tooling: `pyproject.toml`, `uv` lockfile, ruff + mypy on `shared runtime app` in `offline-tests.yml`; (4) legacy move. Each commit must leave the suite green and the demos byte-identical. Still one phase, one completion report.

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
