# CHECKED-IN PROCESS EVIDENCE, not part of the test suite (it MUTATES product files and
# restores them). Run manually from the repo root:  python -B docs/implementation/p1_mutation_harness.py
# Every mutation must be KILLED; a survivor is a coverage gap. Bytecode is disabled and
# __pycache__ cleared before every run so same-length edits cannot reuse stale .pyc.
"""P1 adapter mutation harness. Bytecode disabled, caches cleared per run."""
import pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
AD = "functional_layer/custom_env/box_push/env/box_push_v1_adapter.py"

M = [
 ("P1-1 unknown dispatch key falls back to Wait", AD,
  "        return None                      # no fallback arm — caller turns this into MalformedCall",
  "        return {agent_ids[0]: WaitSkill(agent_ids[0])}"),
 ("P1-2 primitive steps from BaseSkill._steps", AD,
  "        return primitive_steps, calls_made",
  "        return max((sk._steps for sk in skills.values()), default=0), calls_made"),
 ("P1-3 outcome trusts the raw label", AD,
  "            if box_post.delivered and not box_pre.delivered:\n                return ExecutionOutcome.SUCCESS",
  '            if any(sk.label == "delivered" for sk in [] ) or False:\n                return ExecutionOutcome.SUCCESS'),
 ("P1-4 pre-flight becomes a feasibility gate", AD,
  "        if call.zone is not None and call.zone != DELIVERY_ZONE:",
  "        if call.box is not None and self._env.core_env.world.objects[int(call.box.value)].delivered:\n            return UngroundedCall(reason='box already delivered', call=call)\n        if call.zone is not None and call.zone != DELIVERY_ZONE:"),
 ("P1-5 entities label agents as empty (belief-style)", AD,
  '        for other_id, other in world.agents.items():\n            if other_id != agent_id:\n                x, y = other.position\n                grid[int(x)][int(y)] = "agent"',
  "        pass"),
 ("P1-6 delivered box labeled target_object", AD,
  "            if not obj.delivered:       # delivered boxes are non-colliding ghosts; their cell",
  "            if True:       # delivered boxes are non-colliding ghosts; their cell"),
 ("P1-7 post-flight disabled", AD,
  "        if fault is not None:",
  "        if False:"),
 ("P1-8 wait consumes a primitive step", AD,
  "            if all(sk.is_done for sk in skills.values()):\n                break",
  "            if primitive_steps > 0 and all(sk.is_done for sk in skills.values()):\n                break"),
 ("P1-9 timeout detection dropped", AD,
  "        timed_out = any(sk._steps >= sk._MAX_STEPS for sk in skills.values())",
  "        timed_out = False"),
 ("P1-10 failure class always UNCHANGED", AD,
  "            if world_changed:\n                failure_class = FailureStateClass.PARTIAL_EXECUTION\n            elif finished_on_first_call:",
  "            if False:\n                failure_class = FailureStateClass.PARTIAL_EXECUTION\n            elif finished_on_first_call:"),
 ("P1-11 final STAY not submitted", AD,
  "            try:\n                self._obs, _rewards, terminations, truncations, _infos = env.step(actions)",
  "            if all(sk.is_done for sk in skills.values()) and all(a == int(Actions.STAY) for a in actions.values()):\n                break\n            try:\n                self._obs, _rewards, terminations, truncations, _infos = env.step(actions)"),
 ("P1-12 raw label erased", AD,
  "        raw_label = RawLabel(primary.label) if primary.label is not None else None",
  "        raw_label = None"),
 ("P1-13 authoritative reason dropped", AD,
  '                details.append("authoritative_reason=" + self._push_failure_reason(call, post))',
  "                pass"),
 ("P1-14 post-terminal guard removed", AD,
  "        if self.is_terminal():",
  "        if False:"),
 ("P1-15 reset guard removed", AD,
  "        if self._obs is None:",
  "        if False:"),
 ("P1-16 coop builds only one instance", AD,
  "            return {\n                a0: CooperativePushSkill(a0, a1, box=cell),\n                a1: CooperativePushSkill(a1, a0, box=cell),\n            }",
  "            return {a0: CooperativePushSkill(a0, a1, box=cell)}"),
 ("P1-17 box cell from a constant not world", AD,
  "        position = self._env.core_env.world.objects[int(box.value)].position\n        return (int(position[0]), int(position[1]))",
  "        return (0, 0)"),
 ("P1-18 export reads agent_positions not world", AD,
  "            AgentSnapshot(AgentId(aid), (int(a.position[0]), int(a.position[1])), int(a.direction))\n            for aid, a in world.agents.items()",
  "            AgentSnapshot(AgentId(aid), (int(p[0]), int(p[1])), int(self._env.agent_dirs[aid]))\n            for aid, p in self._env.agent_positions.items()"),
 ("P1-19 goto success ignores facing", AD,
  "        return agent_snapshot.position == pose and agent_snapshot.direction == push_dir",
  "        return agent_snapshot.position == pose"),
 ("P1-20 identity resolution skips agents", AD,
  "        for agent in call.agents:\n            if agent.value not in world.agents:",
  "        for agent in []:\n            if agent.value not in world.agents:"),
 # ── the three survivors from the independent P1 test review ──
 ("P1-21 coop post-flight arm disabled", AD,
  "        if call.skill is SkillName.COOPERATIVE_PUSH:",
  "        if False:"),
 ("P1-22 success by position not by flip", AD,
  "            if box_post.delivered and not box_pre.delivered:",
  "            if box_post.position in post.static.delivery_zone:"),
 ("P1-23 agent-landing reason dropped", AD,
  '        if any(a.position == landing for a in post.agents):\n            return f"landing_cell_occupied_by_agent{identity}"',
  "        pass"),
 ("P1-24 box-landing reason dropped", AD,
  '        if any(b.position == landing and not b.delivered for b in post.boxes):\n            return f"landing_cell_occupied_by_box{identity}"',
  "        pass"),
 ("P1-25 raw-label conversion escapes untyped", AD,
  "            raise InfrastructureFaultError(InfrastructureFault(\n                kind=FaultKind.MALFORMED_BACKEND_RESULT,",
  "            raise ValueError(InfrastructureFault(\n                kind=FaultKind.MALFORMED_BACKEND_RESULT,"),
 # ── F2 pins from the P1 consistency check: the env.step exception wrap ──
 ("P1-26 env.step wrap reverted to bare raise", AD,
  '''                raise InfrastructureFaultError(InfrastructureFault(
                    kind=FaultKind.BACKEND_API_EXCEPTION,
                    message=f"env.step raised {type(error).__name__}: {error}",
                    detail=f"primitive_steps_before_failure={primitive_steps}",
                    source="BoxPushV1Adapter._drive",
                )) from error''',
  "                raise"),
 ("P1-27 env.step fault drops the primitive count", AD,
  '''detail=f"primitive_steps_before_failure={primitive_steps}",''',
  '''detail="",'''),
 # ── round-2 consistency-check pins ──
 ("P1-28 alien-label fault drops case-(c) provenance", AD,
  '''                # case (c) provenance: the attempt ran; the consumed primitives survive here
                detail=f"primitive_steps_before_failure={primitive_steps}",
                source="BoxPushV1Adapter._interpret",''',
  '''                source="BoxPushV1Adapter._interpret",'''),
 ("P1-29 refusal loses the shared prefix", AD,
  '''                message="refused: execution after a terminal episode (D8)",''',
  '''                message="execution after a terminal episode (D8)",'''),
 # ── round-3 consistency-check pin ──
 ("P1-30 runaway cap reverts to the retired detail spelling", AD,
  '''                    detail=f"primitive_steps_before_failure={primitive_steps}; the attempt's "''',
  '''                    detail=f"primitive_steps_consumed={primitive_steps}; the attempt's "'''),
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
