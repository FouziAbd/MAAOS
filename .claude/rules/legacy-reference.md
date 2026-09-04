---
paths:
  - "middleware_layer/**/*"
  - "model_layer/**/*"
  - "functional_layer/custom_env/box_push/env/box_push_centralized.py"
  - "functional_layer/custom_env/cooperative_search_transport/**/*"
---

# Legacy / Research Reference Rules

These paths contain pre-V1 research/reference implementations.

They are not an alternative supported Symbolic-Twin runtime and must not be
used as architectural precedent for the R0-R6 refactor.

Useful algorithms, backend semantics, prompts, and experiments may be inspected
for evidence, but classify them before reuse as one of:

- authoritative backend behavior;
- historical experiment;
- legacy prompt/parser behavior;
- reusable utility;
- unsupported/deprecated runtime path.

Do not migrate legacy behavior into the current runtime merely because it
exists.

Do not perform broad legacy package moves/deletions as part of an unrelated
R-phase. R6 may quarantine legacy code only as a separate reviewable hygiene
change.
