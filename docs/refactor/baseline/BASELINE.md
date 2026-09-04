# R0-R6 Pristine Baseline

Captured by `/refactor-preflight` before any refactor edit.

- Date: 2026-09-04
- Commit: `116d1fdde7b54f5e2f44f98f9f36304c92569162` (branch `middleware_layer`)
- Offline suite: **641 tests**, `OK (skipped=1)` via
  `python -B -m unittest discover -s tests -t .`
  (tail saved in `tests_pristine.txt`; the single skip is the pre-existing
  opt-in live-LM skip, not a regression)

## Demo evidence

Captured headless with `SDL_VIDEODRIVER=dummy` from
`functional_layer/custom_env/box_push/env/box_push_v1_run.py`:

- `demo_advisory_two_track.txt` — `--policy advisory_two_track`:
  GOAL_REACHED, executive steps 9, primitive steps 62, discrepancies 3,
  one `[nl recovery]` after three `Push(agent_0; box_1; delivery_zone)`
  failures.
- `demo_symbolic_primary.txt` — `--policy symbolic_primary`:
  HALTED_REPEATED_FAILURE after the same three failures,
  executive steps 7, primitive steps 42, discrepancies 3.

## Binding requirement for R0

R0 characterization tests must reproduce the decision sequences recorded in
these two demo files (cycle-by-cycle call, decision kind, and outcome), not
merely the terminal status lines.
