from .env.toy_rescue_env import ToyRescueEnv
from pettingzoo.utils import parallel_to_aec, wrappers

def parallel_env(render_mode=None):
    """
    Returns the Parallel Environment.
    """
    env = ToyRescueEnv(render_mode=render_mode)
    # Optional: Add standard wrappers here if needed
    # env = wrappers.AssertOutOfBoundsWrapper(env)
    # env = wrappers.OrderEnforcingWrapper(env)
    return env

def env(render_mode=None):
    """
    Returns the AEC (Agent Environment Cycle) Environment.
    Wraps the parallel environment using parallel_to_aec.
    """
    env = parallel_env(render_mode=render_mode)
    env = parallel_to_aec(env)
    return env