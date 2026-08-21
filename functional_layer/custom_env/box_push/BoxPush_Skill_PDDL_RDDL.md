# BoxPush — Skill-level PDDL & RDDL from the description

This document derives two formal planning models of BoxPush — one **PDDL** (classical),
one **RDDL** (factored MDP) — **entirely from the natural-language problem description**
(`box_push_problem_description.md`), at the **skill** level. The environment source code is
never used as input; it (and `BoxPush_Centralized_POMDP.md`) serve only as a downstream
**validation oracle**.

The actions of both models **are the skills** — `explore`, `goto_push_pose`, `push`,
`cooperate_push`, `wait` — not primitive moves. There is no grid, no coordinates, no
orientation.

## Files
| File | What it is |
|---|---|
| `box_push_problem_description.md` | **The input.** Skill-level English description. |
| `pddl/box_push_domain.pddl` | Classical STRIPS domain, known weights (primary). |
| `pddl/box_push_problem.pddl` | Instance: 2 agents, box0 heavy, box1 light, nothing discovered. |
| `pddl/box_push_domain_fond.pddl` | FOND variant: weight *discovered* by pushing (`oneof`). |
| `rddl/box_push_skills.rddl` | Skill-level factored MDP: concurrency + reward + delivery CPFs. |

## Mapping: description → model

Every skill and outcome in the description maps to a construct in each language. Nothing in
the description is left unmodeled, and nothing is invented beyond it.

| Description concept | PDDL | RDDL |
|---|---|---|
| box discovered by exploring | `explore` adds `(discovered ?b)` | `discovered'` CPF from `do_explore` |
| get behind a known box | `goto_push_pose` adds `(in-pose ?a ?b)` | `in-pose'` CPF from `do_goto` |
| one agent delivers light box | `push` pre `(light ?b)` → `(delivered ?b)` | `delivered'` light branch |
| lone push of heavy fails / reveals weight | (known-weights: N/A) · FOND `oneof` | `weight-known'` + block penalty in reward |
| both agents deliver heavy box | `cooperate_push(?a1 ?a2 ?b)` macro | `delivered'` heavy branch (two distinct cooperating agents) |
| task done | `:goal (and (delivered box0) (delivered box1))` | terminate when all `delivered` |
| every cycle costs a little; delivery is worth a lot | (plan length / `:metric`) | `reward`: `-STEP_COST + DELIVER_REWARD·(newly delivered)` |
| shared knowledge | single global fluents (no per-agent belief) | single global state fluents |

## The modeling decisions the description forced (the specification gaps)

These are the points where the English was silent or ambiguous and a choice had to be made
— the real output of the "from description alone" exercise:

1. **`explore` targeting.** "Search until a box is found" does not say *which* box. Modeled
   as `explore(?a ?b)` discovering a specific box, letting the planner/policy choose. An
   alternative (explore discovers an arbitrary undiscovered box) needs nondeterminism.
2. **Weight discovery.** "Weight is unknown until you push" is inherently nondeterministic.
   Two legitimate readings, both provided: **known-weights** (deterministic STRIPS, primary
   — treats "one heavy, one light" as prior knowledge) and **discovered-by-pushing** (FOND
   `oneof` / RDDL hidden weight).
3. **"Both at once" for the heavy box.** Classical PDDL has no timestep concurrency;
   resolved with a two-agent **macro-action** `cooperate_push(?a1 ?a2 ?b)`. RDDL expresses
   it natively via two concurrent `do_cooperate` action-fluents.
4. **Reward magnitudes.** The description says only "small cost per cycle, delivery worth a
   lot." Concrete numbers (`STEP_COST=0.01`, `DELIVER_REWARD=20`) are a modeling choice, not
   from the text — chosen to preserve the *ordering* the description implies.
5. **Blocked / waiting_partner outcomes.** These are execution-failure labels with no
   goal-level effect; folded into the reward (block penalty) in RDDL and omitted from the
   deterministic PDDL (a classical plan assumes skills succeed).
6. **In-pose persistence & release.** The description doesn't say whether being "in
   position" survives across cycles; modeled as sticky, cleared on delivery.

## How to run / validate (oracle downstream)

- **PDDL (deterministic) — VERIFIED.** Solved with `pyperplan box_push_domain.pddl
  box_push_problem.pddl` → a 7-step plan delivering both boxes:
  `explore ×2 → goto_push_pose ×3 → push a1 box1 (light) → cooperate_push a1 a2 box0
  (heavy)`. Note pyperplan is positive-STRIPS only, so the domain uses complement
  predicates (`unexplored`, `pending`) instead of negative preconditions and a
  `(different ?a1 ?a2)` predicate instead of `=`; the `wait` no-op is omitted (kept in
  RDDL). Fast Downward would also accept the negative-precondition form directly.
- **FOND:** solve `box_push_domain_fond.pddl` with a FOND planner (PRP / myND); expect a
  *policy* that pushes once to test weight, then branches to `cooperate_push` on the
  heavy-revealed outcome.
- **RDDL (pending tool install):** load `box_push_skills.rddl` in **pyRDDLGym**
  (`pip install pyRDDLGym`); a scripted skill policy should reach both-delivered with total
  reward dominated by the two `+20` deliveries. Not yet machine-validated here — pyRDDLGym
  was not installed in this environment.
- **Cross-check (after):** the derived skill preconditions/effects should agree with the
  Level-1 option table in `BoxPush_Centralized_POMDP.md` — a consistency check performed
  *after* modeling, never used as input.
