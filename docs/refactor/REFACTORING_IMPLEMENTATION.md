# MAAOS R0-R6 Refactoring Implementation Record

This document records the behavior-preserving architectural refactor performed
after completion of Symbolic-Twin BoxPush V1 P0-P4.

Source refactoring plan:

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

Frozen V1 semantic authorities:

- `docs/decisions/P0_V1_DECISIONS.md`
- `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`

Historical P0-P4 implementation record:

`docs/implementation/P0_P4_IMPLEMENTATION.md`

Do not duplicate or rewrite historical P0-P4 claims here.

---

## R0 — Protect the current baseline

Status: COMPLETE (2026-09-04)

Implementation:
- Pristine baseline frozen before any edit (pre-flight, commit `11ff1c3` over
  baseline SHA `116d1fd`): `docs/refactor/baseline/` holds the 641-test suite
  tail, both headless demo transcripts, `BASELINE.md`, and
  `mypy_pristine.txt` (49 errors over `shared/` + `runtime/`, the
  must-not-increase R6 baseline).
- No production code changed: nothing under `shared/`, `domain/`,
  `symbolic/`, `nl/`, `runtime/`, or `functional_layer/` was touched. Domain
  model, projection, planner optimism, discrepancy rules, and trace semantics
  are unmodified.

Tests/evidence:
- New `tests/test_r0_characterization.py` (7 tests; suite 641 -> 648,
  pin updated in `REFACTOR_STATUS.md` in the same change set):
  - `TestDecisionOrderIsPinnedInCode` — hard-coded exact decision sequences:
    symbolic_primary `EXECUTE x7 + HALT`
    (-> `HALTED_REPEATED_FAILURE`), advisory_two_track
    `EXECUTE x7 + REQUEST_PROPOSAL + EXECUTE x2` (-> `GOAL_REACHED`).
  - `TestEpisodesEqualTheFrozenBaselineTranscripts` — cycle-by-cycle
    (decision, grounded call, outcome, discrepancy kind, `[nl recovery]`
    marker), step-accounting footer (9/62/3 advisory, 7/42/3 primary), and
    outcome/reason line all equal the frozen
    `docs/refactor/baseline/demo_*.txt`, with anti-vacuity guards.
  - `TestDesignedDiscrepanciesStayVisible` — exactly three
    `execution_failure_of_applicable_skill` discrepancies per policy, all on
    `Push(agent_0; box_1; delivery_zone)`, each a realized backend execution
    with the discrepancy attached to its failing entry.
- Full suite after the change: `python -B -m unittest discover -s tests -t .`
  -> 648 tests, OK (skipped=1: the pre-existing opt-in live-LM skip).
- Both headless demos re-run post-change and byte-identical to the frozen
  baseline transcripts; mypy unchanged at 49 errors.
- Reviews: `test-reviewer` PASS (sufficiency; transcript rendering verified
  field-by-field against `box_push_v1_run.py`); `architecture-reviewer` PASS
  (0 FAIL; zero production edits, no early R1+ machinery, invariants intact).

Compatibility notes:
- Tests import the backend adapter by established convention (`tests` is
  excluded from the guarded packages in `test_no_backend_imports.py`);
  offline, deterministic, no LM, no render.

Warnings/deferred:
- WARN (accepted): the characterization module caches one episode per policy
  across its test methods; revisit if a later phase makes history entries
  lazy or mutable.
- WARN (accepted): `loop.env.close()` is not called on the two cached
  headless adapters (harmless without render).
- DEFERRED: contract/protocol tests -> R1; policy extraction/purity -> R2;
  comparison lifecycle -> R3; runtime import boundaries/composition -> R4;
  probe domain -> R5; mypy gate, observation aliasing, malformed-backend
  typed faults, ruff/uv/CI enforcement -> R6.

---

## R1 — Introduce contracts without changing behavior

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R2 — Extract orchestration policies

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R3 — Correct the comparison lifecycle

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R4 — Make domain composition explicit

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R5 — Prove architectural substitutability

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R6 — Correctness and repository hygiene

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## Final Definition of Completion

Status: NOT YET AUDITED

Record the final `/refactor-audit` result here only after R6.
