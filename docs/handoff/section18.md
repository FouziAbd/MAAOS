# Section 18 — Fouzi V1 Handoff Contract

> Evidence-based audit of the repository as it exists, performed before P0-P4 implementation.
> Every non-`TBD` claim below is anchored to `path:line -> class/function` read from source.
> Nothing here is aspirational: where the code does not establish a semantic, the row says
> `MISSING` or `AMBIGUOUS` rather than inventing one.

**Audit baseline:** branch `middleware_layer`, commit `9cb39cd`, Python 3.12.3.
**Audit date:** 2026-08-18. **Audit method:** direct source reading + two `backend-investigator`
sub-audits + one independent `architecture-reviewer` contract check.
**Last revised:** 2026-08-19, after P0 implementation and the P0 consistency audit.

> ### How to read the status columns
>
> The audit body is preserved as written, because it is the evidence record for the BACKEND as it
> exists. A `MISSING` / `UNDEFINED` / `AMBIGUOUS` cell therefore means **"the existing backend code
> does not establish this"** — it does not mean the V1 contract leaves it open.
>
> Every such item that V1 has since frozen carries an inline **→ V1** annotation naming the
> deciding entry in `docs/decisions/P0_V1_DECISIONS.md`. All sixteen decisions are FINAL; §L is
> fully closed. Nothing in this document is a live open question awaiting a choice.

## Status legend

- `SATISFIED` — code/spec evidence is sufficient
- `PARTIAL` — some required semantics/evidence are missing
- `MISSING` — required contract is absent
- `AMBIGUOUS` — code/spec genuinely permits multiple interpretations; requires decision

## Headline findings

0. **HIGHEST SEVERITY — execution labels are computed from BELIEF, not from the authoritative
   backend, and `too_heavy` is therefore deterministically mislabelled.** `PushSkill` decides
   `blocked` vs `too_heavy` by reading the *belief* label of the cell beyond the box
   (`skill_executor_push.py:218-221`), where `_BLOCKING = ("wall","agent")` (`:36`). But the belief
   updater **deliberately never writes `"agent"`** — another agent's cell is recorded as `"empty"`
   (`deterministic_grid_updater.py:215-220`, with an explicit comment explaining why), while the
   backend *does* reject a light push whose landing cell holds an agent
   (`_cell_free_for_box`, `multi_agent_box_push_env.py:301-303`). Consequence, verified end-to-end:
   **a light box blocked by the partner agent is always reported as `too_heavy`.** An unobserved
   (`"unknown"`) landing cell produces the same mislabel. The planner prompt then treats
   `too_heavy` as permanent evidence of weight (`box_push_centralized.py:275-276`), so one mislabel
   corrupts the reasoning track for the rest of the episode. **Until the V1 wrapper derives the label
   from `world` instead of the belief grid, every downstream `ExecutionDiscrepancy` is uninterpretable.**
   This is the highest-leverage fix in P1.
1. **No executive-step concept exists in code.** The only budget is primitive joint steps
   (`multi_agent_box_push_env.py:141`). The executive-step contract must be *created* at P0/P1;
   it cannot be extracted from the runner.
2. **Failure class depends on *when* a skill fails, not on (skill, label).** All three contract
   failure classes already occur, and the *same* label changes class with timing: `goto_push_pose →
   blocked` is rejection-before-transition on the first `step()` and partial-execution after 39
   navigation steps. **§C's table is keyed by skill+label and is therefore structurally incapable of
   expressing the real semantics** — V1 must record the classification per attempt at runtime
   (pre-state, post-state, primitive count), not look it up in a static table.
3. **Malformed NL output is silently rewritten to `explore`** (`box_push_centralized.py::_skill_parser`,
   the `decided.get(aid, ("explore", None))` default in `::main`,
   `centralized_dspy_planner.py:106-108`) — and there are three further silent paths
   (§B-consistency-7/8/9): dropped arguments, silent re-grounding onto a *different box*, and a
   second inconsistent `WaitSkill` fallback. The DSPy exception path is the worst: an API failure is
   an `InfrastructureFault` by contract, which must abort the cycle before any further skill command
   (`SUPERVISOR_P0_P4_CONTRACT.md:163`), yet here it is converted into `explore` and **executed
   against the authoritative environment for up to 30 primitive steps**.
4. **Label contract drift in both directions.** The advertised label `moved` does not exist in code;
   `cooperate_push` can return the undocumented `none_known`; and `_timeout()` sets `label="timeout"`
   which every subclass overwrites — so **`PushSkill` reports budget exhaustion as `pushed`, a
   success label** (`:226-228`).
5. **A usable optimistic symbolic model already exists** as PDDL
   (`pddl/box_push_domain.pddl`) with a verified 7-step plan. Its optimism is real and *desirable*:
   `in-pose` is non-exclusive and has no geometry, so the frozen plan puts one agent in pose for two
   boxes at once and two agents in the same pose cell — guaranteed `ExecutionDiscrepancy` sources
   that must **not** be "fixed" (§J-3).
6. **Exact state is reachable only via env attributes**; there is no `export_full_state()`, and the
   belief layer that currently feeds skills is partial-observation and dead-reckoned from a
   **multiplexed reward channel** that is provably corruptible (§F).

---

## A. Repository and execution baseline

| Requirement | Status | Evidence | Current semantics | Gap / action |
|---|---|---|---|---|
| Repository/branch/commit frozen | PARTIAL | branch `middleware_layer`, commit `9cb39cd` | Working branch, uncommitted `.claude/` + docs present | Freeze a V1 branch/commit before P0 |
| Install instructions | PARTIAL | `requirements.txt` | `pettingzoo>=1.24`, `gymnasium`, `minigrid`, `dspy-ai`, `pyperplan>=2.1`, `pyRDDLGym>=2.7`; deps unpinned except two | Pin exact versions for deterministic V1 (P3 requires it) |
| Python/OS constraints | PARTIAL | venv `/home/fouzi/PettingZooEnv`, Python 3.12.3, Linux/WSL2 | Established by environment, not declared in repo | Declare in a manifest at P0 |
| Run command | SATISFIED | `box_push_centralized.py::main` | `cd functional_layer/custom_env/box_push/env && python box_push_centralized.py`; requires a live Ollama at `LLM_BASE` (the `dspy.LM` setup in `::main`) | Add an offline V1 entry point that does not need an LM |
| Automated test command | SATISFIED (P0) | `python3 -m unittest discover -s tests -t .` — 580 tests, deterministic and offline (1 skip: the MAAOS_LIVE_LM-marked live-LM integration test), no LM required (the P1 module steps the real backend headlessly; P0 modules step nothing) | P0 contract freeze + P1 live-backend integration (tests/test_p1_adapter.py) | — |
| Target OS/CI | PARTIAL | — | No CI config in repo | OS/Python frozen by **Decision 10**; CI is a project-management question, not V1 semantics (decisions §18 item 10) |

---

## B. Executive skill vocabulary and backend mapping

**Current BACKEND vocabulary** (what the audit found): `skill_executor_push.py:373-386 make_skill`
and `box_push_centralized.py:300 _VALID_SKILLS` = `{explore, goto_push_pose, push, cooperate_push,
wait}`. All five are **composed multi-primitive skills**; none is a single backend action.

> **→ V1: the backend factory is NOT the vocabulary authority.** `shared/skills.py::SkillName` +
> `REGISTRY` are (`:82`, **Decision 11**), and each signature carries a frozen
> `backend_dispatch_key` (**Decision 14**). Note the divergence the audit row hides: `make_skill`
> has arms for only four tokens and returns `WaitSkill` from a silent default for everything else,
> so `"wait"`, `"Push"` and `""` are observationally identical there. P1 dispatches exhaustively on
> the frozen key with no fallback; the backend itself is unchanged.

| Executive skill | Typed arguments | Backend file/class | Direct or composed? | Symbolic preconditions (PDDL) | Success effects | Actual result labels | Richer backend feasibility absent from symbolic model |
|---|---|---|---|---|---|---|---|
| `explore` | none | `shared_skills.py:261 ExploreSkill` | Composed; frontier BFS, `_MAX_STEPS=30` (`:263`) | `(unexplored ?b)` (`box_push_domain.pddl` `:action explore`) | `discovered(?b)` | `found_target` (`shared_skills.py:280`), `found_decoy` (`:282`), `explored` (`:286`, on timeout) | Discovery is emergent from a 3×3 view; symbolic model treats it as a one-shot action on a named box |
| `wait` | none | `shared_skills.py:301 WaitSkill` | Degenerate; `done=True` in `__init__` (`:306`) → **consumes 0 primitive steps** | omitted from PDDL (`box_push_domain.pddl` (no `wait` action)) | none | `done` (`shared_skills.py:307`) | Livelock risk, §C-note-4 |
| `goto_push_pose` | `box: (x,y)` optional | `skill_executor_push.py:112 GotoPushPoseSkill` | Composed; `_MAX_STEPS=40`, `_NO_PROGRESS=8` (`:119-120`) | `(discovered ?b) ∧ (pending ?b)` (`:action goto_push_pose`) | `in-pose(?a,?b)` | `in_position` (`:154`), `none_known` (`:146`), `blocked` (`:168` stale-bail, `:172` timeout) | Real navigation may be impossible/blocked; target cell is the single cell `B−D` (`:150`) |
| `push` | `dest: (x,y)` optional | `skill_executor_push.py:182 PushSkill` | Composed; `_MAX_STEPS=30` (`:190`) | `(in-pose ?a ?b) ∧ (light ?b) ∧ (pending ?b)` (`:action push`) | `delivered(?b)` | `delivered` (`:213`), `pushed` (`:215` dest reached, `:228` timeout), `blocked` (`:220`, `:225`), `too_heavy` (`:221`) | Box destination must be free (`_cell_free_for_box`); heavy boxes never move for one agent |
| `cooperate_push` | `box: (x,y)` optional, `partner_id: str` | `skill_executor_push.py:238 CooperativePushSkill` | Composed; **inherits `_MAX_STEPS=150`** (`shared_skills.py:216`), `_WAIT_LIMIT=10` (`:250`) | `(different ?a1 ?a2) ∧ (heavy ?b) ∧ (in-pose ?a1 ?b) ∧ (in-pose ?a2 ?b) ∧ (pending ?b)` (`:action cooperate_push`) | `delivered(?b)` | `none_known` (`:294`), `blocked` (`:300`, `:308`), `delivered` (`:324`), `waiting_partner` (`:330` timeout, `:350` partner not converging) | Requires exact tandem geometry + simultaneous `MOVE_FORWARD`; self-navigates to its own slot |

### Skill vocabulary consistency findings

1. **`moved` is advertised but unreachable.** Documented at `skill_executor_push.py:7` and in prompts
   at `box_push_centralized.py:53`, `:243`, `:288`; there is no `_finish("moved")` in
   `CooperativePushSkill` (`:285-368`). **Action:** delete `moved` from docstrings/prompts, or add
   the effect — do not leave the prompt advertising a label the executor cannot produce.
2. **`none_known` is producible by `cooperate_push`** (`:294`) but is absent from its advertised set
   (`box_push_centralized.py:53`).
3. **`found_decoy` is unreachable in BoxPush.** `ExploreSkill` can emit it (`shared_skills.py:282`),
   but every box is a red `TargetPackage` (`box_push_env.py:104-106`) and no decoy is ever placed.
4. **`timeout` is never observable.** `BaseSkill._timeout` sets `label="timeout"`
   (`shared_skills.py:233`), but every subclass immediately overwrites it (`:286`;
   `skill_executor_push.py:172`, `:228`, `:330`). Consequence: **budget exhaustion is reported as
   `pushed` (a success label) by `PushSkill`** (`:228`) and as `blocked`/`waiting_partner` elsewhere.
   Success-on-timeout is indistinguishable from real success at the executive interface.
5. **`in_progress`** (`box_push_centralized.py::main`) is a runner-level substitute when a skill is still
   running at episode end — it is not a backend label.
6. Argument semantics are **positionally overloaded**: the same `(x,y)` means *box cell* for
   `goto_push_pose`/`cooperate_push` and *destination cell* for `push` (`skill_executor_push.py:376-377`).
   V1 typed arguments must disambiguate these.
7. **Silent argument dropping.** `_skill_parser`'s skill-name regex succeeds independently of the
   coordinate regex (`box_push_centralized.py::_skill_parser`), so `push [foo,bar]` yields `("push", None)`
   → `PushSkill(dest=None)`, which per `:187-188` pushes straight ahead until the box stops. A
   malformed argument silently becomes **different skill semantics**.
8. **Silent re-grounding onto a different object — worst of the silent paths.**
   `GotoPushPoseSkill._resolve_box` (`skill_executor_push.py:128-136`) and
   `CooperativePushSkill._resolve_box` (`:263-270`) discard the planner's `[bx,by]` whenever it is
   out of range, not currently a target in belief, or already on the goal, and substitute
   `_nearest_undelivered_target` (`:98-107`) — then report success. The predictor predicts effects on
   box A while the executor acts on box B, and the monitor will misattribute the resulting mismatch
   to model optimism rather than to a grounding fault. In V1 this must raise
   `InfrastructureFault(missing grounding)`.
9. **Two different silent fallbacks for the same error class:** `_skill_parser` defaults to `explore`
   (`box_push_centralized.py::_skill_parser`) while `make_skill` defaults to `WaitSkill`
   (`skill_executor_push.py:386`).

### Symbolic ↔ backend signature misalignment (RESOLVED — Decisions 11 / 14)

`.claude/rules/testing.md` requires aligned argument types across registry/model/backend. They are
not aligned today:

| Skill | Symbolic (`box_push_domain.pddl`) | Backend (`skill_executor_push.py:373-386`) | Mismatch |
|---|---|---|---|
| `explore` | `(?a - agent ?b - box)` — discovers a *named* box (`:action explore`) | no argument; reports whatever appeared (`shared_skills.py:279-282`) | arity |
| `goto_push_pose` | `(?a ?b - box)` (`:action goto_push_pose`) | `[bx,by]` grid cell | **object vs cell** |
| `push` | `(?a ?b - box)`, effect `delivered` in one action (`:action push`) | `[tx,ty]` destination cell; may end `pushed` ≠ delivered | object vs cell **and** effect |
| `cooperate_push` | `(?a1 ?a2 ?b)` — one joint action (`:action cooperate_push`) | per-agent instance; must be assigned to both agents in the same cycle (`:252-256`) | **joint vs per-agent** |

**→ V1: resolved in P0.** **Decision 11** freezes one typed signature per skill, identical in the
registry, the IR, the planner and the wrapper: arguments are IDENTITIES (`AgentId`/`BoxId`/`ZoneId`),
never grid cells, so the object-vs-cell mismatch cannot survive the wrapper; `CooperativePush` is
ONE executive skill whose wrapper owns both per-agent instances (**Decision 1**); `Push` is
push-to-zone with symbolic success `delivered(box)`; and `Explore` leaves the symbolic action set
(**Decision 5**), so its arity mismatch is moot — it resolves to `OutsideSymbolicModel`
(**Decision 15**). Enforced by `DomainIR.__post_init__` (the IR must hold the registry's signature
OBJECT) and `tests/test_contract_invariants.py`.

The `box_push_domain.pddl` column above describes the LEGACY file, which is now banner-marked
`;; SUPERSEDED FOR V1`; the authority is `domain/box_push_v1.py::DOMAIN_IR` (decisions §18 item 1).

---

## C. Failure semantics matrix

> **Structural caveat — read before using this table.** The rows below are keyed by
> *(skill, label)*, but the real failure class is a function of *(skill, label, **when in the
> attempt** it fired)*. The same `blocked` from `goto_push_pose` is rejection-before-transition on the
> first `step()` and partial-execution after 39 navigation steps. **A static table cannot express
> this.** V1 must record the classification per attempt at runtime — pre-state, post-state, and a
> real `env.step()` count — and this table serves only to enumerate the *reachable* modes.
>
> Note also that `BaseSkill._steps` is **not** a primitive-step counter and must not be used for the
> count: `GotoPushPoseSkill` increments it only after its early returns (`skill_executor_push.py:170`)
> and `PushSkill` only when *issuing* a push, never on the evaluation iteration (`:226`). The wrapper
> must count `env.step()` invocations per attempt.

**Verified: every *reachable* failure mode is enumerated below, and none of them is a guaranteed
no-op at the world-state level** — even a rejection still submits `STAY` to `env.step()`
(`_finish` returns `Actions.STAY`, `shared_skills.py:237-240`; submitted at
`box_push_centralized.py::main`), which increments `step_count` and writes `last_action`.

> **Reading the "Executive step consumed?" column.** The *backend* has no executive-step concept at
> all (see §C "Executive step" below), so every cell reads "n/a in backend". It is **not** an open
> V1 question: **Decision 2** answers every row uniformly — any invocation that reaches the executor consumes
> exactly one executive step, success or failure, and any rejection before the executor consumes
> zero. Primitive steps are counted separately by the wrapper.

| Skill | Failure label/mode | State unchanged / partial / rejected | Example state changes before failure | Primitive steps consumed | Executive step consumed? (backend) | Evidence |
|---|---|---|---|---:|---|---|
| `goto_push_pose` | `blocked` (stale bail) | **Partial** | Agent has navigated arbitrarily far; direction changed | up to ~40 | **n/a in backend** → 1 (Decision 2) | `skill_executor_push.py:161-168` |
| `goto_push_pose` | `blocked` (timeout) | **Partial** | as above | 40 | n/a in backend → 1 (Decision 2) | `:170-173` |
| `goto_push_pose` | `none_known` | **Rejected before transition** (first `step()`) | none | 0 skill-internal; runner still submits `STAY` | n/a in backend → 1 (Decision 2) | `:144-146` |
| `push` | `too_heavy` | **Partial ONLY IF an earlier cell of the same attempt moved the box; otherwise `UNCHANGED`** | A failed `MOVE_FORWARD` was really executed (−0.1 penalty), so a transition WAS attempted — but nothing moved, and `ExecutionResult` rejects `PARTIAL_EXECUTION` unless `world_key()` changed. Earlier pushes in the same skill may have moved the box several cells | ≥2 | n/a in backend → 1 (Decision 2) | `:209-221`; env `multi_agent_box_push_env.py:222-223` |
| `push` | `blocked` (beyond-cell occupied) | **Partial** | as above | ≥2 | n/a in backend → 1 (Decision 2) | `:218-220`; env `:226,233-234` |
| `push` | `blocked` (nothing in front) | **Rejected** if on first `step()`, else **Partial** | none, or prior successful pushes | 0 or more | n/a in backend → 1 (Decision 2) | `:224-225` |
| `push` | `pushed` **on timeout** | **Partial, mislabelled as success** | box moved but destination not reached | 30 | n/a in backend → 1 (Decision 2) | `:226-228` |
| `cooperate_push` | `blocked` (dest/runway) | **Rejected** on first `step()`, else **Partial** | possible repositioning | 0..150 | n/a in backend → 1 (Decision 2) | `:299-300`, `:305-308` |
| `cooperate_push` | `waiting_partner` | **Partial** | agent navigated to its slot and turned | up to 150 | n/a in backend → 1 (Decision 2) | `:328-331`, `:344-350` |
| `cooperate_push` | `none_known` | **Rejected** | none | 0 | n/a in backend → 1 (Decision 2) | `:292-294` |
| malformed call | *(never reaches the executor)* | **Silently rewritten to `explore`** | full `explore` execution occurs | up to 30 | 0 in V1 | `box_push_centralized.py::_skill_parser` — **→ V1: forbidden.** A malformed call is a typed `MalformedCall` → `InfrastructureFault`, never a substituted skill (**Decision 7**) |

### Environment-level failure facts (authoritative)

- **No pre-transition rejection exists at the env boundary.** `step()` increments
  `world.episode.step_count` on its *first line* (`multi_agent_box_push_env.py:141`) before any
  legality check, and `a.last_action` is written for every agent unconditionally (`:152`).
  Therefore *every* env step changes state, even a wholly failed one.
- **Lone heavy push:** penalty only, no movement (`:222-223`). Note this is backend-infeasible but
  **symbolically *inapplicable*** under the current PDDL, whose `push` carries a `(light ?b)` guard
  (`box_push_domain.pddl` `:action push` precondition) — see §H-3/§H-4. It becomes an optimistic-failure case only under an
  abstraction that drops the weight guard.
- **Blocked light push / blocked move:** no positional change, −0.11 net reward
  (`multi_agent_box_push_env.py:220-221`, `:233-234`).
- **Failure is invisible in `infos`:** `infos` is always `{aid: {}}` (`:145`, `:175`). The *only*
  machine-readable failure signal at the env boundary is the reward scalar.
- **Tandem infeasible:** both agents fall through to Phase B and each fails individually
  (`:198-199` → `:222`/`:220`), so a failed cooperative push still costs a primitive step and a penalty.

### Step definitions to freeze

- **Primitive step:** one `MultiAgentBoxPushEnv.step(actions)` joint transition.
  Counter: `world.episode.step_count`, incremented at `multi_agent_box_push_env.py:141`.
  It is a **joint** counter (one increment per call regardless of agent count), and the episode
  budget is `config.max_steps` (600 in the runner, `box_push_centralized.py::main`), enforced at `:170-172`.
- **Executive step:** **MISSING from the backend — no such concept exists in code** (→ V1: defined by **Decision 2**; the wrapper owns the counter). The runner's `skill_cycle`
  (the `skill_cycle` counter in `box_push_centralized.py::main`) counts *planner calls*, is used only for logging, and is never
  compared against any budget. One executive cycle consumes a variable, effectively unbounded number
  of primitive steps (`cooperate_push` alone may consume ~150).
- **Failed executive call consumption rule:** absent from the code; **now frozen** by
  `P0_V1_DECISIONS.md` Decision 2 — one validated invocation that reaches the executor consumes one
  executive step whether it succeeds or fails; a call rejected before executor invocation consumes
  zero. Primitive steps are counted separately by the wrapper (never from `BaseSkill._steps`).

**Note 4 — livelock:** if the planner assigns `wait` to both agents, `WaitSkill` is `done` at
construction, the inner loop breaks before any `env.step` (`box_push_centralized.py::main`),
`step_count` never advances, truncation can never fire, and the outer loop issues planner calls
forever. The only current guard is prompt text (`:293`). A V1 executive-step budget fixes this
structurally.

---

## D. Complete state contract

### Backend state/export

- **Primary state classes:** `WorldState{agents, objects, static, episode}` in
  `cooperative_search_transport/env/state.py:89-94`; constructed fresh per reset at
  `box_push_env.py:119-125`.
- **Existing full-state export:** **MISSING from the backend.** There is no `state()`,
  `export_full_state()`, `observe()` or `is_terminal()` method on `MultiAgentBoxPushEnv`.
  **→ V1:** the interface is frozen in P0 as `shared/backend_contract.py::V1Environment` and built
  exclusively from `core_env.world` (**Decision 4**); P1 implements it. Ground truth is reachable only
  by attribute access (table below). `get_initial_world_objects()` (`box_push_env.py:133-134`) is
  the only deepcopy accessor and returns *initial* objects only.
- **Coordinate convention:** `grid[x][y]`, x = column, y = row; `DIRECTION_VECTORS` =
  RIGHT(0)=(+1,0), DOWN(1)=(0,+1), LEFT(2)=(−1,0), UP(3)=(0,−1) (`constants.py:31-36`).
- **Stable agent IDs:** `"agent_0"`, `"agent_1"` (`multi_agent_box_push_env.py:54`). Stable across reset.
- **Stable box IDs:** ints `0` (HEAVY) and `1` (LIGHT), keys of `world.objects`
  (`box_push_env.py:79-82`). Stable across steps and resets. **Caveat:** the MiniGrid render objects
  are re-created on every move (`multi_agent_box_push_env.py:351`), so identity must be taken from
  `object_id`, never from grid contents — and the grid carries no identity at all (both boxes render
  as identical `TargetPackage`).
- **Reset semantics:** fully deterministic and **fixed** — boxes always at `(6,6)`/`(8,4)`
  (`box_push_env.py:78-82`), agents always at `(10,10)`/`(10,9)` facing `LEFT`
  (`multi_agent_box_push_env.py:90-91`, `:107-113`). `seed` is accepted and seeds `np_random`
  (`minigrid.minigrid_env:125`, the installed dependency — not a repository file) but **no BoxPush code consumes it** — the seed is observationally inert.
- **Terminal semantics:** `_all_targets_delivered()` (`:370-372`) — all `is_target` objects
  `delivered`. Sets `world.episode.terminated` and all-agent `terminations` (`:165-169`).
- **Truncation semantics:** `step_count >= config.max_steps` (`:170-172`). Both flags can be True
  in the same step.
- **Delivery predicate:** purely positional — `tuple(obj.position) in set(world.static.delivery_zone)`
  (`:242`). **No agent involvement is required**; a box that ends up in the goal column by any means
  is delivered.
- **Deadlock semantics:** **MISSING from the backend.** No deadlock/unsolvable detection exists anywhere in the env. **→ V1: Decision 12** — the frozen instance defines no deadlock, so the `NoPlan` acceptance obligation is met by a purpose-built synthetic instance in P2/P4.
  The only stuck-handling is skill-layer heuristics (`shared_skills.py:242-253 _check_stuck`,
  `skill_executor_push.py:161-168`), which are execution heuristics, not domain semantics.
- **Post-terminal behavior:** `self.agents` is never emptied on termination (contrary to PettingZoo
  convention), so `step()` remains callable and keeps incrementing `step_count`. `AMBIGUOUS` in the backend — **→ V1: Decision 8** refuses post-terminal execution as an `InfrastructureFault`.
- **`reset()` changes the *type* of `world.agents`.** `multi_agent_box_push_env.py:78-79` sets
  `core_env.world.agents = self.agents` (a **list**) in `__init__`; `box_push_env.py:119-125` replaces
  `world` wholesale with `agents={}` (a **dict**) during reset, which
  `multi_agent_box_push_env.py:133-134` then populates. Calling `step()` before `reset()` raises
  `TypeError` at `:151`. The V1 wrapper must enforce reset-before-use, and P1 must test it.

### State variable classification

| Variable | Type/domain | Fluent? | Skills/logic that may modify it | Exact accessor | Evidence |
|---|---|---|---|---|---|
| Agent position | `Tuple[int,int]`, 1..10 interior | yes | `_move_forward`, light push, tandem push | `env.agent_positions[aid]` **and** `world.agents[aid].position` (two copies) | `multi_agent_box_push_env.py:98`, `:204-205`, `:229-230`, `:268` |
| Agent direction | int 0-3 | yes | `_turn_left`/`_turn_right` | `env.agent_dirs[aid]` **and** `world.agents[aid].direction` | `:99`, `:251-259` |
| Agent last action | int 0-3 | yes | every step, unconditionally | `world.agents[aid].last_action` | `:152` |
| Box position | `Tuple[int,int]` | yes | `_set_box_position` (light + tandem push) | `world.objects[oid].position` | `state.py:64`; `:348-351` |
| Box `required_agents` | int, 1 or 2 | **static** | never written after reset | `world.objects[oid].required_agents` | `box_push_env.py:80-81` |
| Box `is_target` | bool (always True) | static | never | `world.objects[oid].is_target` | `box_push_env.py:80-81` |
| Box `delivered` | bool | yes | `_check_delivery` | `world.objects[oid].delivered` | `:243` |
| Delivered count | int | yes | `_check_delivery` | `world.episode.delivered_target_count` | `:244` |
| Episode step count | int | yes | env `step()` | `world.episode.step_count` | `:141` |
| Terminated / truncated | bool | yes | env `step()` | `world.episode.{terminated,truncated}` | `:166`, `:171` |
| Walls | list of cells | **static** | never | `world.static.walls` | `box_push_env.py:88-92`, `:122` |
| Goal zone | list of 10 cells | **static** | never | `world.static.delivery_zone` / `GOAL_ZONE` | `box_push_env.py:39`, `:100` |

**Fields declared but never written by BoxPush** (undefined semantics here, do not model them in V1):
`AgentState.carrying_object_id`, `.active`, `.cooperating`, `ObjectState.carried_by`,
`.engaged_agents` (`state.py:54,55,58,70,73`).

### Canonical StateSnapshot

**Frozen at P0 — implemented in `shared/state_snapshot.py`.** `StateSnapshot{agents, boxes, static,
episode}`, source fields exactly the non-static rows above plus the static
`required_agents`/walls/goal-zone context, with deterministic canonical JSON and sha256 keys.

- `world_key()` covers agents + boxes + static and is the **comparison/bookkeeping** criterion (:88).
- `replay_key()` additionally covers episode bookkeeping; replay/debug only.
- Episode `step_count`/`terminated`/`truncated` are **deliberately excluded** from `world_key()`:
  the predictor predicts a successor world, not how many primitive steps the backend needed, so
  including them would make every predicted-vs-observed comparison mismatch.
- Construction order does not affect the canonical form (agents/boxes/walls/zone are sorted).
- `__eq__`/`__hash__` delegate to `world_key()`, so `==`, `set` and `dict` membership all use the
  same criterion as the explicit call.

**The monitor compares on TWO bases (Decision 13), never on whole `StateSnapshot`s.** A raw
whole-snapshot comparison is the wrong criterion: a successful `GotoPushPose` changes the world
while the symbolic effect adds only `in_pose`, so it would report a mismatch on the happy path.

1. **Symbolic basis** — the monitored subset of the **symbolic projection**
   (`shared/symbolic_state.py`, `domain.box_push_v1.project`). The projection is declared
   non-geometric: `in_pose` is the one predicate that cannot be read from a snapshot by inspection
   (its truth would have to be derived from the pose cell `B−D`), so it is **executive-tracked and
   excluded from the monitored subset**, and maintained instead by
   `ProjectionContract.apply_outcome`. Two snapshots differing only in positions project to the
   same symbolic state — the behavioural proof that no feasibility oracle leaked in
   (`tests/test_symbolic_projection.py`).
2. **World basis** — the deterministic world effect the skill's own success semantics imply,
   declared per skill in `SkillIR.predicted_world_effects` and grounded by the P2 predictor.
   Computing an intended pose cell or landing cell is arithmetic, **not** a feasibility query, and
   is explicitly permitted (Decision 13.2/13.3). This is what preserves `:271` literally rather
   than reinterpreting it.

`ExecutionDiscrepancy` carries a separate, correctly named key pair per basis; a symbolic key is
never written into a `*_world_key` field. Either basis alone can carry a `STATE_EFFECT_MISMATCH`,
and `EXECUTION_FAILURE_OF_APPLICABLE_SKILL` needs neither — the authoritative typed
`ExecutionOutcome` is always available (Decision 13.7). See decisions §14.1 for the coverage each
basis actually provides, which is uneven: the symbolic basis is discriminative for `Push` and
`CooperativePush` only.

The frozen initial state is `domain/box_push_v1.initial_state()`. Drift against the authoritative
backend is detected by `tests/test_backend_freeze_drift.py`, which scrapes `box_push_env.py` and
`multi_agent_box_push_env.py` for the goal-zone literal, both `ObjectState` definitions, the agent
start positions, the joint step counter and the tandem rule, and compares them to the freeze. (It
reads the source text rather than importing, so it stays offline and dependency-free.) That test
was verified to fail when the backend's `GOAL_ZONE` is edited. **The snapshot must be built from `world`, not from `core_env.grid` and not from the
belief layer** — see §F for why both are unsound. Nothing in `shared/` or `domain/` may import the
backend; enforced statically by `tests/test_no_backend_imports.py`.

---

## E. Agents and V1 sequential rule

- **Number of agents:** 2 (`EnvConfig.num_agents` default 2, minimum 2 enforced, `state.py:42-48`;
  runner uses 2 at `box_push_centralized.py::main`).
- **Backend action semantics:** PettingZoo `ParallelEnv` — `step()` takes a **joint dict** for all
  agents simultaneously (`multi_agent_box_push_env.py:140`); missing agents default to `STAY` (`:147`).
- **Resolution order within a joint step is NOT simultaneous:** turns for all agents (`:150-156`),
  then Phase A tandem pushes (`:186-209`), then Phase B individual movers **in `self.agents` list
  order against already-mutated state** (`:212-234`), then delivery (`:162`). Outcomes are therefore
  order-dependent — e.g. `agent_1` can move into a cell `agent_0` just vacated, but not vice versa.
- **V1 executive sequential rule:** **MISSING from the backend — → V1: frozen by Decision 1.** One executive step issues exactly one grounded skill invocation; `CooperativePush` is a single sequential executive skill that internally coordinates both agents. Original audit finding follows. The current runner is
  *concurrent*: one planner call assigns a skill to both agents, and both skills advance on every
  primitive step (`box_push_centralized.py::main`). A strictly sequential executive rule would be a
  behavior change; a "joint executive decision" reading matches the code as it stands.
- **Joint skill treatment:** `cooperate_push` is emergent, not an explicit joint action. Both agents'
  skills independently return `MOVE_FORWARD` and the env's tandem rule matches them
  (`_find_tandem`, `:312-328`). **Nothing enforces that both agents receive `cooperate_push` in the
  same cycle** — the requirement exists only as prompt text (`box_push_centralized.py:271-278`).
  If only one agent gets it, it finishes `waiting_partner` after `_WAIT_LIMIT=10` (`:344-350`).

---

## F. Observation contract

> **→ V1: the observation contract is frozen in `shared/observation.py`.** Four channels —
> `PUBLIC_EXECUTION_RESULT`, `EXACT_STATE`, `BACKEND_LOCAL_OBSERVATION`, `DEBUG_FULL` — with a
> `Track → channels` visibility matrix (`V1_VISIBILITY`) and an `is_visible` predicate. Under
> Decision 5 the V1 NL track reads `EXACT_STATE` (typed data), **not** the belief grid, so it does
> not inherit the rendered-grid defects deferred by Decision 9. The audit text below records the
> pre-freeze situation and is retained as evidence.

| Information | Backend produces? | Public execution result? | Symbolic track visibility (V1) | NL track visibility | Debug/eval only? | Evidence |
|---|---|---|---|---|---|---|
| terminal skill label | yes (skill layer) | yes — the only executive feedback | should be typed execution result | currently injected as prose | no | `box_push_centralized.py::main` |
| local observation | yes — **3×3 egocentric, occluded** | raw MiniGrid dict `{image, direction, mission}` | **not used in V1** | current belief input | no | `multi_agent_box_push_env.py:357-364`; `agent_view_size=3` (`:328`) |
| exact full state | yes, **attributes only** | no | **yes in V1 after normalization** | policy-defined typed view | — | `world` (§D); no export method |
| primitive-step detail | partially (rewards) | no | optional trace | optional summary | debug | `infos` always empty (`:145`) |
| failure reason | **no** | reward scalar only | must be derived by the wrapper | — | — | `:145`, `:175` |

**Critical:** the current skill layer does **not** consume exact state. It consumes a belief grid
built by `middleware_layer/belief_updaters/deterministic_grid_updater.py`, in which:

- **agent position is dead-reckoned from the reward signal**, not observed
  (`deterministic_grid_updater.py:287-308`, success threshold `reward > -0.06` at `:56`);
- **agents are written into the belief grid as `"empty"`** (`:215-220`), so the `"agent"` labels in
  `skill_executor_push.py:36` `_BLOCKING` and `:60` `_nav_blocked` are effectively dead except for the
  manual partner injection at `:360-364`.

Both are **legitimate V1 discrepancy sources** and must stay in the backend, but they mean the V1
symbolic adapter must read `world` directly and bypass the belief layer entirely. Keep the belief
machinery for later partial-observation milestones (per the V1 scope rule); do not delete it.

**The reward channel is multiplexed and is therefore structurally invalid as a move-success
observable.** One scalar carries: `-0.01` per step (`multi_agent_box_push_env.py:142`), `-0.1`
move-fail (`:221`, `:223`, `:234`), `+0.1` light push (`:232`), `+0.2` joint push (`:207`), `+20`
delivery (`:248`), `+10` completion **to every agent** (`:168-169`). Provable corruption: on the
terminal step an agent whose `MOVE_FORWARD` failed receives `-0.01 - 0.1 + 10 = +9.89`, far above the
`-0.06` success threshold (`deterministic_grid_updater.py:56`), so the belief layer advances a
position that did not move. `_check_delivery` compounds this with `for aid in (pushers or self.agents)`
(`:245-248`), paying +20 to everyone when no agent is adjacent. This is the hard evidence that V1
must not derive state from rewards.

**Belief-sharing fragility:** `box_push_centralized.py::main` aliases one `shared_grid` object into
both agents' updaters, but `DeterministicGridUpdater.reset()` (`:153-159`) rebuilds `_grid` from
`_initial` — so calling `reset_belief()` silently un-shares the team map. P1 must pin this with a
reset test.

---

## G. Tasks and goals

### Task input format

The backend has only the mission string `"push all target boxes onto the goal zone"`
(`box_push_env.py:75-76`). **Frozen at P0 — `shared/task.py`:** `Task{task_id, description,
goal_delivered: tuple[BoxId], zone}` carries both the text form the NL track interprets (:169) and
the typed goal the symbolic track plans against, so a translator residual can be computed between
them. Representative instances are `domain/box_push_v1.TASKS`
(`deliver_both`, `deliver_light`, `deliver_heavy`).

### Goal / success condition

All `is_target` boxes `delivered`, i.e. each box position ∈ `GOAL_ZONE = [(1,y) for y in 1..10]`
(`box_push_env.py:39`; `_all_targets_delivered` `:370-372`). Delivery is positional only (`:242`).

### Failure / termination conditions

Truncation at `step_count >= max_steps` (600 in the runner). No deadlock detection, no failure
terminal state. An unsolvable configuration simply truncates.

### Costs and hard prohibitions

- Default skill cost: **1** (supervisor default; the backend has no skill-level cost model).
- Non-unit costs: **none defined**. Note the *reward* model is not a cost model and must not be
  confused with one: `-0.01`/step, `-0.1` move-fail, `+0.1` light push, `+0.2` joint push,
  `+20` delivery, `+10` completion (`multi_agent_box_push_env.py:37-41`).
- Hard prohibitions established by code: only actions 0-3 are exposed
  (`action_space` → `Discrete(4)`, `:82-85`); actions 4/5/6 are silently ignored if submitted — **→ V1: Decision 7** by extension (decisions §7.1); they are not executive skills.

---

## H. Representative task instances

All five are expressed against the **frozen fixed layout**: 12×12, outer wall only, goal column
`x=1` rows 1-10, `box_0` HEAVY at `(6,6)`, `box_1` LIGHT at `(8,4)`, `agent_0` at `(10,10)`,
`agent_1` at `(10,9)`, both facing `LEFT`.

1. **Normal light-box success** — `agent_0`: `goto_push_pose [8,4]` → `in_position`, then
   `push [1,4]` → `delivered`. Exercises the deterministic success path and prediction match.
2. **Cooperative heavy-box success** — both agents `cooperate_push [6,6]` in the same cycle; the skill
   self-navigates to tandem slots `B−D` and `B−2D`, then joint `MOVE_FORWARD` → `delivered`.
3. **Symbolically applicable but backend-infeasible** — the cleanest case is **`push(a1, box_1)` on the
   LIGHT box**. The PDDL action is applicable (`in-pose ∧ light ∧ pending`, `box_push_domain.pddl` `:action push` precondition)
   and its effect is `delivered` in **one** symbolic action, with no grid, no distance and no path
   model. The backend must actually push the box cell-by-cell from `(8,4)` across `x=7…1`
   (`PushSkill.step`, `skill_executor_push.py:199-233`), and any obstruction — the other box, the
   partner agent, a wall — yields `blocked`/`too_heavy` **after the box has already moved several
   cells**. This is simultaneously the optimistic-failure case and the partial-execution case.
   A second instance is the PDDL plan's own `goto_push_pose a1 box0; goto_push_pose a2 box0` pair,
   which targets one cell twice — see §J-3.
4. **Symbolically inapplicable call** — `push(a1, box_0)` on the HEAVY box: the PDDL precondition
   `(light ?b)` fails (`box_push_domain.pddl` `:action push` precondition), so the symbolic track must reject it *before*
   execution. Note the backend has a matching real failure label (`too_heavy`,
   `multi_agent_box_push_env.py:222-223`), so this doubles as the evidence case that symbolic
   inapplicability and backend infeasibility are **different** rejections and must be reported
   through different channels. A second, purely backend-level instance: `push` with no box in front
   → `blocked` on the first `step()` (`skill_executor_push.py:224-225`).
5. **Malformed call** — planner emits `"I think we should push the box"`; `_skill_parser` fails the
   `re.match` skill-token test and returns `("explore", None)` (`box_push_centralized.py::_skill_parser`).
   **→ V1: this is forbidden.** A malformed call becomes a typed `MalformedCall` rejection
   (**Decision 7**), never a silently substituted skill. Frozen in
   `shared/skills.py::MalformedCall`; the P3 removal of the runner's `explore` fallback is a
   scheduled work item (decisions §18 item 9).

**`NoPlan` case:** available at the symbolic level — remove `(different a1 a2)` from the problem, or
mark a heavy box `pending` with only one agent object, and the classical planner returns no plan.
Not reachable from the current runner, which has no planner.

---

## I. Acceptance trace template

### Trace: `optimistic_light_push` (the canonical optimistic-failure trace)

- Task: deliver `box_0` (heavy) and `box_1` (light) to the goal column.
- Initial canonical state: as §H.
- Symbolic plan/result:
  `PlanFound([GotoPushPose(a0,box_1,z), Push(a0,box_1,z), GotoPushPose(a0,box_0,z),
  GotoPushPose(a1,box_0,z), CooperativePush((a0,a1),box_0,z)])` under
  `domain/box_push_v1.py::DOMAIN_IR`, where `Push` delivers in one action with no path model.
  **No `Explore` step:** V1 is fully observable from initialization, so `Explore` is not in the
  symbolic action set (**Decision 5**) and a call to it resolves to `OutsideSymbolicModel`
  (**Decision 15**). The legacy `.soln`'s two leading `explore` steps are superseded.

| Executive step | Pre-state | Grounded skill | Symbolically applicable? | Prediction | Backend result | Post-state | Failure state class | Primitive steps | Executive step consumed? | Report / orchestrator consequence |
|---:|---|---|---|---|---|---|---|---:|---|---|
| 1 | `a0@(10,10) dir LEFT`, `box_1@(8,4)` | `GotoPushPose(a0, box_1, delivery_zone)` | yes | symbolic: `in_pose(a0,box_1)` (executive-tracked). world (**Decision 13.3**, P2): `a0@(9,4) dir LEFT` | raw `in_position` → typed `success` | `a0@(9,4) dir LEFT` | — | ~7 | **yes — 1** | both bases agree → no report. Note the symbolic basis is **vacuous** here: `in_pose` is excluded from the monitored subset, so success and failure project identically. The world basis is what discriminates (decisions §14.1) |
| 2 | `a0@(9,4)`, `box_1@(8,4)` | `Push(a0, box_1, delivery_zone)` | yes | symbolic: `delivered(box_1)`. world: `box_1@(1,4)`, `a0@(2,4)` | raw `blocked`/`too_heavy` → typed `partial` or `failure`; or `delivered` | e.g. `box_1@(5,4)`, `a0@(6,4)` — **box moved 3 cells, then failed** | **partial execution with changed state** | up to 30 | **yes — 1** | `ExecutionDiscrepancy(state_effect_mismatch + execution_failure_of_applicable_skill)`, `mismatched_bases = (world_state, symbolic_projection)` → orchestrator replans from the *actual* post-state. **Must not add a path/reachability oracle to symbolic applicability** — predicting the landing cell is an effect, not a feasibility query (**Decision 13.2/13.3**). |

### Trace: `symbolically_inapplicable` (contrast case)

| Executive step | Pre-state | Grounded skill | Symbolically applicable? | Prediction | Backend result | Post-state | Failure state class | Primitive steps | Executive step consumed? | Report / orchestrator consequence |
|---:|---|---|---|---|---|---|---|---:|---|---|
| 1 | `a0@(7,6)`, `box_0@(6,6)` HEAVY | `Push(a0, box_0, delivery_zone)` | **no** — `(light box_0)` fails (`box_push_domain.pddl` `:action push` precondition) | none — never executed | *(not issued)* | unchanged | rejected pre-execution | 0 | **no — 0** | symbolic rejection; **not** an `ExecutionDiscrepancy`. If the NL track proposed it, that is a `TrackDivergence`. Backend's own `too_heavy` (`multi_agent_box_push_env.py:222-223`) is the separate case that arises only if the call *is* executed. |

Remaining traces (`cooperative_success`, `malformed_call`, `no_plan`) are to be recorded during
P1/P2 against the real wrapper, not hand-written now.

---

## J. Existing planner/domain assets

1. **PDDL classical domain — SUPERSEDED FOR V1; reference only.** `pddl/box_push_domain.pddl`
   (STRIPS+typing) encodes the *skills as actions* with no grid and no coordinates, which is the
   right shape and is why `domain/box_push_v1.py::DOMAIN_IR` was modelled on it. But the files
   themselves must **not** be planned against: they lack the `zone` parameter (Decision 11), still
   declare `explore` (Decision 5), and use object identifiers that do not parse
   (`BoxId.parse("box0")` raises). The recorded 7-step `.soln` opens with two `explore` steps that
   are no longer in the action set. All four artifacts now carry a `;; SUPERSEDED FOR V1` banner;
   P2 **re-issues** them from `DOMAIN_IR` (decisions §18 item 1). The strongest P2 asset in the
   repository is the frozen IR, not these files.
2. **RDDL factored MDP — partial IR candidate.** `rddl/box_push_skills.rddl` models the same skills as
   concurrent action fluents with `KronDelta` (deterministic) transitions plus a reward model and a
   `weight-known` discovery fluent. It is closer to the supervisor's "structured skill IR with later
   probabilistic extension" than the PDDL is. **Not yet** in the typed-IR form P0 must freeze
   (no explicit provenance/version metadata, no observation block, no per-skill cost field).
3. **Known abstraction mismatches (keep them — they are the designed discrepancy sources).**
   - **`in-pose` has no geometry.** `GotoPushPoseSkill` navigates to the single cell `B−D`
     (`skill_executor_push.py:150`), so `goto_push_pose a1 box0` and `goto_push_pose a2 box0` — both
     present in the verified `.soln` — target the **same cell**, which two agents cannot occupy.
     Meanwhile backend `cooperate_push` does its **own** slot navigation to `B−D`/`B−2D` (`:272-283`),
     making the preceding `goto_push_pose` calls unnecessary.
   - **`in-pose` is non-exclusive.** `box_push_domain.pddl` `:action goto_push_pose` adds `(in-pose ?a ?b)` and deletes
     nothing, so one agent can be in pose for *both* boxes simultaneously — and the verified plan does
     exactly that (`box_push_problem.pddl.soln`: the consecutive `(goto_push_pose a1 box1)` and
     `(goto_push_pose a1 box0)` steps, one agent in pose for both boxes). In the backend an agent occupies one cell. This is the cleanest
     scenario-#2 instance in the domain.
   - **`goto_push_pose` has no reachability model.** Its only preconditions are
     `(discovered ?b) ∧ (pending ?b)` (`:action goto_push_pose`), yet the backend returns `blocked` when the partner
     occupies the pose or the route freezes (`skill_executor_push.py:161-168`). This is the textbook
     optimistic-`Navigate` case the contract describes.

   Expect `ExecutionDiscrepancy` from all three; **do not "fix" them by teaching the symbolic model
   geometry, exclusivity, or reachability.** Adding the `in-pose` delete effect *after* observing a
   failure would specifically violate the "do not silently strengthen the symbolic model" rule — if
   it is added, it must be a deliberate, documented P0 decision — **→ V1: Decision 6** keeps `in-pose` optimistic and NON-exclusive, deliberately.
4. **Environment pathfinding/search helpers — classified as BACKEND EXECUTION, not symbolic oracles.**
   The BFS helpers all operate on the *belief* grid inside skill execution and are themselves
   optimistic (`_bfs_avoid_boxes` treats `"unknown"` as passable, `skill_executor_push.py:65`), so
   they cannot function as feasibility oracles today.

   **The real oracle temptations are the exact ground-truth predicates in the env**, ranked by danger.
   Each is a one-line call that would make symbolic applicability *exactly correct* and destroy the
   intended discrepancy:

   | Function | Location | Why it is a trap |
   |---|---|---|
   | `_cell_free_for_box` | `multi_agent_box_push_env.py:296-310` | Exact "can the box land here". Wiring it into `push` applicability deletes scenario #2 for single pushes. |
   | `_tandem_feasible` | `:330-346` | Exact precondition for the joint heavy push; removes the only nontrivial cooperative discrepancy. |
   | `_find_tandem` | `:312-328` | Exact formation checker; turns `cooperate_push` applicability into backend simulation. |
   | `_is_free_for_agent` | `:272-286` | Exact occupancy oracle; makes `goto_push_pose` position-aware and deletes its `blocked` discrepancy. |
   | `_bfs_avoid_boxes` | `skill_executor_push.py:63-88` | The P1 adapter DOES feed it the exact grid — deliberately, as the recorded Decision 16 obligation-4 resolution: exact navigation **inside execution** is legal (Decision 6 governs applicability). The trap this row guards is unchanged for the SYMBOLIC side: applicability/planning must never reach it, and the import guard makes that structural. |
   | `_push_dir_toward_goal` | `:39-47` | Manhattan-nearest goal cell then an axis choice. **Permitted for effect grounding** (Decision 13.3) — it consults no walls, no occupancy and no search. Still forbidden in *applicability*: a precondition may not depend on it. |
   | `_nearest_undelivered_target` | `:98-107` | Already used as a *silent* re-grounding oracle (§B-consistency-8). |

   **Required guard:** put the symbolic package behind an import boundary that cannot reach
   `functional_layer.custom_env.box_push.env.*` or `shared_skills`, and enforce it with a **static**
   no-backend-import test, not only a behavioral one.

5. **Legacy code that must NOT be adopted as a V1 component** (classify explicitly so an implementer
   does not reach for the nearest-looking thing):
   - `middleware_layer/action_executor.py:48-52` — `execute_action` returns
     `{"action": …, "valid": True, …}` **without ever calling `env.step()`**: a hardcoded success
     report. `middleware_orchestrator.py:185` clamps out-of-range actions into range before it.
     Both are the malformed-becomes-valid antipattern. Reachable only via
     `MiddlewareOrchestrator` (`:193`), which the BoxPush runner never calls — it is dead on this
     path. **Do not use as the P1 executor.**
   - `middleware_layer/middleware_orchestrator.py:10 MiddlewareOrchestrator` — despite the name, this
     is a per-agent prompt/belief helper, **not** the contract's track orchestrator. Reusing the name
     in P4 will actively mislead.
   - `box_push_per_step.py:246-261` — exposes `MOVE_FORWARD`/`TURN_LEFT`/… as the planner's decision
     vocabulary, which the project rules prohibit at the executive level. **Legacy, out of V1 scope.**
   - `cooperative_search_transport/env/obs_parser.py:112-140 parse_cst_obs` — indexes the view as
     `image[depth][lateral]` while `shared_skills.py:54-60` and
     `deterministic_grid_updater.py:170-181` use `image[lateral][depth]`. At `agent_view_size=3` the
     centre cell coincides so `front_center` is accidentally correct, but `front_left`/`front_right`
     and `rel_ahead`/`rel_side` are transposed. Fix or delete before the NL track consumes them.
6. **Prose domain docs** (`BoxPush_Centralized_POMDP.md`, `BoxPush_Skill_PDDL_RDDL.md`,
   `box_push_problem_description.md`) — background only; the PDDL/RDDL header comments state they were
   derived from the description, not from the code, so **the code overrides them** wherever they differ.

---

## K. P0-P4 gap summary

| Phase | Ready inputs | Missing / blocked items | Evidence |
|---|---|---|---|
| **P0** | — | **COMPLETE.** Frozen typed contracts in `shared/` + `domain/box_push_v1.py`; executive runtime state in `runtime/`; 400 offline tests | `shared/{state_snapshot,symbolic_state,comparison_keys,skills,skill_ir,execution,planner_result,discrepancy,divergence,faults,reports,task,observation,trace_schema,orchestration_config,versioning,backend_contract}.py`; `domain/box_push_v1.py`; `runtime/executive_history.py`; `tests/` (14 modules, 400 tests) |
| **P1** | — | **COMPLETE.** `functional_layer/custom_env/box_push/env/box_push_v1_adapter.py::BoxPushV1Adapter` implements the frozen `V1Environment` protocol over the real backend: `world → StateSnapshot` normalization (D4, world-only — behaviourally pinned by grid-vandalism and cache-desync tests); authoritative typed outcome derived from world with the headline-0 `too_heavy`-vs-`blocked` re-derivation in `detail` (D3); explicit typed TIMEOUT from the backend budget (D3); per-attempt `env.step()` counter cross-checked against the joint `step_count` (D2); exhaustive dispatch on `backend_dispatch_key`, no fallback, `make_skill` never called (D14/D16); identity-only pre-flight + per-skill post-flight substitution faults with the result attached (D16); reset-before-use and post-terminal refusal via `InfrastructureFaultError` (D8); `CooperativePush` as ONE executive invocation owning both instances (D1). 47 integration tests in `tests/test_p1_adapter.py`; 30/30 targeted adapter mutations killed (`docs/implementation/p1_mutation_harness.py`) | The runner-faithful drive loop submits a finishing skill's terminal STAY, so a backend-rejected attempt costs 1 primitive step; belief/middleware machinery untouched and unused (AST-pinned) |
| **P2** | — | **COMPLETE.** `symbolic/` (7 modules): declarative applicability + the ONE deterministic successor (`applicability.py` — literal membership only, geometry cannot reach it); exact-state belief with Decision 13.8 outcome maintenance incl. the consuming-skill retention rule (`belief.py`); deterministic BFS planner returning the 3-way `PlannerResult` with typed budget exhaustion → `PlannerFailure(timed_out=True)` and `except Exception` → `PlannerFailure` (`planner.py`); world-effect predictor grounding `SkillIR.predicted_world_effects` on clause-9 bounded inputs, partial by design on ray miss (`predictor.py`); monitor over BOTH comparison bases with clause-7 outcome-only failure reports (`monitor.py`); deterministic PDDL re-issue from `DOMAIN_IR` byte-pinned to the checked-in `_v1` artifacts + `.soln` from the deterministic planner with `pyperplan` validity cross-check (`pddl_gen.py`, decisions §18 item 1 CLOSED); synthetic `NoPlan` instance (`synthetic.py`, Decision 12). Guards: four import escape routes + predictor input bound (`tests/test_p2_symbolic.py::TestSymbolicSideGuards`). 69 tests (53 unit/guard + 9 PDDL + 7 live acceptance incl. the flagship plan→execute→monitor→replan story with the designed `ExecutionDiscrepancy` and the demonstrated consuming-skill livelock + recovery); 50/50 targeted mutations killed (`docs/implementation/p2_mutation_harness.py`, incl. the VA/L series added by the V1-acceptance and consistency rounds). The `/acceptance-test` deliverable sits on top: `tests/test_v1_acceptance.py` (10 tests — six supervisor cases as `TraceEntry`-recorded live cycles) + `docs/implementation/acceptance_traces.md` (human-readable traces, regenerated live and byte-pinned by `TestTraceDocumentPinned`) | Decisions §19.1 records the P4-binding discoveries (livelock, `CallValidation` gating, belief-not-reprojection monitor wiring, monitor `ValueError`→fault wrap, ghost-identity routing order) |
| **P3** | — | **COMPLETE.** `nl/` (12 modules): offline LM seam with typed recorded fixtures and typed fixture-miss error (`seam.py`, decisions §18 item 3 CLOSED); pinned temperature-0/cache-on runtime (`runtime_config.py`) with the live DSPy binding on the legacy side only (`model_layer/planner/v1_nl_live.py`, consumed solely by the MAAOS_LIVE_LM=1-marked `tests/test_p3_live_lm.py`); strict typed parser on the frozen call rendering — `MalformedCall`, never substitution (`parser.py`, §18 item 9 CLOSED via replacement+pinned banner); TaskInterpreter with a verb+object+no-negation coverage classifier and explicit residuals (`task_interpreter.py`); ObservationInterpreter with backend-pinned direction words, provenance-blind (`observation_interpreter.py`); exact-rederived bounded semantic belief (`semantic_belief.py`); SkillSelector + one-attempt RepairSkillCall through the seam with request CONTENT golden-pinned (`skill_selector.py`, `repair.py`); Translator deriving the symbolic action set from the frozen registry, residual for Explore/Wait (`translator.py`); RecoveryProposer answering the §19.1 livelock with re-establishment, never inventing skills (`recovery.py`); stub `NLTrack` peer with the exactly-one-of `NLProposal` and observe-before-propose precondition (`track.py`). Guards: `nl/` auto-covered by the fail-closed import guard (no backend/dspy/runtime), bidirectional nl↔symbolic isolation, AST provenance ban incl. `primitive_steps` + getattr/string evasions, closure-based no-dspy scan over default test modules. 51 offline tests; 37/37 targeted mutations killed (`docs/implementation/p3_mutation_harness.py`); `requirements.txt` pinned exactly (§18 item 2 CLOSED) | Both P3 adversarial reviews addressed to 0 outstanding: architecture 0 FAIL / 5 WARN (all five fixed), test review 5 FAIL / 7 WARN / 5 NOTE (all FAIL/WARN fixed, Q-series mutation-pinned) |
| **P4** | Runner loop shape as reference only | Track comparator, three typed report channels, symbolic-primary + advisory policies, executive loop manager, `NoPlan` vs `PlannerFailure` routing, policy-independent executor, `InfrastructureFault` short-circuit, repeated-failure bookkeeping, executive step budget, trace/history; **case-(c) budget charging**: `TraceEntry`/`ExecutiveHistory` accessors report RECORDED accounting only (lower bounds), so the loop must charge mid-execution-fault attempts (one executive step + the `primitive_steps_before_failure` from fault detail) from fault provenance on top of the sums; and DECIDE whether case-(c) attempts feed repeated-failure counts (currently they do not — faults escalate via `faults_since`, failures via `failure_count`; make that a recorded decision, not an accident) | current runner has no typed results, no retry/failure bookkeeping, and no exception handling (`box_push_centralized.py` has no `try/except`) |

### Ordered implementation dependencies

**Tier 0 — CLOSED.** Every gating decision is frozen in `docs/decisions/P0_V1_DECISIONS.md`
(Decisions 1-16, all FINAL): §L-8 → Decision 5, §L-2 → Decision 1, §L-1 → Decision 2,
§L-9 → Decision 6, §L-10 → Decision 3 + 11, signature alignment → Decision 11 + 14.

**Tier 1 — P0 artifacts: COMPLETE.** `StateSnapshot` normalized **exclusively from `core_env.world`**
with deterministic serialization/hash; the symbolic projection; `PlannerResult`; the three report
channels; trace schema; model version/provenance; the `V1Environment` interface. 400 offline tests.

**Tier 2 — P1 wrapper** — **COMPLETE (see the P1 roadmap row)**. Original scope, in this order of importance:
   1. **the headline-0 fix** — derive `too_heavy` vs `blocked` from `world` (`required_agents` plus
      actual post-transition state), never from `entities["grid"]`;
   2. `world`-only snapshot plus a `world`↔`grid` consistency assertion (§L-7);
   3. a real per-attempt `env.step()` counter (**not** `BaseSkill._steps`, §C caveat);
   4. reset-before-use enforcement (§D) and the belief-sharing reset test (§F);
   5. typed rejection of malformed/ungrounded calls; delete the `_resolve_box` silent fallbacks;
   6. round-trip serialization and deterministic transition tests — **the first tests in the repo.**

**Tier 3 — P2 symbolic track** — **COMPLETE (see the P2 roadmap row)** on `DOMAIN_IR` (re-issuing the PDDL from it), with `PlannerResult`
routing and the world-effect predictor. The **static no-backend-import guard (§J-4) already exists**
(`tests/test_no_backend_imports.py`, package-discovering and fail-closed). Scenario #2 must be
`goto_push_pose → blocked` and/or the non-exclusive `in-pose` case, **not** the lone heavy push:
under Decision 5 the lone heavy push is symbolically *inapplicable* (the `(light ?b)` guard), which
makes it scenario #4, not #2.

**Tier 4 — P3 NL track** — **DONE.** The offline seam that blocked this tier exists
(`nl/seam.py`; live binding at `model_layer/planner/v1_nl_live.py`); the legacy
`CentralizedDSPyPlanner.configure_ollama` path is unchanged and superseded for V1.

**Tier 5 — P4 orchestrator/executive loop** — requires P1+P2+P3 interfaces. Owns the **executive**
budget; §C note 4 proves a primitive budget cannot bound the loop.

**Critical path (remaining): `P4` only.** Tiers 0-4 are DONE (see the roadmap rows above):
the headline-0 label fix landed in P1 (authoritative typed outcomes with raw labels demoted to
provenance), P2 delivered the symbolic track, and P3 the NL track. What remains is the
orchestrator/executive loop and its report-channel consumers.

### "Do not change" list — reusable backend behavior

- The env transition core: `_resolve_pushes`, `_find_tandem`, `_tandem_feasible`, `_check_delivery`,
  `_all_targets_delivered` (`multi_agent_box_push_env.py:178-346`, `:370-372`). This is the
  authoritative execution semantics.
- The composed skill implementations in `skill_executor_push.py` and `shared_skills.py` — wrap them,
  do not reimplement them. **One explicit exception at the wrapper boundary, not in this file:** the
  terminal label must be *re-derived* from `world` (headline 0), because `PushSkill`'s belief-based
  `blocked`/`too_heavy` inference (`:218-221`) is not authoritative. Override the label in the V1
  wrapper; do not edit the skill's navigation or push behavior to achieve it.
- All BFS/frontier/nearest-target helpers (§J-4) — keep them **inside execution**.
- The partial-observation belief stack (`middleware_layer/belief_updaters/`) — preserve for later
  milestones; V1 bypasses it rather than deleting it.
- The fixed deterministic layout (`box_push_env.py:78-82`, `multi_agent_box_push_env.py:90-91`) —
  it is what makes V1 reproducible.

---

## L. Decisions requiring explicit user/supervisor resolution

Genuine ambiguities only — items the code *and* the contract together do not determine.

> **Resolution status: ALL ELEVEN ITEMS ARE CLOSED.** They are frozen in
> `docs/decisions/P0_V1_DECISIONS.md` (**FINAL**). That document is authoritative for V1 semantics;
> this section is retained as the evidence record of *why* each item was ambiguous in the code.
> Item 4 is closed by that document §7.1, item 11 by Decision 12 (synthetic `NoPlan` instance deferred
> to P2/P4, not blocking P0), and item 10 by Decision 11 (`Push` is push-to-zone). Remaining
> engineering tasks are listed there in §18 as work items, not as open questions.
>
> Four further decisions were added after the P0 consistency audit and are also FINAL:
> **Decision 13** (prediction/monitoring boundary — effects may be predicted on both a world and a
> symbolic basis; applicability may not use feasibility oracles; `in_pose` is outcome-tracked
> without exclusivity), **Decision 14** (frozen `backend_dispatch_key` per skill, exhaustive P1
> dispatch with no fallback) and **Decision 15** (`OutsideSymbolicModel` as a fourth typed
> validation result) and **Decision 16** (the P1 adapter translates backend arguments explicitly
> per skill; the legacy overloaded coordinate slot is never filled generically). They close audit
> findings rather than §L items.

1. **Executive-step consumption.** No executive-step concept exists in code (§C). Decide: (a) does one
   attempted grounded skill = one executive step regardless of primitive cost? (b) does a *failed*
   attempt consume one? (c) does a rejected-before-transition call (`none_known`, first-step `blocked`)
   consume one? (d) is the V1 episode budget counted in executive steps, primitive steps, or both?
   **Blocks:** trace schema, executive loop manager, repeated-failure bookkeeping.
2. **Sequential vs joint executive rule.** The V1 assumption says "deterministic sequential executive
   decisions", but the backend is a `ParallelEnv` and `cooperate_push` is *only* achievable when both
   agents act in the same primitive step (`_find_tandem` requires two simultaneous `MOVE_FORWARD`s).
   Decide whether V1's executive step issues **one joint decision for both agents** (matches the code)
   or **one agent at a time** (would require redefining `cooperate_push` as a single-executive-skill
   joint macro that internally drives both agents). Recommend the joint-decision reading, since the
   contract already permits "a high-level joint skill may internally coordinate multiple agents".
3. **Timeout labelling.** `PushSkill` reports budget exhaustion as `pushed` — a success label
   (`skill_executor_push.py:226-228`). Decide whether V1 (a) adds a distinct `timeout`/`partial` label
   at the wrapper boundary, or (b) preserves current labels and records exhaustion separately in the
   execution result. This is a backend-semantics change either way, so it needs explicit approval.
4. **Actions 4/5/6.** `action_space` is `Discrete(4)` but `step()` silently ignores 4/5/6 rather than
   rejecting them (`multi_agent_box_push_env.py:147-234`). Decide whether the V1 wrapper rejects
   out-of-space actions as `InfrastructureFault` or preserves the silent no-op.
5. **Post-terminal stepping.** `self.agents` is never cleared, so the env keeps stepping after
   `terminated` (§D). Decide whether the V1 wrapper hard-stops at terminal.
6. **Target OS/CI and dependency pinning.** Not established anywhere in the repo (§A).
7. **Whether the known grid-desync artifacts are in scope for V1.** `_set_box_position` overwrites
   `DeliveryTile`s with `None` (`:348-351`), and a tandem push transiently erases A1's marker before
   later agents generate observations (`:200-209` vs `:357-364`). These corrupt the *rendered/observed*
   grid but not `world`. Since V1 reads `world`, they are harmless to the symbolic track — but they do
   affect the NL/belief track. Note `custom_get_frame` (`:57-75`) rewrites all markers, so calling
   `render()` incidentally repairs the grid — rendered and headless runs can diverge in
   `core_env.grid` contents. Decide whether P0-P4 fixes them or documents and defers them.
8. **Full observability vs. `explore` and weight discovery — the deepest ambiguity.** The contract
   (`SUPERVISOR_P0_P4_CONTRACT.md:167`) mandates exact, fully observable symbolic state. Under that
   reading `(discovered ?b)` is true from the start — yet `box_push_problem.pddl` `(:init … (unexplored box0) (unexplored box1))` initialises both
   boxes `(unexplored …)`, `explore` is a first-class skill, and the whole runner is built around
   discovery. **Either `explore` leaves the V1 executive vocabulary, or `discovered`/`weight-known`
   are retained as epistemic fluents, which reintroduces partial knowledge into symbolic state.**
   This decision also selects `box_push_domain.pddl` (known weights) vs
   `box_push_domain_fond.pddl` (discovery-by-pushing) as the frozen V1 model — and therefore decides
   whether the lone heavy push is scenario #2 or scenario #3 (§H-3/§H-4). **Blocks the skill registry,
   the initial state, and the acceptance-scenario mapping.**
9. **Is `in-pose` exclusive?** The frozen PDDL says no (`box_push_domain.pddl` `:action goto_push_pose`); the backend says
   yes (one agent, one cell). Leaving it non-exclusive is a legitimate optimistic abstraction that
   yields the cleanest scenario-#2 case; making it exclusive strengthens the symbolic model. Either is
   defensible, but it must be decided **up front and documented** — adding the delete effect after
   observing a failure is exactly the prohibited silent strengthening.
10. **Semantics of `pushed`.** The backend uses it both for "box reached the caller-supplied `dest`"
    (`skill_executor_push.py:214-215`) and for "budget exhausted mid-push" (`:226-228`), while the
    symbolic `push` has no intermediate outcome at all (`box_push_domain.pddl` `:action push` effect). Deciding whether
    V1's `push` is *push-to-goal* (matches PDDL) or *push-to-cell* (matches backend) changes the
    argument type, the effects, and the label set. Related to §L-3.
11. **Does the frozen instance admit a deadlock / `NoPlan` case?** The contract asks for one "if the
    domain defines one" (`:267`). On the current open 12×12 arena with a full left goal column and
    boxes at `(6,6)`/`(8,4)`, no deadlock configuration was found. Decide whether V1 adds a harder
    instance (e.g. a box in a corner) specifically to exercise `NoPlan`, or whether the `NoPlan`
    acceptance case is satisfied symbolically only (§H).
---

## Audit provenance

- Files read directly during this audit: `skill_executor_push.py` (full), `box_push_schema.py` (full),
  `box_push_env.py` (full), `multi_agent_box_push_env.py` (`:44-135`, `:136-255`, `:310-374`),
  `shared_skills.py` (`:205-311`), `box_push_centralized.py` (`:296-345`),
  `pddl/box_push_domain.pddl`, `pddl/box_push_problem.pddl`, `rddl/box_push_skills.rddl` (head),
  `SUPERVISOR_P0_P4_CONTRACT.md`, `CLAUDE.md`, `.claude/rules/*.md`.
- Additional files verified during the adversarial review pass:
  `middleware_layer/belief_updaters/deterministic_grid_updater.py` (`:205-222`, `:56`),
  `middleware_layer/action_executor.py` (`:35-60`), `middleware_layer/middleware_orchestrator.py`,
  `multi_agent_box_push_env.py` (`:288-310`), `pddl/box_push_problem.pddl.soln`.
- Sub-audits: two `backend-investigator` runs (env semantics; runner/step accounting) and one
  `architecture-reviewer` adversarial contract check. The reviewer **refuted one of the auditor's
  findings** (the lone heavy push is symbolically *inapplicable* under the frozen known-weights PDDL,
  not an optimistic-failure case), **downgraded another** ("failure is never a no-op" → failure class
  depends on attempt timing), and **contributed headline 0**, which outranks every finding in the
  first pass. All load-bearing claims — including the reviewer's — were re-verified against source
  before being recorded here; the `too_heavy` mislabel chain and the `ActionExecutor` fabricated
  success were confirmed line-by-line.
- Unverified-at-runtime claims are marked as such in place; nothing in this document was executed.
- **No product code was modified by this audit.**

### Revision 2026-08-20b — serialization faithfulness

A third review round found that `canonical()` was verified almost entirely for KEY PRESENCE across
the whole contract surface. Roughly thirty value corruptions survived the suite — a field still
emitted but carrying a constant, a mirror of a neighbouring field, or an emptied container —
including the failure **post-state**, the **step accounting**, the typed **outcome**, the **task**,
and an `observed_world_key` mirroring `predicted_world_key` (a mismatch collapsed to "no mismatch").

Patching them one assertion at a time does not converge, so the property is now stated generally in
`tests/test_canonical_faithfulness.py`: for any type whose `canonical()` claims to carry field F,
two instances differing ONLY in F must serialize differently. A companion test derives the type list
from `shared/` so a new contract type cannot ship with an unverified serialization, and the
exclusion list (episode bookkeeping out of the world form) is checked not to reverse silently.

Two real product gaps surfaced with it: `ExecutiveObservation.canonical()` silently dropped `notes`,
and `StateSnapshot` box ordering was never normalization-tested — dropping the box sort gave two
snapshots of the same world different `world_key()`s, splitting the repeated-failure bucket (:118).

Also corrected: two trace assertions that mirrored the object they were built from, a fixture whose
`executive_step=0` made a hardcoded `0` pass, a `sorted()` in `SymbolicState.canonical()` that only
frozenset iteration order appeared to prove, and a duplicate-skill-name guard whose test was
actually satisfied by the duplicate-dispatch-key guard.

### Revision 2026-08-20d — P1 implemented

`BoxPushV1Adapter` lands (see the roadmap row for the full obligation mapping). Register updates:

- **T-W5 (text pins vs behaviour) — closed.** `test_reset_export_equals_the_frozen_initial_state`
  now pins the frozen instance against the LIVE backend (positions, facings, boxes, walls, goal
  zone in one executing assertion), subsuming the source-text drift pins' load-bearing role; the
  text pins remain as fast early warnings.
- **T-W1 (serialized plan cost) — closed** (`test_plan_cost_is_not_plan_length_in_disguise` now
  pins `canonical()["cost"]` under a non-unit registry).
- **T-W2 (trace provenance model_version) — re-assigned P1 → P4.** P1 emits `ExecutionResult`s,
  not `TraceEntry`s; the decision belongs to the first component that writes real traces (the P4
  loop manager). Recorded here so the ownership change is explicit, not silently dropped.
- **Decision 16 obligation 4 — RESOLVED** (exact world-derived grid; see P0_V1_DECISIONS §17).
- **Shared-surface addition (P0-frozen contracts, additive):** `shared/faults.py` gains
  `InfrastructureFaultError` — the exception that carries a fault across the `execute_skill`
  boundary, with an optional attached `ExecutionResult` for post-execution faults. Required by
  D8/D16: the protocol's return union deliberately excludes the fault channel, and P4 must be
  able to catch it without importing the backend-side adapter. Exported; no frozen semantic
  changed.
- **One raw-vs-typed disagreement became MORE reachable than P0 predicted:** delivering the LAST
  box ends the episode in the same joint `env.step`, before the skills' evaluation iteration —
  so the raw label is the non-terminal marker while the authoritative outcome is SUCCESS
  (`test_cooperative_push_is_one_executive_invocation` pins it). D3 is what makes this benign.

### Revision 2026-08-21i — P3 consistency check round 3 closed

Round 3 audited round 2's fix delta: 1 FAIL / 3 WARN, all closed here. The FAIL was a
RECURSION of round 2's own FAIL class: 21h corrected 21g's "sweep complete" overclaim and then
made the identical overclaim itself — five +5-drifted post-306 citations survived in `shared/`
(`faults.py`, `execution.py`, `orchestration_config.py` ×2) and `tests/test_execution_contract.py`,
several load-bearing. All five are now semantic anchors, 21h's claim is scoped honestly in
place, and — the durable fix — the property is now MECHANICAL:
`tests/test_domain_freeze.py::TestLegacyRunnerCitationDiscipline` greps the contract packages
and every non-legacy docs tree
for any `box_push_centralized.py:<n≥306>` citation and fails on the first hit (mutation Q15
pins the guard itself). WARNs: "cannot"/"no" added to the negation tokens with a five-form
residual pin (`tests/test_p3_nl.py::test_every_negation_form_reaches_the_residual`, mutation
Q16); revision 21f's counts restored to as-of-close values with a growth annotation (the
retro-sync had made the history self-contradictory); 21h's mailbox-pin attribution corrected
to the companion test. Known accepted residue: the legacy reference doc
`functional_layer/custom_env/box_push/BoxPush_Centralized_POMDP.md` retains drifted numbers —
legacy package, outside the guard's scope by design. Harness 37/37; P3 module 51 tests; suite 580.

### Revision 2026-08-21h — P3 consistency check round 2 closed

Round 2 audited round 1's WARN-fix delta: 1 FAIL / 3 WARN, all closed here. (1) FAIL — the
citation sweep had stopped at round 1's six enumerated sites and revision 21g recorded it as
complete while five in-family stale citations survived, all off by +5 after the banner
insertion: 18 numeric citations plus 4 bare shorthands across this file and the decisions doc
were converted to `::_skill_parser`/`::main` semantic anchors, and 21g's claim was corrected in
place. (Round 3 then found THIS sweep also scope-incomplete — five more in `shared/` and
`tests/` — and replaced manual sweeping with a mechanical guard; see 21i.) (2) The requirement rule
over-covered (live-demonstrated: `"two" in "network"` classified "The network needs repair" as
covered): the classifier is now TOKEN-based (stems against word prefixes), bare counts are not
requirement objects, the precision boundary is pinned both ways
(`tests/test_p3_nl.py::test_requirement_rule_precision_boundary`; the mailbox
interior-substring pin is its companion
`test_object_stems_match_token_prefixes_not_interior_substrings`) with "The agents need a break" recorded as the accepted imprecision
ceiling; mutants Q11/Q13 re-anchored + Q14 substring-regression added — Q14 SURVIVED on first
run (no test separated prefix from substring matching) and was killed by the mailbox pin;
35/35. (3) Tiers 2/3 now carry COMPLETE markers matching the roadmap rows.

### Revision 2026-08-21g — P3 consistency check closed

`/consistency-check P3` on the post-review fix delta: 0 FAIL / 4 WARN, all four closed in this
revision. (1) The tightened task classifier under-covered the frozen `TASK_DELIVER_HEAVY`
("It needs both agents" — expressible via `heavy(box)`/`required_agents` and the
`CooperativePush` arity): a requirement-clause rule was added and ALL frozen representative
tasks now pin fully-covered (`tests/test_p3_nl.py::test_every_frozen_representative_task_classifies_fully_covered`,
mutation Q13). (2) Harness mutants V1/X1 were crash-kills (NameError/TypeError) overstating
their evidence — reworked to behavioral mutants (local import; empty-residual), 34/34 killed.
(3) The six `:313-314`-family sites enumerated by the check were swept to the
`::_skill_parser` semantic form and the stale "Critical path (remaining)" paragraph now reads
P4-only — round 2 then found the sweep INCOMPLETE (five in-family survivors and a systemic +5
drift across every post-306 citation into the legacy runner); the full-family sweep landed in
revision 2026-08-21h. (4) The `runtime`-ban
claim on `nl/` was enforced nowhere on the real tree — `runtime_violations()` ran only on probe
trees; a real-tree assertion now backs it
(`tests/test_no_backend_imports.py::test_the_real_tree_has_no_runtime_imports_on_the_symbolic_side`).

### Revision 2026-08-21f — P3 NL baseline

P3 implemented: `nl/` package (seam, runtime config, parser, task/observation interpreters,
semantic belief, skill selector, repair, translator, recovery, stub track) + the legacy-side
live DSPy binding + 47 offline tests + 33-mutant harness, all green/killed at this
revision's close (grown by later rounds to 51/37/580 — see 21g-21i). Suite total 574
(1 skip = the MAAOS_LIVE_LM-marked live test). Decisions §18 items 2, 3 and 9 closed (item 9
via replacement + pinned SUPERSEDED banner, reading recorded).

Review round: architecture 0 FAIL / 5 WARN (translator action set now DERIVED from
`REGISTRY.symbolic_action_set()`; direction words backend-pinned; coverage classifier
tightened to verb+object+no-negation with the over-claim cases pinned; runtime-config
truthfulness fixed with explicit api_key and consumed seed; stale citations swept to
function-name form and the banner pinned). Test review 5 FAIL / 7 WARN / 5 NOTE — the
systemic finding: recorded-seam fixtures were fail-closed on request determinism but blind to
request CONTENT, so the whole information channel to the model (belief, menu, format, raw text
under repair, observation facts) could be emptied or inverted with every test green. Closed
with golden request-content assertions, direct ObservationInterpreter units (incl. truthful
delivered-status and all four direction words), track outcome-plumbing and lifecycle pins,
`primitive_steps` + getattr/string-evasion guard tightening, a closure-based no-dspy scan, and
the Q-series mutants (Q1-Q12) — all killed.

Recorded residuals: parser box/zone prefix-dispatch tolerance (documented + pinned);
transitive deps (litellm/openai) unpinned; `pygame`/`pygame_ce` side-by-side (pre-existing);
NLRequest str-coercion/dedup semantics (NOTE-level, untested by choice).

### Revision 2026-08-21e — V1 acceptance round + P2 consistency check

`/acceptance-test` delivered `tests/test_v1_acceptance.py` (10 tests: the six supervisor cases
as live `TraceEntry`-recorded cycles — normal success; the optimistic failure with livelock +
scripted recovery; pre-executor rejection at 0/0 steps with the backend untouched; malformed +
ghost-identity handling traced across BOTH layers; synthetic `NoPlan`; deadlock documented N/A
per Decision 12) and the byte-pinned `docs/implementation/acceptance_traces.md`, regenerated
live at test time. Its test-review returned 0 FAIL / 4 WARN / 5 NOTE; all WARNs fixed in-suite
(failure specifics, plan identities, direct success-match assertions, TraceEntry-coexistence
enforcement) and pinned by the VA-series mutants.

The `/consistency-check P2` independent pass then audited the whole post-review fix delta:
1 FAIL / 3 WARN, all documentation/guard-hardening — no product-code defect. Closed in this
revision: this document's stale counts (447→526 suite tests, 46→50 harness mutants) and the
now-false "no trace is ever produced" coverage cell; the clause-9 guard's fifth escape route
(`from symbolic import *`, closed + L3 mutant); the monitor `ValueError` escape and the
ghost-identity routing order, both recorded as P4-binding items in decisions §19.1 (items 4-5).

### Revision 2026-08-21d — P2 symbolic baseline

P2 implemented: `symbolic/` package (applicability, belief, planner, predictor, monitor,
pddl_gen, synthetic) + 69 tests + 50-mutant harness (46 at the time of this revision; the
acceptance and consistency rounds later extended it), all green/killed. Both adversarial reviews
returned 0 FAIL; every WARN and every surviving-mutant finding from the test review was fixed and
mutation-pinned in the same round (predictor zone-identity check, `v1_artifacts` raise-not-assert,
clause-9 guard hardened to four escape routes after review demonstrated `import symbolic` and
`from symbolic import predictor as _p` evasions, direction-vector table pinned against the
backend's `constants.DIRECTION_VECTORS`, monitor key-pair/message orientation pins, nearest-cell
pin on a synthetic two-cell ray, ≥2-literal `unsatisfied` pin, non-LEFT-direction prediction pins).

Key discoveries recorded as P4 inputs in decisions §19.1: the demonstrated consuming-skill
livelock and its re-establishment escape; `CallValidation` gating as the orchestrator's job;
monitor wired on the belief, not a re-projection. Decisions §18 items 1 & 6 and §19 D-1..D-4
closed; §14.1 world-basis cells landed. Scenario #2 re-validated against the adapter
(`tests/test_p2_acceptance.py::TestScenarioTwoRevalidatedAgainstTheAdapter`).

### Revision 2026-08-21c — consistency check round 3 (at the P1 baseline)

Round 3 found 1 FAIL, 3 WARNs — again inside the previous fix:

- **F-1:** the runaway-cap producer spelled the case-(c) provenance key `primitive_steps_consumed`
  while the P4 work item and the revision note instruct P4 to parse `primitive_steps_before_failure`
  — and the stray spelling collided with the name of the `TraceEntry.primitive_steps_consumed`
  accessor, which reports 0 for the same cycle (W-1). Fixed by renaming the cap's key: ONE exact
  key now spans all four case-(c) producers, `shared/faults.py` states it exactly (wildcard
  retired), and `test_runaway_cap_fault_carries_the_single_provenance_key` pins it (cap exercised
  by lowering the module constant) with harness mutation P1-30.
- W-2: the refusals-carry-no-provenance assertion now runs on BOTH refusal producers.
- W-3: the accessor docstring names all three zero-situations (rejection, case-(b) refusal,
  case-(c) mid-execution).

The baseline commit was amended to include this round; the tag moved with it.

### Revision 2026-08-21b — consistency check round 2 (fix-of-the-fix)

The second `/consistency-check P1` found 2 FAILs, both introduced by round 1's F1 rewording:

- **F-A:** `TraceEntry.executive_steps_consumed`'s docstring asserted a false biconditional
  ("0 unless the call reached the executor") that case (c) falsifies, and
  `ExecutiveHistory`'s budget sums inherit it — the natural P4 budget source under-charged
  exactly the runaway/exception attempts a budget exists for. Fixed by RESCOPING, not schema
  change: both accessors now state they report recorded accounting only; the history sums are
  documented as lower bounds; the P4 roadmap row carries the explicit charging work item; and
  `test_case_c_trace_accessors_report_recorded_accounting_only` freezes the 0/0 behaviour as
  deliberate.
- **F-B:** the alien-label producer was named case (c) by the rule while carrying none of the
  `primitive_steps_*` provenance the rule itself demands. Both remaining producers (alien label,
  dispatch guard) now attach it; the seam test asserts it; harness mutation P1-28 pins it.
- W-1: both refusal messages now begin with `refused:` (pinned by test + mutation P1-29), so
  (b)/(c) discrimination needs no per-site string knowledge. W-2: the case-(c)/repeated-failure
  interaction is recorded in the P4 work item as a decision to make, not an accident to inherit.

### Revision 2026-08-21 — P1 consistency check

`/consistency-check P1` ran two passes (self + independent architecture-reviewer). 12 PASS,
2 FAIL, 2 WARN — both FAILs in the previous fix delta, both contract-text:

- **F1:** the attempt-occurred rule had been frozen as a two-case dichotomy
  (`result is not None` ⟺ step consumed), which classified a 600-primitive-step runaway or a
  mid-drive `env.step` exception as "nothing happened" — contradicting Decision 2. Reworded to
  the three-case rule (see the corrected 2026-08-20e bullet); no code path changed.
- **F2:** the `env.step` exception wrap was claimed "mutation-pinned" while nothing exercised
  it. Now genuinely pinned: `test_env_step_exception_becomes_a_typed_backend_fault` (seam
  injection, asserts kind, message, `primitive_steps_before_failure`, cause chaining, and that
  the world really advanced) plus harness mutations P1-26/P1-27.
- W1: stale roadmap-row counts corrected. W2 (recommendation): the audit's live probe — frozen
  `DOMAIN_IR` Push effects applied to a pre-projection equal the projection of the real
  backend's post-state (monitored keys identical) — should land as the first P2 monitor test.
  (**Landed:** `tests/test_p2_acceptance.py::TestSuccessfulTransitionsMatchPredictions`.)

Also verified live during the audit: C3 symbolic-effects-vs-successor agreement (above), no
`unknown` cells in the exact entities view, dispatch coverage of all registry keys, and the
three-case fault routing probes.

### Revision 2026-08-20e — P1 review round

Both P1 reviews returned (architecture: 0 FAIL / 5 WARN; test: 3 FAIL / 6 WARN). All addressed:

- **Coop substitution arm, success-by-flip, and both landing-cell reasons now covered** — the
  three review FAILs were branch-level coverage holes; each now has a live-backend test and a
  checked-in mutation (`docs/implementation/p1_mutation_harness.py`, 25/25 killed).
- **Untyped escapes closed in code:** a backend label outside the frozen vocabulary now raises
  `InfrastructureFaultError(MALFORMED_BACKEND_RESULT)`; an exception out of `env.step` becomes
  `BACKEND_API_EXCEPTION` with `primitive_steps_before_failure` in detail. Both unreachable with
  the frozen backend, both typed anyway, both pinned by a seam test AND a harness mutation (the
  `env.step` pin was added by the P1 consistency check — the first revision claimed it while only
  the label path was pinned). P4 needs no second generic handler.
- **Attempt-occurred discrimination rule frozen** (`shared/faults.py`) — THREE cases, not two
  (the two-case form first recorded here erased the mid-execution fault class and was corrected
  by the P1 consistency check): (a) `result is not None` ⇒ one executive step, accounting
  attached; (b) `result is None` + pre-attempt refusal (D8/reset-before-use) ⇒ zero steps, world
  untouched; (c) `result is None` + mid-execution fault (`env.step` raised, runaway cap, alien
  label) ⇒ one executive step per Decision 2 (the call reached the executor), world possibly
  changed, primitive accounting in `fault.detail` only (`primitive_steps_before_failure=N`, which
  EVERY case-(c) producer attaches) — P4 resynchronizes via `export_full_state()`. The fault KIND is never the discriminator
  (`EXECUTOR_MONITOR_PROTOCOL_FAILURE` serves refusals AND post-execution faults), and only
  `result is not None ⇒ step consumed` is a safe inference. Binding on P4.
- Runaway-cap fault now carries the consumed primitive count; the goto post-flight's
  claims-success-only scoping is recorded in Decision 16 obligation 3; the two obligation-4
  stale lines corrected; both mutation harnesses checked in as process evidence
  (`docs/implementation/p{0,1}_mutation_harness.py`); `_move_box(delivered=True)` now bumps
  `delivered_target_count` so injected fixtures stay backend-producible.
- Noted as equivalent-or-near-unreachable, no action: `_push_failure_reason` branch order
  (heavy-front + wall-landing jointly unreachable on the frozen instance); asymmetric-coop
  `timed_out any()` / primary-agent raw-label provenance (unpinnable until P2 consumes them);
  `observe()`'s shallow copy aliasing inner dicts (hygiene).

### Revision 2026-08-20c — serialization faithfulness, stated per key

The round-3 module asserted the right idea with the wrong granularity: it compared whole canonical
dicts, so any single differing key satisfied it, and its coverage test derived TYPES rather than
FIELDS. Both gaps were demonstrated — a newly added field still shipped unprotected, and four case
variants moved two fields at once, proving nothing about either.

The property is now stated per key: for every key `canonical()` emits, there must exist two
instances whose serialization of THAT key differs, and the key list is derived from `canonical()`
itself. Deliberately constant discriminator tags (`channel`, `result`) are exempt from sensitivity
and pinned by value instead. Transposition-vulnerable pairs (`StaticWorld` width/height,
`StepAccounting`) get literal-value assertions, because a consistent swap of two fields is a
bijection that no difference test can detect — which is why a 12x12 frozen instance hid it.
`TraceEntry` and `ExecutionResult` additionally must EMIT every field they declare, so a field
added but never serialized cannot silently vanish from a trace.

That surfaced seventeen further payload corruptions, of which the sharpest was a regression from
the round-3 fix itself: `comparison_bases` and `mismatched_bases` were asserted as object
properties while `"comparison_bases": []` in the serialized form survived — the trace losing the
per-basis verdict the new tests had just been written to protect.

Three backend-drift blind spots closed alongside: the agent starting facing was pinned by a
whole-file substring satisfied by an unrelated line (flipping the real per-agent assignment
survived), the grid size was asserted only against literals in a test file with nothing reading the
backend, and `PRODUCIBLE_RAW_LABELS` was only additively checked — the table gating
`ExecutionResult.raw_label` could be widened or narrowed per skill with the suite green. All three
now have exact lockdowns.

### P0 coverage ceiling — what is proven, and at what level

P0 froze contracts; no executor, planner, orchestrator, monitor, translator or NL track exists.
Several `.claude/rules/testing.md` regression properties are therefore proven **only at the
type/contract level**. They are listed here so P1-P4 do not inherit them as "already covered":

| Required property | P0 status | Owner |
|---|---|---|
| Aligned argument types across registry/model/backend | **Registry↔IR fully covered** — they share the signature OBJECT and grounded calls reject raw types. Backend side: dispatch arms and skill arithmetic are source-pinned, and the three constructor signatures Decision 16 translates into are pinned by `test_backend_freeze_drift.py` | — |
| Canonical `StateSnapshot` normalization + structural equality | **Fully covered** — order independence (agents AND boxes), field-level key sensitivity, cross-process digest | — |
| The three report channels stay separate | **Fully covered** | — |
| `PlanFound`/`NoPlan`/`PlannerFailure` distinct; `PlannerFailure → InfrastructureFault` | **Planner half behavioural (P2):** all three results exercised (`tests/test_p2_symbolic.py::TestPlanner` — solvable → 5-step `PlanFound`, synthetic single-agent instance → `NoPlan`, node budget → `PlannerFailure(timed_out=True)`, raised exception → `PlannerFailure`); conflation mutation-pinned both directions. The `PlannerFailure → InfrastructureFault` conversion is the runtime path and remains P4 | P4 |
| Successful execution matches the symbolic predicted normalized `StateSnapshot` | **Behavioural (P2):** live goto/push/coop successes match BOTH bases (`tests/test_p2_acceptance.py::TestSuccessfulTransitionsMatchPredictions`); coop verified by world-key MEMBERSHIP over the declared two-candidate slot set | — |
| Backend rejection of an optimistic-but-applicable skill records the right failure + `ExecutionDiscrepancy` | **Fully behavioural (P2):** the flagship acceptance test plans optimistically, executes against the real backend, and the applicable-but-infeasible `Push` produces `EXECUTION_FAILURE_OF_APPLICABLE_SKILL` carrying raw label, failure class and detail (`tests/test_p2_acceptance.py::TestOptimisticPlanFailsInBackend`); message content and key-pair orientation mutation-pinned (X1/X2/X8) | — |
| Malformed/invalid NL calls rejected or repaired before executor invocation | **Behavioural (P3):** `nl/parser.py` returns typed `MalformedCall` (raw preserved), `nl/repair.py` makes exactly ONE typed repair attempt (counting-seam-pinned), the standing rejection carries both reasons, and substitution is mutation-pinned impossible (N1/N2/K1 in `docs/implementation/p3_mutation_harness.py`). The `MalformedCall → InfrastructureFault` invocation at the cycle boundary is P4's loop | P4 |
| A new current-cycle `InfrastructureFault` short-circuits execution | Type level only — `short_circuits_cycle`, `arises_before_execution` and the `TraceEntry` refusal are covered; no loop exists | P4 |
| Orchestration policy changes decisions, not executor semantics | **Not testable at P0** — `OrchestrationPolicy` has no consumer | P4 |
| Representative tasks terminate as expected | **Partial (P2):** the flagship story reaches `all_targets_delivered` under scripted replanning; the autonomous loop is P4 | P4 |
| NL default tests use stubs | **Behavioural (P3):** every LM interaction in the default battery goes through `RecordedLM` fixtures with a typed miss error; request CONTENT is golden-pinned (test-review FAIL-1/2 closed); `dspy` is absent from the default import closure, enforced by a closure-based AST scan over all default test modules; live coverage only behind MAAOS_LIVE_LM=1 | — |
| No hidden backend feasibility oracle is introduced | **Fully guarded (P2):** import-level fail-closed guards, projection-level geometry blindness (`project(near) == project(far)` key equality), and the clause-9 predictor guard closing four import escape routes + the AST input bound (`tests/test_p2_symbolic.py::TestSymbolicSideGuards`); guard escapes themselves mutation-pinned (L1/L2) | — |
| Traces include task, snapshots, proposals, decision, prediction, execution, channels, provenance, model version | **Behavioural for recorded cycles:** `tests/test_v1_acceptance.py::RecordingHarness` produces a frozen `TraceEntry` per executive cycle against the live backend, rendered into the byte-pinned `docs/implementation/acceptance_traces.md`. The producing LOOP is still scripted test scaffolding — the autonomous P4 loop does not exist | P4 |

---

### Revision 2026-08-20 — P0 close-out

Third and final reconciliation, closing the `/consistency-check P0` findings before P1 begins.
Three FAILs, all self-inflicted by the previous round, plus ten contract/documentation gaps:

- **`Push.predicted_world_effects` described one primitive push, not the executive macro.**
  `PushSkill` loops; the agent ends one cell behind wherever the box STOPPED
  (`agent_post == box_post - D`), not on the box's pre-state cell. On the frozen instance the box
  travels (8,4)→(1,4) while the agent ends at (2,4). Now pinned by a source drift test AND an
  executable replay of the loop.
- **`CooperativePush` sourced the push direction from `agent1.direction_pre`.** The backend derives
  it from the box and zone and then TURNS both agents onto it, so both terminal directions are real
  world effects that implicit frame conditions would have mispredicted. Direction and both terminal
  slots are now declared and drift-pinned; the set-valued slot semantics are preserved because slot
  assignment depends on backend proximity with an `agent_id` tie-break.
- **Every PDDL citation in both documents was shifted +19 lines** by the `;; SUPERSEDED` banner,
  including Decision 5's evidence, which landed on a banner rule. All are now **semantic anchors**
  (`:action push`), and `tests/test_domain_freeze.py` bans line-only citations into those files.
- Raw-label membership is enforced (`Push` + `waiting_partner` no longer constructs);
  `in_progress` is no longer a `RawLabel` (it marks the ABSENCE of a terminal label) and the label
  partition is now provably total; the two senses of "rejected" are separated
  (`CallValidation.is_pre_executor_rejection` vs `BACKEND_REJECTED_BEFORE_TRANSITION`);
  `TraceEntry` refuses impossible lifecycles and its `rejection` field is renamed `validation`,
  since on the execution path it legitimately holds an acceptance; the observation contract is
  exported and its channel count corrected; Decision 16 freezes the P1 adapter's per-skill argument
  translation; Decision 13 clause 8 now says an executive-tracked fluent is invalidated only when
  the attempt could have disturbed its prior truth; the guard probes no longer write into the
  working tree; Decision 13 renumbered to nine ordered clauses.

Verification: 400 tests green from the repository root and from two foreign working directories,
under six `PYTHONHASHSEED` values; 117/117 adversarial mutations killed with bytecode disabled and
`__pycache__` cleared before every run.

Two independent adversarial reviews of these fixes then found six further FAILs, all now closed:
three in the fixes themselves (three surviving bare `` `:NN` `` PDDL citations that the new guard
failed open on; a Decision 16 pre-flight that would have converted the designed
`ExecutionDiscrepancy` into `MISSING_GROUNDING` and acted as a feasibility gate; twelve `§17.x`
pointers shifted by inserting Decision 16) and three in the tests (`canonical()` verified for key
PRESENCE only, so nine value-corrupting mutations survived — including the failure post-state and
the step accounting; a `world_changed` test whose loop variable was never used; and six
`predicted_world_effects` mutations killed only by the golden digest, among them a collapsed
cooperative slot set and a pose-cell sign flip). The declarations are now pinned verbatim.

### Revision 2026-08-19 — post-P0 reconciliation

Triggered by `/consistency-check P0`, which ran an independent `architecture-reviewer` pass and
found one FAIL plus eleven WARNs against the P0 implementation. Changes to this document:

- Added the "How to read the status columns" note: a `MISSING`/`UNDEFINED`/`AMBIGUOUS` cell is a
  statement about the **backend**, not an open V1 question. Ten such cells were being read as live
  blockers.
- Annotated the resolved items inline with their deciding entry (Decisions 1-16).
- Corrected the §B vocabulary authority (`SkillName`/`REGISTRY`, not `make_skill`) and recorded the
  missing `"wait"` dispatch arm.
- Removed "(P0 blocker)" / "blocked on §L-…" / "Tier 0 — nothing should be written first", all of
  which described a state that no longer exists.
- Replaced the `PlanFound([explore…])` trace example, which used a skill Decision 5 removed from
  the symbolic action set, and annotated the acceptance trace with both Decision 13 comparison
  bases.
- Updated the test count (220 → 400) and module count (10 → 14), and recorded the PDDL artifacts as
  `;; SUPERSEDED FOR V1`, including the previously unrecorded identifier divergence
  (`BoxId.parse("box0")` raises).
- Corrected the residual-work cross-references after the decisions document was renumbered for
  Decisions 13-15. *(Historical: residual work has since moved again, to §18; see the 2026-08-20
  entry. Section references are now guarded by a test.)*

A second reconciliation round followed two independent adversarial reviews of these very fixes
(`architecture-reviewer`: 3 FAIL / 13 WARN; `test-reviewer`: 4 FAIL / 10 WARN). It corrected three
further defects introduced by the first round — a `CooperativePush` world effect that placed both
agents on the same cell, a `Push` effect attributed to `push_dir` when the backend uses the agent's
own facing, and a surviving projection-only claim in `shared/state_snapshot.py` — plus three
pre-existing product-behaviour holes that no test covered (grounded-call argument types,
`delivered`'s presence in `world_key()`, and `all_targets_delivered` being conjunctive).

The one FAIL of the first round was in the P0 code, not in this document: `ExecutionDiscrepancy` demanded a
world-state key pair, so the `STATE_EFFECT_MISMATCH` a compliant symbolic monitor produces could
not be constructed at all. Fixed by Decision 13 and `shared/discrepancy.py`; regression-pinned in
`tests/test_prediction_and_monitoring.py`.
