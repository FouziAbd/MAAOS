"""Executive runtime state (P4 loop-manager territory).

Deliberately OUTSIDE `shared/`: `shared/` holds frozen typed contracts only. The symbolic track
must never import this package — repeated-failure bookkeeping must not become a hidden symbolic
feasibility predicate (SUPERVISOR_P0_P4_CONTRACT.md:118). Enforced by
`tests/test_no_backend_imports.py`.
"""
