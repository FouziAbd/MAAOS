"""P2 — the V1 symbolic track: applicability, belief, planner, predictor, monitor, PDDL emitter.

This package is the SYMBOLIC side. It imports only `shared` and `domain` — never the backend,
never `runtime` — and `tests/test_no_backend_imports.py` discovered and enforces that the moment
this directory appeared (the guard is fail-closed by design).

Internal layering, per Decision 13 clause 9 (statically guarded in `tests/test_p2_symbolic.py`):

    applicability / belief / planner      may import each other's DECLARATIVE machinery only
    predictor / monitor                   monitor-side; may read `StateSnapshot` geometry
    applicability / belief / planner      must NEVER import predictor or monitor

The prohibition that shapes everything here (Decision 6): symbolic APPLICABILITY and PLANNING
decide from declarative literals alone — no BFS, no reachability, no occupancy, no backend
feasibility, no procedural simulation. A plan that is symbolically valid may still fail in the
authoritative backend; that failure is the designed V1 signal (`ExecutionDiscrepancy`), never a
reason to strengthen this model.
"""
from symbolic.applicability import apply_effects, evaluate, ground_literals
from symbolic.belief import ExactSymbolicBelief
from symbolic.planner import Universe, ground_calls, plan
from symbolic.predictor import (
    first_zone_cell_along,
    predict_symbolic,
    predict_world_candidates,
    push_dir,
)
from symbolic.monitor import monitor_execution
from symbolic.pddl_gen import emit_domain, emit_problem
from symbolic.synthetic import noplan_instance

__all__ = [
    "apply_effects", "evaluate", "ground_literals",
    "ExactSymbolicBelief",
    "Universe", "ground_calls", "plan",
    "first_zone_cell_along", "predict_symbolic", "predict_world_candidates", "push_dir",
    "monitor_execution",
    "emit_domain", "emit_problem",
    "noplan_instance",
]
