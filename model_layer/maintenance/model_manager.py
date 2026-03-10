import torch
import pyro
import dspy
import pyro.distributions as dist
import os
from dotenv import load_dotenv, find_dotenv
from dynamic_loader import evaluate_llm_response, load_model_from_string, extract_python_code
from model_layer.maintenance.skills_merge import merge_skills
from model_layer.storage.history import History


# ==========================================
# 1. The Exact DSPy Signatures
# ==========================================
class GeneratePyroModel(dspy.Signature):
    """You are an expert in Probabilistic Programming Languages and Reinforcement Learning.
    Write a Pyro world model that maps game states and actions to next states and rewards."""
    system_instructions = dspy.InputField(desc="Instructions on the environment and tensor shapes.")
    error_feedback = dspy.InputField(desc="If your previous attempt failed, the error traceback is here. Fix it.")
    generated_code = dspy.OutputField(
        desc="A valid Python code block enclosed in ```python tags containing the ai_generated_model function.")


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


class RefinePyroModel(dspy.Signature):
    """You are a Senior ML Engineer. Upgrade a linear Pyro model into a non-linear architecture based on empirical errors."""
    current_working_code = dspy.InputField(desc="The baseline model that currently compiles.")
    empirical_feedback = dspy.InputField(desc="Data showing where the linear model failed.")
    error_feedback = dspy.InputField(desc="If your previous refinement crashed PyTorch, the error is here.")
    refined_code = dspy.OutputField(
        desc="A valid Python code block enclosed in ```python tags with the upgraded ai_generated_model.")


# ==========================================
# 2. The Model Manager Class
# ==========================================
class ModelManager:
    """
    This class is responsible for maintaining the abstract PDDL/Skill model
    as well as the dynamic Bayesian Continuous World Model (Pyro).
    """

    def __init__(self, model=None, skills=None, goals=None, constraints=None, abstraction_mapping=lambda x: x):
        self.model = model
        self.skills = skills or []
        self.abstraction_mapping = abstraction_mapping
        self.goals = goals or []
        self.constraints = constraints or []

        # Dynamic Bayesian Model Tracking
        self.world_model_code = None
        self.world_model_function = None
        self.current_mse = float('inf')
        self.current_params = 0

        # LLM Sub-agents
        self.generator = dspy.Predict(GeneratePyroModel)
        self.expander = dspy.Predict(ExpandPyroModel)
        self.reducer = dspy.Predict(ReducePyroModel)
        self.refiner = dspy.Predict(RefinePyroModel)

    def _count_model_parameters(self):
        """Helper to evaluate the size of the model."""
        total_params = 0
        for name, tensor in pyro.get_param_store().items():
            total_params += tensor.numel()
        return total_params

    def initialize_world_model(self, states, actions, next_states, rewards, max_retries=3):
        """Generates the foundational baseline model from scratch."""
        print("\n--- Initializing Bayesian World Model ---")
        N, state_dim = states.view(states.size(0), -1).shape
        _, action_dim = actions.view(actions.size(0), -1).shape

        # EXACT PROMPT RESTORED FROM world_model_generator.py
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

        for attempt in range(1, max_retries + 1):
            response = self.generator(system_instructions=base_instructions, error_feedback=current_feedback)
            code = response.generated_code
            clean_code = extract_python_code(code)

            success, error_log, evidence = evaluate_llm_response(clean_code, states, actions, next_states, rewards)

            if success:
                self.world_model_code = clean_code
                self.current_mse = evidence['mse_states']
                self.current_params = self._count_model_parameters()
                self.world_model_function, _ = load_model_from_string(clean_code)
                print(f"✅ Baseline Initialized. MSE: {self.current_mse:.4f} | Params: {self.current_params}")
                return True

            current_feedback = f"Your previous code crashed with this error: {error_log}. Please rewrite the function to fix this bug."

        return False

    def model_expansion(self, new_info, target_mse=0.01, max_retries=3):
        """Expands capacity (adds latent variables/variance) when underfitting."""
        print(f"\n🚀 Expanding Model (Current MSE: {self.current_mse:.4f})")
        states, actions = new_info['states'], new_info['actions']
        next_states, rewards = new_info['next_states'], new_info['rewards']

        error_msg = "None. First expand attempt."

        for attempt in range(1, max_retries + 1):
            feedback = f"Current State MSE is {self.current_mse:.4f}. It must be below {target_mse}. Add latent variables or dynamic variance to increase capacity."

            response = self.expander(current_working_code=self.world_model_code, empirical_feedback=feedback,
                                     error_feedback=error_msg)
            new_code = response.expanded_code
            clean_code = extract_python_code(new_code)

            success, crash_log, new_evidence = evaluate_llm_response(clean_code, states, actions, next_states, rewards)

            if success and new_evidence['mse_states'] < self.current_mse:
                self.world_model_code = clean_code
                self.current_mse = new_evidence['mse_states']
                self.current_params = self._count_model_parameters()
                self.world_model_function, _ = load_model_from_string(clean_code)
                print(f"✅ Expansion Success! New MSE: {self.current_mse:.4f} | Params: {self.current_params}")
                return True
            else:
                if not success:
                    error_msg = f"Code crashed. Log: {crash_log}"
                else:
                    error_msg = f"Expansion worsened MSE to {new_evidence['mse_states']:.4f}. Try a different, more stable expansion technique."

        print("❌ Expansion Failed.")
        return False

    def model_restriction(self, restriction_info, target_mse=0.01, max_retries=3):
        """Prunes the model complexity for speed, ensuring MSE stays strictly below target_mse."""
        print(f"\n🪓 Reducing Model (Target MSE < {target_mse})")
        states, actions = restriction_info['states'], restriction_info['actions']
        next_states, rewards = restriction_info['next_states'], restriction_info['rewards']

        error_msg = "None. First reduce attempt."

        for attempt in range(1, max_retries + 1):
            feedback = f"Current State MSE is {self.current_mse:.4f}. Prune the model complexity (remove matrices or latent plates) to reduce the parameter count below {self.current_params}, but keep MSE strictly below {target_mse}."

            response = self.reducer(current_working_code=self.world_model_code, empirical_feedback=feedback,
                                    error_feedback=error_msg)
            new_code = response.reduced_code
            clean_code = extract_python_code(new_code)

            success, crash_log, new_evidence = evaluate_llm_response(clean_code, states, actions, next_states, rewards)

            if success and new_evidence['mse_states'] <= target_mse:
                new_params = self._count_model_parameters()
                if new_params < self.current_params:
                    self.world_model_code = clean_code
                    self.current_mse = new_evidence['mse_states']
                    self.current_params = new_params
                    self.world_model_function, _ = load_model_from_string(clean_code)
                    print(f"✅ Reduction Success! New MSE: {self.current_mse:.4f} | Params: {self.current_params}")
                    return True
                else:
                    error_msg = "Model generated successfully, but parameter count did not decrease. Prune more aggressively."
            else:
                if not success:
                    error_msg = f"Code crashed. Log: {crash_log}"
                else:
                    error_msg = f"Pruning pushed MSE too high ({new_evidence['mse_states']:.4f} > {target_mse}). You removed too much capacity. Prune fewer parameters."

        print("❌ Reduction Failed.")
        return False

    def model_refinement(self, refinement_info, max_retries=3):
        """Attempts to optimize the mathematical architecture (priors, distributions) to lower MSE."""
        print(f"\n🔧 Refining Model Architecture (Current MSE: {self.current_mse:.4f})")
        states, actions = refinement_info['states'], refinement_info['actions']
        next_states, rewards = refinement_info['next_states'], refinement_info['rewards']

        # 1. Quickly evaluate current code to get the evidence dict for the prompt
        print("Gathering evidence for refinement...")
        success, _, evidence = evaluate_llm_response(self.world_model_code, states, actions, next_states, rewards)

        if not success or not evidence:
            print("Failed to get empirical evidence for current model. Cannot refine.")
            return False

        # EXACT PROMPT RESTORED FROM world_model_generator.py
        current_error_msg = "None. First refinement attempt."

        for attempt in range(1, max_retries + 1):
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

            response = self.refiner(current_working_code=self.world_model_code, empirical_feedback=feedback_prompt,
                                    error_feedback=current_error_msg)
            new_code = response.refined_code
            clean_code = extract_python_code(new_code)

            eval_success, crash_log, new_evidence = evaluate_llm_response(clean_code, states, actions, next_states,
                                                                          rewards)

            if eval_success:
                new_mse = new_evidence['mse_states']
                if new_mse < self.current_mse:
                    self.world_model_code = clean_code
                    self.current_mse = new_mse
                    self.current_params = self._count_model_parameters()
                    self.world_model_function, _ = load_model_from_string(clean_code)
                    print(f"✅ Refinement Success! New MSE: {self.current_mse:.4f} | Params: {self.current_params}")
                    return True
                else:
                    # Restore the specific rejection memory
                    current_error_msg = f"""
                    WARNING: Your last attempt INCREASED the error to {new_mse:.4f}. 
                    You tried to use this architecture, and it FAILED:
                    {new_code}

                    DO NOT generate this exact same architecture again. Start from the baseline and try a completely DIFFERENT, simpler approach.
                    """
            else:
                current_error_msg = f"Your upgraded code crashed with: {crash_log}. Fix the PyTorch dimensions."

        print("❌ Refinement Failed to improve the model.")
        return False

    def bayesian_parameter_update(self, new_transitions):
        """Run SVI to update the existing model parameters."""
        if not self.world_model_code:
            print("No model initialized. Cannot update parameters.")
            return self.model

        print("\n--- Updating Bayesian Parameters via SVI ---")
        success, _, evidence = evaluate_llm_response(
            self.world_model_code,
            new_transitions['states'],
            new_transitions['actions'],
            new_transitions['next_states'],
            new_transitions['rewards']
        )

        if success:
            self.current_mse = evidence['mse_states']
            print(f"✅ Parameters Updated. New MSE on latest data: {self.current_mse:.4f}")

        return self.model

    def merge_skills(self, other_skills):
        return merge_skills(self.skills, other_skills)

    def get_forward_function(self):
        """Returns the compiled Python function to be executed by the RL Agent."""
        return self.world_model_function


# ==========================================
# 3. Main Execution Block for Testing
# ==========================================
if __name__ == "__main__":
    import random
    import numpy as np

    # 1. Lock Randomness
    SEED = 123
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    pyro.set_rng_seed(SEED)

    # 2. Setup Cloud LLM & Prevent LiteLLM Connection Drops
    load_dotenv(find_dotenv())
    my_api_key = os.getenv('GITHUB_TOKEN')

    os.environ["OPENAI_API_BASE"] = "https://models.inference.ai.azure.com"
    os.environ["OPENAI_API_KEY"] = my_api_key

    print("Connecting to GPT-4o via GitHub Models...")
    lm = dspy.LM(
        model='openai/gpt-4o',
        api_base='https://models.inference.ai.azure.com',
        api_key=my_api_key,
        temperature=0.0
    )
    dspy.settings.configure(lm=lm)

    # 3. Load Data
    try:
        dataset = torch.load('kaz_transitions.pt', weights_only=True)
        states, actions = dataset['states'], dataset['actions']
        rewards, next_states = dataset['rewards'], dataset['next_states']
        print("Loaded actual game transitions.")
    except FileNotFoundError:
        print("Using dummy tensors for testing...")
        states, actions = torch.randn(50, 11), torch.randn(50, 1)
        next_states, rewards = torch.randn(50, 11), torch.randn(50)

    transition_data = {
        'states': states,
        'actions': actions,
        'next_states': next_states,
        'rewards': rewards
    }

    # 4. Instantiate the Manager
    manager = ModelManager()

    print("\n" + "=" * 50)
    print("   TESTING MODEL MANAGER LIFECYCLE")
    print("=" * 50)

    init_success = manager.initialize_world_model(states, actions, next_states, rewards)

    if init_success:
        # Test Expand
        expand_success = manager.model_expansion(transition_data, target_mse=0.01)

        if expand_success:
            # Test Reduce
            reduce_success = manager.model_restriction(transition_data, target_mse=0.01)

            # Test Refine
            refine_success = manager.model_refinement(transition_data)

            print("\n" + "=" * 50)
            print("=== FINAL MANAGER LIFECYCLE RESULTS ===")
            print(f"Final Model MSE:    {manager.current_mse:.4f}")
            print(f"Final Model Params: {manager.current_params}")
            print(f"Is Forward Function Ready? {'Yes' if manager.get_forward_function() else 'No'}")
            print("=" * 50)