# CHECKED-IN PROCESS EVIDENCE, not part of the test suite (it MUTATES product files and
# restores them). Run manually from the repo root:  python -B docs/implementation/p2_mutation_harness.py
# Every mutation must be KILLED; a survivor is a coverage gap. Bytecode is disabled and
# __pycache__ cleared before every run so same-length edits cannot reuse stale .pyc.
"""P2 symbolic-track mutation harness."""
import pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
AP, BE, PL, PR, MO, PG, SY = ("symbolic/applicability.py", "symbolic/belief.py",
    "symbolic/planner.py", "symbolic/predictor.py", "symbolic/monitor.py",
    "symbolic/pddl_gen.py", "symbolic/synthetic.py")

M = [
 # ── applicability ──
 ("A1 applicability ignores a failing precondition", AP,
  "        if not state.holds(literal)", "        if False and not state.holds(literal)"),
 ("A2 inapplicable becomes validated", AP,
  "    if unsatisfied:\n        return SymbolicallyInapplicable(",
  "    if False:\n        return SymbolicallyInapplicable("),
 ("A3 outside-model becomes validated", AP,
  "    if isinstance(resolved, OutsideSymbolicModel):\n        return resolved",
  "    if False:\n        return resolved"),
 ("A4 negative effects not applied", AP,
  "        else:\n            literals.discard(literal)", "        else:\n            pass"),
 ("A5 positive effects not applied", AP,
  "        if effect.positive:\n            literals.add(literal)",
  "        if effect.positive:\n            pass"),
 # ── belief ──
 ("B1 sync clears tracked literals", BE,
  "        self._projected = self._projection.monitored_view(self._project(snapshot))",
  "        self._projected = self._projection.monitored_view(self._project(snapshot))\n        self._tracked = SymbolicState.of(())"),
 ("B2 failure retracts regardless of world_changed", BE,
  "                self._tracked, literal, succeeded=False, world_changed=result.world_changed",
  "                self._tracked, literal, succeeded=False, world_changed=True"),
 ("B3 consuming-skill failure retracts preconditions", BE,
  "        # FAILURE: never apply success effects; a consuming skill retracts nothing; an",
  "        for literal in ground_literals(resolved, call, [e.predicate for e in negative]):\n            self._tracked = self._projection.retract(self._tracked, literal)\n        # FAILURE: never apply success effects; a consuming skill retracts nothing; an"),
 ("B4 success skips the negative effects", BE,
  "            for literal in ground_literals(resolved, call, [e.predicate for e in negative]):\n                self._tracked = self._projection.retract(self._tracked, literal)\n            return",
  "            return"),
 ("B5 outside-model outcomes mutate the belief", BE,
  "        if isinstance(resolved, OutsideSymbolicModel):\n            return",
  "        if isinstance(resolved, OutsideSymbolicModel):\n            self._tracked = SymbolicState.of(())\n            return"),
 # ── planner ──
 ("P1 noplan becomes empty planfound", PL,
  "        return NoPlan(\n            reason=f\"search space exhausted",
  "        return PlanFound(plan=(), model_version=model_version) or NoPlan(\n            reason=f\"search space exhausted"),
 ("P2 budget exhaustion returns noplan", PL,
  "                return PlannerFailure(\n                    error=f\"node budget {node_budget} exceeded after {len(visited)} states\",\n                    timed_out=True,\n                )",
  "                return NoPlan(reason=\"budget\")"),
 ("P3 exceptions escape untyped", PL,
  "    except Exception as error:                           # any computation failure is typed\n        return PlannerFailure(error=f\"{type(error).__name__}: {error}\")",
  "    except ZeroDivisionError as error:\n        return PlannerFailure(error=f\"{type(error).__name__}: {error}\")"),
 ("P4 goal check drops a literal", PL,
  "    return all(state.holds(literal) for literal in goal)",
  "    return any(state.holds(literal) for literal in goal) if goal else True"),
 ("P5 grounding drops the coop pair collapse", PL,
  "                if call.key() not in seen:", "                if True:"),
 ("P6 expansion order not deterministic", PL,
  "    calls.sort(key=lambda c: (str(c.skill), c.key()))", "    pass"),
 ("P7 satisfied goal returns NoPlan", PL,
  "        if _goal_satisfied(state, goal):\n            return PlanFound(plan=(), model_version=model_version)",
  "        if _goal_satisfied(state, goal):\n            return NoPlan(reason=\"already satisfied\")"),
 # ── predictor ──
 ("R1 push_dir tie preference flipped (killed by the synthetic-zone tie pin)", PR,
  "    if abs(dx) >= abs(dy) and dx != 0:", "    if abs(dx) > abs(dy) and dx != 0:"),
 ("R2 ray miss returns a guessed cell", PR,
  "    if not candidates:\n        return None", "    if not candidates:\n        return zone_cells[0]"),
 ("R3 pose cell sign flip", PR,
  "        pose = (box.position[0] - dx, box.position[1] - dy)",
  "        pose = (box.position[0] + dx, box.position[1] + dy)"),
 ("R4b push uses push_dir not agent facing (real)", PR,
  "        agent = snapshot.agent(call.agents[0])\n        direction = agent.direction",
  "        agent = snapshot.agent(call.agents[0])\n        direction = push_dir(snapshot.box(call.box).position, zone_cells)"),
 ("R5 coop emits one candidate", PR,
  "        return (\n            _with_agent(_with_agent(base, first, front, direction), second, rear, direction),\n            _with_agent(_with_agent(base, first, rear, direction), second, front, direction),\n        )",
  "        return (\n            _with_agent(_with_agent(base, first, front, direction), second, rear, direction),\n        )"),
 ("R6 outside-model skills get predictions", PR,
  "    return ()                                # Explore / Wait: outside the symbolic model",
  "    return (snapshot,)"),
 ("R7 delivered flag not predicted", PR,
  "        predicted = _with_box(snapshot, call.box, landing, delivered=True)\n        predicted = _with_agent(",
  "        predicted = _with_box(snapshot, call.box, landing, delivered=False)\n        predicted = _with_agent("),
 # ── monitor ──
 ("M1 failure of applicable skill unreported", MO,
  "    if not succeeded:", "    if False:"),
 ("M2 symbolic mismatch unreported", MO,
  "    if predicted_symbolic is not None and not projection.agrees(",
  "    if False and predicted_symbolic is not None and not projection.agrees("),
 ("M3 world membership accepts any key", MO,
  "        if observed_key not in candidate_keys:", "        if False:"),
 ("M4 outside-model failure silently ok", MO,
  "        if succeeded:\n            return ()", "        return ()"),
 ("M5 world mismatch reported with symbolic keys", MO,
  "                predicted_world_key=candidate_keys[0],\n                observed_world_key=observed_key,",
  "                predicted_symbolic_key=projection.monitored_key(predicted_symbolic) if predicted_symbolic else None,\n                observed_symbolic_key=projection.monitored_key(observed_symbolic) if predicted_symbolic else None,"),
 # ── pddl / synthetic ──
 ("G1 emitter drops an action", PG,
  "    for ir in sorted(domain.skills, key=lambda s: s.signature.backend_dispatch_key):",
  "    for ir in sorted(domain.skills, key=lambda s: s.signature.backend_dispatch_key)[1:]:"),
 ("G2 emitter drops the goal", PG,
  "    lines.append(f\"  (:goal (and {goal_atoms}))\")", "    lines.append(\"  (:goal (and ))\")"),
 ("G3 soln banner loses the optimism note", PG,
  "        \";; plan is OPTIMISTIC by design: executed literally, its final step fails in the\",",
  "        \";; plan note\","),
 ("S1 synthetic gains a second agent", SY,
  "    universe = Universe(agents=(AGENT_0,), boxes=(BOX_HEAVY,), zone=DELIVERY_ZONE)",
  "    from domain.box_push_v1 import AGENT_1\n    universe = Universe(agents=(AGENT_0, AGENT_1), boxes=(BOX_HEAVY,), zone=DELIVERY_ZONE)"),
 # ── X-series: pins added by the test-review fix round ──
 ("X1 monitor swaps the symbolic key pair", MO,
  "            predicted_symbolic_key=projection.monitored_key(predicted_symbolic),\n            observed_symbolic_key=projection.monitored_key(observed_symbolic),",
  "            predicted_symbolic_key=projection.monitored_key(observed_symbolic),\n            observed_symbolic_key=projection.monitored_key(predicted_symbolic),"),
 ("X2 monitor swaps the message orientation", MO,
  "            message=f\"monitored symbolic mismatch on success: predicted-only=\"\n                    f\"{only_predicted}, observed-only={only_observed}\",",
  "            message=f\"monitored symbolic mismatch on success: predicted-only=\"\n                    f\"{only_observed}, observed-only={only_predicted}\","),
 ("X3 first_zone_cell_along takes the FARTHEST cell", PR,
  "    return min(candidates)[1]", "    return max(candidates)[1]"),
 ("X4 unsatisfied list truncated to one literal", AP,
  "            unsatisfied=unsatisfied,", "            unsatisfied=unsatisfied[:1],"),
 ("X6 goto prediction hardcodes LEFT", PR,
  "        box = snapshot.box(call.box)\n        direction = push_dir(box.position, zone_cells)\n        dx, dy = _DIRECTION_VECTORS[direction]",
  "        box = snapshot.box(call.box)\n        direction = 2\n        dx, dy = _DIRECTION_VECTORS[direction]"),
 ("X7 coop prediction hardcodes LEFT", PR,
  "        direction = push_dir(box.position, zone_cells)   # coop's D comes from the box and zone",
  "        direction = 2   # coop's D comes from the box and zone"),
 ("X8 failure discrepancy loses class and detail", MO,
  "                    f\"{result.outcome}, raw={result.raw_label}, \"\n                    f\"failure_class={result.failure_class}, detail={result.detail!r}\",",
  "                    f\"{result.outcome}, raw={result.raw_label}\",",),
 ("X9 unexpected-outcome message genericized", MO,
  "            message=f\"registry-only skill {call.skill} did not succeed: outcome=\"\n                    f\"{result.outcome}, raw={result.raw_label}\",",
  "            message=\"discrepancy\","),
 ("X10 _with_agent keeps the old facing", PR,
  "            AgentSnapshot(a.agent_id, position, direction) if a.agent_id.value == agent_id else a",
  "            AgentSnapshot(a.agent_id, position, a.direction) if a.agent_id.value == agent_id else a"),
 ("V1 direction-vector table transposed (DOWN<->UP)", PR,
  "_DIRECTION_VECTORS = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}",
  "_DIRECTION_VECTORS = {0: (1, 0), 1: (0, -1), 2: (-1, 0), 3: (0, 1)}"),
 ("Z1 zone identity check deleted", PR,
  "    if call.zone is not None and call.zone != zone:", "    if False:"),
 ("L1 guard escape: bare package-root import", AP,
  "    return SymbolicState.of(literals)",
  "    return SymbolicState.of(literals)\n\n\nimport symbolic  # mutant: package-root escape"),
 ("L2 guard escape: aliased predictor import-from", PL,
  "from symbolic.applicability import apply_effects, evaluate",
  "from symbolic.applicability import apply_effects, evaluate\nfrom symbolic import predictor as _oracle  # mutant"),
 ("L3 guard escape: star-import from the package root", PL,
  "from symbolic.applicability import apply_effects, evaluate",
  "from symbolic.applicability import apply_effects, evaluate\nfrom symbolic import *  # noqa: F403 -- mutant"),
 # ── VA-series: pins added by the V1-acceptance review round ──
 ("VA1 failed rejection reclassified as unchanged", "functional_layer/custom_env/box_push/env/box_push_v1_adapter.py",
  "            elif finished_on_first_call:\n                failure_class = FailureStateClass.BACKEND_REJECTED_BEFORE_TRANSITION",
  "            elif finished_on_first_call:\n                failure_class = FailureStateClass.UNCHANGED"),
 ("VA2 trace accepts a faulted-and-executed cycle", "shared/trace_schema.py",
  "            early = [f for f in self.faults if f.arises_before_execution]",
  "            early = []"),
 ("VA3 planner expansion order reversed changes the plan identity", "symbolic/planner.py",
  "    calls.sort(key=lambda c: (str(c.skill), c.key()))",
  "    calls.sort(key=lambda c: (str(c.skill), c.key()), reverse=True)"),
]

def run():
    for cache in ROOT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"],
                          cwd=ROOT, capture_output=True, text=True).returncode == 0

bad = []
for name, rel, old, new in M:
    path = ROOT / rel
    original = path.read_text()
    if old not in original:
        bad.append((name, "ANCHOR")); print(f"ANCHOR??  {name}"); continue
    path.write_text(original.replace(old, new, 1))
    try:
        if run():
            bad.append((name, "SURVIVED")); print(f"SURVIVED  {name}")
        else:
            print(f"killed    {name}")
    finally:
        path.write_text(original)
print(f"\n{len(M)-len(bad)}/{len(M)} killed")
for n, w in bad: print(f"  !! {n}: {w}")
