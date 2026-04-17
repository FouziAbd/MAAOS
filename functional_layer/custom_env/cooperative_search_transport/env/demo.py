from constants import Actions
from multi_agent_env import MultiAgentCooperativeSearchTransportEnv
from state import EnvConfig
import time


def main():
    config = EnvConfig(render_mode="human", num_agents=2)
    env = MultiAgentCooperativeSearchTransportEnv(config=config)

    observations, infos = env.reset(seed=42)
    env.render()
    time.sleep(2)
    action_plan = [
        {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.TURN_LEFT},
        {"agent_0": Actions.TURN_RIGHT, "agent_1": Actions.STAY},
        {"agent_0": Actions.MOVE_FORWARD, "agent_1": Actions.STAY},
    ]

    for actions in action_plan:
        observations, rewards, terminations, truncations, infos = env.step(actions)
        env.render()
        print("Rewards:", rewards)
        print("Terminations:", terminations)
        print("Truncations:", truncations)
        print("observations:", observations)

        if all(terminations.values()) or all(truncations.values()):
            break
        #time.sleep(5)
    env.close()


if __name__ == "__main__":
    main()