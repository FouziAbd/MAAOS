# MAAOS Symbolic-Twin BoxPush V1 — P0-P4 Implementation Record

**Status: COMPLETE.** All five phases implemented, adversarially reviewed, and closed by a
three-auditor hostile final audit with **0 FAIL** on every surface (2026-08-21, revision 21n in
`docs/handoff/section18.md`). One open corrective action is carried (see §6).

Everything in this document describes **implemented and tested** behavior unless explicitly
marked otherwise; every claim cites the code or test that establishes it.

---

## 1. Architecture map

| Package | Responsibility | Key constraint (enforced, not conventional) |
|---|---|---|
| `shared/` | Frozen P0 contracts: skills/registry, `SkillIR`, `StateSnapshot`, `ExecutionResult` + raw-label vocabulary, `PlannerResult` trio, three report channels, `TraceEntry`, faults + the three-case rule, orchestration config, ids, tasks, observation visibility | Types refuse illegal states at construction (arity/type checks, producible-label enforcement, failure-class-vs-world cross-check, trace lifecycle legality) |
| `domain/box_push_v1.py` | The frozen V1 instance: `DOMAIN_IR`, projection contract, tasks, golden keys | Imports only `shared` + stdlib (whitelist-tested) |
| `functional_layer/.../box_push_v1_adapter.py` (P1) | `V1Environment` over the authoritative backend: world-only export, exact-grid execution feed, typed outcomes derived from world state, three-case fault production, exhaustive dispatch, identity-only pre-flight | Never rewrites backend semantics; raw labels demoted to provenance |
| `symbolic/` (P2) | Declarative applicability + the ONE successor, BFS planner (trio results), monitor-side predictor (both Decision-13.6 bases), dual-basis monitor, exact-state belief (13.8 maintenance), deterministic PDDL emitter, synthetic NoPlan instance | Structurally oracle-free: fail-closed import guards + five-route predictor-reachability guard + AST input bounds |
| `nl/` (P3) | Peer NL track behind an offline LM seam: parser (never substitutes), task/observation interpreters, semantic belief, selector, one-attempt repair, translator with residual, recovery proposer, stub track | Cannot import backend/dspy/runtime (auto-discovered guard); bidirectionally isolated from `symbolic/` |
| `model_layer/planner/v1_nl_live.py` | The only DSPy binding, behind the seam, consuming the pinned temperature-0 config | Referenced only by the `MAAOS_LIVE_LM=1`-gated test |
| `runtime/` (P0 history + P4) | Policy-independent executor, track comparator (sole `TrackDivergence` source), pure orchestrator, executive loop manager, `ExecutiveHistory` | Backend by injection only; executor signature admits no policy input (structurally pinned) |

**Import-guard matrix** (fail-closed, namespace-package-proof —
`tests/test_no_backend_imports.py`): `shared` → stdlib; `domain` → shared;
`symbolic` → shared+domain; `nl` → shared+domain; `runtime` → shared+domain+symbolic+nl;
nothing imports the backend, dspy, or `runtime` from the symbolic side; no cycles.

## 2. Phase deliverables (evidence-backed)

- **P0 — domain freeze** (`p0-v1-freeze`): 19 `shared/` modules + frozen instance; 16 recorded
  decisions (`docs/decisions/P0_V1_DECISIONS.md`); golden world/symbolic keys pinned.
- **P1 — classical environment** (`p1-v1-classical-env`): the adapter, runner-faithful drive
  loop, headline-0 fix (authoritative typed outcomes), per-attempt `env.step` counter,
  reset/terminal guards. 47 integration tests.
- **P2 — symbolic baseline** (`p2-v1-symbolic-baseline`): the symbolic track + PDDL re-issued
  byte-for-byte from `DOMAIN_IR` (pyperplan cross-checked); the designed optimistic failure
  demonstrated live; the consuming-skill livelock discovered and recorded (§19.1).
- **P3 — NL baseline** (`p3-v1-nl-baseline`): the seam-isolated NL track, recorded fixtures,
  pinned dependencies, typed malformed-call handling replacing the legacy `explore` fallback
  (banner-pinned supersession).
- **P4 — orchestrator + loop** (`p4-v1-orchestrator`): the executive, enacting all five
  §19.1 P4-binding decisions; case-(a)/(c) fault accounting; single-channel escalation;
  rejection + cross-cycle liveness guards; goal-outranks-budget tie; advisory NL evidence
  preserved on every executed entry; one export per cycle (count-pinned).

## 3. The V1 semantic core (all live-demonstrated)

- **Intentional optimism**: symbolic applicability is literal membership only; a symbolically
  applicable skill failing in the backend is the expected signal
  (`EXECUTION_FAILURE_OF_APPLICABLE_SKILL`), never a reason to strengthen the model — the
  flagship acceptance story *requires* the failure to occur, so a smuggled oracle turns tests
  red (`tests/test_v1_acceptance.py`, `tests/test_p2_acceptance.py`).
- **Three channels, one producer each**: `ExecutionDiscrepancy` (monitor),
  `TrackDivergence` (comparator), `InfrastructureFault` (typed sites); grep-verified tree-wide.
- **Planner trio**: `PlanFound`/`NoPlan`/`PlannerFailure` distinct types;
  failure→fault before orchestration; `NoPlan`→HALT semantic routing.
- **Step semantics**: primitive = one `env.step`; executive = one attempted skill; recorded
  accounting + case-(c) fault-provenance charges; conservation verified live under both
  policies.
- **The policy split** (the architecture's thesis, run autonomously):
  SYMBOLIC_PRIMARY halts at the repeated-failure threshold with the discrepancy history;
  ADVISORY_TWO_TRACK escapes the recorded consuming-skill livelock via the NL
  RecoveryProposer's re-establishment and reaches the goal — byte-identical executor
  semantics on the common prefix (`TestCase7ExecutiveLoop`).

## 4. Evidence infrastructure

- **629 deterministic offline tests** (1 gated live skip), green across 5 hash seeds and
  foreign cwds. **281 mutation-harness mutants, all killed**: P0 121, P1 30, P2 50, P3 37,
  P4 43 (`docs/implementation/p*_mutation_harness.py`; hang⇒kill semantics).
- **Mechanical pins**: suite-count row == live unittest discovery
  (`TestHandoffCountsAreMechanical`); citation-drift guard over the whole contract side
  (`TestLegacyRunnerCitationDiscipline`); byte-pinned human-readable acceptance traces
  regenerated live at test time (`docs/implementation/acceptance_traces.md`).
- All six supervisor acceptance scenarios covered at component AND loop level (deadlock is a
  recorded N/A per Decision 12, with the unsolvable obligation met by the synthetic instance).

## 5. Final audit record (2026-08-21)

| Auditor | Verdict |
|---|---|
| backend-investigator (ground truth) | 0 FAIL / 0 PARTIAL / 7 PASS |
| architecture-reviewer (deliverables + 11-item hunt) | 0 FAIL / 1 WARN / 33 PASS |
| test-reviewer (regression evidence, live-verified) | 0 FAIL / 1 PARTIAL / 32 PASS |

The PARTIAL (a stale mutant count in section18's P4 row) is fixed in revision 21n. The full
per-item tables live in the audit record; section18's revision log (21a-21n) is the complete
process narrative.

## 6. Open corrective action + recorded notes

1. **H8 (WARN, code)**: `runtime/loop.py::_advisory_proposal` catches every exception from
   `nl_track.propose` and rewrites it into a MalformedCall-backed COVERAGE_GAP divergence —
   infrastructure provenance laundered into the divergence channel. Smallest correction:
   distinguish typed NL outputs from raised exceptions; record the latter as a
   non-short-circuiting fault. Deliberately not fixed in the report-mode audit.
2. Documentation notes (harmless, recorded): the headline-0 "always too_heavy" rationale in
   `shared/execution.py` is legacy-belief-feed-specific and inverts under the exact grid
   (labels are provenance-only); a `BACKEND_REJECTED_BEFORE_TRANSITION` attempt still
   truthfully costs one terminal-STAY primitive step.
3. Candidate hardening: per-phase mutant counts have no mechanical pin (the suite count does).

## 7. Recorded limits and deferrals (not defects)

- `ExecutiveHistory.faults_since` is an unconsumed accessor (contract `:163` is permissive).
- Two identifier-level pins guard behaviorally-equivalent-mutant decisions (belief-wired
  monitor; orchestrator-issued recovery) — they bite textual drift, not semantic rewrites,
  and say so.
- The NL task-interpreter's coverage classifier has a recorded imprecision ceiling in both
  directions (`nl/task_interpreter.py`).
- P5+ (stochastic DBNs, Julia compilation, concurrency, VLM input, learning) is implemented
  nowhere and claimed nowhere; `middleware_layer/` and the legacy runners are preserved
  reference for later partial-observability work (known belief-grid defects recorded in
  section18 §K notes).

## 8. Runbook

```bash
# full battery (from the repo root)
python -B -m unittest discover -s tests -t .
# per-phase mutation harnesses (mutate + restore product files; run one at a time)
python -B docs/implementation/p0_mutation_harness.py   # ... p1..p4 likewise
# regenerate the byte-pinned acceptance traces after intentional behavior changes
python -B -m tests.test_v1_acceptance --write
# live NL integration (requires local Ollama serving the pinned model)
MAAOS_LIVE_LM=1 python -B -m unittest tests.test_p3_live_lm
```
