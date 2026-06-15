# Cooperative Search and Transport — Dec-POMDP Formulation

Since each agent only sees its own local view, this is a **Decentralized POMDP (Dec-POMDP)**: ⟨I, S, A, T, R, Ω, O, h⟩

---

## I — Agents

```
I = { agent_0, agent_1 }
```

---

## S — State Space

Each state s ∈ S is a tuple of:

| Component | Values |
|---|---|
| Agent position (×2) | (x, y) ∈ [0,11]² |
| Agent direction (×2) | RIGHT=0, DOWN=1, LEFT=2, UP=3 |
| Agent carrying (×2) | None \| object_id ∈ {0,1,2,3} |
| Object position (×4) | (x, y) ∈ [0,11]² |
| Object delivered (×4) | {False, True} |
| Object carried_by (×4) | None \| agent_id |
| Object engaged_agents (×2 targets) | ⊆ I |
| Step count | ∈ [0, max_steps] |

**Initial state s₀:**

```
agent_0: pos=(10,10)  dir=LEFT  carrying=None
agent_1: pos=(10,9)   dir=LEFT  carrying=None

obj_0: pos=(2,9)   is_target=True   required_agents=2   (cooperative)
obj_1: pos=(6,5)   is_target=True   required_agents=1   (solo)
obj_2: pos=(9,2)   is_target=False  required_agents=1   (decoy)
obj_3: pos=(10,4)  is_target=False  required_agents=1   (decoy)
```

---

## A — Joint Action Space

```
A = A₀ × A₁,   each Aᵢ = { TURN_LEFT(0), TURN_RIGHT(1), MOVE_FORWARD(2),
                              STAY(3), PICK_OR_INTERACT(4), DROP(5), COOPERATE(6) }
```

| Action | Effect |
|---|---|
| TURN_LEFT / TURN_RIGHT | direction = (dir ∓ 1) mod 4 |
| MOVE_FORWARD | move 1 cell in facing direction if free |
| STAY | no-op |
| PICK_OR_INTERACT | pick up object in front cell (solo) OR latch onto cooperative object |
| DROP | release carried/cooperative object at current position |
| COOPERATE | signal cooperative intent; keeps cooperative hold without moving |

---

## T — Transition Function (deterministic)

T: S × A → S, executed in this **fixed order** each step:

1. **Turns + individual moves + COOPERATE flag** — agents turn/move independently; COOPERATE sets a flag only
2. **PICK_OR_INTERACT** — solo pickup or cooperative latch; full hold (both latched) removes object from grid
3. **DROP** — solo release or cooperative disengage; if hold breaks, object returns to its last logical position
4. **Resolve cooperative carry** — if all engaged agents choose MOVE_FORWARD facing the **same direction**, agents + object move together as one unit; STAY or COOPERATE holds in place; any incompatible action disengages the agent and breaks the hold
5. **Sync solo-carried objects** — carried object follows its carrier's new position
6. **Delivery check** — if a target object's logical position ∈ delivery zone → mark as delivered

---

## Ω — Observation Space (per agent)

Each agent observes a **partial, egocentric** view:

- A **3×3 local grid patch** rotated to align with the agent's facing direction
- Cell encoding: `EMPTY(0), WALL(1), DELIVERY(2), AGENT(3), TARGET_OBJECT(4), NON_TARGET_OBJECT(5)`

**Not observable:**
- Own absolute position or direction (must be tracked externally)
- Other agent's direction, carrying state, or cooperative latch status
- Object identity (obj_0 vs obj_1) or required_agents count
- State of `engaged_agents` list (partial vs full hold)

---

## O — Observation Function

Deterministic given state: each agent sees the 3×3 grid patch immediately in front of itself, rotated so "forward" in the patch aligns with the agent's facing direction.

---

## R — Reward Function

R: S × A → ℝ² (per-agent rewards, not shared globally)

| Event | Reward |
|---|---|
| Per step (always) | −0.01 |
| Failed MOVE_FORWARD (blocked) | −0.10 |
| Successful PICK_OR_INTERACT (solo) | +0.10 |
| Cooperative latch (partial hold) | +0.05 |
| Cooperative carry step (joint move) | +0.20 per engaged agent |
| Target delivery — solo or cooperative | +20.0 per engaged agent |
| All targets delivered (episode end) | +10.0 per agent |

---

## h — Horizon

`h = 250` steps (truncation). Natural termination when both obj_0 and obj_1 are delivered.

---

## World Topology

```
12×12 grid with outer walls and two internal vertical walls:

  x=4: wall for y ∈ [1,10] \ {3, 8}    ← two passage gaps
  x=8: wall for y ∈ [1,10] \ {6}        ← one passage gap

Three rooms:
  Left room   x ∈ [1,3]   contains delivery zone and obj_0
  Middle room x ∈ [5,7]   contains obj_1
  Right room  x ∈ [9,10]  agents start here; contains decoys obj_2, obj_3

Delivery zone: (1,1), (2,1), (1,2), (2,2)   top-left corner of left room
```

ASCII map (y increases downward):

```
############
#DD........#
#DD........#
#...#......#
####.###.###
#...#..#...#
#...#T.....#
#...####.###
#...#......#
#T..#......#
##########.#
###########.
```

Legend: `#`=wall, `D`=delivery zone, `T`=target object, `.`=empty

---

## Cooperative Carry Protocol

obj_0 (required_agents=2) follows a 3-phase protocol:

| Phase | Condition | Valid actions for engaged agent |
|---|---|---|
| PARTIAL LATCH | 1 of 2 agents latched | COOPERATE (6) only — wait for partner |
| FULL HOLD | both agents latched, object off-grid | MOVE_FORWARD (same dir as partner), STAY, COOPERATE |
| DELIVERY | both agents on delivery zone | DROP (5) — both must drop before object registers as delivered |

Breaking the hold at any phase (wrong action, incompatible directions, solo DROP before delivery zone) returns the object to its last logical position on the grid.

---

## What Makes This Hard

| Challenge | Description |
|---|---|
| Partial observability | Agents see only a 3×3 patch; most of the 12×12 grid is hidden at any step |
| Asymmetric task structure | obj_0 requires 2 agents; obj_1 requires 1 — optimal play requires implicit role assignment |
| Cooperative synchronization | Both agents must latch, face the same direction, move in sync, and reach the delivery zone together |
| Sparse reward | Delivery reward (+20) is the only large signal; most steps yield only −0.01 |
| Credit assignment | It is unclear from local observations alone whether a teammate is on track or stuck |
| Decoy objects | obj_2 and obj_3 are non-targets; picking them up wastes steps with no delivery reward |
