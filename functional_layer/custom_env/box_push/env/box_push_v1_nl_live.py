"""LIVE seam backend for the V1 NL track — the only place the NL track meets DSPy.

Lives beside the V1 runner and adapter in the sys.path-mounted env dir BY DESIGN: the
auto-discovered import guard (`tests/test_no_backend_imports.py`) forbids `nl/` from importing
dspy, and `functional_layer/` sits outside the guarded packages (like the adapter), so the live
binding is built here and injected as an `LMSeam`. Consumes only the pinned `NLRuntimeConfig`
(temperature 0, cache on). Used by the runner's opt-in `--nl live` path (`box_push_v1_run.py`)
and by the opt-in `tests/test_p3_live_lm.py` (`MAAOS_LIVE_LM=1`); no default test imports this
module. Relocated 2026-09-18 from `model_layer/planner/v1_nl_live.py` (post-R6 legacy
relocation; `.claude/rules/legacy-packages.md`).
"""
from __future__ import annotations


def build_live_seam(config):
    """NLRuntimeConfig -> LMSeam backed by a dspy.Predict call. Imports dspy lazily so that
    merely importing this module never requires the framework."""
    import dspy

    lm = dspy.LM(
        model=config.model,
        api_base=config.api_base,
        api_key=config.api_key,
        temperature=config.temperature,
        seed=config.seed,
        cache=config.cache,
    )

    class _OneField(dspy.Signature):
        """Answer the request exactly as the format field instructs."""
        request: str = dspy.InputField(desc="Named fields of a typed NL-module request.")
        answer: str = dspy.OutputField(desc="The single answer line the format asks for.")

    predict = dspy.Predict(_OneField)

    class _LiveSeam:
        def complete(self, request):
            rendered = "\n".join(f"{k}: {v}" for k, v in request.fields)
            with dspy.context(lm=lm):
                return predict(request=rendered).answer

    return _LiveSeam()
