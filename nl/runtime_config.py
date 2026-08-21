"""Pinned deterministic NL runtime configuration (§18 items 2/3; contract :234-236).

`PINNED_V1_NL_RUNTIME` is the ONE configuration a live V1 NL run may use: temperature 0,
response caching ON, fixed model/provider. Model and api_base match the legacy runner's
hardcoded values (`box_push_centralized.py::main`); `cache=True` is a DELIBERATE departure from
the legacy `cache=False` — the supervisor contract (:236) requires response caching for the V1
baseline. Consumed only through the seam builder in `model_layer/planner/v1_nl_live.py`. Default tests never instantiate a live seam;
this module exists so the LIVE path has exactly one, pinned, reviewable configuration.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NLRuntimeConfig:
    provider: str
    model: str
    api_base: str
    api_key: str                     # ollama ignores the value but the client requires one
    temperature: float
    seed: int                        # forwarded to the LM client by the live seam builder
    cache: bool

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("NLRuntimeConfig requires a model")
        if self.temperature != 0.0:
            # V1 is a temperature-0 baseline (contract :235). A nonzero temperature is a
            # different experiment, not a V1 configuration.
            raise ValueError("V1 NL runtime is a temperature-0 baseline")


PINNED_V1_NL_RUNTIME = NLRuntimeConfig(
    provider="ollama",
    model="ollama_chat/gemma4:e4b",
    api_base="http://localhost:11434",
    api_key="ollama",
    temperature=0.0,
    seed=42,
    cache=True,
)
