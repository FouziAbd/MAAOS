# Middleware Layer

The middleware layer bridges the functional environment and model layer (agent + planner) by providing LLM-based simplification of observations and coordination of tactical summaries with the planner.

## Overview

The middleware architecture enables LLM-based agents to make informed decisions by:
1. Computing tactical assessments (nearest threats, alignment angles, attack feasibility)
2. Passing these assessments to the planner along with observation context
3. Enforcing strict action rules based on game state (e.g., `attack_ok` flag)

## Key Concept: Tactical Summaries

Instead of raw arrays, agents receive **tactical assessments** like:
```
nearest_ally: dist=0.45 rel=(0.12,0.34)
nearest_zombie: dist=0.61 rel=(-0.22,0.18) angle_deg=45.3 in_front=True
ally_block_attack=false
attack_ok=true
turn_hint=NONE
[IMPORTANT: Each ROTATE action turns only 10 degrees. You may need 2-3+ rotations to face a target that's 30+ degrees away.]
```

This gives the LLM:
- **Tactical state**: distances, angles, threat assessment
- **Decision flags**: `attack_ok` (can attack safely), `ally_block_attack` (friendly fire risk)
- **Guidance**: `turn_hint` (LEFT/RIGHT/NONE for alignment)
- **Constraints**: rotation step size (10 degrees per action)

---

## Components

### 1. **ObservationSimplifier** (`observation_simplifier.py`)
Converts raw observations into human-readable summaries using LLM.

**Features:**
- Handles numpy arrays, dictionaries, and other observation formats
- Uses DSPy `ChainOfThought` for reasoning before output
- Caches results by observation hash to avoid redundant LLM calls
- Generic across different environments

**Status:** Part of middleware, used when tactical summary is unavailable.

---

### 2. **ActionDescriptor** (`action_descriptor.py`)
**DEPRECATED for KAZ**: Now uses raw action descriptions directly.

Previously generated enriched descriptions; current implementation passes simple action maps to preserve action-index alignment:
```
0 -> move forward
1 -> move backward
2 -> rotate left
3 -> rotate right
4 -> attack / use weapon
5 -> no-op
```

**Reason for change**: LLM was confusing between action numbers and enriched descriptions. Simple mappings are more reliable.

---

### 3. **ScenarioSimplifier** (`scenario_simplifier.py`)
Condenses verbose scenario and goal descriptions into concise, actionable text.

**Features:**
- Simplifies long scenario descriptions
- Simplifies goal/objective statements
- Uses DSPy `ChainOfThought` for reasoning
- Caches results (one-time call at agent initialization)
- For KAZ: Includes role-specific tactics (Archer vs Knight)

**Current KAZ Scenario with Critical Rules:**
```
If 'attack_ok=true' in the observation → CHOOSE ACTION 4 (ATTACK) immediately.
If 'attack_ok=false' in the observation → DO NOT ATTACK. Instead:
  - If turn_hint=LEFT → Choose action 2 (rotate left)
  - If turn_hint=RIGHT → Choose action 3 (rotate right)
  - If no zombie → Choose action 0 (move forward) or action 5 (no-op)
If ally_block_attack=true → Do NOT choose action 4.
```

---

### 4. **ActionExecutor** (`action_executor.py`)
Maps planner-chosen action indices to environment `step()` calls.

**Features:**
- Validates action indices against environment's action space
- Supports action clamping to valid range
- Pass-through execution (action index → env.step())

---

### 5. **MiddlewareOrchestrator** (`middleware_orchestrator.py`)
Central coordinator for all middleware components.

**Key Method:**
```python
def process_observation(self, raw_observation, agent_instructions="", tactical_summary=""):
    """
    If tactical_summary provided: returns it directly with context (no LLM processing)
    Otherwise: runs LLM simplification on raw observation
    """
```

**Features:**
- Accepts pre-computed tactical summaries (e.g., from `summarize_kaz_obs`)
- Adds context about rotation mechanics
- Caches simplified scenario, goal, and actions
- Provides unified interface to agent

---

## Integration with Agent

The `Agent` class now includes:

```python
def choose_action_with_tactical_info(self, obs, tactical_summary: str = ""):
    """
    Enhanced method that accepts tactical assessment.
    If tactical_summary provided, passes it directly to middleware.
    """
```

**Usage in KAZ:**
```python
# Compute tactical assessment for agent
role = "Archer" if "archer" in agent_id else "Knight"
tactical_summary = summarize_kaz_obs(
    obs=agent_obs,
    role=role,
    num_archers=2,
    num_knights=2,
    max_arrows=10,
    max_zombies=10
)

# Add rotation note
tactical_summary = tactical_summary + "\n[IMPORTANT: Each ROTATE action turns only 10 degrees. You may need 2-3+ rotations...]"

# Pass to agent
action = agent.choose_action_with_tactical_info(agent_obs, tactical_summary)
```

---

## Data Flow (KAZ Example)

```
Functional Layer              |    Middleware                  |    Model Layer
───────────────────────────────────────────────────────────────────────────────
env.step(actions)            |                                |
  observations               |                                |
           ─────────────────→| summarize_kaz_obs()           |
           tactical summary  │ (compute distances,           |
           ◄─────────────────│  angles, attack_ok)           |
                             |                                |
                             │ MiddlewareOrchestrator         |
                             │ .process_observation()    ────→ Agent
                             │ (passes tactical summary)  obs, tactic
                             │                           ◄──── choose_action_with_tactical_info()
                             │                           return: action_idx
           ◄─────────────────│ ◄────────────────────────┤
env.step(action_idx)        │
  reward, next_obs           │
           ◄─────────────────│
```

---

## Kill Tracking (KAZ)

The KAZ environment now tracks kills per agent:

```python
# Initialize kill counter
kills = {agent_id: 0 for agent_id in env.agents}

# During each step, accumulate kills from rewards
for agent_id, reward in rewards.items():
    if reward > 0:
        kills[agent_id] += reward

# Print current kills each step
print(f"Kills: {kills}")

# At episode end, print summary
print("EPISODE FINISHED - KILL STATISTICS:")
print(f"archer_0: {kills['archer_0']} zombies killed")
print(f"archer_1: {kills['archer_1']} zombies killed")
print(f"knight_0: {kills['knight_0']} zombies killed")
print(f"knight_1: {kills['knight_1']} zombies killed")
print(f"TOTAL: {sum(kills.values())} zombies killed")
```

---

## Planner Output Validation

The DSPy planner enforces `attack_ok` rules through:

1. **Clear constraints** in output field descriptions
2. **Post-processing validation** that forces correct actions:
   - If `attack_ok=true` and LLM doesn't output 4 → force to 4
   - If `attack_ok=false` and LLM outputs 4 → force to 2 (rotate left)

This ensures **rule compliance** even if the LLM is confused about action-outcome mapping.

---

## Benefits

1. **Tactical Context**: Agents understand threat proximity, alignment, and attack viability
2. **Attack Reliability**: `attack_ok` flag prevents wasted attacks and ensures proper positioning
3. **Rotation Awareness**: LLM knows rotation is incremental (10°/step), not instant
4. **Kill Tracking**: Measure agent performance episode-by-episode
5. **Modular**: Tactical assessment computation (separate from LLM) + LLM decision-making
6. **Validated Decisions**: Planner output is checked and corrected if needed

---

## Current Status (KAZ Integration)

✅ **Working:**
- Tactical summaries computed correctly (distances, angles, attack_ok)
- `attack_ok` flag controls action selection
- Agents kill zombies with increasing success
- Kill counts tracked and reported
- Rotation mechanics understood by agents

⚠️ **In Progress:**
- Observation quality optimization (adding more tactical details)
- Performance analysis (success rates, efficiency metrics)

---

## Example: Full KAZ Loop with Middleware

```python
from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator
from model_layer.agent import Agent

# Setup
env = knights_archers_zombies_v10.parallel_env(...)
lm = dspy.LM(model='ollama_chat/llama3:latest', api_base='http://localhost:11434')
kills = {}

observations, infos = env.reset()

while env.agents:
    actions = {}
    
    for agent_id in env.agents:
        if agent_id not in my_controllers:
            # Create middleware
            middleware = MiddlewareOrchestrator(
                env=env,
                agent_id=agent_id,
                LLM_model=lm,
                scenario_description=get_scenario_description(agent_id),
                goal_description=get_goal_description(agent_id),
                action_space=actions_details,
                environment_name="KAZ Zombie Survival",
                observation_spec=get_observation_description()
            )
            
            # Create agent with middleware
            my_controllers[agent_id] = Agent(
                agent_id=agent_id,
                scenario_description=get_scenario_description(agent_id),
                goal_description=get_goal_description(agent_id),
                action_space=actions_details,
                LLM_model=lm,
                middleware=middleware
            )
            
            kills[agent_id] = 0
        
        # Compute tactical summary
        role = "Archer" if "archer" in agent_id else "Knight"
        tactical_summary = summarize_kaz_obs(
            obs=observations[agent_id],
            role=role,
            num_archers=2,
            num_knights=2,
            max_arrows=10,
            max_zombies=10
        )
        
        # Add rotation note
        tactical_summary += "\n[IMPORTANT: Each ROTATE action turns only 10 degrees...]"
        
        # Choose action with tactical info
        actions[agent_id] = my_controllers[agent_id].choose_action_with_tactical_info(
            observations[agent_id], 
            tactical_summary
        )
    
    # Step environment
    observations, rewards, terminations, truncations, infos = env.step(actions)
    
    # Track kills
    for agent_id, reward in rewards.items():
        if reward > 0:
            kills[agent_id] += reward
    
    print(f"Kills: {kills}")

# Print statistics
print("EPISODE FINISHED - KILL STATISTICS:")
print(f"Total kills: {sum(kills.values())}")
```

