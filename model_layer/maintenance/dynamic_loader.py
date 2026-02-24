import re
import torch
import pyro
import pyro.distributions as dist
from pyro_pipeline import validate_model, fit_model, evaluate_model

# ==========================================
# 1. Simulate the LLM Response (Safely Formatted)
# ==========================================
# We use this MD variable to prevent Markdown parsers from breaking the text block
MD = "```"

good_mock_llm_response = f"""
Certainly! Here is the Bayesian Linear World Model you requested for the Knights Archers Zombies environment.

{MD}python
import torch
import pyro
import pyro.distributions as dist

def ai_generated_model(states, actions, next_states=None, rewards=None):
    states_flat = states.view(states.size(0), -1)
    actions_flat = actions.view(actions.size(0), -1)

    N, state_dim = states_flat.shape
    _, action_dim = actions_flat.shape

    weight_s = pyro.sample("weight_s", dist.Normal(0., 1.).expand([state_dim, state_dim]).to_event(2))
    weight_a = pyro.sample("weight_a", dist.Normal(0., 1.).expand([action_dim, state_dim]).to_event(2))
    weight_r_s = pyro.sample("weight_r_s", dist.Normal(0., 1.).expand([state_dim]).to_event(1))
    weight_r_a = pyro.sample("weight_r_a", dist.Normal(0., 1.).expand([action_dim]).to_event(1))

    with pyro.plate("data_plate", N):
        mean_next_state = torch.matmul(states_flat, weight_s) + torch.matmul(actions_flat, weight_a)
        mean_reward = torch.matmul(states_flat, weight_r_s) + torch.matmul(actions_flat, weight_r_a)

        if next_states is not None:
            next_states = next_states.view(next_states.size(0), -1)

        pyro.sample("obs_next_state", dist.Normal(mean_next_state, 0.1).to_event(1), obs=next_states)
        pyro.sample("obs_reward", dist.Normal(mean_reward, 0.5), obs=rewards)
{MD}

Let me know if you need this adjusted!
"""

syntax_error_mock_llm_response = f"""
{MD}python
def ai_generated_model(states, actions)
    return states
{MD}
"""

bad_shape_mock_llm_response = f"""
{MD}python
import torch
import pyro
import pyro.distributions as dist

def ai_generated_model(states, actions, next_states=None, rewards=None):
    states_flat = states.view(states.size(0), -1)
    N, state_dim = states_flat.shape

    # Bad math: state_dim + 5
    weight_s = pyro.sample("w_s", dist.Normal(0., 1.).expand([state_dim, state_dim + 5]).to_event(2))

    with pyro.plate("data", N):
        mean_next = torch.matmul(states_flat, weight_s)
        pyro.sample("obs", dist.Normal(mean_next, 0.1).to_event(1), obs=next_states)
{MD}
"""


# ==========================================
# 2. The Code Extractor
# ==========================================
def extract_python_code(llm_text):
    """Uses Regex to find the text between the python markdown tags, with fallbacks."""
    print("--- Extracting Code from LLM Response ---")

    # 1. Try to find the strict ```python ... ``` block
    match_strict = re.search(r'```python\n?(.*?)\n?```', llm_text, re.DOTALL)
    if match_strict:
        print("[PASS] Successfully extracted strict Python code block.")
        return match_strict.group(1)

    # 2. Try to find a generic ``` ... ``` block (LLM forgot the 'python' label)
    match_generic = re.search(r'```\n?(.*?)\n?```', llm_text, re.DOTALL)
    if match_generic:
        print("[PASS] Successfully extracted generic markdown code block.")
        return match_generic.group(1)

    # 3. Fallback: Assume the LLM just output raw code without any markdown tags
    print("[WARNING] No markdown tags found. Attempting to parse raw text as code...")
    # Clean up any weird leading/trailing whitespace
    return llm_text.strip()


# ==========================================
# 3. The Dynamic Executor
# ==========================================
def load_model_from_string(code_string, function_name="ai_generated_model"):
    """Safely compiles the string into a Python function in memory."""
    print(f"\n--- Dynamically Compiling '{function_name}' ---")

    # Pre-load the necessary libraries so the LLM code doesn't crash if it forgets imports
    isolated_namespace = {
        'torch': torch,
        'pyro': pyro,
        'dist': dist
    }

    try:
        exec(code_string, isolated_namespace)

        if function_name in isolated_namespace:
            print(f"[PASS] Function '{function_name}' successfully loaded into memory.\n")
            return isolated_namespace[function_name], None
        else:
            return None, f"Error: The LLM did not name the function '{function_name}'."

    except Exception as e:
        return None, f"Syntax Error in LLM Code: {str(e)}"


# ==========================================
# 4. The Master Evaluation Wrapper
# ==========================================
def evaluate_llm_response(llm_response_string, states, actions, next_states, rewards):
    # Step A & B
    extracted_code = extract_python_code(llm_response_string)
    if not extracted_code: return False, "Error: No markdown tags.", None
    model_to_test, compilation_error = load_model_from_string(extracted_code)
    if not model_to_test: return False, compilation_error, None

    # Step C & D
    is_valid, val_error = validate_model(model_to_test, states, actions, next_states, rewards)
    if not is_valid: return False, val_error, None
    fitted_guide, fit_error = fit_model(model_to_test, states, actions, next_states, rewards, iterations=1000)
    if not fitted_guide: return False, fit_error, None

    # Step E: Evaluate now catches the empirical evidence
    eval_passed, eval_error, empirical_evidence = evaluate_model(model_to_test, fitted_guide, states, actions, next_states, rewards)
    if not eval_passed:
        return False, eval_error, None

    return True, "Success!", empirical_evidence


# ==========================================
# Main Execution
# ==========================================
if __name__ == "__main__":
    print("========================================")
    print("      STARTING DYNAMIC LLM LOADER       ")
    print("========================================")

    # 1. Load Data
    try:
        dataset = torch.load('kaz_transitions.pt', weights_only=True)
        test_states = dataset['states']
        test_actions = dataset['actions']
        test_rewards = dataset['rewards']
        test_next_states = dataset['next_states']
        print(f"Loaded {len(test_states)} real transitions from KAZ.\n")
    except FileNotFoundError:
        print("WARNING: 'kaz_transitions.pt' not found. Using dummy tensors.\n")
        test_states, test_actions = torch.randn(50, 11), torch.randn(50, 1)
        test_next_states, test_rewards = torch.randn(50, 11), torch.randn(50)

    # 2. Select Mock Response to Test
    # Try changing this to good_mock_llm_response or bad_shape_mock_llm_response to see the different pipeline branches!
    current_mock_test = bad_shape_mock_llm_response

    # 3. Run the Pipeline Wrapper
    success, feedback = evaluate_llm_response(
        current_mock_test,
        test_states,
        test_actions,
        test_next_states,
        test_rewards
    )

    # 4. Print Final Payload
    if success:
        print("\n========================================")
        print("[FINAL RESULT] Model is ready for MARL integration!")
        print("========================================")
    else:
        print("\n========================================")
        print(f"[FINAL RESULT] Pipeline Failed. Sending this payload back to LLM:\n'{feedback}'")
        print("========================================")