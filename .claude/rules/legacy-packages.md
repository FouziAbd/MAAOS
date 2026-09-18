---
paths:
  - "legacy/**/*"
  - "functional_layer/custom_env/box_push/env/box_push_v1_nl_live.py"
  - "shared/**/*"
  - "runtime/**/*"
  - "app/**/*"
  - "tests/**/*"
---

# Legacy Packages (R6 owner decision, option (a) for report Phase 6 item 6; relocation completed 2026-09-18)

`legacy/` holds the **pre-V1 reference code**: `middleware_layer/`,
`model_layer/`, `utils/` and the empty `ui/`. They are not an alternative
supported Symbolic-Twin runtime and must not be used as architectural
precedent.

Status of the legacy tree:

- `legacy/` is a plain directory (no `__init__.py`); the trees keep their
  original import names (`middleware_layer.*`, `model_layer.*`, `utils.*`)
  and are run with `legacy/` on `sys.path` — the legacy runners under
  `functional_layer/` mount it themselves; the in-tree demos run as
  `cd legacy && python -m model_layer.agent`;
- excluded from the mypy gate (`[tool.mypy] files` in `pyproject.toml` does not
  list it; `follow_imports = silent`) and from ruff (`[tool.ruff]
  extend-exclude`);
- skipped by the auto-discovering import guard
  (`tests/test_no_backend_imports.py::LEGACY_PACKAGES` lists `legacy`, NOT
  the four tree names, so a resurrected top-level copy is guarded fail-closed);
- must **not be imported** by `shared/`, `runtime/`, `app/`, or `tests/`
  (statically or via `importlib`/`__import__`) under any name — `legacy.*`
  resolves as a namespace package from the repo root, so `legacy`,
  `middleware_layer`, `model_layer` and `utils` are all banned roots;
- **no exception**: the supported V1 live seam (the only dspy binding;
  `build_live_seam(NLRuntimeConfig)`) is
  `functional_layer/custom_env/box_push/env/box_push_v1_nl_live.py`, beside the
  V1 runner, consumed by the runner's opt-in `--nl live` path and by the opt-in
  `tests/test_p3_live_lm.py` (`MAAOS_LIVE_LM=1`). It was relocated there on
  2026-09-18 from `model_layer/planner/v1_nl_live.py`; it sits outside the
  guarded packages because the import guard forbids `nl/` from importing dspy.

The (empty) allowlist and the layout are pinned by
`tests/test_r6_legacy_boundary.py`; adding a name to the allowlist is a
deliberate owner-level decision.

The post-R6 owner task (seam relocation, then `git mv` under `legacy/`) is
**done** (2026-09-18; `docs/refactor/REFACTORING_IMPLEMENTATION.md`
§"Post-R6 maintenance: legacy relocation"). Do not move or delete the legacy
tree again without an explicit owner request.

See also `.claude/rules/legacy-reference.md` for how legacy material may be
inspected and classified before any reuse.
