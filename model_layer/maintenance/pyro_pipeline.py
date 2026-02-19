import torch
import pyro
import pyro.distributions as dist
import pyro.poutine as poutine
from pyro.infer import SVI, Trace_ELBO, Predictive
from pyro.infer.autoguide import AutoNormal
from pyro.optim import Adam

# ==========================================
# 0. Baseline Data and Models
# ==========================================

# Dummy known data (e.g., 7 heads, 3 tails)
known_data = torch.tensor([1., 0., 1., 1., 0., 1., 1., 1., 0., 1.])


def given_model(data=None):
    """A GOOD MODEL: correctly infers the hidden bias of a coin."""
    mean = pyro.sample("mean", dist.Uniform(0.0, 1.0))
    size = len(data) if data is not None else len(known_data)

    with pyro.plate("data_plate", size):
        return pyro.sample("obs", dist.Bernoulli(mean), obs=data)


def broken_model(data=None):
    """A BROKEN MODEL: Hallucinates bad tensor shapes."""
    with pyro.plate("mean_plate", 3):
        mean = pyro.sample("mean", dist.Uniform(0.0, 1.0))  # Shape: (3,)

    size = len(data) if data is not None else len(known_data)
    with pyro.plate("data_plate", size):
        # CRASH: PyTorch cannot broadcast a tensor of shape (3,) against (10,)
        return pyro.sample("obs", dist.Bernoulli(mean), obs=data)


# ==========================================
# 1. The Validator
# ==========================================

def validate_model(model_fn, data):
    print(f"\n--- [STEP 1] Running Validator on '{model_fn.__name__}' ---")
    try:
        trace = poutine.trace(model_fn).get_trace(data)
        trace.compute_log_prob()

        print("Execution Graph Trace Shapes:")
        print(trace.format_shapes())
        print("Status: [PASS] Validation successful. Tensor shapes align.")
        return True, None

    except Exception as e:
        error_msg = f"Shape mismatch or execution error: {str(e)}"
        print(f"Status: [FAIL] Validation failed.\nError details: {error_msg}")
        return False, error_msg


# ==========================================
# 2. The Inference Engine
# ==========================================

def fit_model(model_fn, data, iterations=500):
    print("\n--- [STEP 2] Running Inference Engine (SVI) ---")
    try:
        guide = AutoNormal(model_fn)
        optimizer = Adam({"lr": 0.02})
        svi = SVI(model_fn, guide, optimizer, loss=Trace_ELBO())

        pyro.clear_param_store()
        print(f"Starting training loop for {iterations} iterations...")

        for step in range(iterations):
            loss = svi.step(data)
            if step % 100 == 0:
                print(f"  -> Step {step:^4} | Loss: {loss:.4f}")

        # Calculate final loss at the last step
        final_loss = svi.step(data)
        print(f"  -> Step {iterations:^4} | Final Loss: {final_loss:.4f}")
        print("Status: [PASS] Model successfully fitted.")
        return guide, None

    except Exception as e:
        error_msg = f"Inference diverged or failed: {str(e)}"
        print(f"Status: [FAIL] Inference failed.\nError details: {error_msg}")
        return None, error_msg


# ==========================================
# 3. The Evaluator
# ==========================================

def evaluate_model(model_fn, guide, original_data):
    print("\n--- [STEP 3] Running Evaluator (Posterior Predictive Check) ---")
    try:
        predictive = Predictive(model_fn, guide=guide, num_samples=500)
        posterior_predictions = predictive(data=None)
        simulated_data = posterior_predictions["obs"]

        real_mean = original_data.mean().item()
        simulated_mean = simulated_data.float().mean().item()
        difference = abs(real_mean - simulated_mean)

        print("Calculating evaluation scores...")
        print(f"  -> Real Data Mean:      {real_mean:.4f}")
        print(f"  -> Simulated Data Mean: {simulated_mean:.4f}")
        print(f"  -> Absolute Difference: {difference:.4f} (Threshold: 0.15)")

        if difference < 0.15:
            print("Status: [PASS] Evaluation successful. Model fits the data well.")
            return True, None
        else:
            fail_msg = f"Poor fit. Real mean: {real_mean:.4f}, Simulated mean: {simulated_mean:.4f}. Difference ({difference:.4f}) exceeds 0.15 threshold."
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
    print("   STARTING PYRO EVALUATION PIPELINE    ")
    print("========================================")

    # ⚠️ Swap between given_model and broken_model to test the error handling ⚠️
    model_to_test = given_model

    llm_feedback_payload = None

    # 1. Validate
    is_valid, val_error = validate_model(model_to_test, known_data)

    if not is_valid:
        llm_feedback_payload = val_error
        print(f"\n[PIPELINE HALTED] Failed at Validation.")
        print(f"[PAYLOAD FOR LLM] -> '{llm_feedback_payload}'")
    else:
        # 2. Fit
        fitted_guide, fit_error = fit_model(model_to_test, known_data)

        if fitted_guide is None:
            llm_feedback_payload = fit_error
            print(f"\n[PIPELINE HALTED] Failed at Inference.")
            print(f"[PAYLOAD FOR LLM] -> '{llm_feedback_payload}'")
        else:
            # 3. Evaluate
            eval_passed, eval_error = evaluate_model(model_to_test, fitted_guide, known_data)

            if not eval_passed:
                llm_feedback_payload = eval_error
                print(f"\n[PIPELINE HALTED] Failed at Evaluation.")
                print(f"[PAYLOAD FOR LLM] -> '{llm_feedback_payload}'")
            else:
                print("\n========================================")
                print(" [SUCCESS] PIPELINE EXECUTED PERFECTLY! ")
                print("========================================")