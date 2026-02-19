import torch
import pyro
import pyro.distributions as dist
import pyro.poutine as poutine
from pyro.infer import SVI, Trace_ELBO, Predictive
from pyro.infer.autoguide import AutoNormal
from pyro.optim import Adam


# ==========================================
# 0. The KAZ World Models
# ==========================================

# ==========================================
# 0. The KAZ World Models (Flattened)
# ==========================================

def given_model(states, actions, next_states=None, rewards=None):
    """A GOOD MODEL: A Bayesian Linear World Model for KAZ."""

    # 1. Dynamically flatten any 3D/4D states into a clean 2D matrix (N, Total_Features)
    states_flat = states.view(states.size(0), -1)
    actions_flat = actions.view(actions.size(0), -1)

    N, state_dim = states_flat.shape
    _, action_dim = actions_flat.shape

    # 2. Priors
    weight_s = pyro.sample("weight_s", dist.Normal(0., 1.).expand([state_dim, state_dim]).to_event(2))
    weight_a = pyro.sample("weight_a", dist.Normal(0., 1.).expand([action_dim, state_dim]).to_event(2))
    weight_r_s = pyro.sample("weight_r_s", dist.Normal(0., 1.).expand([state_dim]).to_event(1))
    weight_r_a = pyro.sample("weight_r_a", dist.Normal(0., 1.).expand([action_dim]).to_event(1))

    # 3. Observations
    with pyro.plate("data_plate", N):
        mean_next_state = torch.matmul(states_flat, weight_s) + torch.matmul(actions_flat, weight_a)
        mean_reward = torch.matmul(states_flat, weight_r_s) + torch.matmul(actions_flat, weight_r_a)

        # Ensure next_states is also flattened before comparing
        if next_states is not None:
            next_states = next_states.view(next_states.size(0), -1)

        pyro.sample("obs_next_state", dist.Normal(mean_next_state, 0.1).to_event(1), obs=next_states)
        pyro.sample("obs_reward", dist.Normal(mean_reward, 0.5), obs=rewards)


def broken_model(states, actions, next_states=None, rewards=None):
    """A BROKEN MODEL: Hallucinates bad tensor shapes."""
    states_flat = states.view(states.size(0), -1)
    actions_flat = actions.view(actions.size(0), -1)

    N, state_dim = states_flat.shape
    _, action_dim = actions_flat.shape

    # THE ERROR: We expand the state weights to the wrong dimensions (state_dim + 5)
    weight_s = pyro.sample("weight_s", dist.Normal(0., 1.).expand([state_dim, state_dim + 5]).to_event(2))
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


def bad_model(states, actions, next_states=None, rewards=None):
    """A BAD MODEL: Runs perfectly, but ignores inputs and guesses randomly."""
    states_flat = states.view(states.size(0), -1)
    N, state_dim = states_flat.shape

    dummy_state_mean = pyro.sample("dummy_s", dist.Normal(0., 1.).expand([state_dim]).to_event(1))
    dummy_reward_mean = pyro.sample("dummy_r", dist.Normal(0., 1.))

    with pyro.plate("data_plate", N):
        # FIX: Flatten next_states so PyTorch doesn't crash during log_prob validation!
        if next_states is not None:
            next_states = next_states.view(next_states.size(0), -1)

        pyro.sample("obs_next_state", dist.Normal(dummy_state_mean, 1.0).to_event(1), obs=next_states)
        pyro.sample("obs_reward", dist.Normal(dummy_reward_mean, 1.0), obs=rewards)


# ==========================================
# 1. The Multi-Dimensional Validator
# ==========================================

def validate_model(model_fn, states, actions, next_states, rewards):
    print(f"\n--- [STEP 1] Running Validator on '{model_fn.__name__}' ---")
    try:
        trace = poutine.trace(model_fn).get_trace(states, actions, next_states, rewards)
        trace.compute_log_prob()

        print("Execution Graph Trace Shapes:")
        print(trace.format_shapes())
        print("Status: [PASS] Validation successful. Tensor matrices align.")
        return True, None

    except Exception as e:
        error_msg = f"Shape mismatch or execution error: {str(e)}"
        print(f"Status: [FAIL] Validation failed.\nError details: {error_msg}")
        return False, error_msg


# ==========================================
# 2. The Multi-Dimensional Inference Engine
# ==========================================

def fit_model(model_fn, states, actions, next_states, rewards, iterations=1000):
    print("\n--- [STEP 2] Running Inference Engine (SVI) ---")
    try:
        guide = AutoNormal(model_fn)
        optimizer = Adam({"lr": 0.01})
        svi = SVI(model_fn, guide, optimizer, loss=Trace_ELBO())

        pyro.clear_param_store()
        print(f"Starting training loop for {iterations} iterations...")

        for step in range(iterations):
            loss = svi.step(states, actions, next_states, rewards)
            if step % 100 == 0:
                print(f"  -> Step {step:^4} | Loss: {loss:.4f}")

        final_loss = svi.step(states, actions, next_states, rewards)
        print(f"  -> Step {iterations:^4} | Final Loss: {final_loss:.4f}")
        print("Status: [PASS] Model successfully fitted to multi-dimensional data.")
        return guide, None

    except Exception as e:
        error_msg = f"Inference diverged or failed: {str(e)}"
        print(f"Status: [FAIL] Inference failed.\nError details: {error_msg}")
        return None, error_msg


# ==========================================
# 3. The Multi-Dimensional Evaluator (MSE Score)
# ==========================================

def evaluate_model(model_fn, guide, states, actions, real_next_states, real_rewards):
    print("\n--- [STEP 3] Running Evaluator (Posterior Predictive Check) ---")
    try:
        predictive = Predictive(model_fn, guide=guide, num_samples=100)
        posterior_predictions = predictive(states, actions, None, None)

        simulated_next_states = posterior_predictions["obs_next_state"].mean(dim=0)
        simulated_rewards = posterior_predictions["obs_reward"].mean(dim=0)

        # FIX: Flatten real_next_states to match the simulated output dimensions (N, 135)
        real_next_states_flat = real_next_states.view(real_next_states.size(0), -1)

        # Calculate Mean Squared Error (MSE) using the flattened tensor
        mse_states = torch.nn.functional.mse_loss(simulated_next_states, real_next_states_flat).item()
        mse_rewards = torch.nn.functional.mse_loss(simulated_rewards, real_rewards).item()

        print("Calculating MSE evaluation scores...")
        print(f"  -> Next State MSE: {mse_states:.4f} (Threshold: 1.0)")
        print(f"  -> Reward MSE:     {mse_rewards:.4f} (Threshold: 1.0)")

        if mse_states < 1.0 and mse_rewards < 1.0:
            print("Status: [PASS] Evaluation successful. Model fits the world dynamics well.")
            return True, None
        else:
            fail_msg = f"Poor fit. State MSE: {mse_states:.4f}, Reward MSE: {mse_rewards:.4f}. Exceeds 1.0 threshold."
            print(f"Status: [FAIL] Evaluation failed.\nReason: {fail_msg}")
            return False, fail_msg

    except Exception as e:
        error_msg = f"Evaluation execution failed: {str(e)}"
        print(f"Status: [FAIL] Evaluation crashed.\nError details: {error_msg}")
        return False, error_msg


# ==========================================
# Main Execution Pipeline
# ==========================================

if __name__ == "__main__":
    print("========================================")
    print("   STARTING MARL WORLD MODEL PIPELINE   ")
    print("========================================")

    # 0. Load Data (Fallback to dummy data if PettingZoo script wasn't run)
    try:
        dataset = torch.load('kaz_transitions.pt', weights_only=True)
        states = dataset['states']
        actions = dataset['actions']
        rewards = dataset['rewards']
        next_states = dataset['next_states']
        print(f"Loaded {len(states)} real transitions from KAZ.")
    except FileNotFoundError:
        print("WARNING: 'kaz_transitions.pt' not found. Generating dummy 2D tensors to test the math...")
        # Simulating 50 timesteps. 11 state features, 1 action feature.
        states = torch.randn(50, 11)
        actions = torch.randn(50, 1)
        next_states = torch.randn(50, 11)
        rewards = torch.randn(50)

    # ⚠️ Swap between given_model / broken_model / bad_model to test the error handling ⚠️
    model_to_test = given_model

    llm_feedback_payload = None

    # 1. Validate
    is_valid, val_error = validate_model(model_to_test, states, actions, next_states, rewards)

    if not is_valid:
        llm_feedback_payload = val_error
        print(f"\n[PIPELINE HALTED] Failed at Validation.")
        print(f"[PAYLOAD FOR LLM] -> '{llm_feedback_payload}'")
    else:
        # 2. Fit
        fitted_guide, fit_error = fit_model(model_to_test, states, actions, next_states, rewards)

        if fitted_guide is None:
            llm_feedback_payload = fit_error
            print(f"\n[PIPELINE HALTED] Failed at Inference.")
            print(f"[PAYLOAD FOR LLM] -> '{llm_feedback_payload}'")
        else:
            # 3. Evaluate
            eval_passed, eval_error = evaluate_model(model_to_test, fitted_guide, states, actions, next_states, rewards)

            if not eval_passed:
                llm_feedback_payload = eval_error
                print(f"\n[PIPELINE HALTED] Failed at Evaluation.")
                print(f"[PAYLOAD FOR LLM] -> '{llm_feedback_payload}'")
            else:
                print("\n========================================")
                print(" [SUCCESS] PIPELINE EXECUTED PERFECTLY! ")
                print("========================================")