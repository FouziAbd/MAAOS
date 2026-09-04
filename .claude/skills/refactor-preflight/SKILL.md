---
name: refactor-preflight
description: One-time preparation before /refactor-phase R0 — capture the pristine baseline, make the suite-count pin movable, add offline CI, record tooling decisions and the next-domain note. Run once, review, commit.
disable-model-invocation: true
---

# R0 Pre-flight

Run this exactly once, on a clean tree, before `/refactor-phase R0`.
Everything here is preparation; it must not change product behavior.

## 0. Read first

- `CLAUDE.md`
- `docs/refactor/REFACTOR_STATUS.md`
- `.claude/rules/suite-count-pin.md`
- `tests/test_domain_freeze.py` (class `TestHandoffCountsAreMechanical`)
- `functional_layer/custom_env/box_push/env/box_push_v1_run.py --help`

## 1. Capture the pristine baseline BEFORE editing anything

Create `docs/refactor/baseline/` and save:

```bash
python -B -m unittest discover -s tests -t . 2>&1 | tail -5 > docs/refactor/baseline/tests_pristine.txt
cd functional_layer/custom_env/box_push/env
SDL_VIDEODRIVER=dummy python box_push_v1_run.py --headless --policy advisory_two_track > ../../../../docs/refactor/baseline/demo_advisory_two_track.txt
SDL_VIDEODRIVER=dummy python box_push_v1_run.py --headless --policy symbolic_primary  > ../../../../docs/refactor/baseline/demo_symbolic_primary.txt
```

Write `docs/refactor/baseline/BASELINE.md` with: date, `git rev-parse HEAD`,
the exact test count, and a note that R0 characterization tests must
reproduce the decision sequences in the demo files.

## 2. Make the suite-count pin movable

`tests/test_domain_freeze.py::TestHandoffCountsAreMechanical` reads
`docs/handoff/section18.md` and asserts the documented count equals discovery.
R0 adds tests, so this would fail on the first phase.

Do the minimum:

1. Change the test to read `docs/refactor/REFACTOR_STATUS.md` instead.
   Keep the regex, the "exactly once" assertion, and the discovery comparison.
   Update the docstring to say where the live pin now lives.
2. In `docs/refactor/REFACTOR_STATUS.md` add a section `## Baseline evidence`
   containing exactly one line of the form
   `Current offline suite: N tests, deterministic and offline`
   plus the frozen baseline SHA and a pointer to `docs/refactor/baseline/`.
3. In `docs/handoff/section18.md` annotate the historical `641 tests, ...`
   phrase so the phrase no longer matches the regex verbatim
   (e.g. `641 tests (P0-P4 freeze count; live pin now in docs/refactor/REFACTOR_STATUS.md), deterministic and offline`).
   Do not delete or rewrite anything else in that historical document.
4. Remove the "Do not hard-code an expected test count here" sentence in
   `REFACTOR_STATUS.md` and replace it with a pointer to the pin line.

This is NOT weakening a test: the mechanical check is preserved, only its
source document moves.

## 3. Record R6 tooling decisions now (so R1 static checks have a target)

Add a `## R6 tooling decisions` table to `REFACTOR_STATUS.md`:
mypy (scoped to `shared/` + `runtime/` first), ruff, uv lock, GitHub Actions,
import-boundary tests in unittest. If `mypy` is installed, run
`python -m mypy shared runtime --ignore-missing-imports`, save the output to
`docs/refactor/baseline/mypy_pristine.txt`, and record the error count as the
"must not increase" baseline. If it is not installed, record that and ask the
user to install it; do not `pip install` yourself.

## 4. Add offline CI

Create `.github/workflows/offline-tests.yml`: ubuntu-latest, Python 3.12,
`SDL_VIDEODRIVER=dummy`, `pip install -r requirements.txt`, then the full
offline suite. Nothing else. No live LM, no network-dependent job.

## 5. Next-domain note

Create `docs/refactor/NEXT_DOMAIN.md` with the fields the supervisor report's
Phase 4/5 defaults depend on (observability, state representation, action
model, concurrency, uncertainty). Leave it marked `NOT YET ANSWERED` and tell
the user to fill it in or mark it "Unknown" before R4.

## 6. Verify and report

```bash
git diff --check
python -B -m unittest discover -s tests -t .
```

Ask `test-reviewer` to confirm the pin move preserves the mechanical check.
Then report files changed, commands run, the recorded baseline count and SHA,
and stop. Do not start R0 in the same invocation.
