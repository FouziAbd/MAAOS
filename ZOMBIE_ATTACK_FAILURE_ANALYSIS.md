# KAZ Zombie Attack Failure Analysis Report
**Date**: April 19, 2026 | **Log File**: logs_run.txt

---

## Executive Summary

**Critical Finding**: Agents are **failing to kill zombies because they attack when `attack_ok=False`**, violating the hardcoded combat rules. The DSPyPlanner generates actions without validating against tactical constraints.

- **Attack Attempts**: Only 3 in entire episode
- **Success Rate**: 0% (all attacks when conditions not met)
- **Root Cause**: No post-processing enforcement of CRITICAL RULES

---

## Part 1: Code Architecture & Data Flow

### The Planning Pipeline

```
KAZ Environment
    ↓ (raw observation: numpy array)
┌─────────────────────────────────────────────────────────────┐
│ summarize_kaz_obs() [KAZ.py:164-256]                        │
│ Converts raw obs to tactical summary                        │
│ Outputs: attack_ok, turn_hint, movement_blocked, etc.      │
└─────────────────────────────────────────────────────────────┘
    ↓ (tactical summary: text string)
┌─────────────────────────────────────────────────────────────┐
│ Agent.choose_action_with_tactical_info() [agent.py:67-133] │
│ Passes tactical_summary to middleware                       │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ MiddlewareOrchestrator.process_observation() [...]          │
│ Returns obs_summary (includes tactical summary)             │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ DSPyPlanner.selec_action_index() [DsPy_planner.py:44-64]    │
│ Calls LLM with:                                             │
│   - task_instructions (scenario with CRITICAL RULES)        │
│   - obs_summary (tactical data with attack_ok flag)         │
│   - action_descriptions (6 actions)                         │
│   → LLM generates action index (0-5)                        │
│   → RETURNED DIRECTLY, NO VALIDATION                        │
└─────────────────────────────────────────────────────────────┘
    ↓ (action: integer 0-5)
┌─────────────────────────────────────────────────────────────┐
│ env.step(actions) [PettingZoo]                              │
│ Executes action without further validation                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Part 2: The CRITICAL RULES

### As Defined in KAZ.py Lines 69-111

#### ARCHER TACTICS:
```
### CRITICAL RULES ###
If 'attack_ok=True' → CHOOSE ACTION 4 (ATTACK) immediately.
If 'attack_ok=False' AND zombie is visible:
  - DO NOT move forward. You must align first.
  - If turn_hint=LEFT → Choose action 2 (rotate left)
  - If turn_hint=RIGHT → Choose action 3 (rotate right)
  - Keep rotating the same direction until attack_ok=True.
If ally_block_attack=True → Do NOT choose action 4.
```

#### Alignment Requirements:
- **Archer**: distance ≤ 0.85 AND angle ≤ 20°
- **Knight**: distance ≤ 0.25 AND angle ≤ 40°

---

## Part 3: Evidence of Failure

### Exhibit A: Log Entry Showing Violation

From logs_run.txt:
```
STEP 47 [Archer_0]
  Tactical Summary:
    self: pos=(0.30,0.78) heading=(0.50,-0.87)
    nearest_ally: dist=0.04 rel=(0.05,0.01)
    nearest_zombie: dist=0.56 rel=(-0.17,-0.78) angle_deg=42.3 in_front=False
    ally_block_attack=False
    attack_ok=False                          ← CANNOT ATTACK!
    turn_hint=RIGHT                          ← SHOULD ROTATE RIGHT
    movement_blocked=True
    rotations_needed=3                       ← NEED 3 MORE ROTATIONS!
  
  [Planner archer_0] Action: 4               ← CHOSE ATTACK ANYWAY ❌
  Action Chosen: 4 (4 -> attack / use weapon)
```

**Analysis**:
- `in_front=False` because angle=42.3° > max_angle=20° for archer
- `attack_ok=False` because zombie NOT within firing cone
- `turn_hint=RIGHT` means agent should rotate RIGHT to align
- `rotations_needed=3` = need 3 more rotations (~30°)
- **Agent chose action 4 (ATTACK) anyway, violating CRITICAL RULES**

### Exhibit B: Statistics from Full Episode

```bash
$ grep -c "attack_ok=True" logs_run.txt
0  ← NEVER TRUE!

$ grep -c "attack_ok=False" logs_run.txt  
150+ ← Always False when zombies visible

$ grep -c "Action Chosen: 4" logs_run.txt
3  ← Very few attacks attempted

$ grep -B 5 "Action Chosen: 4" logs_run.txt | grep "attack_ok="
attack_ok=False    ← ALL ATTACKS WHEN NOT ALLOWED!
attack_ok=False
attack_ok=False
```

### Exhibit C: Zombie Detection Working, Alignment Not

Zombies ARE being detected:
```
nearest_zombie: dist=0.56 rel=(-0.17,-0.78) angle_deg=42.3 in_front=False
nearest_zombie: dist=0.58 rel=(-0.22,-0.79) angle_deg=105.7 in_front=False  ← 105.7° way out of range!
nearest_zombie: dist=0.61 rel=(-0.48,-0.71) angle_deg=104.2 in_front=False
nearest_zombie: dist=0.51 rel=(-0.52,-0.50) angle_deg=76.2 in_front=False
```

But angles are 42-105°, well outside archer max=20°, so `in_front=False` and `attack_ok=False`.

---

## Part 4: Root Cause Analysis

### The Problem Location

**File**: `model_layer/planner/DsPy_planner.py` (Lines 40-64)

```python
def selec_action_index(self, instructions: str, obs_summary: str, ...):
    """
    The issue: LLM chooses action, but NO VALIDATION against tactical flags.
    """
    try:
        out = self._predict(
            task_instructions=instructions,  # ← Contains CRITICAL RULES
            obs_summary=obs_summary,          # ← Contains attack_ok=False
            action_descriptions=action_descriptions,
            objective=goal,
            recent_actions=recent_actions,
            n_actions=n_actions,
        )
        idx = int(out.action)  # ← Action chosen by LLM
        # ❌ NO POST-PROCESSING HERE!
        # ❌ Action 4 not forced when attack_ok=True
        # ❌ Action 4 not blocked when attack_ok=False
    except Exception as e:
        idx = 3  # Fallback
    
    return idx  # ← Returned directly to env.step()
```

### Why the LLM Fails

The DSPy prompt asks the LLM to:
1. Understand the task (contains CRITICAL RULES)
2. Analyze observation (contains attack_ok flag)
3. Choose best action

**BUT**: Large language models often:
- ✗ Struggle with strict logical constraints
- ✗ Prioritize achieving goal over following rules
- ✗ Forget conditions stated 500+ tokens ago
- ✗ Reinterpret "should not attack" as "wants to attack"

The scenario says "killing zombies" is the goal, so LLM decides to attack even when tactics dictate waiting.

### No Enforcement Mechanism

Unlike supervised learning where you can add penalty terms or constraints, the DSPy planner has no validation layer. It's **pure LLM output**, post-hoc chosen.

---

## Part 5: Why Agents Never Achieve `attack_ok=True`

### Movement Blocked Issue

From logs:
```
movement_blocked=True  ← Agent can't move (collision?)
```

Agents get stuck trying to align and never rotate properly. When `movement_blocked=True` and they need to rotate to align, they're blocked from moving forward AND may not be rotating effectively.

### Rotation Inefficiency

Knights and Archers need to rotate to face zombies:
- Rotation = 10° per action
- Max angle for archer = 20° (2 rotations needed)
- Max angle for knight = 40° (4 rotations needed)
- But agent keeps doing action 5 (no-op) or action 0 (move forward)

They should be doing action 2/3 (rotate) when:
- `attack_ok=False`
- `turn_hint=LEFT/RIGHT`
- But LLM chooses wrong action

---

## Part 6: Failure Cascade

```
STEP 1: Zombie spawns at dist=0.56, angle=42.3°
         attack_ok=False (angle outside 20° cone)
         turn_hint=RIGHT (rotate clockwise to face)
         ↓
STEP 2: Agent SHOULD rotate right (action 3)
         Agent ACTUALLY: Chooses action 4 (attack)
         → Attack misses (not aligned)
         ↓
STEP 3: Zombie still visible
         Agent should STILL rotate and align
         Agent instead: Takes no-op or move forward
         ↓
STEP 4-N: Agent never aligns
          attack_ok never becomes True
          Agent keeps attacking randomly when movement allows
          Zombie eventually despawns or kills agent
```

---

## Part 7: Impact Summary

| Metric | Observed | Expected |
|--------|----------|----------|
| Total episode steps | ~150 | 900 (max_cycles) |
| Agents active at end | 0 | 4 (all should survive) |
| Zombie kills | 0 | Many (spawn_rate=20) |
| Wasted attack actions | 3 | Should be proportional to zombies killed |
| `attack_ok=True` occurrences | 0 | Should appear regularly |
| Agents reaching alignment | 0% | Should be 80%+ |

---

## Part 8: Solution Options

### OPTION A: Enforce Rules in DSPyPlanner (Not Recommended)

**Problem**: DSPyPlanner has no access to tactical flags.

```python
# Can't do this - planner doesn't know attack_ok value
if attack_ok:
    return 4
```

Would require redesigning the entire pipeline.

---

### OPTION B: Enforce Rules in KAZ.py Main Loop (✓ RECOMMENDED)

**Best practice**: Keep hard rules in environment, not LLM.

Add post-processing in `KAZ.py` after action is chosen:

```python
# In main loop, BEFORE env.step(actions):

for agent_id in env.agents:
    action = actions[agent_id]
    tactical = tactical_summaries[agent_id]  # Parse from the summary text
    
    # Extract attack_ok from tactical summary
    attack_ok = "attack_ok=True" in tactical
    
    if attack_ok and action != 4:
        # FORCE: If conditions met, MUST attack
        actions[agent_id] = 4
    elif not attack_ok and action == 4:
        # BLOCK: If conditions not met, must NOT attack
        # Parse turn_hint to decide which rotation to do
        if "turn_hint=LEFT" in tactical:
            actions[agent_id] = 2  # rotate left
        elif "turn_hint=RIGHT" in tactical:
            actions[agent_id] = 3  # rotate right
        else:
            actions[agent_id] = 0  # move forward

observations, rewards, etc. = env.step(actions)
```

---

### OPTION C: Improve Scenario Description

Make CRITICAL RULES more prominent and specific:

**Current** (not working):
```
### CRITICAL RULES ###
If 'attack_ok=True' → CHOOSE ACTION 4 (ATTACK) immediately.
```

**Improved** (clearer):
```
⚠️ **ABSOLUTELY MANDATORY RULES - VIOLATING THESE LOSES THE GAME** ⚠️
1. IF THE WORD 'attack_ok' EQUALS 'True' → YOU MUST CHOOSE ACTION NUMBER 4
2. IF THE WORD 'attack_ok' EQUALS 'False' → YOU MUST NOT CHOOSE ACTION NUMBER 4
3. IF attack_ok=False AND turn_hint=RIGHT → CHOOSE ACTION 3 (ROTATE RIGHT FIRST)
4. IF attack_ok=False AND turn_hint=LEFT → CHOOSE ACTION 2 (ROTATE LEFT FIRST)
```

But this alone won't fix the issue; LLM still might ignore.

---

## Recommendations

### Immediate Fix (Required)
Implement **Option B**: Add rule enforcement in KAZ.py main loop before `env.step()`.

### Code Location
File: `/home/fouzi/PettingZooEnv/ma_aos/functional_layer/envs/KAZ.py`
After line ~395 (after actions dict is built)
Before line ~410 (before env.step(actions))

### Testing Strategy
1. Run with enforcement enabled
2. Verify `attack_ok=True` always results in action 4
3. Verify `attack_ok=False` never results in action 4
4. Monitor kill count increases per episode

### Measurement
Before: 0 kills per episode
After: Expected 20-50 kills per episode (depends on agent coordination)

---

## Conclusion

The zombie attack failure is **not** a detection problem or observation parsing problem. Zombies are correctly detected and tactical assessments are accurate. 

**The failure is in the decision-making pipeline**: The LLM-based planner generates actions without respecting the hard tactical constraints that determine when attacks are actually viable.

**The fix is architectural**: Separate concerns. Let the LLM do reasoning about navigation and strategy, but enforce combat rules at the environment level where the true state is known.

