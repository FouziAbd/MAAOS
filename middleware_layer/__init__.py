"""
Middleware Layer
================

Bridges functional environments and model layer (agent + planner).

Components:
- observation_simplifier: LLM-based observation summarization
- action_descriptor: LLM-based action description enrichment
- scenario_simplifier: LLM-based scenario/goal condensing
- action_executor: Maps action indices to environment steps
- middleware_orchestrator: Central coordinator for all middleware components
"""

from middleware_layer.observation_simplifier import ObservationSimplifier
from middleware_layer.action_descriptor import ActionDescriptor
from middleware_layer.scenario_simplifier import ScenarioSimplifier
from middleware_layer.action_executor import ActionExecutor
from middleware_layer.middleware_orchestrator import MiddlewareOrchestrator

__all__ = [
    "ObservationSimplifier",
    "ActionDescriptor",
    "ScenarioSimplifier",
    "ActionExecutor",
    "MiddlewareOrchestrator",
]
