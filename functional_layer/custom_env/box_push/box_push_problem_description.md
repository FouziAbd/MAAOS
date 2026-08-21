# BoxPush — Problem Description (skill-level, formalization input)

> **Purpose.** This is the *sole input* from which the PDDL and RDDL models are built. It
> is a plain-English description of the box-pushing task at the granularity of **skills**
> (the agents' high-level actions). It contains no source code, no grid coordinates, and no
> low-level movement primitives. Any downstream formal model must be derivable from this
> text alone. Anything left unstated here becomes an explicit modeling decision later — so
> the description is written to be as complete and unambiguous as the skill level allows.

---

## The task

Two agents work as a team on an open arena. Their job is to get **both target boxes onto
the GOAL zone**. The task is complete when both boxes are on the goal zone.

There are **two boxes**:
- one is **LIGHT** — a single agent can push it;
- one is **HEAVY** — it moves only when **both agents push it together**.

At the start:
- the boxes' **locations are unknown** and must be found;
- a box's **weight is unknown** until an agent tries to push it.

The two agents **share what they know**: once either agent discovers a box (its location,
or later its weight), both agents know it.

## The skills

Each agent chooses **one skill per decision cycle**. The skills are:

### `explore`
Search the arena until a box is found.
- **Outcomes:** `a box is discovered` | `nothing new found`.

### `goto_push_pose(box)`
Move into position directly behind a known box, on the side away from the goal, ready to
push it toward the goal.
- **Precondition:** the box is known (already discovered) and not yet delivered.
- **Outcomes:** `in position` | `the box is not known` | `blocked`.

### `push(box)`
From the push position, push the box toward the goal until it reaches the goal zone.
- **Precondition:** the agent is in the push position for this box.
- **Outcomes:** `delivered` | `too heavy` (the box did not move — one agent is not enough)
  | `blocked`.

### `cooperate_push(box)`
Together with the partner, line up behind the HEAVY box and push it jointly to the goal.
- **Precondition:** the box is known and heavy; **both agents commit to it in the same
  cycle**.
- **Outcomes:** `delivered` | `waiting for the partner` | `blocked`.

### `wait`
Do nothing this cycle.

## Rules of the world

1. A **LIGHT** box needs exactly **one** agent: `goto_push_pose` then `push`.
2. A **HEAVY** box needs **both** agents: `cooperate_push`. A lone `push` of a heavy box
   **fails**, and by failing it **reveals** that the box is heavy.
3. Once a box is **known to be heavy**, it can only be delivered by `cooperate_push`
   (never a lone `push` again).
4. Knowledge is **shared**: a discovery by one agent is immediately known to both.
5. Coordination guidance: do **not** put both agents on the same LIGHT box; do **not**
   leave a target box undelivered; do **not** `wait` while a target is undelivered.

## Objective

Deliver both boxes. Delivering a box is the goal; every cycle spent has a small cost, so
the team should deliver both boxes in as few cycles as possible, cooperating on the heavy
one.
