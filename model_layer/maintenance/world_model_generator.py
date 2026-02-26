import torch
from dynamic_loader import evaluate_llm_response
import os
from dotenv import load_dotenv, find_dotenv
import dspy

import random
import numpy as np
import pyro

load_dotenv(find_dotenv())
my_api_key = os.getenv('GITHUB_TOKEN')

# 1. Lock PyTorch and Python Randomness
SEED = 123
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
pyro.set_rng_seed(SEED)

# ==========================================
# 1. Setup Cloud LLM (GPT-4o via GitHub)
# ==========================================

# 2. Lock the LLM Randomness (Temperature = 0)
lm = dspy.LM(
    model='openai/gpt-4o',
    api_base='https://models.inference.ai.azure.com',
    api_key=my_api_key,
    temperature=0.0  # <-- This stops the LLM from being creative
)
dspy.settings.configure(lm=lm)


# ==========================================
# 2. Define the DSPy Signature
# ==========================================
class GeneratePyroModel(dspy.Signature):
    """You are an expert in Probabilistic Programming Languages and Reinforcement Learning.
    Write a Pyro world model that maps game states and actions to next states and rewards."""

    system_instructions = dspy.InputField(desc="Instructions on the environment and tensor shapes.")
    error_feedback = dspy.InputField(desc="If your previous attempt failed, the error traceback is here. Fix it.")

    generated_code = dspy.OutputField(
        desc="A valid Python code block enclosed in ```python tags containing the ai_generated_model function.")


# ==========================================
# 3. The Orchestrator Loop
# ==========================================
def run_ai_coder_loop(states, actions, next_states, rewards, max_retries=3):
    # We dynamically inject the shapes into the prompt so the LLM knows the math dimensions
    N, state_dim = states.view(states.size(0), -1).shape
    _, action_dim = actions.view(actions.size(0), -1).shape

    base_instructions = f"""
            You are an AI generating a Pyro Probabilistic Program for a Bayesian Linear Regression world model. 
            You MUST use the following exact template. Do not change the function signature.

            The environment data dimensions:
            - states flattened shape: (N, {state_dim})
            - actions flattened shape: (N, {action_dim})

            CRITICAL PYRO RULES:
            1. Use `pyro.param("name", torch.randn(...))` to define your priors for weights and biases. Do NOT use `pyro.sample` for the weights.
            2. Because `next_states` is a multi-dimensional array ({state_dim} features), you MUST append `.to_event(1)` to its distribution. Example: `dist.Normal(mean, 1.0).to_event(1)`
            3. Do not overcomplicate the baseline. Keep the variance hardcoded to 1.0.

            ```python
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
                # YOUR CODE HERE: Create weight_s, weight_a, bias_s, weight_r_s, weight_r_a, bias_r using pyro.param

                # 3. Plate and Observations
                with pyro.plate("data_plate", N):
                    # YOUR CODE HERE: Calculate mean_next_state and mean_reward using torch.matmul

                    # Flatten next_states for comparison
                    if next_states is not None:
                        next_states = next_states.view(next_states.size(0), -1)

                    # YOUR CODE HERE: Sample 'obs_next_state' (using obs=next_states). REMEMBER .to_event(1)!
                    # YOUR CODE HERE: Sample 'obs_reward' (using obs=rewards)
            ```

            Fill in the "YOUR CODE HERE" sections. Ensure matrix dimensions align for torch.matmul.
            Output the complete, runnable python code.
            """

    current_feedback = "None. This is your first attempt."
    generator = dspy.Predict(GeneratePyroModel)

    for attempt in range(1, max_retries + 1):
        print(f"\n========================================")
        print(f"   LLM GENERATION ATTEMPT {attempt}/{max_retries}")
        print(f"========================================")

        # 1. Ask LLM for code
        print("Waiting for the LLM to generate...")
        response = generator(
            system_instructions=base_instructions,
            error_feedback=current_feedback
        )
        llm_text = response.generated_code

        print("\n--- RAW LLM OUTPUT ---")
        print(llm_text)
        print("----------------------\n")

        # 2. Pass it to the sandbox you built
        print("Executing code through pipeline...")
        success, feedback, evidence = evaluate_llm_response(llm_text, states, actions, next_states, rewards)

        if success:
            print("\n🎉 [SUCCESS] Phase 1 Baseline created!")
            return True, llm_text, evidence
        else:
            print(f"\n⚠️ [FAILED] Attempt {attempt} crashed.")
            print(f"Error caught: {feedback}")
            # Update the feedback for the next loop iteration
            current_feedback = f"Your previous code crashed with this error: {feedback}. Please rewrite the function to fix this bug."

    print("\n❌ [STOP] LLM failed to generate a working model after maximum retries.")
    return False, None, None


# ==========================================
# 4. Phase 2: The Refinement Loop
# ==========================================
class RefinePyroModel(dspy.Signature):
    """You are a Senior ML Engineer. Upgrade a linear Pyro model into a non-linear architecture based on empirical errors."""

    current_working_code = dspy.InputField(desc="The baseline model that currently compiles.")
    empirical_feedback = dspy.InputField(desc="Data showing where the linear model failed.")
    error_feedback = dspy.InputField(desc="If your previous refinement crashed PyTorch, the error is here.")

    refined_code = dspy.OutputField(
        desc="A valid Python code block enclosed in ```python tags with the upgraded ai_generated_model.")


def run_refinement_loop(baseline_code, evidence, states, actions, next_states, rewards, max_retries=5, previous_error_msg="None. First refinement attempt."):
    print("\n========================================")
    print("   STARTING PHASE 2: MODEL REFINEMENT   ")
    print("========================================")

    feedback_prompt = f"""
        Your goal is to LOWER the Mean Squared Error (MSE) of the model.

        Current Best Model Performance:
        - State MSE: {evidence['best_error']:.4f}
        - Reward MSE: {evidence['worst_error']:.4f}

        Empirical Failure Case:
        - The model completely failed to predict the state features at indices: {evidence['worst_features']}.

        Task: Modify `ai_generated_model` to reduce the error. 

        CRITICAL RULES:
        1. Maintain PyTorch dimension broadcasting rules.
        2. DO NOT USE DEEP NEURAL NETWORKS (nn.Sequential, nn.Linear, etc.). 
        3. Keep the model fundamentally linear or Bayesian, but try adding:
           - A latent variable (`pyro.sample` inside the plate)
           - Dynamic/learnable variance instead of hardcoding `1.0` in the Normal distributions.
           - Different prior distributions.
        4. If you use raw tensors for weights, you MUST wrap them in `pyro.param("name", tensor)`.
        """

    refiner = dspy.Predict(RefinePyroModel)
    current_error = previous_error_msg

    for attempt in range(1, max_retries + 1):
        print(f"\n[REFINEMENT ATTEMPT {attempt}/{max_retries}] Waiting for GPT-4o...")
        response = refiner(
            current_working_code=baseline_code,
            empirical_feedback=feedback_prompt,
            error_feedback=current_error
        )
        llm_text = response.refined_code

        print("\n--- RAW REFINED CODE ---")
        print(llm_text)
        print("------------------------\n")

        print("Executing refined code through pipeline...")
        success, feedback, new_evidence = evaluate_llm_response(llm_text, states, actions, next_states, rewards)

        if success:
            print("\n🚀 [SUCCESS] The AI successfully upgraded to a new world model!")
            return True, llm_text, new_evidence
        else:
            print(f"⚠️ [FAILED] Refinement crashed: {feedback}")
            current_error = f"Your upgraded code crashed with: {feedback}. Fix the PyTorch dimensions."

    return False, None, None


# ==========================================
# Main Execution
# ==========================================
if __name__ == "__main__":
    # Load Data
    try:
        dataset = torch.load('kaz_transitions.pt', weights_only=True)
        states, actions = dataset['states'], dataset['actions']
        rewards, next_states = dataset['rewards'], dataset['next_states']
    except FileNotFoundError:
        print("WARNING: Data not found. Using dummy tensors.")
        states, actions = torch.randn(50, 11), torch.randn(50, 1)
        next_states, rewards = torch.randn(50, 11), torch.randn(50)

    num_refinements = 3
    results = []

    print("\n" + "=" * 60)
    print("   PHASE 1: CREATING INITIAL BASELINE")
    print("=" * 60)

    # 1. Get the initial baseline
    success, current_code, current_evidence = run_ai_coder_loop(states, actions, next_states, rewards, max_retries=5)

    if success:
        results.append({
            "Iteration": "Baseline",
            "Success": success,
            "State_MSE": f"{current_evidence.get('mse_states', 0):.4f}",
            "Reward_MSE": f"{current_evidence.get('mse_rewards', 0):.4f}",
            "Status": "Baseline"
        })

        # Initialize the memory variable BEFORE the loop starts
        current_error_msg = "None. First refinement attempt."

        # 2. Iteratively refine the code!
        for step in range(1, num_refinements + 1):
            print("\n" + "=" * 60)
            print(f"   PHASE 2: REFINEMENT ITERATION {step}/{num_refinements}")
            print("=" * 60)

            # Feed the CURRENT code, evidence, and error message back into the LLM
            refine_success, new_code, new_evidence = run_refinement_loop(
                current_code, current_evidence, states, actions, next_states, rewards, max_retries=3, previous_error_msg=current_error_msg
            )

            if refine_success:
                old_mse = current_evidence.get('mse_states', float('inf'))
                new_mse = new_evidence.get('mse_states', float('inf'))

                # THE ROLLBACK CHECK: Only accept if the error went down
                if new_mse < old_mse:
                    print(f"🚀 [ACCEPTED] MSE improved from {old_mse:.4f} to {new_mse:.4f}. Updating best model.")
                    current_code = new_code
                    current_evidence = new_evidence
                    current_error_msg = "Great job! The previous attempt improved the MSE. Try to lower it even further."
                else:
                    print(f"❌ [REJECTED] MSE worsened ({old_mse:.4f} -> {new_mse:.4f}). Reverting to previous model.")

                    # THE FIX: Give the AI "Negative Memory" of what it just tried
                    current_error_msg = f"""
                                    WARNING: Your last attempt INCREASED the error to {new_mse:.4f}. 
                                    You tried to use this architecture, and it FAILED:
                                    {new_code}

                                    DO NOT generate this exact same architecture again. Start from the baseline and try a completely DIFFERENT, simpler approach (e.g., adding just a single latent variable, or modifying the variance, instead of a deep network).
                                    """

                results.append({
                    "Iteration": f"Refine {step}",
                    "Success": refine_success,
                    "State_MSE": f"{new_mse:.4f}",
                    "Reward_MSE": f"{new_evidence.get('mse_rewards', 0):.4f}",
                    "Status": "Accepted" if new_mse < old_mse else "Rejected"
                })
            else:
                print(f"Refinement {step} failed. Halting loop.")
                break

        # ==========================================
        # Print the Iterative History Table
        # ==========================================
        print("\n" + "="*80)
        print(f"{'Iteration':<12} | {'Success':<10} | {'State MSE':<12} | {'Reward MSE':<12} | {'Status':<12}")
        print("-" * 80)
        for r in results:
            status = r.get('Status', 'Baseline')
            print(f"{r['Iteration']:<12} | {str(r['Success']):<10} | {r['State_MSE']:<12} | {r['Reward_MSE']:<12} | {status:<12}")
        print("="*80)