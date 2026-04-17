"""
Hardcoded cooperative solution for CooperativeSearchTransport.

Grid layout (12×12, y increases downward):
  Walls  : outer border + x=4 (gaps y=3,y=8) + x=8 (gap y=6)
  Delivery zone : (1,1),(2,1),(1,2),(2,2)
  Object-0 (target, requires 2 agents) : (2,9)
  Object-1 (target, requires 1 agent)  : (6,5)
  Agent-0 start : (10,10) facing LEFT
  Agent-1 start : (10,9)  facing LEFT

Strategy:
  1. Agent-1 navigates through the x=8 gap (y=6) and x=4 gap (y=8) to reach
     (2,8) and engages Object-0 (latch #1 of 2).
  2. Simultaneously, Agent-0 follows the same corridor, picks up Object-1 at
     (6,5), carries it through the x=4 gap (y=3) and delivers it to (2,1).
  3. Agent-0 then goes south along x=2 to (2,10) and engages Object-0
     (latch #2 of 2 — object is now jointly held and off-grid).
  4. Both agents turn to face UP and carry Object-0 north 7 steps until it
     reaches (2,2), which is inside the delivery zone.

Direction arithmetic (TURN_LEFT = (dir-1)%4, TURN_RIGHT = (dir+1)%4):
  RIGHT=0  DOWN=1  LEFT=2  UP=3
"""

import time
from constants import Actions
from multi_agent_env import MultiAgentCooperativeSearchTransportEnv
from state import EnvConfig

# Action shortcuts
L = Actions.TURN_LEFT
R = Actions.TURN_RIGHT
F = Actions.MOVE_FORWARD
S = Actions.STAY
P = Actions.PICK_OR_INTERACT
D = Actions.DROP


def main():
    config = EnvConfig(
        width=12,
        height=12,
        num_agents=2,
        num_objects=4,
        num_target_objects=2,
        max_steps=100,
        agent_view_size=3,
        render_mode="human",
        seed=42,
    )

    env = MultiAgentCooperativeSearchTransportEnv(config=config)
    env.reset(seed=42)

    print("\n" + "=" * 72)
    print("HARDCODED COOPERATIVE SOLUTION")
    print("=" * 72)
    print("Agent-0 (green) : solo-carries Object-1 (6,5) → delivers to (2,1)")
    print("Agent-1 (red)   : reaches (2,8), latches onto Object-0 (2,9) first")
    print("Both agents     : jointly carry Object-0 north to delivery zone")
    print("=" * 72 + "\n")
    env.render()
    time.sleep(0.5)

    # ------------------------------------------------------------------
    # Each row: (description, agent_0_action, agent_1_action)
    # Directions after each step are tracked in comments for clarity.
    # ------------------------------------------------------------------
    # fmt: off
    sequence = [
        # ── Phase 1: both agents navigate toward the x=8 gap at y=6 ──────────
        # a0=(10,10)L  a1=(10,9)L
        ("a1 L→UP",                        S, R),   # a1: LEFT→UP
        ("a1 →(10,8)",                     S, F),
        ("a1 →(10,7)  a0 L→UP",            R, F),   # a0: LEFT→UP
        ("a1 →(10,6)  a0 →(10,9)",         F, F),
        ("a1 UP→LEFT  a0 →(10,8)",         F, L),   # a1: UP→LEFT
        ("a1 →(9,6)   a0 →(10,7)",         F, F),
        ("a1 →(8,6)[x=8 gap]  a0 →(10,6)", F, F),
        ("a1 →(7,6)   a0 UP→LEFT",         L, F),   # a0: UP→LEFT
        ("a1 →(6,6)   a0 →(9,6)",          F, F),
        # ── Phase 2: a1 turns south toward Object-0; a0 continues left ───────
        # a0=(8,6)L  a1=(6,6)L
        ("a1 LEFT→DOWN  a0 →(8,6)",        F, L),   # a1: LEFT→DOWN
        ("a1 →(6,7)  a0 →(7,6)",           F, F),
        ("a1 →(6,8)  a0 →(6,6)",           F, F),
        # ── Phase 3: a0 picks up Object-1 ────────────────────────────────────
        # a0=(6,6)L  a1=(6,8)D
        ("a0 LEFT→UP  a1 DOWN→LEFT",       R, R),   # a0: L→UP  a1: D→L
        ("a0 PICK Object-1 at (6,5)  a1 →(5,8)", P, F),
        # ── Phase 4: a0 carries Object-1 north; a1 cuts through x=4 gap(y=8) ─
        # a0=(6,6)U carrying Obj1   a1=(5,8)L
        ("a0 →(6,5)  a1 →(4,8)[x=4 gap]", F, F),
        ("a0 →(6,4)  a1 →(3,8)",           F, F),
        ("a0 →(6,3)  a1 →(2,8)",           F, F),
        # ── Phase 5: a0 turns to head through x=4 gap(y=3); a1 engages Obj-0 ─
        # a0=(6,3)U  a1=(2,8)L
        ("a0 UP→LEFT  a1 LEFT→DOWN",       L, L),
        ("a0 →(5,3)  a1 ENGAGES Object-0", F, P),   # a1 latches on (engaged #1)
        ("a0 →(4,3)[x=4 gap]  a1 waits",  F, S),
        ("a0 →(3,3)  a1 waits",            F, S),
        ("a0 LEFT→UP  a1 waits",           R, S),
        ("a0 →(3,2)  a1 waits",            F, S),
        ("a0 →(3,1)  a1 waits",            F, S),
        ("a0 UP→LEFT  a1 waits",           L, S),
        ("a0 →(2,1)[delivery zone]  a1",   F, S),
        ("a0 DROP Object-1 → DELIVERED!",  D, S),   # +20 reward
        # ── Phase 6: a0 goes south to (2,10); a1 loops to (2,10) via (3,x) ───
        # a0=(2,1)L  a1=(2,8)D
        ("a0 LEFT→DOWN  a1 DOWN→RIGHT",    L, L),   # a1: DOWN→RIGHT
        ("a0 →(2,2)  a1 →(3,8)",           F, F),
        ("a0 →(2,3)  a1 RIGHT→DOWN",       F, R),
        ("a0 →(2,4)  a1 →(3,9)",           F, F),
        ("a0 →(2,5)  a1 →(3,10)",          F, F),
        ("a0 →(2,6)  a1 DOWN→LEFT",        F, R),   # a1: DOWN→LEFT
        ("a0 →(2,7)  a1 →(2,10)",          F, F),
        ("a0 →(2,8)  a1 LEFT→UP",          F, R),   # a1 at (2,10) now faces UP
        # ── Phase 7: a0 completes joint engagement ───────────────────────────
        # a0=(2,8)D  a1=(2,10)U   Object-0 at (2,9)
        ("a0 ENGAGES Object-0 → jointly held!", P, S),  # engaged #2 → off-grid
        # ── Phase 8: a0 turns from DOWN to UP (2× TURN_LEFT) ─────────────────
        ("a0 DOWN→RIGHT",                  L, S),
        ("a0 RIGHT→UP — both face UP now", L, S),
        # ── Phase 9: cooperative carry north ×7 ──────────────────────────────
        # Object travels (2,9)→(2,8)→…→(2,2).  (2,2) is in the delivery zone.
        ("carry ×1 : Object →(2,8)",       F, F),
        ("carry ×2 : Object →(2,7)",       F, F),
        ("carry ×3 : Object →(2,6)",       F, F),
        ("carry ×4 : Object →(2,5)",       F, F),
        ("carry ×5 : Object →(2,4)",       F, F),
        ("carry ×6 : Object →(2,3)",       F, F),
        ("carry ×7 : Object →(2,2) DELIVERED!", F, F),  # +20 each → episode ends
    ]
    # fmt: on

    action_names = {L: "TURN_L", R: "TURN_R", F: "FWD", S: "STAY", P: "PICK", D: "DROP"}

    for step_idx, (desc, a0_act, a1_act) in enumerate(sequence):
        actions = {"agent_0": a0_act, "agent_1": a1_act}
        _, rewards, terminations, truncations, _ = env.step(actions)
        env.render()

        r0 = rewards.get("agent_0", 0.0)
        r1 = rewards.get("agent_1", 0.0)
        print(
            f"Step {step_idx + 1:2d} | {desc:50s} | "
            f"a0={action_names[a0_act]:6s} R={r0:+.2f} | "
            f"a1={action_names[a1_act]:6s} R={r1:+.2f}"
        )

        if all(terminations.values()):
            print("\n✓  SUCCESS — all targets delivered!")
            break
        if all(truncations.values()):
            print("\n✗  Episode truncated (max steps reached)")
            break

        time.sleep(0.2)

    env.close()
    print("\nDemo finished.")


if __name__ == "__main__":
    main()
