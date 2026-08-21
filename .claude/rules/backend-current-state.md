---
paths:
  - "functional_layer/**/*"
  - "middleware_layer/**/*"
  - "model_layer/**/*"
---

# Existing Repository Compatibility Rules

This repository predates the Symbolic-Twin P0-P4 architecture. Reuse it; do not confuse the legacy layering with the target architecture.

Important current facts to preserve unless deliberately changed:

- BoxPush lives under `functional_layer/custom_env/box_push/env/`.
- Existing runners rely on bare imports and runtime `sys.path` insertion. Avoid broad import/package cleanup during P0-P4.
- `box_push_centralized.py` is the current high-level-skill runner.
- The current centralized DSPy planner is a legacy/experimental decision-maker, not the target symbolic-primary P0-P4 orchestrator.
- Existing CST/BoxPush belief machinery is partial-observation oriented; V1 requires an exact canonical symbolic state adapter.
- Shared skill scaffolding is in `functional_layer/custom_env/shared_skills.py`.
- BoxPush task-specific skills are in/around `skill_executor_push.py` and should be reused behind the executive skill API where their semantics match the frozen domain.

Current BoxPush primitive action space is based on turn/move/stay behavior. High-level BoxPush skills such as `goto_push_pose`, `push`, `cooperate_push`, `explore`, and `wait` may compose multiple primitive actions. Verify exact current labels and behavior from code rather than trusting old prose.

Never treat current prompt conventions, parser fallbacks, belief heuristics, or BFS helpers as automatically authoritative symbolic semantics. They must be classified as backend implementation, NL behavior, or legacy behavior before reuse.
