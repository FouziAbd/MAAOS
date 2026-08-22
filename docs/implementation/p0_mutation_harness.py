# CHECKED-IN PROCESS EVIDENCE, not part of the test suite (it MUTATES product files and
# restores them). Run manually from the repo root:  python -B docs/implementation/p0_mutation_harness.py
# Every mutation must be KILLED; a survivor is a coverage gap. Bytecode is disabled and
# __pycache__ cleared before every run so same-length edits cannot reuse stale .pyc.
"""P0 close-out mutation harness. Bytecode disabled and __pycache__ cleared before every run."""
import pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
DOM, BE = "domain/box_push_v1.py", "functional_layer/custom_env/box_push/env/skill_executor_push.py"
MAE = "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py"
EX, TS, SS, SK, FA, DI, SY = ("shared/execution.py", "shared/trace_schema.py",
    "shared/state_snapshot.py", "shared/skills.py", "shared/faults.py",
    "shared/discrepancy.py", "shared/symbolic_state.py")

M = [
 # blockers 1 & 2 — the effect declarations
 ("B1a push agent on the box PRE cell", DOM, '"agent.position_post == box.position_post - D",', '"agent.position_post == box.position_pre",'),
 ("B1b push agent on the terminal box cell", DOM, '"agent.position_post == box.position_post - D",', '"agent.position_post == box.position_post",'),
 ("B1c push offset sign flip", DOM, '"agent.position_post == box.position_post - D",', '"agent.position_post == box.position_post + D",'),
 ("B1d push terminal effect deleted", DOM, '        "agent.position_post == box.position_post - D",\n', ''),
 ("B1e backend push stride", BE, "self._land       = (pos[0] + 2 * dx, pos[1] + 2 * dy)", "self._land       = (pos[0] + 3 * dx, pos[1] + 3 * dy)"),
 ("B1f backend agent advance", BE, "self._expect_pos = (pos[0] + dx, pos[1] + dy)", "self._expect_pos = (pos[0] + 2 * dx, pos[1] + 2 * dy)"),
 ("B2a coop direction from agent facing", DOM, '"D == direction_vector(push_dir(box, zone))",\n        "box.position_post', '"D == direction_vector(agent1.direction_pre)",\n        "box.position_post'),
 ("B2b coop agent1 direction dropped", DOM, '        "agent1.direction_post == push_dir(box, zone)",\n', ''),
 ("B2c coop agent2 direction dropped", DOM, '        "agent2.direction_post == push_dir(box, zone)",\n', ''),
 ("B2d coop slots collapsed", DOM, '"{box.position_post - D, box.position_post - 2*D}",', '"{box.position_post - D, box.position_post - D}",'),
 ("B2e coop delivered_post dropped", DOM, '        "box.delivered_post is True",\n        "agent1.direction_post', '        "agent1.direction_post'),
 ("B2f goto pose sign flip", DOM, '"agent.position_post == box.position_pre - direction_vector(push_dir(box, zone))"', '"agent.position_post == box.position_pre + direction_vector(push_dir(box, zone))"'),
 ("B2g backend coop direction", BE, "push_dir = _push_dir_toward_goal(box)\n        dx, dy   = DIRECTION_VECTORS[Directions(push_dir)]\n        dest     = (box[0] + dx, box[1] + dy)", "push_dir = d\n        dx, dy   = DIRECTION_VECTORS[Directions(push_dir)]\n        dest     = (box[0] + dx, box[1] + dy)"),
 ("B2h backend rear slot", BE, "a2 = (bx - 2 * dx, by - 2 * dy)", "a2 = (bx - dx, by - dy)"),
 ("B2i assign_slots tie-break only", BE, "        i_am_a1 = d_self < d_part or (d_self == d_part and self.agent_id < self.partner_id)", "        i_am_a1 = self.agent_id < self.partner_id"),
 ("B2j find_tandem drops shared direction", MAE, "if a2 == a1 or int(world.agents[a2].direction) != d:", "if a2 == a1:"),
 # contract gaps
 ("G4a label membership removed", EX, "            if self.raw_label not in producible:", "            if False:"),
 ("G4b label membership widened", EX, "producible = PRODUCIBLE_RAW_LABELS.get(self.call.skill, frozenset())", "producible = frozenset(l for v in PRODUCIBLE_RAW_LABELS.values() for l in v)"),
 ("G4c raw_label type check removed", EX, "            if not isinstance(self.raw_label, RawLabel):", "            if False:"),
 ("G5 in_progress readmitted", EX, '    DONE = "done"\n', '    DONE = "done"\n    IN_PROGRESS = "in_progress"\n'),
 ("G6a pre_executor includes acceptance", SK, "        return isinstance(self, (MalformedCall, UngroundedCall, SymbolicallyInapplicable))", "        return isinstance(self, (MalformedCall, UngroundedCall, SymbolicallyInapplicable, ValidatedCall))"),
 ("G6b pre_executor drops inapplicable", SK, "        return isinstance(self, (MalformedCall, UngroundedCall, SymbolicallyInapplicable))", "        return isinstance(self, (MalformedCall, UngroundedCall))"),
 ("G7a rejection may coexist with execution", TS, "            if self.validation is not None and self.validation.is_pre_executor_rejection:", "            if False:"),
 ("G7b pre-exec fault may coexist", TS, "            early = [f for f in self.faults if f.arises_before_execution]", "            early = []"),
 ("G7c fault kind misclassified", FA, "    FaultKind.NL_TRACK_FAILURE,\n})", "    FaultKind.NL_TRACK_FAILURE,\n    FaultKind.BACKEND_API_EXCEPTION,\n})"),
 ("G10a failure always retracts", SY, "        if world_changed:\n            return self.retract(state, literal)\n        return state", "        return self.retract(state, literal)"),
 ("G10b failure never retracts", SY, "        if world_changed:\n            return self.retract(state, literal)\n        return state", "        return state"),
 ("G10c retract sweeps the predicate", SY, "        return SymbolicState.of(set(state.literals) - {literal})", "        return SymbolicState.of(l for l in state.literals if l.predicate != literal.predicate)"),
 ("G10d establish is a no-op", SY, "        return SymbolicState.of(set(state.literals) | {literal})", "        return state"),
 ("G7d is_executable drops OutsideSymbolicModel", SK, "        return isinstance(self, (ValidatedCall, OutsideSymbolicModel))", "        return isinstance(self, ValidatedCall)"),
 ("G8 channel count", "shared/observation.py", "Four channels:", "Three channels:"),
 ("G12 probes write into the repo", "tests/test_no_backend_imports.py", "        root = pathlib.Path(stack.enter_context(tempfile.TemporaryDirectory()))", "        root = REPO_ROOT"),
 # canonical() faithfulness (round-3 survivors)
 ("V1 trace task erased", TS, '            "task": self.task.canonical(),', '            "task": {},'),
 ("V2 model_version frozen", TS, '            "model_version": str(self.model_version),', '            "model_version": "v1.r0",'),
 ("V3 provenance erased", TS, '            "provenance": {"source": self.provenance.source},', '            "provenance": {"source": ""},'),
 ("V4 executive_step frozen", TS, '            "executive_step": self.executive_step,', '            "executive_step": 0,'),
 ("V5 coverage erased", TS, '            "coverage": self.coverage.canonical() if self.coverage else None,', '            "coverage": {} if self.coverage else None,'),
 ("V6 confidence erased", TS, '            "confidence": [c.canonical() for c in self.confidence],', '            "confidence": [{} for c in self.confidence],'),
 ("V7 nl proposal mirrors symbolic", TS, '            "nl_proposal": self.nl_proposal.canonical() if self.nl_proposal else None,', '            "nl_proposal": self.symbolic_proposal.canonical() if self.symbolic_proposal else None,'),
 ("V8 trace pre_state uses replay key", TS, '            "pre_state": self.pre_state.world_key(),', '            "pre_state": self.pre_state.replay_key(),'),
 ("V9 execution call erased", EX, '            "call": self.call.canonical(),', '            "call": {},'),
 ("V10 execution outcome frozen", EX, '            "outcome": str(self.outcome),', '            "outcome": "failure",'),
 ("V11 execution post_state mirrors pre", EX, '            "post_state": self.post_state.world_key(),', '            "post_state": self.pre_state.world_key(),'),
 ("V12 accounting erased", EX, '            "accounting": self.accounting.canonical(),', '            "accounting": None,'),
 ("V13 step counters transposed", EX, '        return {"executive_steps": self.executive_steps, "primitive_steps": self.primitive_steps}', '        return {"executive_steps": self.primitive_steps, "primitive_steps": self.executive_steps}'),
 ("V14 static width mirrors height", SS, '            "width": self.width,', '            "width": self.height,'),
 ("V15 static height mirrors width", SS, '            "height": self.height,', '            "height": self.width,'),
 ("V16 terminated frozen", SS, '            "terminated": self.terminated,', '            "terminated": False,'),
 ("V17 truncated frozen", SS, '            "truncated": self.truncated,', '            "truncated": False,'),
 ("V18 box ordering unnormalized", SS, "        boxes = tuple(sorted(self.boxes, key=lambda b: b.box_id))", "        boxes = tuple(self.boxes)"),
 ("V19 agent ordering unnormalized", SS, "        agents = tuple(sorted(self.agents, key=lambda a: a.agent_id))", "        agents = tuple(self.agents)"),
 ("V20 delivered leaves the world key", SS, '            "delivered": self.delivered,', '            "delivered": False,'),
 ("V21 direction leaves the world key", SS, '            "direction": self.direction,', '            "direction": 0,'),
 ("V22 all_targets disjunctive", SS, "        return bool(targets) and all(b.delivered for b in targets)", "        return bool(targets) and any(b.delivered for b in targets)"),
 ("V23 world mismatch not compared", DI, "        if self.predicted_world_key is not None and (\n            self.predicted_world_key != self.observed_world_key\n        ):", "        if self.predicted_world_key is not None:"),
 ("V24 observed_world mirrors predicted", DI, '            "observed_world_key": self.observed_world_key,', '            "observed_world_key": self.predicted_world_key,'),
 ("V25 mismatch guard weakened", DI, "and not self.mismatched_bases:", "and not self.comparison_bases:"),
 ("V26 key type check removed", DI, "            if value is not None and not isinstance(value, expected):", "            if False:"),
 ("V27 symbolic canonical unsorted", SY, "        return tuple(sorted(l.canonical() for l in self.literals))", "        return tuple(l.canonical() for l in self.literals)"),
 ("V28 deliver_both loses a box", DOM, "    goal_delivered=(BOX_HEAVY, BOX_LIGHT),", "    goal_delivered=(BOX_LIGHT,),"),
 ("V29 task goals unnormalized", "shared/task.py", '        object.__setattr__(self, "goal_delivered", tuple(sorted(set(self.goal_delivered))))', '        object.__setattr__(self, "goal_delivered", tuple(self.goal_delivered))'),
 ("V30 NoPlan reason erased", "shared/planner_result.py", '        return {"result": "NoPlan", "reason": self.reason}', '        return {"result": "NoPlan", "reason": ""}'),
 ("V31 PlannerFailure timed_out frozen", "shared/planner_result.py", '"error": self.error, "timed_out": self.timed_out}', '"error": self.error, "timed_out": False}'),
 ("V32 PlanFound cost is length", "shared/planner_result.py", "        return sum(c.cost for c in self.plan)", "        return len(self.plan)"),
 ("V33 fault message erased", FA, '            "message": self.message,', '            "message": "",'),
 ("V34 fault kind erased", FA, '            "kind": str(self.kind),', '            "kind": "",'),
 ("V35 divergence residual erased", "shared/divergence.py", '            "residual": list(self.residual),', '            "residual": [],'),
 ("V36 is_benign always true", "shared/divergence.py", "        return self.kind is DivergenceKind.BENIGN_ABSTRACTION_MISMATCH", "        return True"),
 ("V37 coverage covered erased", "shared/reports.py", '            "covered": list(self.covered),', '            "covered": [],'),
 ("V38 confidence frozen", "shared/reports.py", '"source": self.source, "confidence": self.confidence,', '"source": self.source, "confidence": 1.0,'),
 ("V39 observation outcome frozen", "shared/observation.py", '            "outcome": str(self.outcome),', '            "outcome": "success",'),
 ("V40 observation steps frozen", "shared/observation.py", '            "primitive_steps": self.primitive_steps,', '            "primitive_steps": 0,'),
 ("V41 observation notes erased", "shared/observation.py", '            "notes": list(self.notes),', '            "notes": [],'),
 ("V42 halt_on_fault flipped", "shared/orchestration_config.py", "    halt_on_infrastructure_fault: bool = True", "    halt_on_infrastructure_fault: bool = False"),
 ("V43 duplicate skill names allowed", SK, "        if len(self._by_name) != len(signatures):", "        if False:"),
 ("V44 skill cost frozen", "shared/skill_ir.py", '            "cost": self.cost,', '            "cost": 1,'),
 ("V45 dispatch fallback to Wait", SK, '        raise KeyError(\n            f"no registry skill dispatches on {key!r}; an adapter must reject an unknown token as "\n            f"a MalformedCall, never substitute a default skill"\n        )', "        return self._by_name[SkillName.WAIT]"),
 ("V46 project reads a position", DOM, "        literals.append(GroundedLiteral(P_DISCOVERED, (name,)))", "        if b.position[0] > 0:\n            literals.append(GroundedLiteral(P_DISCOVERED, (name,)))"),
 ("V47 exports drop the symbolic surface", "shared/__init__.py", '    "GroundedLiteral", "SymbolicState", "ProjectionContract",', '    '),
 ("V48 PDDL banner removed", "functional_layer/custom_env/box_push/pddl/box_push_domain.pddl", ";; SUPERSEDED FOR V1", ";; superseded-ish"),
 ("V49 resolve raises instead of typed result", "shared/skill_ir.py", "        if name in REGISTRY:\n            return OutsideSymbolicModel(", "        if False:\n            return OutsideSymbolicModel("),
 ("V50 symbolic side hardcoded", "tests/test_no_backend_imports.py", "        return tuple(p for p in discovered_guarded_packages(root) if p not in RUNTIME_PACKAGES)", '        return ("shared", "domain")'),
 # ── round-4 additions ──
 ("R1 orchestration policy erased", "shared/orchestration_config.py", '            "policy": str(self.policy),', '            "policy": "symbolic_primary",'),
 ("R2 executive budget erased", "shared/orchestration_config.py", '            "executive_step_budget": self.executive_step_budget,', '            "executive_step_budget": 50,'),
 ("R3 repeated_failure_threshold erased", "shared/orchestration_config.py", '            "repeated_failure_threshold": self.repeated_failure_threshold,', '            "repeated_failure_threshold": 3,'),
 ("R4 GotoPushPoseSkill ctor renamed", "functional_layer/custom_env/box_push/env/skill_executor_push.py",
  "    def __init__(self, agent_id: str, box: Optional[Tuple[int, int]] = None):\n        super().__init__(agent_id)\n        self._box_arg = tuple(box) if box is not None else None",
  "    def __init__(self, agent_id: str, target: Optional[Tuple[int, int]] = None):\n        super().__init__(agent_id)\n        box = target\n        self._box_arg = tuple(box) if box is not None else None"),
 ("R5 PushSkill dest renamed", "functional_layer/custom_env/box_push/env/skill_executor_push.py",
  "    def __init__(self, agent_id: str, dest: Optional[Tuple[int, int]] = None):",
  "    def __init__(self, agent_id: str, destination: Optional[Tuple[int, int]] = None):\n        dest = destination"),
 # ── round-4 survivors reported by the independent test reviewer ──
 ("Q1 comparison_bases erased", DI, '            "comparison_bases": [str(b) for b in self.comparison_bases],', '            "comparison_bases": [],'),
 ("Q2 mismatched_bases erased", DI, '            "mismatched_bases": [str(b) for b in self.mismatched_bases],', '            "mismatched_bases": [],'),
 ("Q3 discrepancy model_version erased", DI, '            "model_version": str(self.model_version) if self.model_version else None,', '            "model_version": None,'),
 ("Q4 discrepancy call erased", DI, '            "call": self.call.canonical(),', '            "call": {},'),
 ("Q5 predicted_symbolic_key erased", DI, '            "predicted_symbolic_key": self.predicted_symbolic_key,', '            "predicted_symbolic_key": None,'),
 ("Q6 execution pre_state erased", EX, '            "pre_state": self.pre_state.world_key(),', '            "pre_state": "",'),
 ("Q7 task description erased", "shared/task.py", '            "description": self.description,', '            "description": "",'),
 ("Q8 divergence message erased", "shared/divergence.py", '            "message": self.message,', '            "message": "",'),
 ("Q9 divergence nl_view erased", "shared/divergence.py", '            "nl_view": self.nl_view,', '            "nl_view": "",'),
 ("Q10 divergence symbolic_view erased", "shared/divergence.py", '            "symbolic_view": self.symbolic_view,', '            "symbolic_view": "",'),
 ("Q11 coverage is_complete frozen", "shared/reports.py", '            "is_complete": self.is_complete,', '            "is_complete": False,'),
 ("Q12 coverage note erased", "shared/reports.py", '            "note": self.note,', '            "note": "",'),
 ("Q13 confidence rationale erased", "shared/reports.py", '"confidence": self.confidence, "rationale": self.rationale}', '"confidence": self.confidence, "rationale": ""}'),
 ("Q14 PlanFound cost frozen", "shared/planner_result.py", '            "cost": self.cost,', '            "cost": 0,'),
 ("Q15 PlanFound model_version erased", "shared/planner_result.py", '            "model_version": str(self.model_version) if self.model_version else None,', '            "model_version": None,'),
 ("Q16 orchestration policy frozen", "shared/orchestration_config.py", '            "policy": str(self.policy),', '            "policy": "symbolic_primary",'),
 ("Q17 halt_on_fault frozen in canonical", "shared/orchestration_config.py", '            "halt_on_infrastructure_fault": self.halt_on_infrastructure_fault,', '            "halt_on_infrastructure_fault": True,'),
 ("Q18 max_rejections frozen", "shared/orchestration_config.py", '            "max_rejections_per_cycle": self.max_rejections_per_cycle,', '            "max_rejections_per_cycle": 5,'),
 ("Q19 skill dependencies erased", "shared/skill_ir.py", '            "dependencies": list(self.dependencies),', '            "dependencies": [],'),
 ("Q20 planner failure drops the error", "shared/planner_result.py", "            kind=FaultKind.PLANNER_COMPUTATION_FAILURE,\n            message=self.error,", "            kind=FaultKind.PLANNER_COMPUTATION_FAILURE,\n            message=\"planner failed\","),
 ("Q21 trace symbolic key guard removed", TS, "        if self.predicted_symbolic_key is not None and not isinstance(\n            self.predicted_symbolic_key, SymbolicKey\n        ):", "        if False:"),
 ("Q22 precondition param guard removed", "shared/skill_ir.py", "        for p in self.preconditions:\n            unknown = set(p.args) - declared", "        for p in ():\n            unknown = set(p.args) - declared"),
 ("Q23 static width mirrors height (transposition)", "shared/state_snapshot.py", '            "width": self.width,\n            "height": self.height,', '            "width": self.height,\n            "height": self.width,'),
 ("Q24 accounting transposed", EX, '        return {"executive_steps": self.executive_steps, "primitive_steps": self.primitive_steps}', '        return {"executive_steps": self.primitive_steps, "primitive_steps": self.executive_steps}'),
 ("Q25 goto labels widened", EX, "    SkillName.GOTO_PUSH_POSE: frozenset({RawLabel.IN_POSITION, RawLabel.NONE_KNOWN, RawLabel.BLOCKED}),", "    SkillName.GOTO_PUSH_POSE: frozenset({RawLabel.IN_POSITION, RawLabel.NONE_KNOWN, RawLabel.BLOCKED, RawLabel.DELIVERED}),"),
 ("Q26 goto labels narrowed", EX, "    SkillName.GOTO_PUSH_POSE: frozenset({RawLabel.IN_POSITION, RawLabel.NONE_KNOWN, RawLabel.BLOCKED}),", "    SkillName.GOTO_PUSH_POSE: frozenset({RawLabel.IN_POSITION, RawLabel.NONE_KNOWN}),"),
 ("Q27 wait labels widened", EX, "    SkillName.WAIT: frozenset({RawLabel.DONE}),", "    SkillName.WAIT: frozenset({RawLabel.DONE, RawLabel.BLOCKED}),"),
 ("Q28 agent facing flipped", "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py", "            self.agent_dirs[agent_id] = Directions.LEFT", "            self.agent_dirs[agent_id] = Directions.RIGHT"),
 ("Q29 grid size default moved", "functional_layer/custom_env/cooperative_search_transport/env/state.py", "    width: int = 12\n    height: int = 12", "    width: int = 16\n    height: int = 16"),
 ("Q30 runner grid size moved", "functional_layer/custom_env/box_push/env/box_push_centralized.py", "config = EnvConfig(width=12, height=12,", "config = EnvConfig(width=16, height=16,"),
 # ── final-gate FAIL: the ternary facing mutant that survived the prefix-substring pin ──
 ("Z1 facing ternary agent_1 flips", "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py",
  "            self.agent_dirs[agent_id] = Directions.LEFT",
  '            self.agent_dirs[agent_id] = Directions.LEFT if agent_id == "agent_0" else Directions.RIGHT'),
 ("Z2 facing ternary agent_0 flips", "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py",
  "            self.agent_dirs[agent_id] = Directions.LEFT",
  '            self.agent_dirs[agent_id] = Directions.RIGHT if agent_id == "agent_0" else Directions.LEFT'),
 ("Z3 facing trailing arithmetic", "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py",
  "            self.agent_dirs[agent_id] = Directions.LEFT",
  "            self.agent_dirs[agent_id] = Directions.LEFT + 1"),
 ("Z4 facing flipped outright", "functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py",
  "            self.agent_dirs[agent_id] = Directions.LEFT",
  "            self.agent_dirs[agent_id] = Directions.UP"),
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
    finally:
        path.write_text(original)
print(f"\n{len(M)-len(bad)}/{len(M)} killed")
for n, w in bad: print(f"  !! {n}: {w}")
