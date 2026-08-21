# MAAOS Symbolic-Twin BoxPush V1 — P0-P4 Implementation Documentation

**Status: COMPLETE** — closed by a three-auditor hostile final audit with 0 FAIL on every
surface (`docs/handoff/section18.md` revision 2026-08-21n). Every claim below is grounded in
the current tree; where low-level behavior is clear in code, this document points at the
file/class/function instead of restating the algorithm.

---

## 1. Scope and V1 assumptions

Scope is **P0-P4 only** (`docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`). V1 is classical and
deterministic at the symbolic level; fully observable for the symbolic track (exact canonical
state, no probabilistic belief); sequential at the executive level (no asynchronous skill
overlap); text/typed-data only for the NL track (no VLM); skill cost 1 throughout. The
symbolic model is **intentionally optimistic**: a grounded skill may be symbolically
applicable and still fail in the authoritative backend — that failure is the expected,
observable signal (§16, §19), never a reason to add a feasibility oracle.

## 2. Repository, branch, commit, commands

- Branch `middleware_layer`, HEAD `c4d21c7`; phase baselines tagged `p0-v1-freeze`,
  `p1-v1-classical-env`, `p2-v1-symbolic-baseline`, `p3-v1-nl-baseline`,
  `p4-v1-orchestrator`.
- Full battery (repo root): `python -B -m unittest discover -s tests -t .`
  → 629 tests, OK (1 skip: the `MAAOS_LIVE_LM=1`-gated live test).
- Mutation harnesses (mutate + restore product files; run one at a time):
  `python -B docs/implementation/p{0..4}_mutation_harness.py` → 121/30/50/37/43, all killed.
- Regenerate the byte-pinned traces after intentional behavior changes:
  `python -B -m tests.test_v1_acceptance --write`.
- Live NL integration: `MAAOS_LIVE_LM=1 python -B -m unittest tests.test_p3_live_lm`
  (requires local Ollama serving the pinned model).
- **Human-watchable V1 run** (pygame window, no LLM needed):
  `cd functional_layer/custom_env/box_push/env && python box_push_v1_run.py`
  (`--policy symbolic_primary` to watch the designed halt; `--headless`; `--delay 0.05`).
- Legacy runner (superseded reference, not a V1 path):
  `cd functional_layer/custom_env/box_push/env && python box_push_centralized.py`.

## 3. Architecture and runtime information flow

One executive cycle (`runtime/loop.py::ExecutiveLoopManager._run_cycle`):

```
env.export_full_state ── belief.sync ──> plan (symbolic/planner.py)
      │                                        │ PlanFound / NoPlan / PlannerFailure
      │                                        ▼
      │                    orchestrator.decide (runtime/orchestrator.py)  ◄─ failure_count
      │                       EXECUTE / REPLAN / REQUEST_PROPOSAL / HALT
      ▼                                        ▼
grounding gate (identity) ──> symbolic gate (evaluate) ──> predictions recorded
                                               ▼
                    executor (runtime/executor.py) ──> BoxPushV1Adapter ──> backend env.step*
                                               ▼
     belief.record_outcome + nl_track.observe (on result.post_state)
                                               ▼
   monitor (symbolic/monitor.py) → ExecutionDiscrepancy   comparator → TrackDivergence
                                               ▼
              TraceEntry → ExecutiveHistory (budgets, repeated-failure counts)
```

Import-guard matrix (fail-closed, namespace-package-proof —
`tests/test_no_backend_imports.py`): `shared`→stdlib; `domain`→shared (whitelist-tested);
`symbolic`→shared+domain; `nl`→shared+domain (dspy banned); `runtime`→shared+domain+
symbolic+nl; the backend is reachable only by injection into the loop. Peer isolation
(`nl`↔`symbolic` in neither direction) and predictor unreachability from
applicability/belief/planner (five closed escape routes) are AST-enforced
(`tests/test_p3_nl.py::TestPeerTrackGuards`, `tests/test_p2_symbolic.py::TestSymbolicSideGuards`).

## 4. Shared typed contracts (`shared/`, frozen at P0)

`skills.py` (registry, `GroundedSkillCall`, five `CallValidation` outcomes incl.
`OutsideSymbolicModel`), `skill_ir.py` (`SkillIR`/`DomainIR`, bind/unbind, registry-object
identity validation), `state_snapshot.py`, `symbolic_state.py` (`GroundedLiteral`,
`SymbolicState`, `ProjectionContract`), `comparison_keys.py` (`WorldKey`/`SymbolicKey` typed
str), `execution.py` (§8-9), `planner_result.py` (§15), `discrepancy.py`/`divergence.py`/
`faults.py` (§16), `reports.py` (`CoverageReport` with explicit residual,
`ConfidenceReport`), `trace_schema.py` (`TraceEntry` with lifecycle legality),
`orchestration_config.py`, `observation.py` (per-track channel visibility `V1_VISIBILITY`),
`task.py`, `ids.py`, `versioning.py`, `backend_contract.py` (`V1Environment` protocol,
obligations D1-D16). Serialization faithfulness is property-tested for every contract type
(`tests/test_canonical_faithfulness.py`).

## 5. Canonical `StateSnapshot` and normalization

`shared/state_snapshot.py::StateSnapshot` — agents (id/position/direction), boxes
(id/position/required_agents/is_target/delivered), `StaticWorld` (walls, delivery zone),
episode bookkeeping. Equality/hash delegate to `world_key()` (sha256 over the canonical world
form, episode excluded); `replay_key()` includes episode. Golden keys for the frozen initial
state: world `f7cf4105cddd127a…`, symbolic `48b414cda26a60e3…`
(`tests/test_contract_invariants.py`; the world key also in `tests/test_p1_adapter.py`). Order-independence and per-field key sensitivity are tested;
the P1 adapter builds snapshots from `core_env.world` only (never belief/rendered layers —
`box_push_v1_adapter.py::export_full_state`).

## 6. Executive skill registry and backend mappings

`shared/skills.py::REGISTRY` — five executive skills, no primitives (audited: no
turn/move/stay on any executive surface):

| Skill | Dispatch key | Typed params | Backend implementation (via adapter arm) |
|---|---|---|---|
| GotoPushPose | `goto_push_pose` | AgentId, BoxId, ZoneId | `skill_executor_push.py::GotoPushPoseSkill` |
| Push | `push` | AgentId, BoxId, ZoneId | `PushSkill` (constructed `dest=None`, Decision 16) |
| CooperativePush | `cooperate_push` | (AgentId,AgentId), BoxId, ZoneId | two `CooperativePushSkill` instances owned by ONE executive call (Decision 1) |
| Explore | `explore` | AgentId | `shared_skills.py::ExploreSkill` — registry-only (`OutsideSymbolicModel`) |
| Wait | `wait` | AgentId | `WaitSkill` — registry-only; 0 primitive steps |

Dispatch is exhaustive on `backend_dispatch_key` with no fallback arm; `make_skill`'s silent
default is never called (`box_push_v1_adapter.py`, pinned by
`tests/test_p1_adapter.py::TestDispatchIsExplicitAndExhaustive`).

## 7. Per-skill symbolic preconditions/effects/costs (frozen `domain/box_push_v1.py::DOMAIN_IR`, `boxpush-v1.r0`)

| Skill | Preconditions | Deterministic success effects | Cost |
|---|---|---|---|
| GotoPushPose | `discovered(box)`, `pending(box)` | `+in_pose(agent,box)` | 1 |
| Push | `in_pose(agent,box)`, `light(box)`, `pending(box)` | `+delivered(box)`, `-pending(box)`, `-in_pose(agent,box)` | 1 |
| CooperativePush | `different(a1,a2)`, `heavy(box)`, `in_pose(a1,box)`, `in_pose(a2,box)`, `pending(box)` | `+delivered(box)`, `-pending(box)`, `-in_pose(a1,box)`, `-in_pose(a2,box)` | 1 |

Frame conditions are implicit (unmentioned literals unchanged —
`symbolic/applicability.py::apply_effects`, the ONE successor shared by planner and
predictor). `predicted_world_effects` declare the world basis (pose cell + facing; landing
cell + delivered; the coop tandem slots as a SET — see §11). Projection: six projectable
predicates (`light, heavy, different, discovered, delivered, pending`) + one
executive-tracked (`in_pose`, optimistic, non-exclusive — Decision 6).

## 8. Per-skill success/failure labels

Raw labels are **provenance only** (Decision 3; the binding rule in `shared/execution.py`) —
the typed outcome is derived from world state, never from labels.
`PRODUCIBLE_RAW_LABELS` (every entry traced to its backend emit site in the final audit):

| Skill | Producible raw labels |
|---|---|
| Explore | `found_target`, `found_decoy`(unreachable in the frozen instance), `explored` |
| GotoPushPose | `in_position`, `none_known`, `blocked` |
| Push | `delivered`, `pushed`, `blocked`, `too_heavy` |
| CooperativePush | `none_known`, `blocked`, `delivered`, `waiting_partner` |
| Wait | `done` |

`moved` is advertised in legacy docs but never emitted; `in_progress` is a runner-level
marker (`NON_TERMINAL_PROGRESS_MARKER`), excluded from the vocabulary; `timeout` is
never-observable (overwritten on every escape path).

## 9. Failure-state and executive-step semantics

- `FailureStateClass` ∈ {UNCHANGED, PARTIAL_EXECUTION, BACKEND_REJECTED_BEFORE_TRANSITION},
  derived from pre/post world comparison and cross-checked at `ExecutionResult` construction
  (a claimed class contradicting the observed states refuses to construct —
  `shared/execution.py`). Failed ≠ no-op is machine-enforced.
- **Two senses of "rejected", never conflated**: pre-executor `CallValidation` rejection
  (0 executive steps, no `ExecutionResult`) vs backend rejection before transition (an
  executed attempt: 1 executive step; costs one truthfully-accounted terminal-STAY primitive).
- Primitive step = one `env.step` (`multi_agent_box_push_env.py` `step_count`); executive
  step = one attempted high-level skill. The three-case fault rule (`shared/faults.py`):
  (a) result attached → recorded accounting charges; (b) `refused:` → 0 steps;
  (c) mid-execution → 1 executive + `primitive_steps_before_failure=N` charged from fault
  provenance by the loop (`runtime/loop.py::_charge_case_c`). Case-(c) attempts do NOT feed
  repeated-failure counts (single-channel escalation,
  `runtime/executive_history.py::append`).

## 10. Environment wrapper and executor

`functional_layer/custom_env/box_push/env/box_push_v1_adapter.py::BoxPushV1Adapter`
implements `V1Environment`: reset-before-use and post-terminal refusal (D8, via
`InfrastructureFaultError`); identity-only pre-flight (`UngroundedCall`, never feasibility);
runner-faithful drive loop; exact world-derived per-step grid for skill execution (legal
under Decision 6 — execution may see geometry, applicability may not); post-flight identity
checks raising case-(a) faults with the completed result attached; per-attempt `env.step`
counter, cross-checked in tests against the backend's joint `step_count`
(`tests/test_p1_adapter.py`). `runtime/executor.py::execute` is the
policy-independent executor: signature `(env, call)` only, gates nothing (gating belongs to
the loop on the typed verdict), structurally pinned
(`tests/test_p4_runtime.py::test_executor_signature_is_the_policy_independence_guarantee`).

## 11. Symbolic IR, planner, predictor, monitor

- **Applicability** (`symbolic/applicability.py::evaluate`): literal membership against the
  frozen preconditions — no geometry, structurally unable to acquire any.
- **Planner** (`symbolic/planner.py::plan`): deterministic BFS over `SymbolicState` literals,
  grounded from a `Universe`; returns the §15 trio; node budget → `PlannerFailure(timed_out)`.
  PDDL artifacts are re-issued byte-for-byte from `DOMAIN_IR`
  (`symbolic/pddl_gen.py::v1_artifacts`, pinned by `tests/test_p2_pddl.py`; pyperplan
  validity/optimality cross-check).
- **Predictor** (`symbolic/predictor.py`): monitor-side only (five import escape routes
  closed by static guard); bounded inputs (positions/directions/delivered/required_agents/
  zone; never walls — AST-enforced); `first_zone_cell_along` is partial by design (ray miss
  → NO world prediction); CooperativePush's terminal slots are a two-candidate SET (backend
  re-derives tandem roles per step — audited).
- **Monitor** (`symbolic/monitor.py::monitor_execution`): success compared on BOTH bases
  (projection `agrees` + world-key candidate membership); non-success of an applicable skill
  stands on the authoritative outcome alone (clause 7). Wired on the **belief** the attempt
  was chosen under (§19.1 item 3), `ValueError` wrapped to a typed fault by the loop.
- **Belief** (`symbolic/belief.py::ExactSymbolicBelief`): projectables re-derived from the
  authoritative snapshot every sync; `in_pose` maintained from typed outcomes per Decision
  13.8 — a failed consuming skill retracts nothing (the recorded livelock, §19).

## 12. NL/DSPy typed modules and offline-test strategy

`nl/` behind the `LMSeam` (`nl/seam.py`): `RecordedLM` exact-match fixtures with a typed
miss error; the only V1 DSPy binding is `model_layer/planner/v1_nl_live.py` — legacy runners and middleware also import dspy but are not V1 paths — (lazy import,
consumes the pinned temperature-0/cache-on `nl/runtime_config.py::PINNED_V1_NL_RUNTIME`).
Modules: `parser.py` (frozen call rendering → `GroundedSkillCall` | `MalformedCall`, never
substitution — Decision 7), `task_interpreter.py` (token-based coverage classifier, explicit
residual, recorded imprecision ceiling both directions), `observation_interpreter.py`
(provenance-blind, backend-pinned direction words), `semantic_belief.py` (exact re-derivation,
bounded history), `skill_selector.py` + `repair.py` (ONE typed repair attempt, then the
rejection stands), `translator.py` (symbolic action set derived from the registry; Explore/
Wait translate with residual), `recovery.py` (re-establishment advice for failed consuming
skills — the livelock escape), `track.py::NLTrack` (observe-before-propose precondition;
`NLProposal` exactly-one-of invariant). Default tests are fully offline (AST-scanned no-dspy
closure); request CONTENT is golden-pinned so fixtures cannot mask emptied prompts.

## 13. Translator and track comparator

The translator (`nl/translator.py::translate_proposal`) maps a typed proposal into the shared
vocabulary with an explicit `CoverageReport` residual and an `nl`-sourced `ConfidenceReport`.
The comparator (`runtime/comparator.py::compare_tracks`) is the **sole constructor of
`TrackDivergence`** (grep-audited): COVERAGE_GAP (outside-model or no well-formed proposal),
TRANSLATION_RESIDUAL, CONTRADICTION, BENIGN_ABSTRACTION_MISMATCH (agent-binding-only
difference under non-exclusive optimism), CONFIDENCE_MISMATCH (below 0.75 against a standing
plan). Divergences are evidence; they never block execution.

## 14. Orchestrator policies and executive loop

`runtime/orchestrator.py::decide` is pure (no env/time/mutation): `NoPlan`→HALT (semantic),
inapplicable head→REPLAN, standing recovery→EXECUTE (every EXECUTE is orchestrator-issued),
and the policy split at `repeated_failure_threshold`: **SYMBOLIC_PRIMARY** halts with the
discrepancy history (never strengthening the model); **ADVISORY_TWO_TRACK** issues
REQUEST_PROPOSAL → the NL recovery advice re-enters through the same grounding/applicability
gates. `runtime/loop.py::ExecutiveLoopManager` owns budgets (executive primary; primitive
secondary; charged = recorded + case-(c) extras; goal outranks budget on the exact tie), the
per-cycle rejection guard and the cross-cycle liveness guard (unconditional, records its own
typed fault), grounding-before-applicability ordering (§19.1 item 5), trace/history wiring
(every executed entry carries decision, validation — None on the case-(a) fault path for
registry-only skills — both prediction bases, NL evidence columns, per-entry channels), and `EpisodeOutcome` reporting.

## 15. `PlanFound` / `NoPlan` / `PlannerFailure`

Distinct types over an abstract base (`shared/planner_result.py`). The planner emits all
three behaviorally (`tests/test_p2_symbolic.py::TestPlanner`); the loop converts
`PlannerFailure` → `InfrastructureFault` BEFORE orchestration (`:156`); the orchestrator
raises `TypeError` if one ever reaches it and routes `NoPlan` to HALT — a legitimate result,
never a fault. `NoPlan` is exercised by the synthetic single-agent instance
(`symbolic/synthetic.py`, Decision 12) at unit, acceptance, and loop level.

## 16. `ExecutionDiscrepancy` / `TrackDivergence` / `InfrastructureFault`

One producer each (grep-audited tree-wide): the monitor, the comparator, and typed fault
sites. `ExecutionDiscrepancy` carries typed key pairs per basis; `InfrastructureFault`
short-circuits the current cycle at every raise site (traced in the final audit), with
episode continuation a config choice (`halt_on_infrastructure_fault`); `TraceEntry` refuses
lifecycle-illegal combinations (pre-execution fault + execution). Known open corrective
action **H8**: `runtime/loop.py::_advisory_proposal` converts `nl_track.propose` exceptions
into a MalformedCall-backed COVERAGE_GAP divergence, blurring infrastructure provenance into
the divergence channel — smallest correction recorded (log a non-short-circuiting fault for
raised exceptions), deliberately unfixed in the report-mode audit.

## 17. Representative state-by-state acceptance traces

`docs/implementation/acceptance_traces.md` — generated live and **byte-pinned**
(`tests/test_v1_acceptance.py::TestTraceDocumentPinned`): the six supervisor scenarios at
component level (per-cycle records with pre/post snapshots, applicability, both predictions,
raw label→typed outcome, failure classification, step consumption, channel reports) and
case 7, the same optimistic story driven by the real executive loop under both policies —
SYMBOLIC_PRIMARY halting at the livelock, ADVISORY_TWO_TRACK escaping via `(nl-recovery)` to
the goal.

## 18. Test matrix and commands

629 tests (commands in §2), 14+ modules: P0 contracts (~400: freeze pins, canonical
faithfulness, channel separation, trace lifecycle, no-backend-imports with fail-closed
probes), P1 adapter (47), P2 symbolic/PDDL/acceptance (69), V1 acceptance (14 incl. loop
cases), P3 NL (51), P4 runtime (42), plus guards. Mutation evidence: 281 mutants across five
checked-in harnesses, all killed (hang⇒kill semantics where liveness is the property).
Mechanical pins: suite-count row == live discovery
(`tests/test_domain_freeze.py::TestHandoffCountsAreMechanical`), tree-wide citation-drift
guard (`TestLegacyRunnerCitationDiscipline`), byte-pinned traces. The final audit sampled
kill reasons and found no vacuous tests, no mocked-away properties, no crash-kill
masquerades, and no doc-pin-only load-bearing property.

## 19. Known V1 limitations and the intentionally optimistic abstraction

- The symbolic model deliberately omits geometry: `in_pose` is optimistic and non-exclusive;
  a stale `in_pose` makes `Push` applicable with a ray that misses the zone (§19 D-2 —
  predictor emits no world prediction there). The demonstrated **consuming-skill livelock**
  (failed Push retains `in_pose`; bare replan repeats forever) is the designed consequence;
  escapes are re-establishment or the `:118` bookkeeping — never weakening the belief rule.
- The symbolic success basis carries one bit per box (`delivered`/`pending`); a Push that
  moved the box and failed projects like a no-op — caught by the typed outcome and world
  basis (recorded in decisions §14.1).
- `ExecutiveHistory.faults_since` is an unconsumed accessor (`:163` permissive). Two
  identifier-level pins guard behaviorally-equivalent-mutant decisions and say so. Per-phase
  mutant counts have no mechanical pin (candidate hardening). The headline-0 "always
  too_heavy" rationale in `shared/execution.py` is legacy-feed-specific (labels are
  provenance-only, so harmless).
- The NL coverage classifier's imprecision ceiling is recorded in both directions
  (`nl/task_interpreter.py`).

## 20. File/class/function index

| Concern | Where |
|---|---|
| Registry, calls, validation outcomes | `shared/skills.py::REGISTRY/GroundedSkillCall/CallValidation` |
| Skill IR / domain | `shared/skill_ir.py::SkillIR/DomainIR`; `domain/box_push_v1.py::DOMAIN_IR` |
| Snapshot + keys | `shared/state_snapshot.py::StateSnapshot.world_key/replay_key` |
| Execution result + labels | `shared/execution.py::ExecutionResult/RawLabel/PRODUCIBLE_RAW_LABELS/FailureStateClass` |
| Faults + three-case rule | `shared/faults.py::InfrastructureFault(Error)/PRE_EXECUTION_FAULT_KINDS` |
| Planner results | `shared/planner_result.py::PlanFound/NoPlan/PlannerFailure` |
| Trace | `shared/trace_schema.py::TraceEntry`; `runtime/executive_history.py::ExecutiveHistory` |
| Adapter | `functional_layer/custom_env/box_push/env/box_push_v1_adapter.py::BoxPushV1Adapter` |
| Applicability/successor | `symbolic/applicability.py::evaluate/apply_effects` |
| Planner / predictor / monitor / belief | `symbolic/{planner.py::plan, predictor.py::predict_*, monitor.py::monitor_execution, belief.py::ExactSymbolicBelief}` |
| PDDL emitter | `symbolic/pddl_gen.py::v1_artifacts` |
| NL modules | `nl/{parser,seam,task_interpreter,observation_interpreter,semantic_belief,skill_selector,repair,translator,recovery,track,runtime_config}.py` |
| Live seam | `model_layer/planner/v1_nl_live.py::build_live_seam` |
| Executor / comparator / orchestrator / loop | `runtime/{executor.py::execute, comparator.py::compare_tracks, orchestrator.py::decide, loop.py::ExecutiveLoopManager}` |
| Decisions / handoff | `docs/decisions/P0_V1_DECISIONS.md` (§18 items, §19/§19.1); `docs/handoff/section18.md` (revisions 21a-21n) |

## 21. Explicitly deferred P5+ work

Not implemented and not claimed: stochastic DBNs/probabilistic belief, learned structure,
Julia MDP/POMDP compilation, asynchronous concurrency, duration distributions
(`DURATION_ANOMALY` is a reserved enum value only), VLM/rendered-image input, CI (recorded as
a project-management question, decisions §18 item 10). `middleware_layer/` (particle-filter
and grid belief updaters) and the legacy runners are preserved reference for later
partial-observability milestones, with their known belief-grid defects recorded in section18
— revival starts from those records, not from trust.
