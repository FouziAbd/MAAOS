# MAAOS R0-R6 Refactoring Implementation Record

This document records the behavior-preserving architectural refactor performed
after completion of Symbolic-Twin BoxPush V1 P0-P4.

Source refactoring plan:

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

Frozen V1 semantic authorities:

- `docs/decisions/P0_V1_DECISIONS.md`
- `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`

Historical P0-P4 implementation record:

`docs/implementation/P0_P4_IMPLEMENTATION.md`

Do not duplicate or rewrite historical P0-P4 claims here.

---

## R0 — Protect the current baseline

Status: COMPLETE (2026-09-04)

Implementation:
- Pristine baseline frozen before any edit (pre-flight, commit `11ff1c3` over
  baseline SHA `116d1fd`): `docs/refactor/baseline/` holds the 641-test suite
  tail, both headless demo transcripts, `BASELINE.md`, and
  `mypy_pristine.txt` (49 errors over `shared/` + `runtime/`, the
  must-not-increase R6 baseline).
- No production code changed: nothing under `shared/`, `domain/`,
  `symbolic/`, `nl/`, `runtime/`, or `functional_layer/` was touched. Domain
  model, projection, planner optimism, discrepancy rules, and trace semantics
  are unmodified.

Tests/evidence:
- New `tests/test_r0_characterization.py` (7 tests; suite 641 -> 648,
  pin updated in `REFACTOR_STATUS.md` in the same change set):
  - `TestDecisionOrderIsPinnedInCode` — hard-coded exact decision sequences:
    symbolic_primary `EXECUTE x7 + HALT`
    (-> `HALTED_REPEATED_FAILURE`), advisory_two_track
    `EXECUTE x7 + REQUEST_PROPOSAL + EXECUTE x2` (-> `GOAL_REACHED`).
  - `TestEpisodesEqualTheFrozenBaselineTranscripts` — cycle-by-cycle
    (decision, grounded call, outcome, discrepancy kind, `[nl recovery]`
    marker), step-accounting footer (9/62/3 advisory, 7/42/3 primary), and
    outcome/reason line all equal the frozen
    `docs/refactor/baseline/demo_*.txt`, with anti-vacuity guards.
  - `TestDesignedDiscrepanciesStayVisible` — exactly three
    `execution_failure_of_applicable_skill` discrepancies per policy, all on
    `Push(agent_0; box_1; delivery_zone)`, each a realized backend execution
    with the discrepancy attached to its failing entry.
- Full suite after the change: `python -B -m unittest discover -s tests -t .`
  -> 648 tests, OK (skipped=1: the pre-existing opt-in live-LM skip).
- Both headless demos re-run post-change and byte-identical to the frozen
  baseline transcripts; mypy unchanged at 49 errors.
- Reviews: `test-reviewer` PASS (sufficiency; transcript rendering verified
  field-by-field against `box_push_v1_run.py`); `architecture-reviewer` PASS
  (0 FAIL; zero production edits, no early R1+ machinery, invariants intact).

Compatibility notes:
- Tests import the backend adapter by established convention (`tests` is
  excluded from the guarded packages in `test_no_backend_imports.py`);
  offline, deterministic, no LM, no render.

Warnings/deferred:
- WARN (accepted): the characterization module caches one episode per policy
  across its test methods; revisit if a later phase makes history entries
  lazy or mutable.
- WARN (accepted): `loop.env.close()` is not called on the two cached
  headless adapters (harmless without render).
- DEFERRED: contract/protocol tests -> R1; policy extraction/purity -> R2;
  comparison lifecycle -> R3; runtime import boundaries/composition -> R4;
  probe domain -> R5; mypy gate, observation aliasing, malformed-backend
  typed faults, ruff/uv/CI enforcement -> R6.

---

## R1 — Introduce contracts without changing behavior

Status: COMPLETE (2026-09-04)

Implementation:
- New `shared/contracts/` package (five modules, pure additions; no existing
  module edited, no production consumer yet — R2/R3/R4 own consumption):
  - `environment.py` -> `Environment[StateT, CallT, ExecutionT, ObservationT]`
    — generic mirror of the frozen `shared.backend_contract.V1Environment`
    surface (which is untouched); admits no feasibility/reachability oracle.
  - `tracks.py` -> `SymbolicTrack` (sync/state/record_outcome, fitted to
    `symbolic.ExactSymbolicBelief`) and `ReasoningTrack` (observe/propose,
    fitted to `nl.track.NLTrack`).
  - `comparison.py` -> `ProposalComparator` and `RecoveryProvider` as callable
    protocols fitted to `runtime.comparator.compare_tracks` and
    `nl.recovery.propose_recovery`.
  - `policy.py` -> `TrackRequest`; immutable validated `PreliminaryContext`
    and `OrchestrationContext`; typed decision variants
    `Execute`/`Replan`/`RequestProposal`/`Halt` (+`PolicyDecision` union) in
    which illegal states are unrepresentable (`Execute` cannot exist without
    a call) and each variant carries its frozen `ExecutiveDecision` member
    for trace-format continuity; `OrchestrationPolicyContract`
    (required_inputs/decide) — named to avoid colliding with the frozen
    `OrchestrationPolicy` config enum.
- Generic only in the domain-owned types the report names (state, call,
  execution outcome, observation, task, proposal, symbolic state); all other
  channels remain the existing shared concrete types. No `Any`-primary or
  dict-shaped abstraction. Decision variants cover exactly the four decisions
  the shipped orchestrator produces (the report's illustrative `AskUser` was
  deliberately not added).

Tests/evidence:
- `tests/contract_conformance.py` — mypy-checked typed identity witnesses:
  any `V1Environment` satisfies the V1 `Environment` parameterization;
  `ExactSymbolicBelief`, `NLTrack`, `compare_tracks`, `propose_recovery`
  checked as concrete classes/functions; test-local `MinimalHaltPolicy`
  proves the policy contract implementable (real classes are R2's).
  `python -m mypy --ignore-missing-imports --follow-imports=silent
  tests/contract_conformance.py` -> Success. Reviewer mutation-tested the
  witnesses: deliberate mis-bindings produce the expected mypy errors, so the
  check is non-vacuous.
- `tests/test_r1_contracts.py` (17 tests; suite 648 -> 665, pin updated in
  the same change set): runtime isinstance+witness checks for all shipped
  components; context immutability/validation; decision-variant illegal-state
  tests; mechanical AST scans (BoxPush-vocabulary ban on whole identifier
  segments, speculative-semantics ban, contracts import only stdlib+shared).
- Full suite: 665 tests, OK (skipped=1). Both headless demos byte-identical
  to `docs/refactor/baseline/`. Scoped mypy
  (`python -m mypy shared runtime --ignore-missing-imports`) unchanged at
  exactly 49 errors; all `shared/contracts/` modules clean.
- Reviews: test-reviewer PASS (0 FAIL); architecture-reviewer PASS (0 FAIL).

Compatibility notes:
- Zero production behavior change: `runtime/`, `domain/`, `symbolic/`, `nl/`,
  `functional_layer/` untouched; `V1Environment` byte-identical; no public
  import moved. Protocol parameters are positional-only so shipped
  implementations conform under their existing parameter names.
- Protocol `isinstance` checks rely on frozen Python 3.12 (Decision 10)
  `getattr_static` semantics (noted inline in the test).

Warnings/deferred:
- WARN (accepted, harden in R6): the AST vocabulary/import scans do not cover
  `*args`/`**kwargs`/lambda parameter names, annotation expressions, relative
  imports, or morphological variants; the import allowlist admits `shared`
  wholesale (so a BoxPush-typed annotation like `BoxId` could slip in via
  `shared.ids`). Current sources verified clean by review.
- WARN (accepted): the adapter's environment conformance is static only via
  `V1Environment` protocol-to-protocol (the adapter file is sys.path-mounted,
  unreachable by mypy); the concrete-instance check is runtime. Full static
  reach arrives with the R4 composition root / R6 static gate.
- DEFERRED: concrete policy classes, loop policy injection, registry dispatch
  -> R2; comparison-before-decision, structured comparison report replacing
  the `TrackDivergence` tuple in `OrchestrationContext`, domain-owned
  equivalence, configurable threshold -> R3; `DomainBundle`, removal of
  concrete imports from `runtime/loop.py`, import-boundary enforcement -> R4;
  probe-domain use of these contracts -> R5; mypy/CI gates and AST-scan
  hardening -> R6.

---

## R2 — Extract orchestration policies

Status: COMPLETE (2026-09-04)

Implementation:
- New `runtime/policies.py`:
  - `SymbolicPrimaryPolicy` / `AdvisoryTwoTrackPolicy` — the two former
    `decide()` branches as `OrchestrationPolicyContract` implementations over
    a shared `_PlanHeadPolicy` base (standing recovery pre-empts, `NoPlan`
    halts, typed `TypeError` refusal of `PlannerFailure`, empty plan halts,
    inapplicable head replans, applicable head executes); subclasses supply
    only the repeated-failure escape (halt-with-history vs REQUEST_PROPOSAL)
    and `required_inputs()` (primary declares no track inputs, advisory
    requests the NL proposal). Pure: constructor takes only
    `repeated_failure_threshold`; no environment surface exists in any input.
    All reason strings preserved verbatim (R0 transcripts pin them).
  - Open registry `POLICY_FACTORIES: dict[str, PolicyFactory]` +
    `build_policy(config)` — dispatch is by configuration NAME, not enum
    identity; unknown names are refused with `LookupError`. The frozen
    `OrchestrationConfig`/`OrchestrationPolicy` enum is untouched as data.
- `runtime/loop.py` — `ExecutiveLoopManager(..., policy=None)` accepts an
  injected policy object (default: `build_policy(self.config)`); `_select`
  builds the immutable `PreliminaryContext`/`OrchestrationContext` and calls
  `self.policy.decide(...)`, returning the context with the decision; the
  cycle branches on the typed variants (`Halt`/`RequestProposal`/`Replan`,
  else `Execute`); `_advisory_proposal(request)` is gated by
  `self.policy.required_inputs(preliminary)` instead of the policy enum
  (report Phase 2 item 5). Acquisition still happens after the decision —
  moving it before is R3's lifecycle change, deliberately not taken.
- `runtime/orchestrator.py` — now a compatibility shim: `CycleDecision` and
  the `decide()` signature/routing/reason strings are preserved exactly,
  delegating through `build_policy` + `policy.decide` (one implementation,
  two surfaces). The enum branch is gone.
- `shared/contracts/policy.py` — docstring phase-note updated (R2 done);
  no contract change.

Tests/evidence:
- `tests/test_r2_policies.py` (23 tests; suite 665 -> 688, pin updated in
  the same change set): contract conformance of both shipped policies
  (runtime + static witnesses `symbolic_primary_policy_conforms`/
  `advisory_two_track_policy_conforms` added to
  `tests/contract_conformance.py`); the full pure decision table on bare
  contexts (`state=None` proves state is never read), including verbatim
  frozen reason strings and determinism/statelessness; `required_inputs`
  declarations plus a loop-level proof that SYMBOLIC_PRIMARY never calls
  `propose()` (exploding track) while `observe()` still feeds; a
  mutation-discriminating test where the injected policy's declaration
  DISAGREES with `config.policy` in both directions (added for the
  test-reviewer's WARN — verified to kill both loop mutations that survived
  the earlier suite: regressing the gate to the enum check, and rebuilding
  the policy from config instead of honoring the injected object); registry
  name-dispatch, openness (new entry, no central edit), and loud refusal;
  a novel test-only policy injected into an unmodified `ExecutiveLoopManager`
  drives a real episode (Phase 2 acceptance "no edits to runtime/loop.py");
  AST import scan pins `runtime/policies.py` to stdlib+`shared`.
- `tests/test_p4_runtime.py`: two direct private calls
  `loop._advisory_proposal()` adapted to the new explicit signature
  (`TrackRequest(nl_proposal=True)`); assertions unchanged.
  `TestOrchestratorRouting` passes unchanged against the shim.
- Full suite: 687 tests, OK (skipped=1). Both headless demos byte-identical
  to `docs/refactor/baseline/demo_*.txt`. R0 characterization (exact
  decision sequences, three designed discrepancies) green under both
  policies. Scoped mypy (`python -m mypy shared runtime
  --ignore-missing-imports`) 49 -> 41 errors (typed-variant narrowing fixed
  eight pre-existing `GroundedSkillCall | None` complaints; nothing new);
  conformance witness file mypy-clean.
- Reviews: test-reviewer 0 FAIL (its main WARN — the `required_inputs` loop
  wiring survived two mutations — was closed by adding the
  policy-vs-config-disagreement test and re-verifying both mutations now
  fail; its registry-key overclaim was fixed with an exact-type assertion);
  architecture-reviewer 0 FAIL (its W6 shim-fidelity question was closed by
  an exhaustive 20-case old-vs-new `decide()` comparison against
  `HEAD:runtime/orchestrator.py` — byte-identical decisions/calls/reasons,
  including the inapplicable-head/threshold ordering probe and `TypeError`
  parity; remaining WARNs recorded below).

Compatibility notes:
- `runtime.orchestrator.decide`/`CycleDecision` imports, the
  `ExecutiveLoopManager` constructor (new parameter is optional, appended
  last), CLI behavior, and the trace format are unchanged. The legacy
  `decide()` surface passes `state=None` into `PreliminaryContext` (its
  signature never carried state; no shipped policy reads it) — callers
  needing state-aware policies hold a policy object.
- The `policy` parameter wins over `config.policy` when both are supplied;
  `config.policy` is then only the registry default that was not consulted.

Warnings/deferred:
- WARN (accepted): `_advisory_proposal`'s gate now trusts the injected
  policy's `required_inputs()`; a custom policy raising from
  `required_inputs()` propagates untyped out of `run()` (same trust level as
  the R1 contract's purity assumption; the R4 composition root owns
  boundary hardening if the report requires it).
- WARN (accepted, reviewer W3/W5): with an injected `policy`, `config.policy`
  becomes an inert default (documented precedence; no trace contradiction —
  `TraceEntry` does not serialize the config policy); the loop's mapping of
  any call-carrying `Halt` to `HALTED_REPEATED_FAILURE` is a pre-R2
  convention now inherited by injected-policy authors (pinned in
  `tests/test_r2_policies.py`). The R4 composition root makes the single
  policy source explicit.
- WARN (accepted, reviewer): the static conformance witnesses are only
  checked when mypy runs on `tests/contract_conformance.py`; wiring that
  into the default/CI job is R6-owned.
- `docs/implementation/p4_mutation_harness.py` annotated as frozen against
  the P4-era orchestrator source (its O1-O4 snippets no longer apply; their
  kill-coverage now lives in `tests/test_r2_policies.py`).
- DEFERRED(R3): acquisition/comparison before the final policy decision;
  structured comparison report in `OrchestrationContext`; comparator
  scoping/equivalence/threshold work.
- DEFERRED(R4): `runtime/loop.py` still imports `domain.box_push_v1`,
  concrete `symbolic`/`nl` functions and the concrete comparator; explicit
  composition root; import-boundary enforcement for the whole runtime.
- DEFERRED(R6): mypy debt (41 remaining scoped errors), AST-scan hardening,
  porting mutation-harness O1-O4 to `runtime/policies.py`, typing the legacy
  shim's `state=None` (`runtime/orchestrator.py`).

---

## R3 — Correct the comparison lifecycle

Status: COMPLETE (2026-09-04)

Implementation:
- `shared/contracts/comparison.py` (report Phase 3 items 1, 3, 5):
  `ComparedAspect` (proposal_form/model_coverage/task_translation/
  action_choice/confidence), `FindingSeverity` (benign/attention —
  descriptive, never calibrated), `ComparisonFinding` (aspect + severity
  wrapping the frozen `TrackDivergence` as the evidence payload:
  kind = classification, message = human-readable summary),
  `ComparisonReport` (findings + `divergences`/`contradicted`/`all_benign`),
  `ActionEquivalence` protocol (domain-owned different-but-equivalent rule),
  and `ProposalComparator` upgraded to `compare() -> ComparisonReport`.
- `shared/contracts/policy.py`: `OrchestrationContext.comparison:
  Optional[ComparisonReport]` replaces the R1 divergence tuple (None = no
  proposal compared; empty report = genuine agreement).
- `domain/box_push_v1.py` -> `BoxPushActionEquivalence` (item 3): the
  Decision-6 agent-binding rule, extracted verbatim from the runtime
  comparator; the comparator source no longer reads `.box`/`.zone`/`.agents`
  (AST-pinned).
- `runtime/comparator.py` -> `BoxPushActionComparator` (items 2, 4, 6):
  injected `ActionEquivalence`; `low_confidence_threshold` constructor
  configuration (default `LOW_CONFIDENCE` = 0.75, validated, exact
  boundary preserved); malformed proposals no longer return early — the
  independent task-translation residual finding is retained;
  `DEFAULT_COMPARATOR` (domain equivalence + default threshold);
  `compare_tracks` kept as the legacy divergence-tuple wrapper. All
  pre-existing `TrackDivergence` payloads byte-identical.
- `runtime/loop.py` (item 7 — the lifecycle correction): each selection
  iteration now builds the `PreliminaryContext`, asks
  `policy.required_inputs`, acquires the requested NL proposal (once per
  cycle, same typed `_advisory_proposal` fault boundary), compares against
  the call an Execute decision would enact (`_compared_call`: standing
  recovery, else plan head), and only then calls `policy.decide` on the
  full `OrchestrationContext` (proposal + report). Executed entries record
  the pre-decision report's divergences — identical content to pre-R3
  because the compared call equals the enacted call. Predictions remain
  strictly post-decision (no oracle). An NL acquisition fault now fires
  PRE-DECISION: its entry carries the planning record and the fault only.
- `runtime/policies.py`: `_route` extracted from `decide` (shipped policies
  receive the report before deciding, and by frozen V1 design do not let it
  alter decisions); `AdvisoryTwoTrackPolicy.required_inputs` requests the
  proposal exactly when its own route on the preliminary is Execute — the
  accepted per-enactment consultation, declared instead of enum-gated.

Tests/evidence:
- `tests/test_r3_comparison.py` (25 tests; suite 688 -> 713, pin updated in
  the same change set): structured findings for every frozen classification
  with byte-identical `canonical()` payloads; malformed+residual retention;
  legacy-wrapper equivalence; configurable/validated threshold with the
  exact accepted boundary; domain equivalence rule + substitution proof
  (swapping the injected equivalence flips benign/contradiction);
  comparator import allowlist and `.box`/`.zone`/`.agents` attribute scan;
  report-at-decide-time through the real loop (recording policies pin that
  enacting decisions see the report and that executed trace rows equal the
  pre-decision report); a reactive test policy HALTs on contradiction
  before any enactment (impossible pre-R3) while symbolic-primary never
  has a report and the shipped advisory policy sees contradictions yet
  decides identically.
- Adapted (authorized R3 lifecycle/contract changes, assertions otherwise
  preserved): `tests/test_r1_contracts.py` (comparison field; comparator
  witness now `DEFAULT_COMPARATOR`; `enum` joined the contracts stdlib
  allowlist), `tests/test_r2_policies.py` (advisory would-enact
  declaration incl. standing recovery and NoPlan-decline),
  `tests/test_p4_runtime.py::test_nl_track_exception_short_circuits_before_
  the_backend` (fault entry is now pre-decision: decision/selection/
  validation/prediction columns pinned None; the core invariants —
  pre-executor classification, zero charges, zero executions, no
  manufactured divergence — unchanged), `tests/contract_conformance.py`.
- Full suite: 713 tests, OK (skipped=1). Both headless demos byte-identical
  to `docs/refactor/baseline/demo_*.txt` (R0 characterization green under
  both policies). Scoped mypy 41 -> 37 errors; conformance witness file
  mypy-clean.
- Reviews: test-reviewer 0 FAIL (six mutation probes all killed — lifecycle
  regression, manufactured empty report, head-vs-recovery comparison,
  reinlined equivalence, re-hardcoded threshold, restored early return; its
  WARNs were closed in this change set: `TestAcquisitionAccounting` pins
  once-per-enactment consultation, the one-consultation gated cycle with
  its unrecorded evidence, and the once-per-cycle acquisition cache — the
  cache-removal mutant it found surviving is verified killed; the vacuous
  raw-confidence test now exercises the comparator; the zip length is
  asserted). architecture-reviewer 0 FAIL (no oracle, channels separate,
  fail-closed routing intact, `CompositeComparator` correctly absent per
  the report's own R5 assignment; its W2/W3 documentation asks are folded
  into the notes above and W4's status reconciliation is done in this
  change set).

Compatibility notes:
- Trace format unchanged: `TraceEntry.divergences` still carries the frozen
  `TrackDivergence` tuple, byte-identical for identical inputs; findings
  structure exists only in the in-memory report. `compare_tracks` import
  surface preserved. CLI unchanged.
- `OrchestrationContext.divergences` (an R1-introduced field with no
  external consumers beyond the adapted R1 test) is replaced by
  `comparison`; this is the exact upgrade R1 documented as R3-owned.
- Observable lifecycle differences (attached-track episodes only; the
  accepted no-track baseline is byte-identical): an exception escaping
  `nl_track.propose()` now faults the cycle BEFORE any decision, selection,
  validation, or prediction (previously after them), with the same
  fail-closed routing and zero charges; a proposal can now be consumed on a
  cycle whose selected call is subsequently gated out (acquisition precedes
  the post-decision gates by construction of the corrected lifecycle) — in
  live/recorded mode this means a `RecordedLM` fixture store recorded
  against enacted-cycle requests only can now see a request (and raise its
  typed fixture-miss fault) on a gated cycle that previously made no LM
  request; malformed proposals with residual now yield the additional
  translation-residual divergence (evidence gain, item 6).

Warnings/deferred:
- WARN (accepted): a subclass overriding `decide()` but not
  `required_inputs()` inherits requests matching the BASE route, not its
  own decisions — mirrors the general R1/R2 policy-purity trust; the
  reactive-policy test overrides both. The R4 composition-root
  documentation must state that a policy overriding `decide` owns
  re-declaring `required_inputs`.
- WARN (accepted, reviewer W3): on a cycle whose enactment is gated out
  after the decision, the already-computed comparison evidence is
  deliberately NOT recorded — those trace entries stay exactly as pre-R3
  (no proposal columns, no divergences). Recording gated-cycle divergence
  evidence would be a trace-content change needing its own justification;
  R4/R6 may decide deliberately.
- DEFERRED(R4): the BoxPush-scoped comparator still lives under `runtime/`
  and the loop composes `DEFAULT_COMPARATOR` itself; the composition root
  owns comparator injection/relocation and whole-runtime import boundaries.
- DEFERRED(R5): composite-comparator aggregation is exercised only by the
  R5 probe work with fakes (report Phase 5 item 4); building production
  aggregation now would be the forbidden speculative machinery.
- DEFERRED(R6): remaining scoped mypy debt (37), AST-scan hardening.

---

## R4 — Make domain composition explicit

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R5 — Prove architectural substitutability

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## R6 — Correctness and repository hygiene

Status: PENDING

Implementation:
- Pending.

Tests/evidence:
- Pending.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## Final Definition of Completion

Status: NOT YET AUDITED

Record the final `/refactor-audit` result here only after R6.
