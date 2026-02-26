import torch
import os
from dotenv import load_dotenv, find_dotenv
import dspy
import pyro
from dynamic_loader import evaluate_llm_response

# ==========================================
# Setup Cloud LLM (GPT-4o via GitHub)
# ==========================================
load_dotenv(find_dotenv())
my_api_key = os.getenv('GITHUB_TOKEN')

print("Connecting to GPT-4o via GitHub Models...")
lm = dspy.LM(
    model='openai/gpt-4o',
    api_base='https://models.inference.ai.azure.com',
    api_key=my_api_key,
    temperature=0.0  # Keeping this 0.0 for PyTorch syntax stability
)
dspy.settings.configure(lm=lm)


# ==========================================
# 0. Size Evaluator Helper
# ==========================================
def count_model_parameters():
    """Counts total trainable parameters currently loaded in Pyro's memory."""
    total_params = 0
    for name, tensor in pyro.get_param_store().items():
        total_params += tensor.numel()
    return total_params


# ==========================================
# 1. The DSPy Signatures
# ==========================================
class ExpandPyroModel(dspy.Signature):
    """You are a Senior ML Engineer. The current probabilistic model is underfitting.
    EXPAND the model's capacity to lower the Mean Squared Error (MSE).

    CRITICAL PYRO RULES:
    1. Maintain PyTorch dimension broadcasting rules.
    2. DO NOT USE deep neural networks (nn.Sequential, nn.Linear, etc.).
    3. Use `pyro.param("name", torch.randn(...))` for weights. Do NOT use `pyro.sample` for weights.
    4. You MUST append `.to_event(1)` when sampling multi-dimensional next_states in the plate. Example: `dist.Normal(mean, var).to_event(1)`
    5. DO NOT invent arbitrary dimensions. If you add latent variables using `pyro.sample`, put them INSIDE the `with pyro.plate("data_plate", N):` block so they match the batch size N.
    """
    current_working_code = dspy.InputField(desc="The baseline model.")
    empirical_feedback = dspy.InputField(desc="Feedback on current MSE and goals.")
    error_feedback = dspy.InputField(desc="Crash logs from previous attempts, if any.")

    expanded_code = dspy.OutputField(
        desc="A valid Python code block enclosed in ```python tags with added capacity (e.g., latents, dynamic variance).")


class ReducePyroModel(dspy.Signature):
    """You are a Senior Software Engineer. The model's MSE is good, but the math is too complex for fast real-time inference.
    PRUNE the model to make it faster while keeping the MSE below the target threshold.

    CRITICAL PYRO RULES:
    1. Maintain PyTorch dimension broadcasting rules. `mean_next_state` MUST remain shape `(N, state_dim)`.
    2. Do NOT alter the core matrix shapes (e.g., `weight_s` must remain `[state_dim, state_dim]`). Shrinking them into 1D vectors will crash `torch.matmul`.
    3. To reduce parameters safely, focus ONLY on deleting latent variables (`pyro.sample` inside the plate) or reverting learnable variances to static tensors.
    4. Use `pyro.param("name", torch.randn(...))` for weights. Do NOT use `pyro.sample` for weights.
    5. The function MUST be named exactly `ai_generated_model`. Do not change the name.
    """
    current_working_code = dspy.InputField(desc="The accurate but overly complex model.")
    empirical_feedback = dspy.InputField(desc="The target MSE we must stay below.")
    error_feedback = dspy.InputField(desc="Crash logs or MSE failures from previous attempts.")

    reduced_code = dspy.OutputField(
        desc="A valid Python code block enclosed in ```python tags with simplified math and removed parameters.")


# ==========================================
# 2. The Isolated Functions
# ==========================================
def expand_model(current_code, current_mse, current_size, states, actions, next_states, rewards, target_mse=0.01,
                 max_retries=3):
    print("\n" + "=" * 50)
    print(f"🚀 INITIATING EXPANSION")
    print(f"   Current MSE: {current_mse:.4f} | Current Size: {current_size} Params")
    print("=" * 50)

    expander = dspy.Predict(ExpandPyroModel)
    error_msg = "None. First expand attempt."

    for attempt in range(1, max_retries + 1):
        print(f"\n--- Expand Attempt {attempt}/{max_retries} ---")
        feedback = f"Current State MSE is {current_mse:.4f}. It must be below {target_mse}. Add latent variables or dynamic variance to increase capacity."

        response = expander(current_working_code=current_code, empirical_feedback=feedback, error_feedback=error_msg)
        new_code = response.expanded_code

        print("\n--- RAW EXPANDED CODE ---")
        print(new_code)
        print("-------------------------\n")

        print("Evaluating expanded code...")
        success, crash_log, new_evidence = evaluate_llm_response(new_code, states, actions, next_states, rewards)

        if success and new_evidence['mse_states'] < current_mse:
            new_size = count_model_parameters()
            print(f"✅ Expansion Successful!")
            print(f"   MSE Improved: {current_mse:.4f} -> {new_evidence['mse_states']:.4f}")
            print(f"   Model Size:   {current_size} -> {new_size} parameters")
            return True, new_code, new_evidence['mse_states'], new_size
        else:
            if not success:
                error_msg = f"Code crashed. Log: {crash_log}"
            else:
                error_msg = f"Expansion worsened MSE to {new_evidence['mse_states']:.4f}. Try a different, more stable expansion technique."
            print(f"❌ Expansion Failed. Reason: {error_msg}")

    print("⚠️ Max retries reached. Expansion failed.")
    return False, current_code, current_mse, current_size


def reduce_model(current_code, current_mse, current_size, states, actions, next_states, rewards, target_mse=0.01,
                 max_retries=3):
    print("\n" + "=" * 50)
    print(f"🪓 INITIATING REDUCTION")
    print(f"   Current MSE: {current_mse:.4f} (Must stay < {target_mse})")
    print(f"   Current Size: {current_size} Params")
    print("=" * 50)

    reducer = dspy.Predict(ReducePyroModel)
    error_msg = "None. First reduce attempt."

    for attempt in range(1, max_retries + 1):
        print(f"\n--- Reduce Attempt {attempt}/{max_retries} ---")
        feedback = f"Current State MSE is {current_mse:.4f}. Prune the model complexity (remove matrices or latent plates) to reduce the parameter count below {current_size}, but keep MSE strictly below {target_mse}."

        response = reducer(current_working_code=current_code, empirical_feedback=feedback, error_feedback=error_msg)
        new_code = response.reduced_code

        print("\n--- RAW REDUCED CODE ---")
        print(new_code)
        print("------------------------\n")

        print("Evaluating reduced code...")
        success, crash_log, new_evidence = evaluate_llm_response(new_code, states, actions, next_states, rewards)

        if success and new_evidence['mse_states'] <= target_mse:
            new_size = count_model_parameters()
            print(f"✅ Reduction Successful!")
            print(f"   New MSE:    {new_evidence['mse_states']:.4f} (Still safe)")
            print(f"   Model Size: {current_size} -> {new_size} parameters")
            return True, new_code, new_evidence['mse_states'], new_size
        else:
            if not success:
                error_msg = f"Code crashed. Log: {crash_log}"
            else:
                error_msg = f"Pruning pushed MSE too high ({new_evidence['mse_states']:.4f} > {target_mse}). You removed too much capacity. Prune fewer parameters."
            print(f"❌ Reduction Failed. Reason: {error_msg}")

    print("⚠️ Max retries reached. Reduction failed to maintain target MSE.")
    return False, current_code, current_mse, current_size


# ==========================================
# 3. The Isolated Test Main
# ==========================================
if __name__ == "__main__":
    import random
    import numpy as np

    # Lock Randomness
    SEED = 123
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    pyro.set_rng_seed(SEED)

    # 1. Load Data
    try:
        dataset = torch.load('kaz_transitions.pt', weights_only=True)
        states, actions = dataset['states'], dataset['actions']
        rewards, next_states = dataset['rewards'], dataset['next_states']
        print("Loaded actual game transitions.")
    except FileNotFoundError:
        print("Using dummy tensors for testing...")
        states, actions = torch.randn(50, 11), torch.randn(50, 1)
        next_states, rewards = torch.randn(50, 11), torch.randn(50)

    # 2. Hardcode the Baseline Model
    baseline_code = """
import pyro
import pyro.distributions as dist
import torch

def ai_generated_model(states, actions, next_states=None, rewards=None):
    # 1. Flatten the inputs
    states_flat = states.view(states.size(0), -1)
    actions_flat = actions.view(actions.size(0), -1)
    N, state_dim = states_flat.shape
    _, action_dim = actions_flat.shape

    # 2. Define Priors
    weight_s = pyro.param("weight_s", torch.randn(state_dim, state_dim))
    weight_a = pyro.param("weight_a", torch.randn(action_dim, state_dim))
    bias_s = pyro.param("bias_s", torch.randn(state_dim))
    weight_r_s = pyro.param("weight_r_s", torch.randn(state_dim, 1))
    weight_r_a = pyro.param("weight_r_a", torch.randn(action_dim, 1))
    bias_r = pyro.param("bias_r", torch.randn(1))

    # 3. Plate and Observations
    with pyro.plate("data_plate", N):
        # Calculate mean_next_state and mean_reward
        mean_next_state = torch.matmul(states_flat, weight_s) + torch.matmul(actions_flat, weight_a) + bias_s
        mean_reward = torch.matmul(states_flat, weight_r_s) + torch.matmul(actions_flat, weight_r_a) + bias_r

        # Flatten next_states for comparison
        if next_states is not None:
            next_states = next_states.view(next_states.size(0), -1)

        # Sample 'obs_next_state' (using obs=next_states). REMEMBER .to_event(1)!
        pyro.sample("obs_next_state", dist.Normal(mean_next_state, 1.0).to_event(1), obs=next_states)

        # Sample 'obs_reward' (using obs=rewards)
        pyro.sample("obs_reward", dist.Normal(mean_reward.squeeze(-1), 1.0), obs=rewards)
"""

    print("\nEvaluating Baseline to get initial stats...")
    success, log, baseline_evidence = evaluate_llm_response(baseline_code, states, actions, next_states, rewards)

    if not success:
        print("Baseline crashed. Check setup.")
        exit()

    initial_mse = baseline_evidence['mse_states']
    initial_size = count_model_parameters()
    target_mse = 0.0100

    print("\n" + "=" * 50)
    print("   BASELINE COMPILED SUCCESSFULLY")
    print(f"   Baseline MSE:  {initial_mse:.4f}")
    print(f"   Baseline Size: {initial_size} parameters")
    print("=" * 50)

    # --- TEST 1: EXPAND ---
    expand_success, expanded_code, expanded_mse, expanded_size = expand_model(
        baseline_code, initial_mse, initial_size, states, actions, next_states, rewards, target_mse=target_mse
    )

    if expand_success:
        # --- TEST 2: REDUCE ---
        reduce_success, final_code, final_mse, final_size = reduce_model(
            expanded_code, expanded_mse, expanded_size, states, actions, next_states, rewards, target_mse=target_mse
        )

        print("\n" + "=" * 50)
        print("=== FINAL PIPELINE RESULTS ===")
        print(f"{'Phase':<15} | {'Parameters':<10} | {'State MSE':<10}")
        print("-" * 50)
        print(f"{'1. Baseline':<15} | {initial_size:<10} | {initial_mse:.4f}")
        print(f"{'2. Expanded':<15} | {expanded_size:<10} | {expanded_mse:.4f} (Goal: < {target_mse})")
        if reduce_success:
            print(f"{'3. Reduced':<15} | {final_size:<10} | {final_mse:.4f} (Kept Safe)")
        else:
            print("Reduction phase failed or skipped.")
        print("=" * 50)
    else:
        print("\nSkipping Reduce test because Expand test failed.")