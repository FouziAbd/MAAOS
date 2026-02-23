import torch
from dynamic_loader import evaluate_llm_response
import os
from dotenv import load_dotenv, find_dotenv
import dspy

# Automatically search up the directory tree to find the .env file
load_dotenv(find_dotenv())

# Get the token securely
my_api_key = os.getenv('GITHUB_TOKEN')

# ==========================================
# 1. Setup Cloud LLM (GPT-4o via GitHub)
# ==========================================
print("Connecting to GPT-4o via GitHub Models...")
lm = dspy.LM(
    model='openai/gpt-4o',
    api_base='https://models.inference.ai.azure.com',
    api_key=my_api_key
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
            # YOUR CODE HERE: Create weight_s, weight_a, weight_r_s, weight_r_a

            # 3. Plate and Observations
            with pyro.plate("data_plate", N):
                # YOUR CODE HERE: Calculate mean_next_state and mean_reward using torch.matmul

                # Flatten next_states for comparison
                if next_states is not None:
                    next_states = next_states.view(next_states.size(0), -1)

                # YOUR CODE HERE: Sample 'obs_next_state' (using obs=next_states) 
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

        # 1. Ask Qwen for code
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
        success, feedback = evaluate_llm_response(llm_text, states, actions, next_states, rewards)

        if success:
            print("\n🎉 [SUCCESS] The AI generated a mathematically sound world model!")
            return True, llm_text
        else:
            print(f"\n⚠️ [FAILED] Attempt {attempt} crashed.")
            print(f"Error caught: {feedback}")
            # Update the feedback for the next loop iteration
            current_feedback = f"Your previous code crashed with this error: {feedback}. Please rewrite the function to fix this bug."

    print("\n❌ [STOP] LLM failed to generate a working model after maximum retries.")
    return False, None


# ==========================================
# Main Execution
# ==========================================
if __name__ == "__main__":
    # Load your PettingZoo data
    try:
        dataset = torch.load('kaz_transitions.pt', weights_only=True)
        states, actions = dataset['states'], dataset['actions']
        rewards, next_states = dataset['rewards'], dataset['next_states']
    except FileNotFoundError:
        print("WARNING: Data not found. Using dummy tensors.")
        states, actions = torch.randn(50, 11), torch.randn(50, 1)
        next_states, rewards = torch.randn(50, 11), torch.randn(50)

    # Run the loop!
    success, final_code = run_ai_coder_loop(states, actions, next_states, rewards, max_retries=10)

    if success:
        print("\nFinal Working Code:")
        print(final_code)