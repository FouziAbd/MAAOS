"""
Simple multi-agent demo with hardcoded action sequence to solve the task.

This demo shows agent movements that exploit the known grid layout to 
find and deliver target packages.
"""

from constants import Actions, Directions
from multi_agent_env import MultiAgentCooperativeSearchTransportEnv
from state import EnvConfig
import time


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
    observations, infos = env.reset(seed=42)
    
    print("\n" + "="*70)
    print("MULTI-AGENT SIMPLE SOLUTION - HARDCODED ACTIONS")
    print("="*70)
    print("Agent 0 (Green): Searches left & up, finds object, delivers")
    print("Agent 1 (Red):   Supports Agent 0, clears path")
    print("="*70 + "\n")
    
    env.render()
    time.sleep(0.5)
    
    action_names = {
        Actions.TURN_LEFT: "TURN_LEFT",
        Actions.TURN_RIGHT: "TURN_RIGHT",
        Actions.MOVE_FORWARD: "MOVE_FWD",
        Actions.STAY: "STAY",
        Actions.PICK_OR_INTERACT: "PICK",
        Actions.DROP: "DROP",
        Actions.COOPERATE: "COOP",
    }
    
    # Hardcoded action sequence to solve the problem
    # Starting: Agent0 at (10,10) facing LEFT, Agent1 at (10,9)
    # KEY FIX: Agent 1 stays in place while Agent 0 explores (avoid collisions)
    action_sequence = [
        ("agent_0: MOVE towards x=0 ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: TURN RIGHT ", {"agent_0": Actions.TURN_RIGHT, "agent_1": Actions.STAY}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_RIGHT}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: TURN LEFT ", {"agent_0": Actions.TURN_LEFT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_LEFT}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: TURN RIGHT ", {"agent_0": Actions.TURN_RIGHT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: PICK UP ", {"agent_0": Actions.PICK_OR_INTERACT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_RIGHT}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: TURN LEFT", {"agent_0": Actions.TURN_LEFT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_LEFT}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: TURN RIGHT ", {"agent_0": Actions.TURN_RIGHT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_LEFT}),
        ("agent_0: DROP ", {"agent_0": Actions.DROP, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: TURN RIGHT ", {"agent_0": Actions.TURN_RIGHT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: TURN RIGHT ", {"agent_0": Actions.TURN_RIGHT, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.MOVE_FORWARD}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_RIGHT}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: PICK UP ", {"agent_0": Actions.PICK_OR_INTERACT, "agent_1": Actions.PICK_OR_INTERACT}),
        ("agent_0: TURN LEFT ", {"agent_0": Actions.TURN_LEFT, "agent_1": Actions.TURN_RIGHT}),
        ("agent_0: MOVE LEFT ", {"agent_0": Actions.TURN_LEFT, "agent_1": Actions.STAY}),
        ("agent_0: MOVE ", {"agent_0": Actions.COOPERATE, "agent_1": Actions.COOPERATE}),
        ("agent_0: MOVE ", {"agent_0": Actions.COOPERATE, "agent_1": Actions.COOPERATE}),
        ("agent_0: MOVE ", {"agent_0": Actions.COOPERATE, "agent_1": Actions.COOPERATE}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: MOVE ", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        ("agent_0: DROP ", {"agent_0": Actions.DROP, "agent_1": Actions.STAY}),
        #("agent_0: MOVE_back_to_delivery", {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY}),
        #("agent_0: DROP_2nd_object", {"agent_0": Actions.DROP, "agent_1": Actions.STAY}),
    ]
    
    # Execute action sequence
    for step, (description, actions) in enumerate(action_sequence):
        observations, rewards, terminations, truncations, infos = env.step(actions)
        env.render()
        
        print(f"Step {step+1:2d} | {description:40s} | " +
              f"R0={rewards['agent_0']:+.3f}, R1={rewards['agent_1']:+.3f}")
        
        if all(terminations.values()):
            print("\n✓ SUCCESS! All targets delivered!")
            break
        
        if all(truncations.values()):
            print("\n✗ Episode truncated")
            break
        
        time.sleep(0.3)
    
    env.close()
    print("\nDemo finished.")


if __name__ == "__main__":
    main()
