---
paths:
  - "middleware_layer/**/*"
  - "model_layer/**/*"
  - "shared/**/*"
  - "runtime/**/*"
  - "app/**/*"
  - "tests/**/*"
---

# Legacy Packages (R6 owner decision, option (a) for report Phase 6 item 6)

`middleware_layer/` and `model_layer/` are **pre-V1 reference code**. They are not
an alternative supported Symbolic-Twin runtime and must not be used as
architectural precedent.

Status of the two trees:

- excluded from the mypy gate (`[tool.mypy] files` in `pyproject.toml` does not
  list them; `follow_imports = silent`) and from ruff (`[tool.ruff]
  extend-exclude`);
- they must **not be imported** by `shared/`, `runtime/`, `app/`, or `tests/`
  (statically or via `importlib`/`__import__`);
- **no exception**: the supported V1 live seam (the only dspy binding;
  `build_live_seam(NLRuntimeConfig)`) is
  `functional_layer/custom_env/box_push/env/box_push_v1_nl_live.py`, beside the
  V1 runner, consumed by the runner's opt-in `--nl live` path and by the opt-in
  `tests/test_p3_live_lm.py` (`MAAOS_LIVE_LM=1`). It was relocated there on
  2026-09-18 from `model_layer/planner/v1_nl_live.py`; it sits outside the
  guarded packages because the import guard forbids `nl/` from importing dspy.

The (empty) allowlist is pinned by `tests/test_r6_legacy_boundary.py`; adding a
name to it is a deliberate owner-level decision.

Post-R6, owner task (recorded in `docs/refactor/REFACTORING_IMPLEMENTATION.md`
§R6 DEFERRED): the seam relocation is done; moving both legacy trees under
`legacy/` remains. Do not perform that move as part of an unrelated R-phase.

See also `.claude/rules/legacy-reference.md` for how legacy material may be
inspected and classified before any reuse.
