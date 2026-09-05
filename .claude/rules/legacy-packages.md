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
- **one named exception**: `model_layer.planner.v1_nl_live` is a **supported V1
  live seam** (the only dspy binding; `build_live_seam(NLRuntimeConfig)`),
  consumed by the runner's opt-in `--nl live` path and by the opt-in
  `tests/test_p3_live_lm.py` (`MAAOS_LIVE_LM=1`). It lives on the legacy side only
  because the import guard forbids `nl/` from importing dspy.

The exception list is pinned by `tests/test_r6_legacy_boundary.py`; extending it
requires editing that test's allowlist deliberately.

Post-R6, owner task (recorded in `docs/refactor/REFACTORING_IMPLEMENTATION.md`
§R6 DEFERRED): relocate the live NL seam out of `model_layer/` to a non-legacy
home compatible with the import guard, then move both legacy trees under
`legacy/`. Do not perform that move as part of an unrelated R-phase.

See also `.claude/rules/legacy-reference.md` for how legacy material may be
inspected and classified before any reuse.
