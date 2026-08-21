# P0 — V1 Design Decisions (FINAL)

> **Status: FINAL.** These decisions are frozen for V1 (P0-P4). They resolve the open items in
> `docs/handoff/section18.md` §L against `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`.
> **Baseline:** branch `middleware_layer`, commit `9cb39cd`.
> No product code was modified to produce this document.

Each decision is classified as:

- **SPEC-DETERMINED** — the supervisor specification already requires this; recorded, not chosen.
- **V1 DESIGN DECISION** — the specification requires *an* answer but does not dictate which; this is
  the frozen V1 answer.
- **V1 DESIGN DECISION (spec-silent)** — the specification does not address it; decided on
  engineering grounds.

No decision below contradicts the supervisor specification. Consequences that constrain later phases
are recorded inline and collected in §18 as work items, not as open questions.

---

## 1. Section L coverage

| §L item | Subject | Frozen by | Status |
|---|---|---|---|
| L-1 | Executive-step consumption | Decision 2 | **Closed** |
| L-2 | Sequential vs joint executive rule | Decision 1 | **Closed** |
| L-3 | Timeout labelling | Decision 3 | **Closed** |
| L-4 | Actions 4/5/6 silently ignored | Decision 7 (by extension) | **Closed** — §7.1 |
| L-5 | Post-terminal stepping | Decision 8 | **Closed** |
| L-6 | Target OS / Python | Decision 10 | **Closed** — dependency pinning is a P3 work item (§18 item 2) |
| L-7 | Rendered-grid desync artifacts | Decision 9 | **Closed** — deferred by decision |
| L-8 | Full observability vs `explore`/discovery | Decision 5 | **Closed** |
| L-9 | `in-pose` exclusivity | Decision 6 | **Closed** |
| L-10 | Semantics of `pushed` | Decision 3 + Decision 11 | **Closed** — push-to-zone |
| L-11 | Deadlock / `NoPlan` instance | Decision 12 | **Closed** — synthetic instance deferred to P2/P4; does not block P0 |

Decisions 13-16 were added after the P0 consistency audit; they close findings the audit
surfaced rather than §L items. Decision 13 replaces an intermediate reading in which the symbolic
projection was treated as the sole monitor criterion — see §14, *What this decision replaces*.

Headline finding 0 of `section18.md` (belief-derived labels; deterministic `too_heavy` mislabel) is
resolved by Decisions 3 + 4 acting together — see §3.1.

---

## 2. Decision 1 — Sequential executive execution; `CooperativePush` is ONE executive skill

**Decision.** One executive step issues exactly one grounded skill invocation. `CooperativePush` is a
single sequential executive skill that may internally coordinate both agents using joint primitive
backend actions in the same primitive transition. Agents not participating in the current executive
skill are idle at the primitive level.

**Supervisor requirement.** `SUPERVISOR_P0_P4_CONTRACT.md:171` — "If multiple agents exist, the domain
must define deterministic sequential executive decision/execution behavior." `:172` — "A high-level
joint skill may internally coordinate multiple agents while still presenting one executive skill
lifecycle." `:106` — "The backend may implement one executive skill by multiple primitive
movements/actions internally."

**Code evidence.** The heavy box physically requires simultaneity: `_find_tandem`
(`multi_agent_box_push_env.py:312-328`) matches only when two agents stand at `B−D` and `B−2D`, both
facing `D`, and **both** submit `MOVE_FORWARD` in the same joint `step()`. The current runner
instantiates `CooperativePushSkill` **per agent** (`box_push_centralized.py:411-415`;
`skill_executor_push.py:252-256`) and relies on the planner assigning it to both — nothing enforces
this (`box_push_centralized.py:271-278` is prompt text only).

**Classification.** **SPEC-DETERMINED.** `:171` requires sequential executive behavior and `:172`
explicitly authorizes the joint-skill construction; this is the only reading satisfying both the
specification and the backend's physics.

**Implementation consequences.**
- The V1 wrapper owns *both* per-agent `CooperativePushSkill` instances behind one executive call.
  `partner_id` plumbing and the `_assign_slots` tie-break (`skill_executor_push.py:272-283`) are
  wrapper-internal and must not appear in the executive signature.
- Idle agents are padded with `STAY`, as the runner already does (`box_push_centralized.py:429-430`).
  Idle padding consumes **primitive** steps only (Decision 2).
- The wrapper latches the **pair ordering** (canonical `AgentId` order) at invocation. It does
  **NOT** latch the front/rear tandem roles: `_assign_slots` re-derives those every `step()` from
  live Manhattan distance (`skill_executor_push.py:302-303`), so roles can flip mid-skill, and a
  wrapper could only prevent that by overriding `_assign_slots` — a backend-semantics change the
  change policy forbids. Decision 16 and the set-valued `CooperativePush.predicted_world_effects`
  both depend on that behaviour being preserved: the set form is exactly what makes the prediction
  invariant under a mid-skill role flip. An earlier revision of this bullet ordered the opposite.

---

## 3. Decision 2 — Executive-step consumption

**Decision.** One **validated grounded skill invocation that reaches the executor** consumes exactly
one executive step, whether it succeeds or fails. A call **rejected before executor invocation**
(malformed, ungrounded, symbolically inapplicable, post-terminal) consumes **zero** executive steps.
Primitive steps are tracked separately and independently.

**Supervisor requirement.** `:116` — "It must also say whether the failed high-level attempt consumes
an executive step." `:118` — the executive loop owns the episode step budget and repeated
`(pre-attempt StateSnapshot, grounded skill)` failure bookkeeping, and "This must not become a hidden
symbolic feasibility predicate." `:269` — "For failed skills record post-state behavior and
executive-step consumption."

**Code evidence.** No executive-step concept exists today. The only counter is
`world.episode.step_count`, incremented unconditionally on the first line of `step()`
(`multi_agent_box_push_env.py:141`); the only budget check is `:170`. `skill_cycle`
(`box_push_centralized.py:376,379`) counts planner calls, is log-only, and is never bounded.
`BaseSkill._steps` is **not** a primitive-step counter — `GotoPushPoseSkill` increments it only after
its early returns (`skill_executor_push.py:170`) and `PushSkill` only when *issuing* a push (`:226`),
never on the evaluation iteration.

**Classification.** **V1 DESIGN DECISION.** The specification mandates that we answer; it does not
prescribe the answer.

**Implementation consequences.**
- The primitive counter is the wrapper's own count of `env.step()` invocations per attempt. It must
  **not** be populated from `BaseSkill._steps`.
- **This structurally fixes the livelock** recorded in `section18.md` §C note 4: a `wait`/`wait` cycle
  performs zero `env.step()` calls, so `step_count` never advances and truncation can never fire
  (`box_push_centralized.py:423-424`). An executive-step budget bounds the loop where a primitive
  budget provably cannot.
- Repeated-failure bookkeeping keys on `(canonical StateSnapshot, grounded skill)` per `:118`, which
  requires the deterministic call serialization frozen in Decision 11.
- **Loop-manager guard.** Because pre-executor rejections are free, a policy that repeatedly proposes
  inapplicable calls is never charged. The executive loop manager bounds *rejections per executive
  cycle*. This is an infrastructure guard on the loop, **not** a symbolic feasibility predicate, so
  `:118` is respected.

---

## 4. Decision 3 — Preserve raw backend labels; add authoritative typed execution status

**Decision.** The V1 wrapper **preserves the raw backend label verbatim** as provenance and adds a
separate, authoritative typed execution status/outcome derived from world state. Timeout is
represented **explicitly** in the typed outcome even when `raw_label == "pushed"`. The raw label is
diagnostic only; the typed outcome is authoritative.

**Supervisor requirement.** `:103` — each skill must have "success/failure labels at the execution
interface." `:39` — the executor "returns execution feedback/status." `:43` — the monitor "Compares
symbolic prediction with authoritative execution." Project change policy: prefer a wrapper/adapter and
preserve backend execution semantics.

**Code evidence.**
- `BaseSkill._timeout` sets `label = "timeout"` (`shared_skills.py:230-235`), and every subclass
  overwrites it: `PushSkill` → `"pushed"` (`skill_executor_push.py:226-228`), `GotoPushPoseSkill` →
  `"blocked"` (`:171-173`), `CooperativePushSkill` → `"waiting_partner"` (`:329-331`), `ExploreSkill`
  → `"explored"` (`shared_skills.py:285-287`). **Budget exhaustion is currently reported as a success
  label by `PushSkill`.**
- `moved` is advertised (`skill_executor_push.py:7`; `box_push_centralized.py:53,243,288`) but no
  `_finish("moved")` exists. `cooperate_push` can return the undocumented `none_known` (`:294`).
  `found_decoy` (`shared_skills.py:282`) is unreachable — every box is a target
  (`box_push_env.py:104-106`).

**Classification.** **V1 DESIGN DECISION.** The specification requires labels at the execution
interface but does not say whether to normalize or to layer them. Layering satisfies the change policy
without touching backend semantics.

### 3.1 This decision plus Decision 4 is what fixes headline finding 0

The raw label is not merely incomplete — it is **provably wrong** in a specific case. `PushSkill`
distinguishes `blocked` from `too_heavy` by reading the *belief* label of the cell beyond the box
(`skill_executor_push.py:218-221`) where `_BLOCKING = ("wall","agent")` (`:36`), but the belief updater
**never writes `"agent"`**: another agent's cell is deliberately recorded as `"empty"`
(`deterministic_grid_updater.py:215-220`), while the backend *does* reject a light push whose landing
cell holds an agent (`_cell_free_for_box`, `multi_agent_box_push_env.py:301-303`). **A light box
blocked by the partner is therefore always labelled `too_heavy`**, as is any push into an unobserved
cell. Because Decision 3 keeps the raw label non-authoritative and Decision 4 sources truth from
`world`, the typed outcome is correct **without editing `PushSkill`**.

**Binding rule:** the raw label is recorded as `raw_label` and is **never** consumed by the monitor,
the planner, or repeated-failure bookkeeping.

---

## 5. Decision 4 — Canonical state comes only from authoritative world state

**Decision.** The V1 canonical `StateSnapshot` is normalized **exclusively** from `core_env.world`.
Never from reward-derived belief, never from `core_env.grid`, never from observations.

**Supervisor requirement.** `:86` — "The environment wrapper converts backend state into a normalized
typed `StateSnapshot`." `:88` — "Deterministic normalization/serialization is used for
equality/hashing/replay/trace keys. Raw backend serialization is not the equality criterion."
`:167` — "Symbolic state is exact/fully observable after wrapper normalization."

**Code evidence.**
- `world` is authoritative: `WorldState{agents, objects, static, episode}`
  (`cooperative_search_transport/env/state.py:89-94`), rebuilt per reset (`box_push_env.py:119-125`).
- The **reward channel is multiplexed** and therefore structurally invalid as a state source:
  `-0.01`/step (`multi_agent_box_push_env.py:142`), `-0.1` move-fail (`:221,223,234`), `+0.1` light
  push (`:232`), `+0.2` joint push (`:207`), `+20` delivery (`:248`), `+10` completion **to every
  agent** (`:168-169`). Provable corruption: on the terminal step an agent whose `MOVE_FORWARD` failed
  receives `-0.01 - 0.1 + 10 = +9.89`, far above the `-0.06` success threshold
  (`deterministic_grid_updater.py:56`), so the belief layer advances a position that did not move.
- `core_env.grid` demonstrably desynchronizes from `world` (`section18.md` §L-7).

**Classification.** **SPEC-DETERMINED.** `:86`/`:88`/`:167` require wrapper-normalized exact state;
the code evidence only establishes which of the three candidate sources can satisfy it.

**Implementation consequences.** P1 adds a `world`↔`grid` consistency assertion and must **not** call
`DeterministicGridUpdater` on the V1 path. Note `box_push_centralized.py:357-363` aliases one
`shared_grid` into both agents' updaters while `DeterministicGridUpdater.reset()` (`:153-159`) rebuilds
`_grid` — so `reset_belief()` silently un-shares the team map. V1 sidesteps this entirely; P3 must not
reintroduce it.

---

## 6. Decision 5 — `Explore` stays in the backend/registry; V1 symbolic state is fully observable

**Decision.** The backend `ExploreSkill` is preserved unchanged and `Explore` remains in the executive
skill registry. The V1 symbolic state is fully observable from initialization: all boxes are
discovered and all weights known at `t=0`. **Discovery is not required by the V1 symbolic planner**,
and `Explore` is not part of the V1 symbolic action set.

**Supervisor requirement.** `:167` — "Symbolic state is exact/fully observable after wrapper
normalization." `:168` — "Existing partial-observation behavior may remain in the backend for later
milestones."

**Code evidence.** The frozen problem instance initializes both boxes `(unexplored …)`
(`pddl/box_push_problem.pddl` `(:init … (unexplored …))`) and the verified 7-step plan (`pddl/box_push_problem.pddl.soln`)
opens with two `explore` actions. Weights are already prior knowledge in that same problem file
(`(:init (heavy box0) (light box1) …)`), so
the "known weights" reading is already the frozen one. `explore`'s only precondition is
`(unexplored ?b)` (`box_push_domain.pddl` `:action explore`).

**Classification.** **SPEC-DETERMINED** for full observability (`:167` is unambiguous);
**V1 DESIGN DECISION** for retaining `Explore` in the backend and registry rather than deleting it —
authorized by `:168` and required by the project scope rule (preserve later-useful POMDP
functionality).

**Implementation consequences.**
- `box_push_problem.pddl` is re-issued for V1 with `(discovered box0) (discovered box1)` replacing
  `(unexplored …)`. **The verified 7-step plan is superseded.** Under full observability the plan
  shortens to approximately
  `goto_push_pose(a1,box1); push(a1,box1); goto_push_pose(a1,box0); goto_push_pose(a2,box0); cooperate_push(a1,a2,box0)`.
  P2 re-verifies with `pyperplan` and records the new `.soln` (§18 item 1).
- `explore` is **dropped from the V1 symbolic domain** and **retained in the executive registry**, so
  the registry stays a superset of the symbolic action set. The NL track may propose `Explore` without
  the symbolic model representing discovery.
- V1 acceptance traces therefore contain no exploration behavior in any symbolic plan. `Explore` is
  exercised only as a backend/NL-track skill.

---

## 7. Decision 6 — Keep the optimistic, non-exclusive `in-pose` abstraction

**Decision.** V1 retains the existing optimistic symbolic abstraction, including non-exclusive
`in-pose` and the absence of any reachability, geometry, or occupancy model. This is an **intentional**
abstraction mismatch. **Never add backend reachability, geometry, BFS, occupancy or feasibility checks
to symbolic applicability.**

**Supervisor requirement.** `:51` — "The symbolic model is intentionally simple and may be optimistic."
`:53` — a skill "may be symbolically applicable even when the richer backend cannot actually reach the
target." `:55` — "**Do not add a hidden reachability/feasibility oracle to the symbolic planner.**"
`:57` — such a failure produces a monitor discrepancy and an orchestrator decision. `:271` —
"Optimistic execution failures are expected discrepancies, not reasons to add an oracle."

**Code evidence — three intended optimism sources.**
1. `in-pose` is **non-exclusive**: `box_push_domain.pddl` `:action goto_push_pose` adds `(in-pose ?a ?b)` and deletes
   nothing, so one agent can be in pose for both boxes simultaneously; the verified plan does exactly
   that. The backend gives an agent one cell.
2. `in-pose` has **no geometry**: `GotoPushPoseSkill` navigates to the single cell `B−D`
   (`skill_executor_push.py:150`), so two agents sent to the same box target the same cell.
3. `goto_push_pose` has **no reachability model**: preconditions are only
   `(discovered ?b) ∧ (pending ?b)` (`box_push_domain.pddl` `:action goto_push_pose`), while the
   backend returns `blocked` when the route
   freezes (`skill_executor_push.py:161-168`).

**Prohibited oracles** (located in `section18.md` §J-4): `_cell_free_for_box`, `_tandem_feasible`,
`_find_tandem`, `_is_free_for_agent`, `_bfs_avoid_boxes`, `_push_dir_toward_goal`,
`_nearest_undelivered_target`.

**Classification.** **SPEC-DETERMINED** for "add no oracle" (`:55` is a prohibition);
**V1 DESIGN DECISION** for retaining non-exclusivity specifically, since the specification does not
dictate the abstraction's content.

**Enforcement.** P2 enforces this with a **static** no-backend-import guard on the symbolic package,
not only a behavioral test: `_bfs_avoid_boxes` becomes an exact reachability oracle the moment P1 adds
`export_full_state()` and someone passes the exact grid instead of `entities["grid"]["cells"]`, and
**the call signature does not change**.

**Acceptance consequence (binding on P2 test design).** Non-exclusive `in-pose` means plan *ordering*
determines executability. The currently recorded plan interleaves
`goto_push_pose(a1,box1); goto_push_pose(a1,box0)`, so by the time `push(a1,box1)` is issued `a1` has
physically left `box1`'s pose and `PushSkill` reports `blocked` immediately
(`skill_executor_push.py:224-225`). This is a **correct** discrepancy under `:53`/`:57`. Therefore
acceptance scenario #1 ("normal success", `:262`) is demonstrated with a plan ordering that does not
interleave poses, and the interleaved ordering is used to demonstrate the discrepancy-and-replan path
(scenario #2). Under no circumstances is `in-pose` given a delete effect to make an acceptance run
pass — that is the prohibited silent strengthening.

### 7.1 Out-of-space primitive actions (closes §L-4)

`action_space` is `Discrete(4)` (`multi_agent_box_push_env.py:82-85`) but `step()` silently ignores
actions 4/5/6 (`:147-234`). The executive never issues primitive actions — only composed skills do,
and those emit `Actions.TURN_LEFT/TURN_RIGHT/MOVE_FORWARD/STAY` only. The V1 wrapper asserts every
submitted primitive action is in-space and raises `InfrastructureFault` (executor protocol failure,
`:160`) if not. Backend behavior is unchanged. This follows from Decision 7's principle and requires no
separate decision.

---

## 8. Decision 7 — Reject malformed calls, invalid grounding and silent object substitution

**Decision.** The V1 wrapper rejects malformed and ungrounded calls with typed results. **No silent
substitution of any kind.**

**Supervisor requirement.** `:159` — "missing grounding" is an enumerated `InfrastructureFault`.
`:156-161` — malformed backend result, serialization failure and executor/monitor protocol failure are
also `InfrastructureFault`. `:163` — a newly raised `InfrastructureFault` "aborts the normal current
cycle at the point of detection. No further skill command is issued until synchronization as
required." Project NL rule: malformed NL skill calls must be typed validation/repair/rejection cases
and must never be silently converted into an unrelated valid skill such as `explore`.

**Code evidence — four silent paths, all verified.**
1. `box_push_centralized.py:313-314` — any unparseable decision → `("explore", None)`.
2. `:404` — a missing agent line → `("explore", None)`.
3. `centralized_dspy_planner.py:106-108` — a bare `except Exception` returns `{}`, reaching the same
   default. **An LLM/API failure is an `InfrastructureFault` by `:161`, which `:163` requires to abort
   the cycle; instead it is executed against the authoritative environment for up to 30 primitive
   steps.**
4. `skill_executor_push.py:128-136` and `:263-270` — `_resolve_box` discards the planner's `[bx,by]`
   whenever it is out of range, not a target in belief, or already on the goal, and substitutes
   `_nearest_undelivered_target` (`:98-107`) — **acting on a different box and reporting success.**
   Additionally `:306-312` drops malformed arguments (`push [foo,bar]` → `PushSkill(dest=None)`, a
   different skill semantics), and `make_skill`'s default arm is `WaitSkill` (`:386`) — a second,
   inconsistent fallback.

**Classification.** **SPEC-DETERMINED.** `:159` + `:163` + the project NL rule leave no discretion.

**Required typed distinctions at the wrapper boundary.**
- `MalformedCall(reason)` and `UngroundedCall(reason)` → rejected pre-executor; zero executive steps
  (Decision 2); `InfrastructureFault` per `:159`.
- `SymbolicallyInapplicable` → a symbolic-track result, **not** an `InfrastructureFault`; zero
  executive steps.
- `PlannerFailure` → `InfrastructureFault` per `:129`; `NoPlan` → a legitimate symbolic result routed
  to the orchestrator per `:128`.

Path 4 is removed first: it makes the monitor misattribute a grounding fault to model optimism.

---

## 9. Decision 8 — Reject execution after terminal state

**Decision.** Once the episode is terminal or truncated, the wrapper refuses further skill execution.
The refusal is `InfrastructureFault` (executor protocol failure) and consumes zero executive steps and
zero primitive steps.

**Supervisor requirement.** Not addressed directly. `:35` gives the executive loop ownership of the
runtime cycle and episode step budget; `:160` makes an "executor/monitor protocol failure" an
`InfrastructureFault`, which is the natural classification for a post-terminal call.

**Code evidence.** `self.agents` is never emptied on termination — assigned only in `__init__`
(`multi_agent_box_push_env.py:55`) and `reset` (`:119`) — so `step()` remains callable after
`terminated` and keeps incrementing `step_count` (`:141`). This violates the PettingZoo convention and
makes the runner's outer guard `while env.agents and not episode_done`
(`box_push_centralized.py:378`) effectively `while not episode_done`. Separately, `reset()` changes the
*type* of `world.agents` from list to dict (`multi_agent_box_push_env.py:78-79` vs
`box_push_env.py:119-125`), so `step()` before `reset()` raises `TypeError` at `:151`.

**Classification.** **V1 DESIGN DECISION (spec-silent).**

**Implementation consequences.** The wrapper also enforces reset-before-use. P1 tests both guards. The
backend is unchanged; both guards live in the wrapper.

---

## 10. Decision 9 — Defer rendered-grid and belief-layer defects

**Decision.** Known defects in `core_env.grid` and the belief layer are documented and deferred, not
fixed, because they do not affect authoritative `world` execution. The partial-observation machinery is
preserved for later milestones.

**Supervisor requirement.** `:168` — "Existing partial-observation behavior may remain in the backend
for later milestones." Project scope rule: preserve later-useful POMDP functionality; add a V1 adapter
rather than deleting.

**Code evidence.** `_set_box_position` writes `None` over the previous cell
(`multi_agent_box_push_env.py:348-351`), destroying `DeliveryTile`s; a tandem push transiently erases
A1's marker before later-indexed agents generate observations (`:200-209` vs `:357-364`);
`custom_get_frame` (`:57-75`) rewrites all markers, so calling `render()` incidentally repairs the grid
and rendered vs headless runs can diverge in `core_env.grid` contents; a delivered box's
`TargetPackage` is never removed from the grid. **None of these touch `world`**, which Decision 4 makes
the sole state source.

**Classification.** **V1 DESIGN DECISION**, authorized by `:168`.

**Implementation consequences.** Safe for the V1 symbolic track by construction. **Not** automatically
safe for P3: a NL track consuming the belief grid inherits every one of these defects plus the
transposed view convention in `obs_parser.py:112-140`. The V1 NL track therefore consumes the typed
`StateSnapshot` — permitted by `:169` (typed data) and exact by `:167` — which sidesteps the issue.

---

## 11. Decision 10 — Freeze Python 3.12 + Linux/WSL2

**Decision.** The V1 target platform is **Python 3.12 on Linux/WSL2**.

**Supervisor requirement.** `:277` — the handoff must provide "install/run/test commands,
Python/package/OS constraints."

**Code evidence.** Verified environment: Python 3.12.3, Linux 6.6.87.2-microsoft-standard-WSL2,
virtualenv at `/home/fouzi/PettingZooEnv`; compiled artifacts confirm 3.12
(`__pycache__/*.cpython-312.pyc`). `requirements.txt` currently pins only `pyperplan>=2.1` and
`pyRDDLGym>=2.7`; `pettingzoo>=1.24.0` is a floor, and `gymnasium`, `pygame`, `numpy`, `dspy-ai`,
`minigrid`, `Pillow`, `requests` are unpinned.

**Classification.** **V1 DESIGN DECISION** — the specification requires the constraint to be stated,
not which platform.

**Implementation consequence.** P3 additionally requires pinned dependency versions
(`:236` — "pin DSPy/runtime dependency versions"), which this decision does not by itself supply
(§18 item 2).

---

## 12. Decision 11 — Frozen executive skill signatures

**Decision — FROZEN.**

```
GotoPushPose   (agent: AgentId, box: BoxId, zone: ZoneId)
Push           (agent: AgentId, box: BoxId, zone: ZoneId)
CooperativePush(agents: tuple[AgentId, AgentId], box: BoxId, zone: ZoneId)   # canonically ordered
Explore        (agent: AgentId)     # registry + backend only; not in the V1 symbolic action set
Wait           (agent: AgentId)
```

These signatures are **identical across the skill registry, the structured IR, the symbolic planner
and the backend wrapper**. No layer sees a different arity, a different type, or an optional argument.

**`Push` semantics are push-to-zone.** Symbolic success is `delivered(box)`. **Cell-by-cell movement,
blocking, partial movement and timeout are backend execution details** surfaced through the typed
execution outcome (Decision 3), never through the symbolic effect.

**Supervisor requirement.** `:82` — "Names used by prompts, backend wrappers, symbolic variables,
traces, and tests should come from these contracts rather than ad hoc strings." `:93-104` — each skill
needs a stable name/signature, typed parameters and a backend mapping. `:118` — repeated-failure
bookkeeping keys on `(pre-attempt StateSnapshot, grounded skill)`, requiring a deterministic
serialization of a grounded call.

**Code evidence — the mismatch being closed.**

| Skill | Symbolic (`box_push_domain.pddl`) | Backend (`skill_executor_push.py:373-386`) | Mismatch closed |
|---|---|---|---|
| `goto_push_pose` | `(?a - agent ?b - box)` (`:action goto_push_pose`) | `GotoPushPoseSkill(agent_id, box=(x,y))` | object vs cell |
| `push` | `(?a ?b - box)`, effect `delivered` (`:action push`) | `PushSkill(agent_id, dest=(x,y))` | object vs cell **and** effect |
| `cooperate_push` | `(?a1 ?a2 ?b)` — one joint action (`:action cooperate_push`) | per-agent instance + `partner_id` (`:252-256`) | joint vs per-agent |

The same positional `(x,y)` currently means *box cell* for `goto_push_pose`/`cooperate_push` and
*destination cell* for `push` (`:376-377`) — one tuple, two meanings. The frozen signatures remove that
overload entirely.

**Classification.** **V1 DESIGN DECISION**, satisfying the `:82`/`:93-104` requirement for stable
typed signatures.

**Rationale.**
- **`BoxId`, not a cell.** Box IDs `0`/`1` are stable across steps and resets
  (`box_push_env.py:79-82`); the grid carries no identity (both boxes render as identical
  `TargetPackage`, `multi_agent_box_push_env.py:351`). Identity-based arguments are what make
  Decision 7 enforceable: an unresolvable `BoxId` is a detectable `UngroundedCall`, whereas a stale
  coordinate is indistinguishable from a valid one — which is exactly how the current silent
  re-grounding hides (`_resolve_box`, `skill_executor_push.py:128-136`, `:263-270`).
- **`zone` on all three push-related skills.** The push direction, and therefore the pose, is a
  function of the target zone — `_push_dir_toward_goal` (`skill_executor_push.py:39-47`) computes it
  from the nearest goal cell. Naming the zone makes that dependency explicit rather than hidden state,
  and keeps `GotoPushPose` and `Push` consistent. `ZoneId` has exactly one member in V1,
  `delivery_zone` (the 10 cells of `box_push_env.py:39`).
- **`CooperativePush` takes an agent pair, not a partner**, per Decision 1 — it is one executive skill,
  not two coordinated ones. The pair is **canonically ordered (ascending `AgentId`)** so the grounded
  call has a deterministic serialization for `:118` bookkeeping. The backend's `_assign_slots`
  tie-break (`skill_executor_push.py:272-283`) stays wrapper-internal and does not leak into the
  signature.
- **`Explore` stays in the registry, out of the symbolic action set** (Decision 5), keeping the
  registry a superset so the NL track may propose it without the symbolic model representing
  discovery.
- **Rejected alternatives.** An optional `dest` argument defeats identical typed semantics and the
  symbolic planner could never populate it. Lifting grid coordinates into the symbolic model would
  make it a duplicate backend simulator, violating `:51`-`:55` and Decision 6.

**Consequence for `pushed`.** Under push-to-zone, `pushed` is not a symbolic outcome. It survives only
as a `raw_label` value (Decision 3) and maps to a **partial** typed outcome, since the box moved but
`delivered(box)` did not become true. `PushSkill`'s timeout-labelled-`pushed` case
(`skill_executor_push.py:226-228`) maps to an explicit timeout outcome, never to success.

---

## 13. Decision 12 — `NoPlan` instance deferred to P2/P4

**Decision.** A synthetic `NoPlan` instance is added during P2/P4 testing. **It does not block P0.**

**Supervisor requirement.** `:266` — the acceptance set requires a "`NoPlan` case where the symbolic
abstraction has one"; `:267` — a "deadlock/unsolvable case **if the domain defines one**."

**Code evidence.** The environment defines no deadlock detection anywhere. On the frozen 12×12 open
arena with a full left goal column (`box_push_env.py:39`) and boxes at `(6,6)`/`(8,4)` (`:79-82`), no
deadlock configuration was found. Under Decision 5 (full observability) the frozen classical problem is
always solvable, so `NoPlan` is not reachable from the frozen instance.

**Classification.** **V1 DESIGN DECISION**, consistent with `:267`'s conditional phrasing — the frozen
domain defines no deadlock, so the acceptance obligation is met by a purpose-built instance rather than
by the shipping one.

**Implementation consequence.** P2 adds a second, clearly-labelled synthetic instance whose goal is
symbolically unachievable (for example a heavy box with only one agent object, or a box walled into a
corner) purely to exercise the `NoPlan → orchestrator` path required by `:128`. The frozen V1 instance
is unchanged.

---

## 14. Decision 13 — Prediction and monitoring boundary

**Decision.** The symbolic model is optimistic about *whether* a skill will succeed. It is NOT
blind about *what* success would do. Nine clauses, all binding:

1. **`StateSnapshot` remains the canonical authoritative runtime state** (Decision 4). Nothing in
   this decision demotes it; the symbolic projection is an additional view, never a replacement.
2. **A symbolic skill may predict deterministic world-state effects that belong to its declared
   success semantics** — an intended agent pose cell, an intended box target position. Each skill
   declares them in `SkillIR.predicted_world_effects`.
3. **Computing an intended pose/target effect is allowed.** `push_dir(box, zone)` is the
   Manhattan-nearest goal cell followed by an axis choice
   (`skill_executor_push.py:39-47`) and the pose cell is `box - direction_vector(push_dir)`
   (`:150`). That is arithmetic on declared success semantics. Grounding it does not consult
   walls, occupancy, other agents, or any search.
4. **Using geometry to decide APPLICABILITY is forbidden**, unchanged from Decision 6. No BFS, no
   reachability, no occupancy, no collision test, no backend feasibility predicate and no
   procedural simulation may gate a precondition or a planner choice. The line is between
   *"where does success put it"* (allowed, an effect) and *"can it get there"* (forbidden, a
   feasibility query).
5. **The backend wrapper is required to use geometry.** Deriving `GotoPushPose`'s authoritative
   typed outcome means comparing the post-state agent cell against the pose cell, and Decision 3's
   `too_heavy`-vs-`blocked` re-derivation means inspecting the landing cell. Neither is optional
   and neither violates clause 4, because the wrapper answers about what HAPPENED, never about
   what WOULD happen.
6. **The monitor compares BOTH bases where each is available:** the predicted world effect against
   `StateSnapshot.world_key()`, and the monitored symbolic projection against
   `ProjectionContract.monitored_key()`. `ExecutionDiscrepancy` carries a separate, correctly
   named key pair per basis. A symbolic key is never written into a `*_world_key` field.
7. **`ExecutionFailure` remains valid with no state-effect comparison at all.** The authoritative
   typed `ExecutionOutcome` is always present, so
   `EXECUTION_FAILURE_OF_APPLICABLE_SKILL` never depends on a predictor existing. `:139` is
   satisfiable in P1 before any P2 predictor lands.
8. **Executive-only fluents stay outcome-tracked.** `in_pose` has no counterpart readable from a
   `StateSnapshot` by inspection, so it is excluded from the monitored SYMBOLIC subset and
   maintained by `ProjectionContract.apply_outcome`:
   - a **pre-executor rejection** (`CallValidation.is_pre_executor_rejection`) leaves symbolic
     state **unchanged** — no attempt occurred, so nothing is applied and nothing is retracted;
   - SUCCESS of `GotoPushPose` establishes the attempted grounded `in_pose` literal;
   - a failed execution NEVER applies the success effect;
   - failure invalidates the exact attempted grounded literal **only when the attempt could have
     disturbed its prior truth**, i.e. only when the world actually changed. `in_pose` is a
     function of agent and box positions: if neither moved (`FailureStateClass.UNCHANGED` or
     `BACKEND_REJECTED_BEFORE_TRANSITION`, both of which `ExecutionResult` refuses to pair with a
     changed world) the prior truth is exactly as guaranteed as before, and retracting it would
     discard a fact the executive still knows. A `PARTIAL_EXECUTION` failure did move things, so
     the literal goes;
   - no global exclusivity is inferred or enforced — Decision 6 keeps `in_pose` non-exclusive, so
     a failure on `in_pose(a0, box_1)` must not disturb `in_pose(a0, box_0)`.
   `ProjectionContract.apply_outcome` therefore requires `world_changed` explicitly; it is not
   defaulted, so no call site can silently pick one of the two behaviours.

   **Consuming skills.** The rule above is scoped to a skill whose SUCCESS EFFECT is the literal
   (`GotoPushPose` establishes `in_pose`). A skill that CONSUMES the literal as a precondition
   (`Push`, `CooperativePush` both delete `in_pose` on success) and then FAILS applies no effect at
   all — positive or negative — and does **not** retract its precondition literals. Retention is
   correct here rather than merely conservative: `PushSkill` advances the agent into the box's
   previous cell on every successful cell of the push, so the pushing formation is preserved and
   `in_pose` remains true of the box's new position; `CooperativePushSkill` likewise preserves the
   tandem. Note this is the OPPOSITE of what the establishing rule's "world changed → retract"
   would say, which is exactly why it is stated separately instead of left to inference.

9. **The world-effect predictor is MONITOR-SIDE ONLY.** Clauses 2-4 would otherwise leave a
   loophole assembled entirely from permitted parts: applicability calls the (allowed) predictor
   and prunes on its output, reconstructing a feasibility oracle without ever naming one.
   Therefore: `SkillIR.predicted_world_effects`, and any predictor output derived from it, **must
   not be read by precondition evaluation, applicability, or plan search** — only by the monitor,
   after execution. And the predictor's own inputs are bounded: agent positions, agent directions,
   box positions, box `delivered`/`required_agents`, and the zone. It must never read
   `StaticWorld.walls`, other agents' occupancy, or any backend state. A predictor that needs to
   know what is in the way has stopped predicting an effect and started testing feasibility.
   *(P2 obligation: add a static guard once the predictor module exists — §18 item 6.)*

**Supervisor requirement.** `:271` and the project testing rule require that successful
deterministic skill execution "matches symbolic predicted normalized `StateSnapshot`". Clause 2
is what makes that literally satisfiable rather than something to reinterpret — but only once
P2 grounds the declared effects (§18 item 6). **No predictor exists in P0.** `predicted_world_effects`
is a declaration of what a skill's success semantics imply; nothing in the repository computes a
predicted post-state today. What P0 delivers is the *freeze*, not the prediction. `:55` and Decision 6 supply clause 4. The `.claude/rules/symbolic-model.md`
predictor/monitor boundary supplies clauses 5-6: *"the predictor computes the model-relative
expected successor; the monitor compares prediction to normalized authoritative execution; do not
mutate applicability to hide a prediction/execution mismatch."*

**Code evidence.**

| Clause | Where |
|---|---|
| 1 | `shared/state_snapshot.py` — `world_key()` / `replay_key()` unchanged |
| 2 | `shared/skill_ir.py::SkillIR.predicted_world_effects`; the three declarations in `domain/box_push_v1.py` |
| 3 | `skill_executor_push.py:39-47`, `:150`, `:152-154`; pinned by `tests/test_backend_freeze_drift.py::test_the_pose_cell_arithmetic_still_matches_the_declared_world_effect` |
| 4 | `tests/test_no_backend_imports.py`; `tests/test_backend_contract.py::TestInterfaceExposesNoOracle`; `tests/test_prediction_and_monitoring.py::test_declared_world_effects_invoke_no_feasibility_oracle` |
| 5 | `shared/backend_contract.py` — obligation D3 plus the closing oracle-scope paragraph (D14 is about dispatch, not geometry) |
| 6 | `shared/discrepancy.py` — four fields, `comparison_bases`, `mismatched_bases` |
| 7 | `tests/test_prediction_and_monitoring.py::test_execution_failure_needs_no_comparison_pair` |
| 8 | `shared/symbolic_state.py::ProjectionContract.apply_outcome` (built on `establish`/`retract`, so a skill's success-time NEGATIVE effect — `Push` deleting `in_pose` — never has to be expressed as `succeeded=False`); `tests/test_prediction_and_monitoring.py::TestExecutiveTrackedOutcomeRule` |
| 9 | `shared/skill_ir.py:predicted_world_effects` docstring; enforcement is a P2 obligation (§18 item 6) |

**Classification.** **SPEC-DETERMINED** for clauses 4, 6 and 7 (the prohibition and the
predictor/monitor boundary are stated in the specification and the project rules).
**V1 DESIGN DECISION** for clauses 2, 3 and 8 — the specification requires *a* rule for
executive-only fluents and *some* prediction basis, and these are the frozen answers.

**What this decision replaces.** An earlier reading treated the symbolic projection as THE monitor
criterion and dropped world-state comparison. That was wrong twice over: it made
`STATE_EFFECT_MISMATCH` unconstructible for a compliant predictor (the field pair demanded world
keys), and it silently weakened `:271` from a state-effect check to a two-bit literal check.

### 14.1 Actual V1 monitor coverage (stated, not implied)

| Skill | Symbolic basis | World basis | Outcome |
|---|---|---|---|
| `Push` | **Discriminative** — `delivered`/`pending` flip | box landing cell + `delivered`; agent follow cell (**P2**) | always |
| `CooperativePush` | **Discriminative** — same | same, plus the two tandem slots (**P2**) | always |
| `GotoPushPose` | **None** — its only effect `in_pose` is executive-tracked, so success and failure project identically | pose cell + facing direction (**P2**) | always |

Every world-basis cell is marked **(P2)**: in P1 the live channels are the symbolic basis and the
authoritative typed outcome. `GotoPushPose` therefore rests entirely on the outcome until the
predictor lands — which is exactly why Decision 13.7 makes `ExecutionFailure` independent of any
comparison.

Of the six monitored predicates only `delivered` and `pending` vary: `light`, `heavy` and
`different` are non-fluent, and `discovered` is emitted unconditionally under Decision 5. The
symbolic basis therefore carries one bit per box. A `Push` that moved the box three cells and then
failed projects identically to a no-op — that case is caught by the typed outcome and by the world
basis, not symbolically. This is a declared limit, recorded so P2 does not discover it by surprise.

---

## 15. Decision 14 — Frozen backend dispatch key; exhaustive adapter dispatch

**Decision.** Every registry skill carries a frozen `backend_dispatch_key`, `Wait` included:

| Skill | `backend_dispatch_key` | Backend implementation |
|---|---|---|
| `GotoPushPose` | `goto_push_pose` | `skill_executor_push.GotoPushPoseSkill` |
| `Push` | `push` | `skill_executor_push.PushSkill` |
| `CooperativePush` | `cooperate_push` | `skill_executor_push.CooperativePushSkill` (both instances, wrapper-owned) |
| `Explore` | `explore` | `shared_skills.ExploreSkill` |
| `Wait` | `wait` | `shared_skills.WaitSkill` |

The P1 adapter dispatches **exhaustively** on this key and keeps **no fallback arm**. An
unrecognized token is a `MalformedCall`; it is never resolved to a default skill.

**Code evidence.** `skill_executor_push.py:373-386` — `make_skill` tests four string arms
(`explore`, `goto_push_pose`, `push`, `cooperate_push`) and returns `WaitSkill(agent_id)` for
everything else. There is **no `wait` arm**: `"wait"`, `"Push"`, `""` and arbitrary garbage are
observationally identical, which is the same silent-substitution class as `_resolve_box`
(Decision 7) and `box_push_centralized.py:313-314`'s rewrite to `explore`.

**Classification.** **V1 DESIGN DECISION.** `:104` requires a backend mapping per skill; it does
not dictate the token. Freezing the token in the signature is what makes the mapping mechanically
checkable rather than a class name compared for truthiness.

**Implementation consequence.** The backend is **not modified** — `make_skill` keeps its current
behaviour, and `tests/test_backend_freeze_drift.py::test_the_backend_factory_still_lacks_a_wait_arm`
pins that claim so the obligation is re-read rather than deleted if the backend ever gains the arm.
The correction lives in the P1 wrapper.

---

## 16. Decision 15 — `OutsideSymbolicModel` is a fourth typed validation result

**Decision.** A registry-valid, grounded call for a skill deliberately absent from the V1 symbolic
model (`Explore`, `Wait` — Decision 5) resolves to `OutsideSymbolicModel`. It is neither
`SymbolicallyInapplicable` nor an `InfrastructureFault`.

- Not `SymbolicallyInapplicable`: that asserts preconditions were evaluated and failed. Here there
  are none to evaluate; the track holds no model. Reporting inapplicability states a symbolic
  verdict the model cannot support.
- Not an `InfrastructureFault`: nothing is broken, so the executive cycle must NOT short-circuit
  (`:163`). `is_infrastructure_fault` is `False`.
- The call **may still be executed** — it is registry-valid and backend-mapped. What the symbolic
  track must not do is predict effects for it, and therefore **no `STATE_EFFECT_MISMATCH` may ever
  be raised for it**. An execution failure is still reportable on the authoritative outcome alone
  (Decision 13.7).

**Code evidence.** `shared/skills.py::OutsideSymbolicModel`; `shared/skill_ir.py::DomainIR.resolve`.
`DomainIR.skill()` deliberately still raises `KeyError`, so a planner cannot silently plan with
`Explore`. Tested in `tests/test_prediction_and_monitoring.py::TestOutsideSymbolicModel`.

**Classification.** **V1 DESIGN DECISION (spec-silent).** The specification enumerates the
rejection kinds but does not name this case, which arises only because Decision 5 keeps `Explore`
in the registry while removing it from the symbolic action set.

---

## 17. Decision 16 — P1 adapter argument translation is explicit and per-skill

**Decision.** The P1 adapter **never calls `skill_executor_push.make_skill`**, and never fills a
generic coordinate slot. It constructs the concrete backend skill classes directly, with a separate
explicitly-derived argument per executive skill.

**Why the factory is unusable as a typed seam.** Its own docstring states the overload:

> "`arg` is the LLM-supplied (x, y): the box cell for goto_push_pose/cooperate_push, the
> destination cell for push. None falls back to nearest-target behaviour."

One parameter with three meanings, plus a silent fallback. Passing a generically-derived tuple
through it is how a `Push` destination becomes a `GotoPushPose` box cell with no error anywhere.

**The frozen translation.**

| Executive call | Backend construction | Argument derivation |
|---|---|---|
| `GotoPushPose(agent, box, zone)` | `GotoPushPoseSkill(agent_id, box=cell)` | `cell` = the position of **the grounded `BoxId`** read from `export_full_state()` (authoritative `world`, Decision 4). **Never `None`** — `None` routes to `_nearest_undelivered_target`, which is silent re-grounding. |
| `CooperativePush((a1, a2), box, zone)` | `CooperativePushSkill(agent_id, partner_id, box=cell)` for **both** agents, with the **same** `cell` | as above; the wrapper owns both instances (Decision 1) and latches the pair ordering. It does NOT latch the front/rear tandem roles — `_assign_slots` re-derives those every `step()`. |
| `Push(agent, box, zone)` | `PushSkill(agent_id, dest=None)` | `dest=None` is the **explicit** encoding of push-to-zone (Decision 11): `PushSkill` finishes `delivered` exactly when the box's landing cell is a goal cell, which is the zone. The adapter reaches this by **validating `zone` against the single frozen `DELIVERY_ZONE`** and refusing any other `ZoneId` — never by defaulting. |

**Why `Push` does not pass an explicit destination cell.** Computing one would mean
`first_zone_cell_along(box_position, D)`, which is a **partial** function — the ray need not cross
the zone when the push direction is vertical (§19 D-2). It would duplicate the backend's own goal test
while adding a failure mode the backend does not have. `dest=None` is a decision about zone
semantics, and it is recorded as one; it is not "leave the argument off".

**The identity obligations that make this safe.** `dest=None` means `PushSkill` pushes whatever is
in front of the agent (`_get_front_cell(obs) != "TARGET_OBJECT"` → `blocked`), and for the two
box-argument skills `_resolve_box` falls back to `_nearest_undelivered_target` whenever the supplied
cell is not a known undelivered target *in the belief grid*. So the adapter must additionally:

1. **Pre-flight — IDENTITY RESOLUTION ONLY.** Resolve the grounded `BoxId` against authoritative
   `world`. If that identity is **absent from the world**, the call is `UngroundedCall`
   (→ `InfrastructureFault(MISSING_GROUNDING)`, zero executive steps). If it resolves, **attempt
   the skill**.

   The pre-flight must **not** ask whether the attempt will succeed. No front-cell check, no
   occupancy, no reachability, no "is the agent actually behind this box" test may gate the
   attempt. Such a gate would be the feasibility oracle Decision 6 forbids, applied at the one seam
   where the adapter can see the grid.

2. **An optimistic `in_pose` that is false in the world is an `ExecutionDiscrepancy`, never a
   grounding fault.** This case is *reachable by design*: `in_pose` is non-exclusive (Decision 6),
   so `Push(a0, box_1, z)` can be symbolically applicable while `a0` is not behind `box_1` at all.
   `box_1` is present in `world` — nothing is ungrounded. The attempt runs and consumes **one
   executive step**, and the report is
   `ExecutionDiscrepancy(EXECUTION_FAILURE_OF_APPLICABLE_SKILL)`. Reporting it as
   `MISSING_GROUNDING` would abort the cycle, charge zero executive steps, and **suppress the
   single most important V1 signal** — the project rule is explicit that this must be observable as
   an `ExecutionDiscrepancy`.

   The raw label and failure class depend on what is actually in front of the agent, and the two
   sub-cases differ. P1 must derive both from `world`, never assume them:

   | Front cell | Backend path | Raw label | Failure class |
   |---|---|---|---|
   | nothing pushable | `_get_front_cell(obs) != "TARGET_OBJECT"` → `_finish("blocked")` on the first `step()`; no `MOVE_FORWARD` is ever issued | `blocked` | `BACKEND_REJECTED_BEFORE_TRANSITION` |
   | a **different** box (e.g. `box_0`, heavy) | the front cell *is* `TARGET_OBJECT`, so the skill issues `MOVE_FORWARD`; the env rejects a lone push of a heavy box (`required_agents > 1` → penalty, no move); the next iteration observes the agent did not advance and finishes | `too_heavy`, or `blocked` if the landing cell holds a **wall or another target box**. An AGENT on the landing cell still yields `too_heavy` — that mislabel is headline 0, and D3 requires P1 to re-derive the distinction from `world` | `UNCHANGED` — a transition *was* attempted but nothing moved; `PARTIAL_EXECUTION` if an earlier cell of the same attempt did move a box |

   An earlier revision of this decision claimed the first row for both sub-cases. It is wrong for
   the second: a real transition is attempted, so "no transition attempted" does not hold.

3. **Post-flight — identity verification.** Confirm the skill acted on the grounded `BoxId`.
   Substitution (the backend silently acted on a different object) violates the adapter's identity
   contract; that is a different thing from the skill failing, and it is an `InfrastructureFault`
   with kind **`EXECUTOR_MONITOR_PROTOCOL_FAILURE`**. The kind matters: `MISSING_GROUNDING` is in
   `PRE_EXECUTION_FAULT_KINDS`, and `TraceEntry` **refuses** to record a pre-execution fault
   alongside an `ExecutionResult` — so using it here would be unconstructible, since the call did
   reach the executor and must be charged its one executive step.

   Verification is **per skill**, because "which object moved" only works where an object moves:

   | Skill | Post-flight check |
   |---|---|
   | `CooperativePush` | the box whose position changed (or became `delivered`) must be the grounded `BoxId`. If a *different* box moved → protocol failure (it passes a box argument, so `_resolve_box` can substitute). |
   | `Push` | **No identity check applies.** `PushSkill` takes no box argument and never calls `_resolve_box` (Decision 16 passes `dest=None`), so backend re-grounding is structurally impossible. A different box moving means the agent was physically behind another box — the designed non-exclusive-`in_pose` case of obligation 2 — and is an `ExecutionDiscrepancy`, **never** `EXECUTOR_MONITOR_PROTOCOL_FAILURE`. Classifying it as a fault would be the same signal suppression obligation 2 exists to prevent. |
   | `GotoPushPose` | **no object moves at all**, so movement cannot be the criterion. When the skill CLAIMS success (raw `in_position`), compare the terminal agent cell against the pose cell of the grounded box, derived from the snapshot (`box - direction_vector(push_dir(box, zone))`); landing on another box's pose cell is a substitution. A blocked/truncated stop makes no identity claim and is not checked — an unconditional cell comparison would raise false substitution faults for ordinary failures. |

   This is post-hoc interpretation of what happened, which Decision 13 clause 5 explicitly requires
   the wrapper to compute; it is not a feasibility query and must never gate the attempt.

4. **The adapter controls what the backend skills can re-ground against.** `_resolve_box` is
   re-evaluated on *every* `step()` against whatever grid the adapter supplies, so a one-time
   pre-flight cannot close it. The adapter therefore feeds the backend skills the `entities`/grid
   view it constructs, and that view is authoritative-`world`-derived — never the reward-derived
   belief grid, whose defects Decision 9 defers and whose target-cell labelling is exactly what
   `_resolve_box` consults. **RESOLVED (P1, 2026-08-20):** the adapter supplies the **full exact grid**, rebuilt from
   `core_env.world` on every primitive step (`box_push_v1_adapter.py::_entities_for`): walls,
   `delivery_zone`, undelivered boxes as `target_object`, OTHER agents as `agent`; a DELIVERED
   box's cell shows the underlying `delivery_zone`, because delivered boxes are non-colliding
   ghosts in the backend and labelling them as boxes would wrongly block navigation and re-offer
   them as targets. Never the belief grid. Consequences accepted and recorded: the belief-only
   defects (agents as `empty` — headline 0's root; `_resolve_box`'s belief-conditioned fallback
   trigger) do not arise on this path, and `_bfs_avoid_boxes` navigates on exact occupancy INSIDE
   execution — legal, since Decision 6 governs applicability, not execution.

   The recorded consequence stands: exact-grid navigation reduces the `goto_push_pose → blocked`
   rate (§J-3's primary acceptance scenario #2). The case remains REACHABLE — a physically
   occupied pose cell still yields no path, a spin, the no-progress bail and `blocked`
   (`tests/test_p1_adapter.py::test_goto_blocked_by_partner_on_the_pose_cell` demonstrates it
   live) — but **P2 must re-validate scenario #2 against the adapter, not against belief-era
   frequencies.**

5. **Never** pass a caller-supplied or NL-supplied coordinate tuple through to the backend. Executive
   arguments are identities (Decision 11); cells are derived inside the adapter, from the snapshot.

The three outcomes are therefore kept strictly apart: **identity absent** → `UngroundedCall`;
**identity present, attempt failed** → `ExecutionDiscrepancy`; **identity present, wrong object
acted upon** → `InfrastructureFault`.

**Classification.** **V1 DESIGN DECISION.** `:104` requires a backend mapping per skill but does not
dictate the argument translation; Decision 7 forbids silent re-grounding, and this is what enforcing
it looks like at the one seam where the legacy overload is reachable.

**Scope.** P0 freezes the obligation; **P1 implements it.** No adapter code exists yet.

---

## 18. Residual work items

These are scheduled engineering tasks, not open decisions.

1. **P2 — RE-ISSUE the PDDL artifacts FROM `DOMAIN_IR`, do not hand-edit them.** Generating them
   from the frozen IR is what stops this divergence recurring. All the legacy files now carry a
   `;; SUPERSEDED FOR V1` banner naming `domain/box_push_v1.DOMAIN_IR` as the authority, pinned by
   `tests/test_domain_freeze.py::TestLegacyPddlIsMarkedSuperseded`. **Three** recorded divergences:
   - *Problem file:* `(unexplored box0) (unexplored box1)` becomes `(discovered box0)
     (discovered box1)`; re-run `pyperplan` and record the new `.soln`. The existing 7-step plan is
     superseded — it opens with two `explore` steps that Decision 5 removes from the action set.
   - *Domain file:* `box_push_domain.pddl` has **no `zone` parameter on any action** and still
     declares `explore`. Decision 11 puts `zone` in every push-related signature, so the domain
     needs a `zone` type, a `delivery_zone` object, and `?z - zone` on `goto_push_pose`, `push`
     and `cooperate_push`; `explore` leaves the symbolic domain.
   - *Identifiers:* objects are `a1 a2 box0 box1`, but the frozen contract uses
     `agent_0 agent_1 box_0 box_1` and **`BoxId.parse("box0")` raises `ValueError`**. This is not
     cosmetic: a P2 planner wired to the current files fails on every un-lift.
2. **P3 — pin dependency versions.** `:236` requires pinned DSPy/runtime versions for the offline
   baseline. Decision 10 fixes only Python/OS.
3. **P3 — introduce the offline LM seam.** `CentralizedDSPyPlanner.configure_ollama`
   (`centralized_dspy_planner.py:35-68`) hardwires `dspy.configure`, and the runner hardcodes the model
   (`box_push_centralized.py:46`). No offline P3 test can exist until this seam is added.
4. ~~**P2 — static no-backend-import guard**~~ — **done in P0.** `tests/test_no_backend_imports.py` discovers guarded packages instead of hardcoding them, and the symbolic side is derived (`discovered_guarded_packages() - RUNTIME_PACKAGES`) so a future `symbolic/` package is covered the day it is created, not the day someone remembers.
5. **P1 — guards and counters:** `world`↔`grid` consistency assertion, reset-before-use,
   post-terminal refusal, per-attempt `env.step()` counter, belief-sharing reset test.
6. **P2 — implement the world-effect predictor** declared by
   `SkillIR.predicted_world_effects` (Decision 13.2/13.3), **and add the static guard Decision 13
   clause 9 requires**: the predictor is monitor-side only, so applicability/planning must be
   structurally unable to import it, and its own inputs must be bounded to positions, directions,
   `delivered`/`required_agents` and the zone. Not implemented in P0 by design: P0 freezes *what
   may be predicted*, P2 grounds it. Until it exists, `GotoPushPose` failure is detected through
   the authoritative typed outcome only.
7. **P1 — exhaustive adapter dispatch** on `backend_dispatch_key` with no fallback arm
   (Decision 14), including the `Wait` route the backend factory lacks.
8. **P1/P4 — prove the executor is policy-independent.** `.claude/rules/testing.md` requires
   "orchestration policy changes decisions, not executor semantics". This is **not testable at
   P0** and is not claimed as covered: no executor and no orchestrator exist, and
   `OrchestrationPolicy` is a config enum only. Recorded here so it is not mistaken for a
   satisfied property.
9. **P3 — remove the runner's silent `explore` fallback.** `_skill_parser` returns
   `("explore", None)` for any unparseable planner output (`box_push_centralized.py:306-314`) and
   the DSPy exception path feeds the same substitution (`:404`). Decision 7 forbids it; the typed
   `MalformedCall` replaces it. Listed separately from item 3 (the offline LM seam), which does not
   cover the parser.
10. **CI** — no CI configuration exists in the repository. Whether V1 requires CI is a project-management
   question, not a V1 semantics decision.

---

## 19. Explicitly deferred to P2 — recorded, not implemented

These are **not** open questions and **not** P0 defects. P0 freezes the contract; P2 builds against
it. Each is listed so that its absence is a recorded decision rather than an oversight.

| # | Deferred item | Why it is not P0 | Where the P0 contract already constrains it |
|---|---|---|---|
| D-1 | **Grounding `predicted_world_effects` into an actual predictor.** No predictor exists anywhere in the repository; the effects are declarations of what a skill's success semantics imply. | P0 freezes *what may be predicted*; computing it needs the P1 wrapper's live state. | `SkillIR.predicted_world_effects`; Decision 13 clauses 2-3, bounded by clause 9 (monitor-side only, bounded inputs). |
| D-2 | **`first_zone_cell_along` is a partial function.** If the push ray runs along an axis that never crosses the zone, no terminal cell exists and V1 defines no result. | **Reachable, not hypothetical.** `Push`'s direction is the AGENT'S FACING (`D == direction_vector(agent.direction_pre)`), not `push_dir` — `PushSkill` never calls `_push_dir_toward_goal`. Since `in_pose` is non-exclusive and optimistic, a failed `GotoPushPose` can leave an agent facing `UP` while `in_pose` survives, making `Push` symbolically applicable with a vertical ray that never reaches the `x=1` column. (For `CooperativePush` the direction IS `push_dir`, which always aims at the nearest goal cell, so that skill is not exposed.) | Decision 16 avoids depending on it (`Push` uses `dest=None`, so the adapter never computes a terminal cell). **P2 obligation:** the predictor must emit NO world-basis prediction when the ray misses the zone, rather than guessing a cell — the symbolic basis and the authoritative outcome still apply. |
| D-3 | **Regenerated PDDL and planner solution.** | The legacy artifacts diverge from the frozen IR on three counts and are banner-marked; regenerating them from `DOMAIN_IR` is a P2 task (§18 item 1). | `domain/box_push_v1.py::DOMAIN_IR` is the authority; `tests/test_domain_freeze.py` pins the banners and bans brittle line citations into the artifacts. |
| D-4 | **Monitor-side predictor implementation** (the component that consumes D-1 and compares both bases). | Requires P1's authoritative post-state and P2's predictor. | `ExecutionDiscrepancy` already carries both typed key pairs; `ProjectionContract.agrees` is the symbolic half. Until it lands, `GotoPushPose` failure is detected through the authoritative typed outcome only (Decision 13 clause 7). |

---

## 20. Binding summary

| # | Decision | Classification |
|---|---|---|
| 1 | Sequential executive execution; `CooperativePush` is one executive skill | SPEC-DETERMINED |
| 2 | Executed invocation = 1 executive step (success or failure); pre-executor rejection = 0; primitive steps tracked separately | V1 DESIGN DECISION |
| 3 | Preserve raw labels; add authoritative typed outcome; timeout explicit | V1 DESIGN DECISION |
| 4 | Canonical `StateSnapshot` only from authoritative world state | SPEC-DETERMINED |
| 5 | `Explore` in backend/registry; V1 symbolic state fully observable; discovery not required | SPEC-DETERMINED (observability) + V1 DESIGN DECISION (retention) |
| 6 | Keep optimistic non-exclusive `in-pose`; never add reachability/geometry/BFS/occupancy/feasibility to symbolic applicability | SPEC-DETERMINED (prohibition) + V1 DESIGN DECISION (abstraction content) |
| 7 | Reject malformed calls, invalid grounding, silent object substitution | SPEC-DETERMINED |
| 8 | Reject execution after terminal state | V1 DESIGN DECISION (spec-silent) |
| 9 | Defer rendered-grid/belief defects; preserve for later partial-observation work | V1 DESIGN DECISION |
| 10 | Python 3.12 + Linux/WSL2 | V1 DESIGN DECISION |
| 11 | Frozen skill signatures; `Push` is push-to-zone with symbolic success `delivered(box)` | V1 DESIGN DECISION |
| 12 | Synthetic `NoPlan` instance deferred to P2/P4; does not block P0 | V1 DESIGN DECISION |
| 13 | Prediction/monitoring boundary: effects may be predicted (world + symbolic bases); applicability may not use feasibility oracles; `in_pose` outcome-tracked without exclusivity | SPEC-DETERMINED (clauses 4,6,7) + V1 DESIGN DECISION (clauses 2,3,8) |
| 14 | Frozen `backend_dispatch_key` per registry skill including `Wait`; exhaustive P1 dispatch, no fallback | V1 DESIGN DECISION |
| 15 | `OutsideSymbolicModel` as a fourth typed validation result; not inapplicable, not a fault | V1 DESIGN DECISION (spec-silent) |
| 16 | P1 adapter translates arguments explicitly per skill; never `make_skill`, never a generic coordinate slot, never silent re-grounding | V1 DESIGN DECISION |
