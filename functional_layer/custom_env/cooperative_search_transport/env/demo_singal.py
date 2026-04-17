from constants import Actions
from cooperative_search_transport_env import CooperativeSearchTransportMiniGridEnv
from state import EnvCoreConfig
import time


def main():
    config = EnvCoreConfig(render_mode="human")
    env = CooperativeSearchTransportMiniGridEnv(config=config)

    observations, infos = env.reset(seed=42)
    env.render()

    action_plan = [
        Actions.MOVE_FORWARD,
        Actions.TURN_RIGHT,
        Actions.MOVE_FORWARD,
    ]

    for actions in action_plan:
        observations, rewards, terminations, truncations, infos = env.step(actions)
        env.render()
        print("Rewards:", rewards)
        print("Terminations:", terminations)
        print("Truncations:", truncations)
        print("observations:", observations)
        print("infos:", infos)

        if terminations or truncations:
            break
        time.sleep(2)
    env.close()


if __name__ == "__main__":
    main()