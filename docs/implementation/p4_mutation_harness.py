# CHECKED-IN PROCESS EVIDENCE, not part of the test suite (it MUTATES product files and
# restores them). Run manually from the repo root:  python -B docs/implementation/p4_mutation_harness.py
# Every mutation must be KILLED; a survivor is a coverage gap. Bytecode is disabled and
# __pycache__ cleared before every run so same-length edits cannot reuse stale .pyc.
"""P4 runtime mutation harness."""
import pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
LO, OR, CO, EH = ("runtime/loop.py", "runtime/orchestrator.py", "runtime/comparator.py",
                  "runtime/executive_history.py")

M = [
 # ── orchestrator ──
 ("O1 NoPlan conflated into a replan loop", OR,
  '''    if isinstance(planner_result, NoPlan):
        return CycleDecision(
            ExecutiveDecision.HALT,''',
  '''    if isinstance(planner_result, NoPlan):
        return CycleDecision(
            ExecutiveDecision.REPLAN,'''),
 ("O2 threshold ignored under symbolic-primary", OR,
  "    if failure_count >= config.repeated_failure_threshold:",
  "    if False and failure_count >= config.repeated_failure_threshold:"),
 ("O3 policy split erased: primary also requests proposals", OR,
  '''        if config.policy is OrchestrationPolicy.ADVISORY_TWO_TRACK:''',
  '''        if True:'''),
 ("O4 inapplicable head executed anyway", OR,
  '''    if isinstance(head_validation, SymbolicallyInapplicable):''',
  '''    if False:'''),
 # ── loop ──
 ("L1 recovery decision entry suppressed", LO,
  '''                self._entry(step, snapshot, symbolic_result=planner_result,
                            decision=ExecutiveDecision.REQUEST_PROPOSAL,
                            selected_call=decision.call)
                self._pending_recovery = self._recovery_for(decision.call)''',
  '''                self._pending_recovery = self._recovery_for(decision.call)'''),
 ("L2 recovery provenance dropped from the executed entry", LO,
  '''            nl_proposal=nl_call_column,
            coverage=nl_coverage, confidence=nl_confidence,''',
  '''            nl_proposal=None,
            coverage=nl_coverage, confidence=nl_confidence,'''),
 ("L3 executed entries lose the decision column", LO,
  "            validation=verdict, decision=ExecutiveDecision.EXECUTE,",
  "            validation=verdict, decision=None,"),
 ("L4 per-entry discrepancies detached (aggregate kept)", LO,
  '''            execution=result, post_state=result.post_state,
            discrepancies=discrepancies, divergences=divergences,''',
  '''            execution=result, post_state=result.post_state,
            discrepancies=(), divergences=divergences,'''),
 ("L5 pending recovery never consumed (standing advice forever)", LO,
  '''            # drops it (a ghost can never become valid). Consistency-round W3 note.
            self._pending_recovery = self._pending_recovery[1:]''',
  '''            # drops it (a ghost can never become valid). Consistency-round W3 note.
            pass'''),
 ("L6 case-c charges dropped", LO,
  '''        match = _CASE_C_KEY.search(fault.detail)
        if match:                              # case (c): one executive step + N primitives
            self._extra_executive += 1
            self._extra_primitive += int(match.group(1))''',
  '''        match = _CASE_C_KEY.search(fault.detail)
        if match:                              # case (c): one executive step + N primitives
            pass'''),
 ("L7 grounding gate skipped (ghost reaches applicability)", LO,
  '''        ungrounded = self._ground_check(snapshot, call)
        if ungrounded is not None:''',
  '''        ungrounded = None
        if ungrounded is not None:'''),
 ("L8 predictions not recorded", LO,
  '''            predicted_symbolic_key=predicted_symbolic_key,
            predicted_world_key=predicted_world_key,''',
  '''            predicted_symbolic_key=None,
            predicted_world_key=None,'''),
 ("L9 monitor wired on a re-projection instead of the belief", LO,
  '''        pre_symbolic = self.belief.state''',
  '''        pre_symbolic = project(snapshot)'''),
 ("L10 rejection guard never fires", LO,
  '''                if rejections > self.config.max_rejections_per_cycle:''',
  '''                if False:'''),
 ("L11 fault-halt config inverted", LO,
  '''        if self.config.halt_on_infrastructure_fault:
            return self._finish(EpisodeOutcome.FAULTED, f"{fault.kind}: {fault.message}")
        return None''',
  '''        if self.config.halt_on_infrastructure_fault:
            return None
        return self._finish(EpisodeOutcome.FAULTED, f"{fault.kind}: {fault.message}")'''),
 ("L12 advisory proposal computed but discarded (comparator dead path)", LO,
  '''            return self.nl_track.propose(self.task)''',
  '''            self.nl_track.propose(self.task)
            return None'''),
 ("L13 executive budget checked against recorded sums only", LO,
  '''        if self.executive_steps_charged >= self.config.executive_step_budget:''',
  '''        if self.history.executive_steps_used >= self.config.executive_step_budget:'''),
 ("L14 cross-cycle liveness guard disabled", LO,
  '''            if self.executive_steps_charged == charged_before:''',
  '''            if False and self.executive_steps_charged == charged_before:'''),
 # -- X/A/E series: P4 review-round pins --
 ('X1 liveness-guard reset branch dropped', LO,
  '''            else:
                self._zero_progress_cycles = 0''',
  '''            else:
                pass'''),
 ('X2 primitive budget dead', LO,
  '''        if self.primitive_steps_charged >= self.config.primitive_step_budget:''',
  '''        if False:'''),
 ('X4 no-recovery-advice HALT branch dropped', LO,
  '''                if not self._pending_recovery:''',
  '''                if False:'''),
 ('X3 divergences computed against the plan head not the selected call', LO,
  '''        divergences = compare_tracks(call, nl_proposal)''',
  '''        divergences = compare_tracks(
            planner_result.plan[0] if getattr(planner_result, "plan", None) else call,
            nl_proposal,
        )'''),
 ('X5 ungrounded fault leaves recovery advice standing', LO,
  '''            self._pending_recovery = ()
            return self._maybe_fault_halt(fault)''',
  '''            return self._maybe_fault_halt(fault)'''),
 ('A1 case-a attached result dropped (the review FAIL, pinned)', LO,
  '''            if error.result is not None:''',
  '''            if False:'''),
 ('A3 liveness guard finishes without its typed fault entry', LO,
  '''                    self._entry(step, snapshot, faults=(fault,))
                    return self._finish(EpisodeOutcome.FAULTED, fault.message)''',
  '''                    return self._finish(EpisodeOutcome.FAULTED, fault.message)'''),
 ('A4 NL propose failure silently swallowed again', LO,
  '''            from nl.track import NLProposal''',
  '''            return None
            from nl.track import NLProposal'''),
 ('A5 goal-vs-budget tie flipped back', LO,
  '''            if self.task.is_satisfied_by(snapshot):
                return self._finish(EpisodeOutcome.GOAL_REACHED, "task goal satisfied")
            exhausted = self._budget_exhausted()
            if exhausted:
                return self._finish(EpisodeOutcome.BUDGET_EXHAUSTED, exhausted)''',
  '''            exhausted = self._budget_exhausted()
            if exhausted:
                return self._finish(EpisodeOutcome.BUDGET_EXHAUSTED, exhausted)
            if self.task.is_satisfied_by(snapshot):
                return self._finish(EpisodeOutcome.GOAL_REACHED, "task goal satisfied")'''),
 ('A6 first-cycle NL observation dropped', LO,
  '''            if first and self.nl_track is not None:''',
  '''            if False:'''),
 ('A7 standing recovery bypasses the orchestrator again', LO,
  '''        if self._pending_recovery:
            return decide(self.config, planner_result, None, 0,
                          standing_recovery=self._pending_recovery[0])''',
  '''        if self._pending_recovery:
            return CycleDecision(ExecutiveDecision.EXECUTE,
                                 call=self._pending_recovery[0])'''),
 ('E2 executor grows policy-shaped parameters', "runtime/executor.py",
  '''def execute(
    env: V1Environment, call: GroundedSkillCall
) -> Union[ExecutionResult, MalformedCall, UngroundedCall]:''',
  '''def execute(
    env: V1Environment, call: GroundedSkillCall, policy=None, history=None
) -> Union[ExecutionResult, MalformedCall, UngroundedCall]:'''),
 ('X8 confidence threshold inflated to 1.0', CO,
  '''LOW_CONFIDENCE = 0.75''',
  '''LOW_CONFIDENCE = 1.0'''),
 # ── comparator ──
 ("C1 contradiction reported as benign", CO,
  '''            divergences.append(TrackDivergence(
                kind=DivergenceKind.CONTRADICTION,''',
  '''            divergences.append(TrackDivergence(
                kind=DivergenceKind.BENIGN_ABSTRACTION_MISMATCH,'''),
 ("C2 confidence mismatch threshold zeroed", CO,
  "LOW_CONFIDENCE = 0.75", "LOW_CONFIDENCE = 0.0"),
 ("C3 malformed proposal produces no evidence", CO,
  '''    if nl_proposal.malformed is not None:''',
  '''    if False:'''),
 ("C4 agent-binding difference escalated to contradiction", CO,
  '''        elif (call.skill, call.box, call.zone) == (
            symbolic_call.skill, symbolic_call.box, symbolic_call.zone
        ):''',
  '''        elif False:'''),
 ("A8 case-a entry loses its decision column again", LO,
  '''                            decision=ExecutiveDecision.EXECUTE,
                            nl_proposal=nl_call_column,''',
  '''                            decision=None,
                            nl_proposal=nl_call_column,'''),
 ("A9 case-a skips belief maintenance again", LO,
  '''                self.belief.sync(error.result.post_state)
                self.belief.record_outcome(error.result)''',
  '''                self.belief.sync(error.result.post_state)'''),
 ("H3 fault-carrying failures accrue repeated-failure counts again", EH,
  '''            if ex.outcome is not ExecutionOutcome.SUCCESS and not entry.faults:''',
  '''            if ex.outcome is not ExecutionOutcome.SUCCESS:'''),
 ("W1a agreeing advisory proposal vanishes from the trace again", LO,
  '''        nl_call_column = call if from_recovery else (
            nl_proposal.call if nl_proposal is not None else None
        )''',
  '''        nl_call_column = call if from_recovery else None'''),
 ("W1b coverage/confidence evidence dropped from executed entries", LO,
  '''        nl_coverage = nl_proposal.coverage if nl_proposal is not None else None''',
  '''        nl_coverage = None'''),
 ("W4a normal path regresses to a redundant re-export", LO,
  '''        self.belief.sync(result.post_state)''',
  '''        self.belief.sync(self.env.export_full_state())'''),
 # ── history ──
 ("H1 failure key drops the pre-state", EH,
  '''        return (pre_state.world_key(), call.key())''',
  '''        return ("", call.key())'''),
 ("H2 successes also feed the failure counts", EH,
  '''            if ex.outcome is not ExecutionOutcome.SUCCESS and not entry.faults:''',
  '''            if True:'''),
]

def run():
    for cache in ROOT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    try:
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        ).returncode == 0
    except subprocess.TimeoutExpired:
        # a mutant that HANGS the suite killed the loop's liveness — that is a kill, and the
        # first harness run proved it the hard way (O4 disabled the inapplicability check and
        # produced an unbounded zero-charge cycle before the loop's liveness guard existed)
        return False

def main():
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


if __name__ == "__main__":
    main()
