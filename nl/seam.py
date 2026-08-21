"""The offline LM seam (§18 item 3) — the ONLY doorway between the NL track and any language
model.

Every NL module that needs a model talks to an `LMSeam`: a typed request in, raw text out.
The default (and only in-repo) implementation is `RecordedLM`, a deterministic fixture store —
default P3 tests never touch a live model (.claude/rules/testing.md). The live DSPy binding
lives OUTSIDE this package (`model_layer/planner/v1_nl_live.py`): the auto-discovered import
guard (`tests/test_no_backend_imports.py`) forbids `nl/` from importing `dspy` at all, so the
seam is structural, not conventional.

A missing fixture is an INFRASTRUCTURE problem with the test/runtime wiring, never an NL
verdict: `RecordedLM` raises the typed `UnrecordedRequestError` rather than inventing text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Tuple


@dataclass(frozen=True, slots=True)
class NLRequest:
    """One typed request to a language model: which module asks, and its named fields.

    Fields are strings built from TYPED data upstream (canonical state, typed outcomes, the
    frozen registry) — never rendered grids, beliefs, or rewards (`shared/observation.py`
    V1_VISIBILITY: the NL track sees EXACT_STATE + PUBLIC_EXECUTION_RESULT only).
    """
    module: str
    fields: Tuple[Tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.module:
            raise ValueError("NLRequest requires a module name")
        items = tuple(sorted((str(k), str(v)) for k, v in dict(self.fields).items()))
        object.__setattr__(self, "fields", items)

    @classmethod
    def of(cls, module: str, **fields: str) -> "NLRequest":
        return cls(module=module, fields=tuple(fields.items()))

    def key(self) -> str:
        """Deterministic serialization — the fixture-store key."""
        return json.dumps(
            {"module": self.module, "fields": dict(self.fields)},
            sort_keys=True, separators=(",", ":"),
        )


class LMSeam(Protocol):
    def complete(self, request: NLRequest) -> str: ...


class UnrecordedRequestError(RuntimeError):
    """A request with no recorded response. Test-infrastructure material, never an NL verdict."""

    def __init__(self, request: NLRequest) -> None:
        super().__init__(
            f"no recorded response for module={request.module!r}; "
            f"request key: {request.key()}"
        )
        self.request = request


@dataclass(frozen=True, slots=True)
class RecordedLM:
    """Deterministic recorded/mock fixture seam. Exact-match on the request key; no fallback."""
    responses: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "responses", tuple((str(k), str(v)) for k, v in dict(self.responses).items()))

    @classmethod
    def of(cls, recorded: Mapping[NLRequest, str]) -> "RecordedLM":
        return cls(responses=tuple((req.key(), text) for req, text in recorded.items()))

    def complete(self, request: NLRequest) -> str:
        table = dict(self.responses)
        try:
            return table[request.key()]
        except KeyError:
            raise UnrecordedRequestError(request) from None
