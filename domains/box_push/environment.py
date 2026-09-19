"""The BoxPush backend boundary (DK1) — the one module of this package that may reach the
authoritative backend, and it does so INSIDE the factory so `import domains.box_push` loads
no backend module (pinned by a subprocess test).

The adapter is imported by its namespace path from the repository root; it mounts its own
sibling modules (`box_push_env`, `skill_executor_push`, ...) on the module search path
itself, so this module contains no path manipulation. `BoxPushV1Adapter()` is the frozen V1 instance
(`_default_config()`: 12x12, two agents, two boxes, headless) — the same construction the
tests use.

DEBT-DK1 (ADR): the namespace path is a SECOND module object beside `box_push_v1_adapter`
(the name the runner and the tests import via the search path). Same code, same behavior — the DK1
transcript test proves it — but no code may rely on adapter `isinstance` identity across the
two names until the recorded cleanup gives the env directory one canonical import path.
"""
from __future__ import annotations

from shared.backend_contract import V1Environment


def make_environment() -> V1Environment:
    """A fresh headless BoxPush V1 environment over the authoritative backend."""
    from functional_layer.custom_env.box_push.env.box_push_v1_adapter import BoxPushV1Adapter
    return BoxPushV1Adapter()


__all__ = ["make_environment"]
