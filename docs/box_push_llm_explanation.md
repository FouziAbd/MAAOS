# How the LLM drives the Box-Push task

*Grounded in an actual run log (`functional_layer/custom_env/box_push/env/box_push_centralized_log.txt`).*

## Setup

Two agents must push two red boxes onto a goal column (`x=1`) on an open 12×12 grid. One box is **light** (one agent can push it), one is **heavy** (only moves when two agents line up in tandem behind it and push together). Crucially, **box positions and weights are unknown at the start** — the agents must explore to find the boxes, and they only learn a box is heavy by *trying* to push it and failing.

A **single centralized LLM** acts as the team commander. Each cycle it sees a shared belief map of both agents and outputs **one high-level skill per agent**, chosen from a fixed menu:

| Skill | Meaning | Possible outcomes (labels) |
|-------|---------|-----------------------------|
| `explore` | search for boxes | `found_target`, `explored` |
| `goto_push_pose [x,y]` | get behind a box, on the side away from the goal | `in_position`, `blocked` |
| `push [x,y]` | push the box in front toward the goal | `pushed`, `delivered`, `too_heavy`, `blocked` |
| `cooperate_push [x,y]` | two agents jointly push the heavy box | `delivered`, `waiting_partner`, `blocked` |
| `wait` | do nothing | `done` |

The LLM does **not** control individual movements. It picks a skill; a deterministic skill routine then executes many primitive steps (turn/move) and reports back a one-word **outcome label**. That label is fed into the next LLM call, so the LLM plans by *reacting to outcomes* — this is the key loop.

## What the LLM actually chose, cycle by cycle

**Cycle 1 — Explore.**
Nothing is known yet, so the LLM sent **both agents to `explore`**. Its stated reasoning: *"Since neither agent has discovered any target boxes, both agents must prioritize exploration to locate the two required red TARGET boxes."* Both found a box.

**Cycle 2 — Test one box, keep exploring.**
The LLM did **not** pile both agents onto the box it found. It sent `agent_0 → goto_push_pose [6,6]` to test that box, and `agent_1 → explore` to find the second one. Reasoning: *"Agent 0 must test the weight of the discovered box… Agent 1 should continue exploring… adhering to the rule of assigning distinct tasks."* This is correct division of labor — it doesn't yet know the box is heavy, so it commits only one agent.

`agent_0` came back `blocked` (the two agents were briefly contending for the same spot).

**Cycle 3 — Recover and reassign.**
Reacting to the `blocked` label, the LLM swapped roles: `agent_1 → goto_push_pose [6,6]`, `agent_0 → explore`. This shows it using the failure outcome to recover rather than blindly retrying. `agent_1` reached `in_position`.

**Cycle 4 — Attempt the push (discover it's heavy).**
The LLM told `agent_1 → push [1,6]` (push toward the goal) and sent `agent_0 → goto_push_pose [8,4]` to start on the second box in parallel. The push came back **`too_heavy`** — the agents have now *discovered* that box [6,6] is the heavy one.

**Cycle 5 — Switch to cooperation.**
This is the most important decision. Reading the `too_heavy` label, the LLM correctly concluded both agents are needed and assigned **`cooperate_push [6,6]` to *both* agents in the same cycle**. Its reasoning: *"…`too_heavy`… indicating it is now HEAVY. When a box is determined to be heavy, BOTH agents must cooperate using `cooperate_push`."* The joint push **delivered the heavy box** in one cycle.

**Cycle 6 — Move to the remaining box.**
With the heavy box done, the LLM focused the team on the light box at [8,4]: `agent_0 → goto_push_pose [8,4]`, `agent_1 → explore` (to confirm nothing else remains). `agent_0` reached `in_position`.

**Cycle 7 — Finish.**
`agent_0 → push [1,4]` delivered the light box solo. **Episode solved** — both boxes delivered.

## What this demonstrates

The LLM showed four non-trivial coordination behaviors, all emerging from outcome-driven planning rather than hardcoded rules:

1. **Exploration under uncertainty** — it doesn't know where boxes are and explores to find them.
2. **Weight discovery** — it learns a box is heavy *empirically* (by a failed push returning `too_heavy`), not from prior knowledge.
3. **Adaptive cooperation** — it commits one agent to test a box, and only escalates to a two-agent joint push *after* discovering the box is heavy. It avoids wastefully pre-positioning both agents "just in case."
4. **Failure recovery** — when a skill returns `blocked`, it reassigns roles instead of retrying the same losing action.

In short: the LLM is a **reactive team planner** operating over a shared belief map. It chooses *what* each agent should attempt; the environment's outcome labels tell it whether the attempt worked; and it replans accordingly. The successful run shows the full loop closing — explore → test → discover heavy → cooperate → deliver → finish the light box.
