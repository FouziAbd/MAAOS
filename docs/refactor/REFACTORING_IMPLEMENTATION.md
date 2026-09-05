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

Status: COMPLETE (2026-09-04)

Implementation:
- `shared/contracts/domain.py` (report Phase 4 item 1) -> `DomainServices`
  protocol: `model_version`, `plan(symbolic_state, state)`,
  `ground(state, call)`, `evaluate(symbolic_state, call)`,
  `predict(symbolic_state, state, call) -> Prediction`,
  `monitor(pre_symbolic, result)` — exactly the domain operations one V1
  cycle performs, in cycle order; nothing hypothetical. `Prediction` is a
  frozen pair of the typed Decision-13 keys (`SymbolicKey`/`WorldKey`).
  Exported from `shared.contracts`; no BoxPush vocabulary (the R1 AST scans
  cover the new module unchanged).
- `runtime/loop.py` (items 2, 3): the generic runtime core. Imports are now
  stdlib + `shared` + `runtime` only — `domain.box_push_v1`, `symbolic`,
  `nl.recovery`, and the comparator import are gone. Every domain operation
  goes through the injected `domain` (`_plan(snapshot)` -> `domain.plan`;
  the former inline `_ground_check` over agents/boxes/zone ->
  `domain.ground`; `evaluate` -> `domain.evaluate` at both call sites;
  the two-basis prediction -> `domain.predict`; `_monitor` -> `domain.monitor`
  with the §19.1 item 4 `ValueError` wrap kept in the loop; trace/provenance
  model version -> `domain.model_version`). The belief is the injected
  `symbolic_track` (attribute name `belief` kept), the comparator and recovery
  provider are injected through their R1/R3 contracts. Constructor:
  positional `(env, task, config, nl_track, provenance, policy)` unchanged;
  new keyword-only `domain` (required), `symbolic_track` (required),
  `comparator` (required iff an `nl_track` is attached — refused with
  `TypeError` at construction otherwise), `recovery_provider` (None = no
  advice exists; REQUEST_PROPOSAL then halts with the existing
  "no recovery advice available" reason). The universe is no longer loop
  state (`_universe`/`_goal` fields removed).
- `app/` (item 3) — the new application/composition package, above the
  runtime in the report's dependency direction; backend-guarded like every
  other package (discovered by `tests/test_no_backend_imports.py`) and the
  only package permitted to import `runtime` besides `runtime` itself.
  - `app/box_push_v1.py` -> `BoxPushDomainServices(task, universe=None)`:
    the pre-R4 inline wiring verbatim (frozen `DOMAIN_IR`/`PROJECTION`/
    `MODEL_VERSION`/`project` + `symbolic` planner/applicability/predictor/
    monitor, the `delivered` goal literals from `task.goal_delivered`, the
    §19.1 item 5 identity grounding); `Universe.from_snapshot` is derived
    from the snapshot the loop passes with each plan request (identities are
    constant within an episode, so the planner input is identical to the
    first-sync universe the loop used to cache); the explicit `universe=`
    override replaces the pre-R4 private-field assignment used for the
    Decision-12 synthetic NoPlan instance. `compose(task)` -> frozen
    `BoxPushComponents` (domain, fresh `ExactSymbolicBelief`,
    `BoxPushActionComparator(BoxPushActionEquivalence())`, `propose_recovery`);
    `build_loop(env, task, config, nl_track, provenance, policy, *,
    loop_class, domain, symbolic_track, comparator, recovery_provider)`
    assembles one loop over a CALLER-constructed environment, each keyword
    overriding one composed component (`loop_class` admits the established
    fault-injection seam of subclassing the loop).
  - `app/comparator.py` <- `runtime/comparator.py` (git mv, content
    unchanged except the docstring): the BoxPush-scoped comparator imports
    the concrete domain equivalence and `nl.track.NLProposal`, which the
    runtime core may not see.
- `functional_layer/custom_env/box_push/env/box_push_v1_run.py` (item 3):
  constructs the adapter and calls `build_loop`; CLI options and output
  unchanged.
- `tests/test_no_backend_imports.py`: `COMPOSITION_PACKAGES = {"app"}` is
  excluded from the :118 "symbolic side must not import runtime" scan (it
  sits above the runtime by construction) and asserted to remain discovered
  and backend-guarded; `symbolic`/`nl`/`domain`/`shared` are now asserted
  explicitly on the symbolic side. Because `app` imports `runtime`, the
  symbolic side is forbidden from importing `app` too (transitive :118
  reach; fail-closed temp-tree probe added), and `shared` is asserted to
  import neither `runtime` nor `app`.
- `.claude/rules/nl-track.md` path glob follows the comparator to
  `app/**/*comparator*`. Contract docstrings (`shared/contracts/tracks.py`,
  `policy.py`, `__init__.py`) updated to the R4 state.

Tests/evidence:
- `tests/test_r4_composition.py` (31 tests; suite 713 -> 744 with the three
  guard tests below, pin updated in the same change set):
  - `TestRuntimeImportBoundary` (item 4): AST allowlist over EVERY
    `runtime/**/*.py` (recursive — a `runtime/<sub>/` package cannot evade
    it, pinned by a temp-tree probe; stdlib whitelist + `shared` + `runtime`;
    explicit forbidden roots `domain`/`symbolic`/`nl`/`app`/backend/legacy/
    adapter modules) with a non-vacuity probe, dynamic-import ban, and a
    vocabulary scan (no `.agents/.box/.zone/...` attribute reads, no
    domain/symbolic names) with its own non-vacuity probe.
  - `TestDomainServicesContract` / `TestGroundingIsDomainOwned`: runtime and
    static (`tests/contract_conformance.py::domain_services_conform`,
    mypy-clean) conformance; the bundle's plan/evaluate/predict pinned equal
    to the pre-R4 inline function applications on the initial state; the
    `universe=` override yields `NoPlan` for the heavy-solo task; all three
    §19.1 item 5 grounding rejections plus the grounded case; Decision 6 at
    the new seam — `plan` reads the snapshot for identities only (every
    agent/box moved, same identities -> identical `PlannerResult`); the
    universe is derived from EACH plan call's snapshot, not cached from the
    first (identity set changed between two calls on one instance, both
    orders -> the second answer follows the second snapshot).
  - `TestCompositionRoot` (acceptance 2): `compose` yields the concrete V1
    components and a fresh belief per loop; `build_loop` injects them and
    the config-named policy; overrides honored by identity; the loop refuses
    construction without domain services and refuses an attached track
    without a comparator; the runner's AST imports/calls `build_loop` and
    never constructs `ExecutiveLoopManager`; `app` is backend-guarded; both
    accepted outcomes and the three designed discrepancies hold through the
    composition root.
  - `TestInjectedSubstitution` (acceptance 3, no loop edit): a strict
    `DomainServices` proxy (refuses any attribute outside the contract)
    drives the full advisory episode and pins the WHOLE consultation sequence
    (nine executed cycles, each exactly plan -> head verdict -> ground ->
    evaluate -> predict -> monitor, so an evaluate-before-ground inversion or
    a pre-decision predict fails it); trace entries carry the domain's model
    version even under a foreign injected `Provenance`; a counting
    `SymbolicTrack` wrapper is the one synced/fed; a canned comparator is the sole source of
    divergence evidence and sees the enacted call; a substitute recovery
    provider's advice is what REQUEST_PROPOSAL enacts through the executor,
    an empty provider and an absent provider both halt with
    "no recovery advice available".
- Adapted (authorized R4 composition change, assertions preserved):
  `tests/test_p4_runtime.py`, `test_r0_characterization.py`,
  `test_r2_policies.py`, `test_r3_comparison.py`, `test_v1_acceptance.py`
  construct through `build_loop` (subclass seams via `loop_class`;
  `_plan(self, snapshot)`); the NoPlan universe test injects
  `BoxPushDomainServices(task, universe=...)` instead of assigning the
  loop's private field; `runtime.comparator` imports and the R3 AST-scan
  paths moved to `app/comparator.py`; `tests/test_r1_contracts.py` and
  `tests/contract_conformance.py` import the comparator from `app`.
- Full suite: 739 tests, OK (skipped=1). Both headless demos byte-identical
  to `docs/refactor/baseline/demo_*.txt` (R0 characterization green under
  both policies). Scoped mypy (`python -m mypy shared runtime
  --ignore-missing-imports`) 37 -> 4 errors (the concrete-import debt left
  the runtime; the four remaining are pre-existing `shared/skill_ir.py`,
  `shared/trace_schema.py`, and one `tuple[()]` narrowing in `loop.py`);
  conformance witness file mypy-clean.
- Reviews: test-reviewer 2 FAIL, both closed in this change set (F1: a
  symbolic-side import of `app` reached `runtime` transitively — the guard
  now forbids `app` on the symbolic side with a probe; F2: the R4 scans were
  not recursive — now `rglob` with a subpackage probe) and its WARNs closed
  (W1 full consultation sequence, W2 domain model-version stamp under a
  foreign provenance, W5 counts, W6 adapter close/message checks); its 17
  mutation probes on a scratch copy: 13 killed, and the 4 survivors (M9
  evaluate-before-ground, M11/M12 `symbolic`/`shared` -> `app`, M16
  provenance-stamped model version) are each now killed by the added tests.
  architecture-reviewer 0 FAIL: its WARNs closed here (`plan` docstring
  constraint + geometry-invariance test; dead `compose()` keywords removed;
  loop error text no longer names the BoxPush composition root; stale
  `tracks.py` sentence; rule-file path globs include `app/**`), its
  owner-decision item is recorded under Compatibility notes below.

Compatibility notes:
- `runtime.loop.ExecutiveLoopManager` name, import path, positional
  parameter order, `EpisodeOutcome`/`EpisodeResult`, `runtime.orchestrator`
  shim, CLI options, and trace serialization are unchanged.
- DELIBERATE CHANGE (report Phase 4 default assumption "preserve ... where
  practical"): the two-argument `ExecutiveLoopManager(env, task)` no longer
  composes BoxPush by default — that default is precisely the BoxPush import
  the phase removes, so a wrapper inside `runtime/` was not practical without
  defeating the boundary. Construction without `domain=`/`symbolic_track=`
  raises `TypeError`; every in-repo caller (runner + tests) goes through
  `app.box_push_v1.build_loop`, whose positional signature mirrors the old
  constructor. No out-of-repo caller exists.
- DELIBERATE CHANGE: `runtime.comparator` import path removed (module moved
  to `app.comparator`, same names: `BoxPushActionComparator`,
  `DEFAULT_COMPARATOR`, `LOW_CONFIDENCE`, `compare_tracks`). A re-export shim
  in `runtime/` would itself be the forbidden BoxPush/NL import. Only tests
  imported it; the frozen historical
  `docs/implementation/p4_mutation_harness.py` still names the old path and
  no longer applies as-is (it was already annotated as frozen at R2).
- OWNER DECISION (architecture-reviewer): the two changes above are exactly
  the report's Phase 4 stop condition "preserving an existing public
  constructor/import path conflicts materially with the clean boundary".
  ACCEPTED by the project owner on 2026-09-04 and recorded, with the
  `build_loop` migration, in `docs/decisions/R4_COMPOSITION_ROOT.md`. The
  alternative — a BoxPush default inside `runtime/` — would abandon
  acceptance criterion 1.
- OWNER ITEM: `CLAUDE.md`'s "Active implementation" list does not yet name
  `app/`; it now holds the comparator and the composition root and belongs
  on that list. Not edited here (project instructions are the owner's).
- Observable behavior: none. The universe derivation moved from
  first-sync caching to per-plan derivation from the same snapshot family;
  BoxPush identities never change within an episode, so every planner input
  is identical (transcripts byte-identical, R0 characterization green).

Warnings/deferred:
- WARN (accepted): `build_loop(..., loop_class=...)` exists for the
  established fault-injection test seam (subclassing `_plan`/`_run_cycle`);
  it is not a production extension point.
- WARN (accepted): a `DomainServices.monitor` implementation raising
  `ValueError` is wrapped by the loop into the typed fault exactly as before;
  any other exception type escaping an injected bundle propagates untyped,
  the same trust level as an injected policy (R2 note).
- DEFERRED(R5): the loop still reads `call.skill` for the NL observe label,
  `task.is_satisfied_by(state)` for the goal test, and
  `runtime/executive_history.py` keys repeated failures on
  `pre_state.world_key()`/`call.key()`; `TraceEntry` is typed to the shared
  V1 state/task/call types. None is BoxPush vocabulary, but the probe domain
  will surface which of them need a contract method versus a structural
  protocol on the domain's own types; extend from that concrete requirement
  (report: "extend the relevant contract based on concrete requirements").
- DEFERRED(R5): composite-comparator aggregation (report Phase 5 item 4).
- DEFERRED(R6): remaining scoped mypy debt (4), AST-scan hardening,
  `app/` joining the mypy/CI scope, observation aliasing, malformed-backend
  typed faults.

---

## R5 — Prove architectural substitutability

Status: COMPLETE (2026-09-04)

Objective: prove that the R4 runtime core executes a non-BoxPush domain
through the same `ExecutiveLoopManager`, same contracts, and same composition
shape, with no BoxPush import or conditional — using a TEST-ONLY probe, not a
second product domain (report Phase 5; `.claude/rules/v1-scope.md`).

Implementation:
- `tests/probe_counter.py` (new; test fixture, not production) — the counter
  probe, entirely under `tests/` per the report's default:
  - `CounterState(counter_id, value, target, stopped, tick)` — immutable;
    `world_key()`/`same_world()` over the canonical content, `tick` is the
    environment's own attempt bookkeeping excluded from the key (the counter
    analogue of the V1 snapshot's step counters, and the "unknown domain
    content" the runtime must carry without reading).
  - `CounterAction` — `Increment(amount)` / `Stop`, naming the counter it acts
    on (the identity the grounding gate checks); `skill`/`cost`/`key()`/
    `canonical()`.
  - `CounterEnvironment` — deterministic, offline, external-dependency-free
    fake backend implementing the R1 `Environment` seam
    (`reset`/`observe`/`export_full_state`/`execute_skill`/`is_terminal`/
    `render`); returns the shared typed `ExecutionResult` (no raw label) or
    `MalformedCall`/`UngroundedCall`; refuses use-before-reset and
    post-terminal execution with "refused:" infrastructure faults. The
    injectable `sticky_at` value is the designed physical obstacle: an
    `Increment(1)` there FAILS with the world unchanged (typed
    FAILURE/UNCHANGED); any other stride succeeds. The symbolic model does not
    know this rule — the frozen optimism/backend-authority relationship,
    reproduced on integers.
  - `CounterSymbolicTrack` (`SymbolicTrack`: exact projection on `sync`,
    `record_outcome` = evidence intake only) and `CounterDomainServices`
    (`DomainServices`: `plan` = Increment(1) to the target then Stop, `NoPlan`
    when the value exceeds the target, empty plan once stopped; `ground` =
    counter identity; `evaluate` = stays within target / at target, no
    environment knowledge; `predict` = both Decision-13 keys from the
    deterministic symbolic transition; `monitor` = non-success ->
    `EXECUTION_FAILURE_OF_APPLICABLE_SKILL` on the typed outcome alone,
    realized-vs-predicted key difference -> `STATE_EFFECT_MISMATCH` with the
    differing pair(s), bare `ValueError` on a counter-identity wiring error so
    the loop's §19.1 item 4 wrap is exercised on a foreign domain).
  - `CounterProposal` (call/coverage/confidence + an OPAQUE `evidence` tuple
    the runtime has no column for), `FakeReasoningTrack` (`ReasoningTrack`,
    LM-free: scripted proposals or an "echo" of its last observation;
    observe-before-propose precondition like the shipped track),
    `CounterActionComparator` (`ProposalComparator`: evidence only —
    COVERAGE_GAP for a call-less proposal, CONTRADICTION for a different call
    with the proposal's evidence carried in `residual`, empty report on
    agreement), `counter_recovery` (`RecoveryProvider`: advises a larger
    stride after a failed Increment).
  - `compose_probe` / `build_probe_loop` — the probe's composition root,
    mirroring `app.box_push_v1.compose`/`build_loop` in shape and injecting
    through the same `ExecutiveLoopManager` keyword seams. A TEST FIXTURE,
    not a supported runtime (`.claude/rules/v1-scope.md`): `/run-v1`, the
    BoxPush runner, and the CLI are unchanged and do not know it exists.
  - Static conformance witnesses (mypy) for every `shared.contracts` protocol
    at the probe's parameterization.
- `shared/contracts/domain_types.py` (new; exported from `shared.contracts`)
  — the answer to the question R4 deferred to R5 ("which of the loop's
  remaining reads need a contract method versus a structural protocol on the
  domain's own types"): none needs a `DomainServices` method; each is a
  structural protocol on the value type, and the member sets are exactly the
  runtime's reads (pinned by
  `tests/test_r5_probe.py::TestDomainTypeContractsAreWhatTheRuntimeReads`):
  `RuntimeState` (`world_key`, `same_world`), `RuntimeCall` (`skill`, `cost`,
  `key`, `canonical`), `TaskContract` (`is_satisfied_by`, `canonical`),
  `AdvisoryProposal` (`call: Optional[RuntimeCall]`, `coverage`,
  `confidence`). `runtime_checkable`; `same_world` is typed on `Self`;
  `RuntimeCall` documents the value-equality (`==`) the loop relies on for
  standing-recovery and discrepancy matching. The frozen V1 types
  (`StateSnapshot`, `GroundedSkillCall`, `Task`, `nl.track.NLProposal`)
  satisfy them unchanged; no BoxPush vocabulary (the R1 contract-source
  scans cover the new module unchanged). STATUS: declared and test-pinned
  only — no production annotation adopts them yet (`runtime/loop.py`,
  `runtime/executive_history.py`, and `shared/trace_schema.py` still name
  `StateSnapshot`/`GroundedSkillCall`/`Task`); adopting them is the R6
  typing migration, deliberately not done here.
- No file under `runtime/`, `domain/`, `symbolic/`, `nl/`, `app/`, or
  `functional_layer/` was edited. `shared/contracts/__init__.py` gained the
  four exports and a docstring sentence; no other `shared/` module changed.

Tests/evidence:
- `tests/test_r5_probe.py` (52 tests; suite 744 -> 796, pin updated in
  `REFACTOR_STATUS.md` in the same change set):
  - Acceptance 1 (`TestProbeFixtureIsBoxPushFree`): AST import allowlist over
    the fixture (stdlib + `shared` + `runtime` only, explicit forbidden
    roots), a whole-identifier BoxPush/geometry vocabulary scan with a
    non-vacuity probe, a SUBPROCESS proof that a full probe episode under BOTH
    shipped policies leaves no module rooted at the BoxPush DOMAIN PACKAGES
    (`domain`/`symbolic`/`nl`/`app`/adapter/backend/legacy) in `sys.modules`
    — any EXECUTED import of those surfaces; an import in a never-executed
    branch is caught by the static R4 allowlist instead — and a scan that no
    production module (`shared/`, `runtime/`, `app/`) names a probe/counter
    concept (no special case). Honest scope: `shared` is allowed, so the
    frozen V1 record modules (`shared.skills`, `shared.state_snapshot`,
    `shared.task`, `shared.execution`, `shared.ids`) DO load during a probe
    episode; acceptance 1 is a statement about `runtime/`, not about
    `shared/` (see DEFERRED below).
  - `TestProbeComponentsSatisfyTheContracts`: every probe component and value
    type is a runtime instance of its contract; the V1 types satisfy the R5
    structural protocols unchanged; probe values are frozen and the world key
    excludes bookkeeping; the probe's `plan` reads the authoritative state for
    identity only (different value/flag/tick -> identical `PlannerResult`, the
    Decision-6 pin the BoxPush bundle also carries).
  - `TestTheSameLoopRunsTheProbe` (the counter analogue of the R0
    characterization, through the unmodified loop): SYMBOLIC_PRIMARY
    `EXECUTE x5 + HALT` -> HALTED_REPEATED_FAILURE with exactly three
    `execution_failure_of_applicable_skill` discrepancies on the failing
    executed entries, world held at the sticky value by the backend, 5/5
    steps charged; ADVISORY `EXECUTE x5 + REQUEST_PROPOSAL + EXECUTE x2` ->
    GOAL_REACHED with the provider's `Increment(2)` enacted through the full
    consultation order (strict `DomainServices` proxy: plan -> head verdict ->
    ground -> evaluate -> predict -> monitor, seven times) and recorded as
    typed recovery provenance; a smooth environment reaches the goal with
    zero discrepancies and predictions equal to the realized keys on both
    bases; `NoPlan` -> HALTED_NO_PLAN with no fault; executive budget ->
    BUDGET_EXHAUSTED; a strict environment proxy proves the runtime uses only
    `reset`/`export_full_state`/`execute_skill` (one export per cycle, no
    re-export after an attempt); composition-root overrides honored by
    identity.
  - `TestAcquisitionOrderAndComparisonBeforeDecision`: one shared event log
    across a recording track, comparator, and policy pins the EXACT whole-
    episode order `[required_inputs, propose, compare, decide]` per enacting
    cycle and `[required_inputs, decide, required_inputs, propose, compare,
    decide]` for the escape cycle; the policy decides with the very objects
    (identity) the track and comparator produced; the compared symbolic side
    equals the enacted call (standing advice on the recovery cycle);
    disagreement is recorded, not followed, by the shipped policy;
    SYMBOLIC_PRIMARY never calls `propose()` while `observe()` is fed the
    `RuntimeCall.skill` label and typed outcome; an acquisition fault is
    pre-decision and fail-closed (no decision/selection/execution columns, no
    manufactured divergence, world untouched).
  - `TestTypedDecisionsDriveTheProbe`: a scripted pure policy drives each
    variant — `Halt` with/without a call (two outcomes), `Replan` free and
    bounded, `Execute` once per cycle, `RequestProposal` enacting the
    provider's advice through the gates, halting with "no recovery advice
    available" when no discrepancy evidence exists, and standing recovery
    matched BY VALUE (an equal but distinct call object is still the recovery
    enactment and consumes the advice — the `RuntimeCall` equality rule).
  - `TestExecutionValidationGatesEveryCall`: an ungrounded recovery call that
    is ALSO symbolically inapplicable faults `MISSING_GROUNDING` before the
    executor at zero cost (the §19.1 item 5 ordering asserted on the routing
    itself, not only on the consultation order); REQUEST_PROPOSAL hands the
    provider the LAST discrepancy for THAT call (two Increment(1) failures at
    different values plus a later failure of another call: the provider
    receives the second Increment(1) discrepancy by identity — §19.1 item 1,
    previously unpinned anywhere in the suite); an
    inapplicable recovery call is REPLANned at zero cost, never executed, and
    the stale advice is ended by the liveness guard; a policy's direct
    `Execute` of an inapplicable/ungrounded call is gated identically; the
    executor returns the environment's typed rejections verbatim; case-(c)
    charging from `primitive_steps_before_failure`; case-(a) first-class
    record; refusal before reset and after terminal; a monitor `ValueError`
    wrapped into `EXECUTOR_MONITOR_PROTOCOL_FAILURE` with the attempt standing.
  - `TestUnknownDomainEvidenceSurvives` (acceptance 3): state objects reach
    the trace and the policy BY IDENTITY with the domain's `tick` intact;
    domain discrepancy messages/model version recorded verbatim; proposal
    `evidence` reaches the policy by identity and the divergence `residual`
    and `canonical()` unchanged; a reactive test policy acts on that evidence
    while an AST scan proves the runtime never reads `.evidence`; the trace
    serializes the probe with the domain's own canonical forms, no adapter.
  - `TestCompositeComparatorAggregation` (item 4): a TEST-LOCAL composite
    concatenates fake components' findings in order (`contradicted`,
    `all_benign`, empty = agreement), is injectable into the probe loop
    beside the real probe comparator with the executed entries carrying
    exactly the fakes' payloads, and an allowlist of every production class
    implementing `compare` (`ProposalComparator`, `BoxPushActionComparator`
    in `app/comparator.py`) pins that no production composite/merged/
    aggregating comparator exists under any name.
  - `TestDomainTypeContractsAreWhatTheRuntimeReads`: AST receiver scans of
    `runtime/**` — bare-name receivers AND attribute chains
    (`self.task.x`, `result.post_state.x`, `error.result.post_state.x`,
    `decision.call.x`) — bound the reads on state/call/task/proposal
    receivers to the protocol member sets, with non-vacuity pins including
    the nested `self.task.is_satisfied_by`; a strict task proxy proves the
    runtime reads only `is_satisfied_by`; the protocols declare exactly the
    documented members and reject a bare object.
- Full suite: `python -B -m unittest discover -s tests -t .` -> 796 tests,
  OK (skipped=1: the pre-existing opt-in live-LM skip). Both headless demos
  (`--headless --delay 0`, `SDL_VIDEODRIVER=dummy`) byte-identical to
  `docs/refactor/baseline/demo_*.txt`; R0 characterization green under both
  policies. Scoped mypy (`python -m mypy shared runtime
  --ignore-missing-imports`) unchanged at 4 errors; `tests/contract_conformance.py`
  mypy-clean.
- `python -m mypy --ignore-missing-imports --follow-imports=silent
  tests/probe_counter.py` -> 31 errors, ALL of one category and NONE at the
  contract witnesses (line 640+): the shared typed channels
  (`ExecutionResult.call/pre_state/post_state`, `ValidatedCall`/
  `UngroundedCall`/`SymbolicallyInapplicable.call`, `PlanFound.plan`,
  `ExecutionDiscrepancy.call`) and the loop's `task` parameter are annotated
  with the V1 concrete types (`StateSnapshot`/`GroundedSkillCall`/`Task`).
  A foreign domain therefore conforms to every `shared.contracts` protocol
  statically AND runs, but the shared record types do not yet admit it
  statically — see DEFERRED(R6) below.
- Reviews: test-reviewer 0 FAIL — 40 mutation probes on a scratch copy; of
  the R5-module survivors it reported, six were closed in this change set
  and re-verified killed (M41a `from_recovery` via `is`; M20 first-matching
  and M39 any-call discrepancy selection in `_recovery_for`, both of which
  had survived the WHOLE 792-test suite; M8 a nested-receiver
  `result.post_state.canonical()` read; M28 a production `MergedComparators`
  class; the evaluate-before-ground routing inversion), and its scope/wording
  asks (subprocess proof scope, `PYTHONPATH` for the subprocess, wider
  geometry token list, plan state-invariance, ghost call also inapplicable)
  are done. architecture-reviewer 0 FAIL — its WARN-2 (`Optional[Any]` /
  `Any` annotations in the new contract) and WARN-3 (value equality
  undocumented) fixed in `domain_types.py`; WARN-1 (protocols not yet
  adopted by production annotations) recorded above; its DEFERRED items
  recorded below.

Compatibility notes:
- No public import, constructor, CLI option, or trace field changed.
  `shared.contracts.__all__` grew by four names (pure addition). Trace
  serialization is unchanged: `TraceEntry.canonical()` calls the same
  `canonical()`/`world_key()` members on whichever domain types it holds.
- Observable behavior: none. No runtime code changed; both demo transcripts
  are byte-identical.
- Serialized-trace caveat (frozen format, unchanged): "unknown evidence
  survives tracing unchanged" holds for the in-memory `TraceEntry` objects
  (state/proposal by identity) and for the domain's own `canonical()` forms
  of task/call/discrepancy/divergence; the canonical JSON still reduces a
  state to `world_key()`, so a domain field such as the probe's `tick` is
  carried in memory but not serialized. This is the existing trace contract,
  not an R5 change.
- Observed fact, now pinned: the executive layer uses only
  `reset`/`export_full_state`/`execute_skill` of the environment;
  `observe`/`is_terminal`/`render` are never called by the loop.

Warnings/deferred:
- WARN (accepted): the probe reuses the shared typed CHANNELS
  (`ExecutionResult`, `PlannerResult`, `CallValidation`,
  `ExecutionDiscrepancy`, `TrackDivergence`, faults, reports, keys) as they
  are — they carry no BoxPush vocabulary and the contracts are typed on them.
  `RawLabel`/`PRODUCIBLE_RAW_LABELS` in `shared/execution.py` are BoxPush-
  specific provenance but optional (`raw_label=None`), so the probe never
  touches them.
- WARN (accepted): `build_probe_loop` mirrors `app.box_push_v1.build_loop`
  by construction rather than by shared code — a shared generic
  "compose over defaults" helper would be a production abstraction with one
  product consumer; not added. `_StrictServicesProxy`/`_CannedComparator`
  are likewise local copies of the R4 test helpers.
- WARN (accepted, test-reviewer): the R5 module covers acquisition ORDER;
  the once-per-cycle acquisition cache remains pinned only by the R3 test
  `test_acquisition_is_cached_across_iterations_within_one_cycle`. AST-based
  read scans cannot see a `getattr(nl_proposal, "evidence")` read (inherent
  limit; the identity/residual tests cover the observable consequence).
- WARN (accepted): `test_the_runtime_and_contracts_name_no_probe_concept`
  forbids the substrings "counter"/"probe" in production identifiers; if a
  legitimate production name (e.g. `step_counter`) ever trips it, narrow it
  to the fixture's class/module names rather than deleting it.
- DEFERRED(R6): static typing of the shared record types. The runtime and the
  contracts are generic in behavior, but `ExecutionResult`, the
  `CallValidation` variants, `PlanFound`, `ExecutionDiscrepancy`, `TraceEntry`,
  `ExecutiveHistory.failure_key`, and the `ExecutiveLoopManager`/`execute`
  signatures are annotated with the V1 concrete types (the 31 fixture mypy
  errors above). Making them generic in call/state (or annotating against the
  R5 `RuntimeState`/`RuntimeCall`/`TaskContract` protocols) is a typing-only
  change across frozen shared types and is the report's Phase 6 acceptance
  "core contracts, runtime ... pass static type checking".
- DEFERRED(R6) design note (architecture-reviewer): generalizing
  `ExecutionResult.call` will meet `ExecutionResult.__post_init__` reading
  the BoxPush `PRODUCIBLE_RAW_LABELS.get(self.call.skill)` table
  (`shared/execution.py`) — a BoxPush coupling inside a shared typed
  channel that the probe sidesteps with `raw_label=None`. R6 must resolve
  the typing with generics/protocols, never by weakening the raw-label
  vocabulary check and never with `Any`/`# type: ignore` in the fixture;
  the fixture's mypy witnesses are the measurable R6 target (31 errors is
  the baseline).
- DEFERRED (unassigned; a real next domain): `shared/skills.py`
  (`SkillName`, the frozen registry), `shared/state_snapshot.py`,
  `shared/task.py`, `shared/ids.py`, and `shared/execution.py::RawLabel`
  remain BoxPush-vocabulary V1 types under `shared/`; acceptance 1 holds for
  `runtime/` and is not a claim about `shared/`. Unresolved, not solved; the
  R5 protocols name the domain-neutral surface a future extraction would
  target.
- DEFERRED(R6): remaining scoped mypy debt (4), AST-scan hardening, `app/`
  and `tests/contract_conformance.py`/`tests/probe_counter.py` joining the
  mypy/CI scope, observation aliasing, malformed-backend typed faults.

---

## R6 — Correctness and repository hygiene

Status: COMPLETE (2026-09-05) — all four commits of the owner's split are
implemented and verified; commit 4 takes the owner's option (a) (reference-only
quarantine) instead of the originally planned `git mv` (see "Commit 4" below).
Reviews: test-reviewer 0 FAIL, architecture-reviewer 0 FAIL (their WARNs closed
in commit 3 or recorded under Warnings/deferred).

Objective: report Phase 6 items 1-6 — observation aliasing, malformed backend
returns, the discriminated NL proposal type, static typing of the architectural
core, CI with lint/type gates, a reproducible dependency lock, and the legacy
quarantine — under the R6 tooling decisions and owner decisions recorded in
`docs/refactor/REFACTOR_STATUS.md`.

### Commit 1 — hygiene (report items 1-3)

Implementation:
- `functional_layer/custom_env/box_push/env/box_push_v1_adapter.py`
  (item 1) `observe()` returns `copy.deepcopy(self._obs)`: the nested per-agent
  dicts and image arrays it used to hand out (shallow `dict(...)`) were the very
  objects `_drive` feeds to the backend skills on the next primitive step.
  `export_full_state()` was already a frozen value built from ints.
  (item 2) Every value read back from the backend is validated at the boundary
  into the typed `MALFORMED_BACKEND_RESULT` fault (`_malformed` helper): the
  `env.reset()` pair and the `env.step()` 5-tuple (`_unpack_step`: per-agent
  observation mappings, per-agent termination/truncation mappings covering every
  agent), the `world` read that builds the snapshot (`_snapshot_from_world`,
  wrapping `AttributeError`/`KeyError`/`TypeError`/`ValueError` including the
  typed snapshot's own refusals), the entities view derived from `world` on
  every primitive step (`_drive`), and the episode flags (`_episode_flags`).
  When an attempt already consumed env steps the fault carries the single
  case-(c) key `primitive_steps_before_failure=N` (N = env.step calls that
  returned); pre-attempt reads carry none; no message starts with `refused:`.
  A raise out of `env.reset` is wrapped as `BACKEND_API_EXCEPTION` (pre-attempt,
  no key), mirroring the `env.step` wrap. The three-case provenance comment in
  `shared/faults.py` now states this third `result=None` shape (a keyless,
  non-`refused:` boundary fault = pre-attempt, zero steps) and that the key
  means "primitives KNOWN to have run" (a stated lower bound at the executor).
  The pre-attempt export now runs BEFORE identity resolution so pre-flight and
  skill construction read a world the export has just validated — nothing
  transitions in between, so the recorded `pre_state` is identical.
- `runtime/executor.py` (item 2, runtime side): an environment return outside
  `ExecutionResult | MalformedCall | UngroundedCall` is raised as
  `MALFORMED_BACKEND_RESULT` instead of reaching the loop as an object whose
  attribute reads raise bare exceptions. The attempt reached the executor, so
  one executive step is consumed (Decision 2); the backend reported no typed
  accounting, so the detail carries `primitive_steps_before_failure=0` and
  states that 0 is the lower bound (the loop's case-(c) charge is then exactly
  one executive step and zero primitives).
- `nl/track.py` (item 3): `NLProposal` is the discriminated union
  `GroundedProposal | MalformedProposal` (`TypeAlias`; PEP 604 so
  `isinstance(x, NLProposal)` also works at runtime). `GroundedProposal(call,
  coverage, confidence, repaired=False)` requires a `GroundedSkillCall` and a
  `ConfidenceReport`; `MalformedProposal(malformed, coverage)` requires a
  `MalformedCall`. Both keep the runtime's `AdvisoryProposal` read surface —
  `MalformedProposal.call`/`.confidence` and `GroundedProposal.malformed` are
  typed-`None` properties — so the trace columns and the R5 protocol are
  unchanged. `NLTrack.propose` returns the variant; `nl/__init__.py` exports
  both. `app/comparator.py` narrows with `isinstance(nl_proposal,
  MalformedProposal)` (the two pre-existing `union-attr` mypy errors are gone;
  the redundant `confidence is not None` guard is dropped because the grounded
  variant's confidence is non-optional).

Tests/evidence:
- `tests/test_r6_hygiene.py` (22 tests; suite 796 -> 818; a 23rd, the
  `env.reset` raise, was added after the architecture review):
  `TestObservationsDoNotAliasBackendState` (deep copy by identity and content;
  every mutation kind on the returned mapping — in-place array writes, scalar
  overwrites, key deletion, nested replacement — invisible to the adapter's own
  observation, the next `observe()`, and the exact state; a spying `_drive`
  proves the observation handed to the skills after vandalism equals a pristine
  adapter's and the attempt is byte-identical; the exported snapshot is frozen
  at every level and unaffected by later backend transitions);
  `TestMalformedBackendReturnsAreTypedFaults` (step tuple of wrong length / not
  a tuple, per-agent flags as lists, flags or observations missing an agent,
  observations not a mapping, malformed reset return with the D8 latch kept
  unset and a sound reset recovering, six malformed-world shapes before an
  attempt at both `export_full_state` and the pre-attempt export inside
  `execute_skill`, a malformed episode record, a world that turns malformed
  after the attempt (case-(c) provenance = the primitives the drive consumed)
  and mid-attempt (provenance = 2), and the sound-backend behavior-preservation
  pin); `TestExecutorNormalizesOffContractReturns` on the R5 probe (five
  garbage return shapes -> the typed fault with the lower-bound provenance; the
  loop records the fault, no execution, one executive step charged, no
  discrepancy, and the backend did run; typed returns pass verbatim by
  identity); `TestProposalVariants` (the real `NLTrack` over `RecordedLM`
  returns each variant; both satisfy `AdvisoryProposal`, are frozen and are
  instances of the union; the comparator narrows: malformed -> COVERAGE_GAP +
  TRANSLATION_RESIDUAL, grounded in-model -> empty report).
- `tests/contract_conformance.py::proposal_narrows_statically` — the mypy
  witness that one `isinstance` check proves the payload (a function returning
  `proposal.call` typed `GroundedSkillCall`, no Optional unwrapping).
- Adapted (assertions preserved or strengthened): `tests/test_p3_nl.py`
  (the exactly-one invariant is now structural: both variants refuse a missing
  or foreign payload and neither admits the other's field);
  `tests/test_p4_runtime.py`, `tests/test_r3_comparison.py`,
  `tests/test_r4_composition.py`, `tests/test_r5_probe.py` construct the
  variants through their existing `_proposal` helpers.
- Mutation probes on a scratch copy (all KILLED by the new tests): shallow
  `observe()`; unvalidated `env.step` unpacking; executor pass-through;
  unguarded world export.
- Full suite 818, OK (skipped=1); both headless demos byte-identical to
  `docs/refactor/baseline/demo_*.txt`.

### Commit 2 — typing (report acceptance "core contracts, runtime, and new policies pass static type checking")

Implementation:
- `shared/value_contracts.py` (new leaf): the R5 structural protocols
  `RuntimeState` / `RuntimeCall` / `TaskContract` / `AdvisoryProposal` moved
  here verbatim so they can BOUND the generic record types without an import
  cycle (`shared.contracts` imports the records; the records now import the
  bounds). `shared/contracts/domain_types.py` re-exports the same objects (the
  R5 import path and the `shared.contracts` export are unchanged);
  `shared.__all__` exports the four names. The leaf imports only
  `shared.comparison_keys` and `shared.reports` (pinned by test).
- Generic frozen records, PEP 695 syntax, covariant by construction (frozen
  fields; pinned by the `v1_records_are_also_generic_records` witness):
  `ExecutionResult[StateT: RuntimeState, CallT: RuntimeCall]`
  (`shared/execution.py`), `PlanFound[CallT: RuntimeCall]` and an abstract
  `PlannerResult.canonical` (`shared/planner_result.py`),
  `ExecutionDiscrepancy[CallT: RuntimeCall]` (`shared/discrepancy.py`),
  `TraceEntry[StateT, CallT, TaskT: TaskContract]` (`shared/trace_schema.py`),
  `ValidatedCall[CallT]` / `UngroundedCall[CallT]` /
  `SymbolicallyInapplicable[CallT]` (`shared/skills.py`; unbounded — held,
  never read; `OutsideSymbolicModel` stays V1-concrete because it consults the
  frozen registry). `TraceEntry.nl_proposal` is typed `Optional[RuntimeCall]`:
  the advisory proposal type is track-owned and a type-parameter bound cannot
  name another parameter, so the column records what the `AdvisoryProposal`
  contract guarantees (docstring in `shared/trace_schema.py`).
- Generic runtime: `ExecutiveLoopManager[StateT, SymbolicStateT, CallT, TaskT,
  ProposalT: AdvisoryProposal]` with every injected collaborator typed at those
  parameters (`env: Environment[StateT, CallT, ExecutionAttempt[StateT, CallT],
  object]`, `nl_track: ReasoningTrack[StateT, TaskT, ProposalT]`, `policy:
  OrchestrationPolicyContract[StateT, CallT, ProposalT]`, `domain:
  DomainServices[StateT, SymbolicStateT, CallT]`, `symbolic_track:
  SymbolicTrack[StateT, SymbolicStateT]`, `comparator:
  ProposalComparator[CallT, ProposalT]`, `recovery_provider:
  RecoveryProvider[CallT]`); `EpisodeResult` and `ExecutiveHistory` generic in
  `[StateT, CallT, TaskT]`; `runtime/executor.py::execute` generic over the R1
  `Environment` contract with the `ExecutionAttempt[StateT, CallT]` type alias;
  `runtime/policies.py` generic in the call type too
  (`SymbolicPrimaryPolicy[StateT, CallT, ProposalT]` — the routing reads only
  the typed plan channel, verdict, count and standing advice); the legacy
  `runtime/orchestrator.py` shim's context is typed
  `PreliminaryContext[None, GroundedSkillCall]`. `shared/contracts/domain.py`
  bounds its state/call TypeVars by the value protocols and types
  `monitor(result: ExecutionResult[StateT, CallT])`.
- `app/box_push_v1.py` names the V1 parameterization once (`V1Loop`,
  `V1DomainServices`, ..., `V1Policy`) and `build_loop`/`compose`/
  `BoxPushComponents` are fully annotated (`env: V1Environment`).
- Two pre-existing debts closed: `shared/skill_ir.py` reused a loop variable
  across two typed loops (renamed); `runtime/loop.py` `extra_faults` tuple
  annotation. `ExecutiveLoopManager._entry` takes explicit typed keyword
  parameters (no `**kw: Any`), so every trace column the loop records is
  type-checked at its call site (architecture-reviewer W2).
- `tests/probe_counter.py` annotated at the probe parameterization
  (`ExecutionResult[CounterState, CounterAction]`, `ProbeLoop`, ...): 31 -> 0
  mypy errors with no `Any` and no `type: ignore` (the R5 target).

Tests/evidence:
- `tests/test_r6_typing.py` (8 tests; suite 818 -> 826): the mypy gate exactly
  as CI runs it (`shared runtime app tests/contract_conformance.py
  tests/probe_counter.py --ignore-missing-imports --follow-imports=silent` ->
  "Success: no issues found") plus a NON-VACUITY probe (a V1-typed record given
  a foreign call and a loop handed a non-task are both reported); both skipped
  — not passed — when mypy is absent. Runtime pins (no type checker): the
  records' and the loop's `__type_params__` names and bounds, records still
  frozen/slotted/subscriptable, `PlannerResult` abstract with every concrete
  result serializing, protocol identity across the three import paths, the
  leaf module's import discipline.
- `tests/contract_conformance.py` gains the R6 witnesses
  `v1_loop_is_typed_at_the_v1_parameters`, `v1_trace_keeps_domain_precision`
  (a V1 entry's `selected_call.box` is reachable statically — nothing widened
  to `Any`), `v1_records_are_also_generic_records` (covariance), and the policy
  witnesses take the third parameter.
- Adapted: `tests/test_canonical_faithfulness.py` coverage scan skips abstract
  bases and protocols (they have no serialization of their own; every concrete
  type is still required); `tests/test_observation_contract.py`'s export
  completeness is satisfied by the four new `shared.__all__` names.
- `python -m mypy shared runtime app --ignore-missing-imports
  --follow-imports=silent`: 4 -> 0 errors (36 source files); with the two test
  files (the config scope) 38 files, Success. Full suite 826, OK (skipped=1);
  both demos byte-identical.

### Commit 3 — tooling (report items 4-5)

Implementation:
- `pyproject.toml`: `[project]` metadata, `requires-python = ">=3.12,<3.13"`
  (Decision 10), runtime dependencies pinned exactly and mirroring
  `requirements.txt` line for line, `[dependency-groups] dev = mypy==2.3.1,
  ruff==0.16.6, PyYAML==6.0.3` (PyYAML parses the workflow in
  `tests/test_r6_tooling.py`; declared so the default suite never depends on a
  transitive edge — architecture-reviewer W6), `[tool.uv] package = false` (flat multi-package tree, never
  built/installed), `[tool.mypy]` with `files` = the R6 gate scope,
  `follow_imports = "silent"`, `ignore_missing_imports`, `[tool.ruff]` lint
  only (`E4,E7,E9,F,W`; legacy/research trees excluded; no formatter — frozen
  sources are not reformatted).
- `uv.lock` (`uv lock`, uv 0.12.9): the transitive environment — 91 packages,
  every registry distribution with sha256 hashes, `requires-python ==3.12.*`,
  the project itself virtual. `uv lock` WARNS that the frozen `numpy==2.4.0`
  pin is yanked upstream ("Backward compatibility bug"); the pin is a recorded
  V1 decision (decisions §18 item 2) and is deliberately not changed here.
- `.github/workflows/offline-tests.yml`: `astral-sh/setup-uv` (uv 0.12.9,
  Python 3.12), `uv sync --locked` (refuses a stale lock, verifies hashes),
  the offline suite, `uv run ruff check shared runtime app`, `uv run mypy`
  (config scope). `SDL_VIDEODRIVER=dummy`; no live LM, service, secret or
  network step beyond package installation. Live-LM tests stay opt-in
  (`MAAOS_LIVE_LM=1`).
- Lint hygiene needed for the core to pass ruff: three unused imports
  (`shared/state_snapshot.py`, `shared/symbolic_state.py`, `shared/task.py`)
  and four ambiguous `l` comprehension variables renamed
  (`shared/symbolic_state.py`) — no behavior.
- `README.md` environment section names the lock and the CI gates.

Tests/evidence:
- `tests/test_r6_tooling.py` (16 tests; suite 826 -> 842): pyproject vs
  requirements pin agreement (every dependency `==`-pinned); dev-group pins;
  not a distributable package; the mypy scope equals `tests/test_r6_typing.py`'s
  gate; ruff lint-only over the default error classes with the legacy trees
  excluded; every runtime and dev pin locked at its version; every locked
  distribution hashed (transitive closure > 50 packages); lock Python 3.12;
  the parsed workflow (push + pull_request triggers, locked sync, the exact
  suite command, `python-version: "3.12"`, the two gate commands, no
  live-model/service/secret content in the executable job); the ruff gate on
  `shared runtime app` with a non-vacuity probe (skipped without ruff).
- `python -m mypy` (config-driven) -> Success (38 files); `python -m ruff
  check shared runtime app` -> All checks passed; `uv lock --check` -> up to
  date. Full suite 842, OK (skipped=1); both demos byte-identical.
- NOT verified here: an actual GitHub Actions run (no `gh` access and the
  branch is unpushed) and `uv sync` into a fresh virtual environment (it would
  duplicate the multi-GB pinned stack locally). The lock/workflow/test evidence
  above is what backs the "CI runs offline" criterion until the first push.

### Earlier-phase items owned by R6

- AST-scan hardening (R1 WARN): `tests/test_r1_contracts.py::_defined_names`
  now also scans `*args`/`**kwargs`, lambda parameters, annotation expressions
  (including string annotations, names and attribute segments), and names
  imported from `shared` (so a BoxPush-typed import such as `BoxId` trips the
  vocabulary scan even though the `shared` root is allowed); morphological
  variants (`pushed`, `boxes`, ...) trip via stem matching while `pose` stays
  whole-word (`proposal`/`propose` are contract words). Non-vacuity test
  `test_the_vocabulary_scan_sees_every_binding_site` (suite 842 -> 843).
- Mutation-harness O1-O4 port (R2): rather than editing the frozen
  `docs/implementation/p4_mutation_harness.py`, the four O-series mutations
  were re-applied to `runtime/policies.py` on a scratch export (NoPlan ->
  Replan; threshold ignored; primary escapes to REQUEST_PROPOSAL; primary
  declares the NL input; inapplicable head executed) — all five KILLED by the
  current suite (4 / 50 / 16 / 5 / 5 failures respectively).
- `app/` in the mypy/CI scope and the probe fixture / conformance witnesses in
  the gate (R4/R5): done in commits 2-3.
- Legacy shim `state=None` typing (R2): done (`PreliminaryContext[None,
  GroundedSkillCall]`).

### Commit 4 — legacy quarantine (report item 6): OPTION (a), owner decision 2026-09-05

The owner's original instruction was a pure `git mv` of `middleware_layer/` and
`model_layer/` under `legacy/` with no content edits, stopping if the move broke
any test or import. It would have:
- break the supported runner's opt-in live path:
  `functional_layer/custom_env/box_push/env/box_push_v1_run.py:92`
  imports `model_layer.planner.v1_nl_live` for `--nl live`;
- break the opt-in live test `tests/test_p3_live_lm.py:17` (same import);
- move a V1 component: `model_layer/planner/v1_nl_live.py` is the V1 live
  DSPy seam (decisions §18 item 10 / P0_V1_DECISIONS.md:852 name it as the
  only dspy binding), placed on the legacy side only because the import guard
  forbids `nl/` from importing dspy;
- turn the suite red by construction: `tests/test_no_backend_imports.py`
  auto-discovers every top-level directory holding `.py` files that is not in
  its `LEGACY_PACKAGES` list as a GUARDED package, so a new `legacy/` tree
  would be scanned and fail on its numpy/dspy/backend imports — a pure `git mv`
  with no content edits cannot keep the suite green (architecture-reviewer);
- break the legacy runners/demos that import both packages
  (`functional_layer/custom_env/box_push/env/box_push_per_step.py`,
  `.../box_push_centralized.py`, `.../box_push_schema.py`,
  `functional_layer/custom_env/cooperative_search_transport/**`,
  `functional_layer/envs/*.py`) and the intra-package absolute imports inside
  `middleware_layer/` and `model_layer/` themselves.
The owner therefore chose the report's FIRST alternative for item 6 — "mark
legacy packages clearly as unsupported/reference-only" — implemented as:
- `README.md` "Legacy code": a REFERENCE-ONLY banner naming both trees, the
  gate exclusion, the import prohibition, and the single named exception;
- `.claude/rules/legacy-packages.md` (new rule): both trees are pre-V1
  reference code, excluded from the mypy/ruff gates, and must not be imported
  by `shared/`, `runtime/`, `app/`, or `tests/` — with ONE named exception,
  `model_layer.planner.v1_nl_live`, the supported V1 live NL seam;
- `tests/test_r6_legacy_boundary.py` (5 tests): an AST scan of the four V1-side
  directories for static AND dynamic (`importlib.import_module` / `__import__`)
  legacy imports whose allowlist is exactly `{"model_layer.planner.v1_nl_live"}`
  (non-vacuous: the lazy in-function import in `tests/test_p3_live_lm.py` is
  seen and is the only hit; a scratch probe proves all four import shapes are
  detected); the exception module exists, defines `build_live_seam`, and is
  named by the runner's opt-in path; both trees exist and sit outside
  `[tool.mypy] files` and inside `[tool.ruff] extend-exclude`; the rule and the
  README state the boundary and the exception.
No file under either legacy tree was edited or moved.

Compatibility notes:
- Trace serialization, CLI options, `EpisodeOutcome`/`EpisodeResult` shapes,
  `runtime.orchestrator` shim, the accepted V1 outcomes and the three designed
  discrepancies are unchanged (R0 characterization green; demos byte-identical).
- DELIBERATE CHANGE (report item 3): `NLProposal(call=..., malformed=..., ...)`
  direct construction no longer exists; construct `GroundedProposal` /
  `MalformedProposal`. The name `NLProposal` remains importable from `nl` and
  `nl.track` as the union type; every attribute read the runtime, comparator,
  trace, and live test perform is unchanged. In-repo callers (tests) adapted;
  no out-of-repo caller is known.
- DELIBERATE CHANGE: `PlannerResult` now has an abstract `canonical`; the base
  was already uninstantiable (`__new__`), so only a hypothetical subclass
  without `canonical` is affected (none exists).
- Typing-only changes (no runtime effect): the loop's/`build_loop`'s parameter
  annotations, the generic parameters on the records (`ExecutionResult`,
  `PlanFound`, ... remain constructible with the same keywords; bare
  annotations elsewhere keep working), `TraceEntry.nl_proposal: Optional[RuntimeCall]`,
  `shared.__all__` + 4 names.
- Observable behavior differences: none on any path the frozen backend takes
  (it never returns a malformed value). Differences exist only where the
  backend or a foreign environment misbehaves: a malformed `env.reset`/`env.step`
  return, a malformed `world`, or an off-contract `execute_skill` return now
  surfaces as `InfrastructureFaultError(MALFORMED_BACKEND_RESULT)` (previously
  a bare `ValueError`/`AttributeError`/`TypeError`/`KeyError`); the runtime
  charges an off-contract return as one executive step with zero primitives.

Warnings/deferred:
- WARN (recorded, owner): `numpy==2.4.0` is yanked upstream; `uv lock` resolves
  the exact pin regardless. Bumping is a recorded-decision matter.
- WARN (accepted): the mypy and ruff gate tests SKIP when the tools are not
  installed (they are dev-group tools, not runtime dependencies); CI installs
  the dev group, so the gates are enforced there and on any developer machine
  with `uv sync`.
- WARN (accepted): the executor's off-contract charge reports the primitive
  count as the lower bound 0 and says so in the fault detail; no other honest
  number exists at that boundary.
- WARN (accepted): the domain/symbolic/nl side is type-checked for inference
  only (`follow_imports = silent`); `python -m mypy domain symbolic nl
  --ignore-missing-imports --follow-imports=silent` reports 30 errors in 3
  files (26 `str` vs `PredicateName` NewType arguments in
  `domain/box_push_v1.py`, 2 in `symbolic/planner.py`, 3 in
  `symbolic/predictor.py` — pre-existing, typing-only, frozen V1 sources) and
  the sys.path-mounted adapter 10; both outside the report's "architectural
  core" and deliberately outside the gate.
- DEFERRED (post-R6, owner's own task, recorded 2026-09-05): "Relocate the
  live NL seam out of `model_layer/` to a non-legacy home compatible with the
  import guard, then move both legacy trees under `legacy/`." Until then the
  quarantine is the option-(a) boundary above. (The R4 owner item —
  `CLAUDE.md` "Active implementation" naming `app/` — is resolved: the entry
  is present.)
- WARN (accepted, architecture-reviewer W3): the contract protocols still name a
  few records unparameterized (`DomainServices.ground -> Optional[UngroundedCall]`,
  `.monitor -> Tuple[ExecutionDiscrepancy, ...]`, `SymbolicTrack.record_outcome`,
  `RecoveryProvider.__call__`, `V1Environment.execute_skill`): under mypy
  defaults these are `[Any]`-parameterized, so the loop's parameterized
  annotations at those seams are accepted rather than proven. Variance
  (contravariant TypeVars in covariant positions) or the frozen P0
  `V1Environment` prevent parameterizing them without a contract change;
  `disallow_any_generics` would surface them. Not an acceptance gap.
- WARN (accepted, architecture-reviewer W5): the adapter reads `self._env.agents`
  raw in the R6 validators (the backend's agent-id list, never a return value);
  a raise out of `env.reset` is now wrapped as `BACKEND_API_EXCEPTION` like
  `env.step` (test `test_a_raise_out_of_reset_is_a_typed_backend_fault`).
- DEFERRED (unassigned; a real next domain): `shared/skills.py`,
  `shared/state_snapshot.py`, `shared/task.py`, `shared/ids.py`,
  `shared/execution.py::RawLabel`/`PRODUCIBLE_RAW_LABELS` remain
  BoxPush-vocabulary V1 types under `shared/` (R5 note); the generic records
  now hold them as parameters rather than by name, which is as far as R6 goes
  without a second real domain.

Compatibility notes:
- Pending.

Warnings/deferred:
- Pending.

---

## Final Definition of Completion

Status: NOT YET AUDITED

Record the final `/refactor-audit` result here only after R6.
