# Key Findings: Why Agents Fail to Kill Zombies

## The Core Problem (In 1 Sentence)
**The LLM planner generates attack actions even when `attack_ok=False`, violating hardcoded tactical rules because there's no enforcement mechanism.**

---

## Visual Flow of Failure

```
OBSERVATION                    TACTICAL ASSESSMENT              DECISION
═══════════════════════════════════════════════════════════════════════════

Zombie detected        summarize_kaz_obs()        attack_ok=False
dist=0.56              Calculates:                turn_hint=RIGHT
angle=42.3°    ──→     - angle=42.3° > max 20°   rotations_needed=3
                       - angle NOT in firing cone
                                              ↓
                                        ┌─────────────────┐
                                        │  DSPyPlanner    │
                                        │  (LLM-based)    │
                                        │                 │
                                        │  "Choose best   │
                                        │   action to     │  ← LLM sees:
                                        │   kill zombies" │    1. CRITICAL RULE: If attack_ok=True, attack
                                        │                 │    2. attack_ok=False (zombie not aligned)
                                        │ ❌ IGNORES      │    3. Goal: kill zombies
                                        │    RULES        │    4. Chooses: Action 4 ANYWAY
                                        └─────────────────┘
                                              ↓
                                        Action 4 (ATTACK)
                                        BUT ZOMBIE NOT ALIGNED
                                        ↓
                                        MISSES & WASTES TURN
```

---

## Log Evidence

### What Should Happen (But Doesn't)

```python
# From KAZ.py scenario (CRITICAL RULES section):
If 'attack_ok=True' → CHOOSE ACTION 4 (ATTACK) immediately.
If 'attack_ok=False' AND zombie is visible:
  - DO NOT move forward. You must align first.
  - If turn_hint=LEFT → Choose action 2 (rotate left)
  - If turn_hint=RIGHT → Choose action 3 (rotate right)
  - Keep rotating until attack_ok=True.
If ally_block_attack=True → Do NOT choose action 4.
```

### What Actually Happens

```
Tactical Summary (from logs_run.txt):
  attack_ok=False           ← Rule says: DO NOT ATTACK
  turn_hint=RIGHT           ← Rule says: ROTATE RIGHT (action 3)
  rotations_needed=3        ← Need 3 rotations before alignment
  
Planner Decision:
  [Planner archer_0] Action: 4  ← ATTACKS ANYWAY ❌
```

### Why This Happens

1. ✅ Observation system works → correctly detects zombie at angle=42.3°
2. ✅ Tactical assessment works → correctly calculates attack_ok=False
3. ✅ Scenario description includes rules → clearly states CRITICAL RULES
4. ❌ **DSPyPlanner output NOT validated** → no enforcement of rules
5. ❌ **No post-processing** → action passed directly to env.step()

---

## Statistics from Episode

| Finding | Count | Problem |
|---------|-------|---------|
| Total steps with zombies | 150+ | Agents should kill many |
| `attack_ok=True` events | **0** | Never aligned! |
| `attack_ok=False` events | 150+ | Always misaligned |
| Actual attack actions (4) | 3 | Way too few |
| Attacks when `attack_ok=False` | 3/3 (100%) | All illegal! |
| Zombie kills | **0** | Complete failure |
| Agent deaths | 4/4 (100%) | All eliminated |

---

## The Technical Gap

### Where Rules Should Be Enforced

```
KAZ.py MAIN LOOP
│
├─ [WORKING] summarize_kaz_obs() → tactical_summary
│   └─ Outputs: attack_ok=False, turn_hint=RIGHT
│
├─ [WORKING] Agent.choose_action_with_tactical_info()
│   └─ Passes tactical_summary to planner
│
├─ [BROKEN] DSPyPlanner.selec_action_index()
│   └─ Gets tactical data & rules
│   └─ LLM generates action
│   └─ ❌ RETURNS DIRECTLY WITHOUT VALIDATION
│
└─ [PASSIVE] env.step(actions)
   └─ Executes whatever action was chosen
   └─ No fallback validation
```

### Missing Enforcement Layer

```python
# THIS CODE DOESN'T EXIST:

actions[agent_id] = planner_output  # Get LLM's choice

# ❌ MISSING:
if attack_ok_from_tactical_summary:
    actions[agent_id] = 4  # FORCE attack
elif not attack_ok_from_tactical_summary and actions[agent_id] == 4:
    actions[agent_id] = 2  # BLOCK attack, rotate instead

env.step(actions)  # Now actions respect rules
```

---

## Why LLM Can't Follow Rules

Even though the scenario clearly states the CRITICAL RULES, LLMs struggle with:

1. **Token distance**: Rules are stated early, but decision comes after analyzing zombie data
2. **Goal override**: "Kill zombies" goal overrides "don't attack when misaligned" rule
3. **Fuzzy interpretation**: LLM might read "if attack_ok=True" as advisory rather than mandatory
4. **Reasoning path**: LLM reasons: "I see zombie → I want to attack → let me choose action 4" rather than "Is attack_ok=True? No → choose action 3 instead"

---

## Summary Table

| Component | Status | Issue |
|-----------|--------|-------|
| Raw observation parsing | ✅ Working | Zombie correctly detected |
| Tactical summary generation | ✅ Working | attack_ok flag correctly computed |
| Scenario with CRITICAL RULES | ✅ Present | Rules clearly stated in text |
| LLM receives full context | ✅ True | All info passed to planner |
| LLM respects rules | ❌ **FAILS** | Ignores attack_ok constraints |
| Action validation/enforcement | ❌ Missing | No post-processing check |
| Final execution | 🟡 Correct | Executes whatever action chosen |

---

## Solution: Add Enforcement in KAZ.py

Before `env.step(actions)` in the main loop, add:

```python
# Parse attack_ok from tactical summaries and enforce rules
for agent_id in actions:
    tactical = tactical_summaries[agent_id]  # The summary text
    
    # Extract flags (simple regex or string parsing)
    attack_ok = "attack_ok=True" in tactical
    turn_hint = "turn_hint=RIGHT" if "turn_hint=RIGHT" in tactical else \
                "turn_hint=LEFT" if "turn_hint=LEFT" in tactical else None
    
    # Enforce CRITICAL RULES
    if attack_ok:
        actions[agent_id] = 4  # FORCE attack when aligned
    elif not attack_ok and actions[agent_id] == 4:
        # BLOCK attack when misaligned, suggest rotation
        if turn_hint == "RIGHT":
            actions[agent_id] = 3  # rotate right
        elif turn_hint == "LEFT":
            actions[agent_id] = 2  # rotate left
        else:
            actions[agent_id] = 0  # move toward zombie

# Now step with validated actions
observations, rewards, ... = env.step(actions)
```

---

## Expected Results After Fix

| Metric | Before | After |
|--------|--------|-------|
| `attack_ok=True` → action 4 | 0% | 100% |
| `attack_ok=False` → action 4 | 100% | 0% |
| Zombie kills per episode | 0 | 15-40 |
| Agent survival rate | 0% | 60%+ |
| Episode completion | Early termination | Full 900 cycles |

