"""`validate_domain` (DK3) — the author-facing check that a `DomainPackage` is correctly
connected to the runtime, reported in the author's terms.

Every check has a stable code (`DKnnn`), a one-line title, and on FAIL/WARN a message that
names the FILE / FUNCTION / CONTRACT MEMBER to fix — never a runtime frame. Each check runs
inside its own guard: an exception inside a check becomes that check's FAIL with the
exception text (and the innermost frame under `domains/`, the author's own file) under
`details`, so one broken component never hides the others and no traceback is the headline.
A check that cannot run is SKIPPED with the reason, never PASS, and never silently absent:
every code in the catalogue appears in every report.

The catalogue (`docs/decisions/DK1_DOMAIN_PACKAGE.md` §"DK3 — validation catalogue"):

    DK001  registry        the name is registered (CLI level; `validate_named`)
    DK002  registry        the registered object is a DomainPackage named like its key
    DK010-DK017 contracts  services / symbolic track / comparator / environment / task /
                           state / call / reasoning track satisfy their `shared.contracts`
                           protocols — missing members are listed by name (members are
                           looked up statically: define them on the class)
    DK018  call equality   calls compare by value (a frozen dataclass)
    DK020  tasks           the default task is declared
    DK030-DK032 environment reset returns a state; export_full_state is stable; observe()
                           does not alias the state; execute before reset is a typed refusal
    DK040-DK043 plan       returns a PlannerResult; heads are grounded; deterministic;
                           `examples.ungrounded_call` is rejected by ground()
    DK050-DK052 evaluate   returns a CallValidation; ValidatedCall carries the head;
                           `examples.inapplicable_call` is SymbolicallyInapplicable
    DK060  predict         returns a Prediction with typed keys
    DK070  execution       a bounded episode under BOTH policies, no advisory track,
                           terminates with a typed EpisodeOutcome (a typed halt is a valid
                           outcome); every trace entry is JSON-serializable; discrepancies
                           are typed. A FAULTED episode is a FAIL naming the faulting
                           component; HALTED_REPEATED_FAILURE with no recovery provider under
                           advisory_two_track is a WARN with guidance
    DK071  advisory        with a declared reasoning track: one advisory episode with it
    DK080  package layout  (CLI level, needs `domains/<name>/`) module roles: only
                           `__init__.py` reaches `app`/`runtime`/`environment`; the symbolic
                           side never imports `environment`, a backend, another domain or the
                           package itself; a backend is imported from `environment.py` only
                           (`__init__.py` included); no dynamic import anywhere
    DK081  backend door    a backend-importing `environment.py` must be enumerated in the
                           guard's `DOMAIN_ENVIRONMENT_MODULES` (the one test-side line a
                           backend-wrapping domain needs; a pure-Python domain needs none);
                           an LM framework or a legacy tree can never be exempted
    DK082  lazy backend    (CLI level) `import domains.<name>` loads no backend module — the
                           backend import belongs INSIDE the environment factory
    DK090  versions        services.model_version matches the plan's model_version

The validator ASSEMBLES loops through `app.assembly.assemble_loop` — it never constructs the
runtime by hand — and it never edits anything. The bounded episodes attach no reasoning
track; the DK071 episode attaches the domain's own declared one, so a run is offline by
RULE (an author must not declare a live LM track; the guide says so), and by construction
for BoxPush (`reasoning_track=None`).

The role rules and backend roots below MIRROR `tests/test_no_backend_imports.py`, which
stays the authority (it is a test module, not importable from here); the DK3 test asserts
the mirrored constants equal the originals and runs both scanners on the same probe trees,
so the mirror cannot drift silently.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import os
import pathlib
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

from runtime.loop import EpisodeOutcome, EpisodeResult
from shared.comparison_keys import SymbolicKey, WorldKey
from shared.contracts import (
    DomainServices,
    Environment,
    Prediction,
    ProposalComparator,
    ReasoningTrack,
    RuntimeCall,
    RuntimeState,
    SymbolicTrack,
    TaskContract,
)
from shared.discrepancy import ExecutionDiscrepancy
from shared.faults import InfrastructureFaultError
from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
from shared.planner_result import NoPlan, PlanFound, PlannerFailure, PlannerResult
from shared.skills import CallValidation, SymbolicallyInapplicable, UngroundedCall, ValidatedCall

from app.assembly import assemble_loop
from app.domain_package import DomainPackage

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GUIDE = "docs/domains/ADDING_A_DOMAIN.md"


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's verdict. `message` is what the author reads; `details` is the raw
    evidence (exception text, offending values) kept out of the headline."""
    code: str
    status: Status
    title: str
    message: str = ""
    details: str = ""

    def render(self) -> str:
        line = f"  {self.status.value:<7} {self.code}  {self.title}"
        if self.message:
            line += f"\n          -> {self.message}"
        if self.details:
            line += f"\n          details: {self.details}"
        return line


#: Every code with its title, in report order. A report always contains each one at least
#: once (DK070 twice: one per policy); a check that could not run is SKIPPED with the reason.
CATALOGUE: Tuple[Tuple[str, str], ...] = (
    ("DK001", "the domain is registered"),
    ("DK002", "the registered object is a DomainPackage"),
    ("DK010", "services satisfy DomainServices"),
    ("DK011", "symbolic track satisfies SymbolicTrack"),
    ("DK012", "comparator satisfies ProposalComparator"),
    ("DK013", "environment satisfies Environment"),
    ("DK014", "task satisfies TaskContract"),
    ("DK015", "state satisfies RuntimeState"),
    ("DK016", "call satisfies RuntimeCall"),
    ("DK017", "reasoning track satisfies ReasoningTrack"),
    ("DK018", "calls compare by value"),
    ("DK020", "default task is declared"),
    ("DK030", "reset returns a RuntimeState"),
    ("DK031", "observe() does not alias the authoritative state"),
    ("DK032", "execute_skill before reset() is a typed refusal"),
    ("DK040", "plan returns a PlannerResult"),
    ("DK041", "plan heads are grounded"),
    ("DK042", "plan is deterministic"),
    ("DK043", "ground() rejects an ungrounded example"),
    ("DK050", "evaluate returns a CallValidation"),
    ("DK051", "the plan head is applicable"),
    ("DK052", "evaluate() rejects an inapplicable example"),
    ("DK060", "predict returns a Prediction"),
    ("DK070", "bounded episode under both policies"),
    ("DK071", "advisory episode with the reasoning track"),
    ("DK080", "package layout follows the module roles"),
    ("DK081", "the backend door is enumerated in the import guard"),
    ("DK082", "importing the package loads no backend"),
    ("DK090", "model versions agree"),
)
_ORDER = {code: i for i, (code, _) in enumerate(CATALOGUE)}
_TITLES = dict(CATALOGUE)
#: the codes only the CLI (`validate_named`) can produce — they need the name / directory
CLI_CODES: FrozenSet[str] = frozenset({"DK001", "DK002", "DK080", "DK081", "DK082"})

#: contract member -> the protocol it belongs to (for actionable AttributeError messages)
_MEMBER_OF: Dict[str, str] = {}
for _proto in (DomainServices, SymbolicTrack, Environment, ProposalComparator, ReasoningTrack,
               RuntimeState, RuntimeCall, TaskContract):
    for _member in getattr(_proto, "__protocol_attrs__", ()):
        _MEMBER_OF.setdefault(_member, _proto.__name__)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    name: str
    findings: Tuple[Finding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ordered = sorted(self.findings, key=lambda f: _ORDER.get(f.code, 999))  # stable
        object.__setattr__(self, "findings", tuple(ordered))

    @property
    def ok(self) -> bool:
        return not any(f.status is Status.FAIL for f in self.findings)

    def count(self, status: Status) -> int:
        return sum(1 for f in self.findings if f.status is status)

    def by_code(self, code: str) -> Finding:
        """The finding for `code`; when a code appears twice (DK070), the worst one."""
        rank = {Status.FAIL: 0, Status.WARN: 1, Status.SKIPPED: 2, Status.PASS: 3}
        matches = sorted((f for f in self.findings if f.code == code), key=lambda f: rank[f.status])
        if not matches:
            raise KeyError(code)
        return matches[0]

    def render(self) -> str:
        lines = [f"validate-domain {self.name}"]
        lines.extend(f.render() for f in self.findings)
        lines.append(
            f"Result: {self.count(Status.PASS)} PASS, {self.count(Status.WARN)} WARN, "
            f"{self.count(Status.FAIL)} FAIL, {self.count(Status.SKIPPED)} SKIPPED"
            + ("" if self.ok else f"  — fix the FAIL items (see {GUIDE})")
        )
        return "\n".join(lines)


def author_frame(error: BaseException) -> str:
    """The innermost traceback frame inside `domains/` — the author's own file — or ''."""
    for frame in reversed(traceback.extract_tb(error.__traceback__)):
        path = pathlib.Path(frame.filename)
        try:
            rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            continue
        if rel.startswith("domains/"):
            return f" at {rel}:{frame.lineno}"
    return ""


# ── the check runner ──────────────────────────────────────────────────────────────────

class _Checks:
    """Accumulates findings; every check body runs under `_guard`."""

    def __init__(self, package: DomainPackage, *, executive_budget: int) -> None:
        self.package = package
        self.executive_budget = executive_budget
        self.findings: List[Finding] = []
        self.blocked_by: Optional[str] = None       # the first contract FAIL, if any
        # shared fixtures, filled by earlier checks and read by later ones
        self.task: Any = None
        self.env: Any = None
        self.services: Any = None
        self.track: Any = None
        self.state: Any = None
        self.head: Any = None

    # ── recording ──
    def _add(self, code: str, status: Status, message: str = "", details: str = "") -> None:
        self.findings.append(Finding(code, status, _TITLES[code], message, details))

    def passed(self, code: str, details: str = "") -> None:
        self._add(code, Status.PASS, details=details)

    def failed(self, code: str, message: str, details: str = "") -> None:
        self._add(code, Status.FAIL, message, details)

    def warned(self, code: str, message: str, details: str = "") -> None:
        self._add(code, Status.WARN, message, details)

    def skipped(self, code: str, message: str) -> None:
        self._add(code, Status.SKIPPED, message)

    def block(self, code: str) -> None:
        if self.blocked_by is None:
            self.blocked_by = code

    def _guard(self, code: str, what: str, body: Callable[[], object]) -> None:
        """Run one check; an escaping exception is that check's FAIL, never a traceback."""
        try:
            body()
        except InfrastructureFaultError as error:
            self.failed(code, f"{what} raised a typed infrastructure fault; see details",
                        f"{error.fault.kind}: {error.fault.message}{author_frame(error)}")
        except AttributeError as error:
            name = getattr(error, "name", None) or str(error)
            owner = _MEMBER_OF.get(str(name))
            hint = (f"{name} is a {owner} member: the object you return for it must define "
                    f"{name} (see {GUIDE} §{owner})" if owner else
                    f"{name!r} is not a contract member — a bug inside the domain's own code")
            self.failed(code, f"{what} raised AttributeError: {hint}",
                        f"{error}{author_frame(error)}")
        except Exception as error:                      # noqa: BLE001 — author-facing by design
            self.failed(code, f"{what} raised {type(error).__name__}; see details",
                        f"{error}{author_frame(error)}")

    # ── protocol conformance with missing-member listing ──
    @staticmethod
    def _missing(obj: object, protocol: type) -> List[str]:
        """Members of `protocol` the object lacks — looked up STATICALLY, because `hasattr`
        would run property getters (an unsynced track's `state` raises by contract)."""
        members = getattr(protocol, "__protocol_attrs__", None)
        if members is None:                             # older typing: derive from annotations/dir
            members = {n for n in dir(protocol) if not n.startswith("_")}
        sentinel = object()
        return sorted(
            m for m in members
            if inspect.getattr_static(obj, m, sentinel) is sentinel
            and inspect.getattr_static(type(obj), m, sentinel) is sentinel
        )

    def _conforms(self, code: str, obj: object, protocol: type, where: str) -> bool:
        missing = self._missing(obj, protocol)
        if missing:
            self.failed(code,
                        f"{where} is missing {', '.join(missing)}: define them on the class "
                        f"(members are looked up statically, so delegation through __getattr__ "
                        f"or a property that raises does not count); see {GUIDE} "
                        f"§{protocol.__name__}", f"got {type(obj).__name__}")
            self.block(code)
            return False
        shadowed = self._shadowed_methods(obj, protocol)
        if shadowed or not isinstance(obj, protocol):
            what = (f"{', '.join(shadowed)} must be a METHOD; a field or attribute of the same "
                    f"name shadows it (rename the field)" if shadowed else
                    "one of its members is not a method/property")
            self.failed(code, f"{where}: {what} (see {GUIDE} §{protocol.__name__})",
                        f"got {type(obj).__name__}")
            self.block(code)
            return False
        self.passed(code, f"{type(obj).__name__}")
        return True

    @staticmethod
    def _shadowed_methods(obj: object, protocol: type) -> List[str]:
        """Protocol members that are METHODS on the protocol but not callable on the object
        (e.g. a dataclass field named `key` shadowing `Call.key()`)."""
        sentinel = object()
        found = []
        for member in getattr(protocol, "__protocol_attrs__", ()):
            if not inspect.isfunction(inspect.getattr_static(protocol, member, None)):
                continue                                # properties: presence is enough
            on_type = inspect.getattr_static(type(obj), member, sentinel)
            on_obj = inspect.getattr_static(obj, member, sentinel)
            value = on_obj if on_obj is not sentinel else on_type
            if isinstance(value, property) or (value is not sentinel and not callable(value)):
                found.append(member)
        return sorted(found)

    # ── DK010-DK020: contracts ──
    def check_contracts(self) -> None:
        p = self.package
        self.task = p.task()
        self._conforms("DK014", self.task, TaskContract, "the task object (is_satisfied_by / canonical)")

        def services() -> None:
            self.services = p.services(self.task)
            self._conforms("DK010", self.services, DomainServices,
                           "services (plan / ground / evaluate / predict / monitor / model_version)")
        self._guard("DK010", "services(task)", services)

        def track() -> None:
            self.track = p.symbolic_track()
            self._conforms("DK011", self.track, SymbolicTrack, "the symbolic track (sync / state / record_outcome)")
        self._guard("DK011", "symbolic_track()", track)

        if p.comparator is None:
            self.skipped("DK012", "no comparator declared (only needed with a reasoning track)")
        else:
            self._guard("DK012", "comparator()",
                        lambda: self._conforms("DK012", p.comparator(), ProposalComparator,  # type: ignore[misc]
                                               "the comparator (compare)"))

        def env() -> None:
            self.env = p.environment()
            self._conforms("DK013", self.env, Environment,
                           "the environment (reset / observe / export_full_state / execute_skill / is_terminal / render)")
        self._guard("DK013", "environment()", env)

        if p.reasoning_track is None:
            self.skipped("DK017", "no reasoning track declared (optional)")
        else:
            self._guard("DK017", "reasoning_track()",
                        lambda: self._conforms("DK017", p.reasoning_track(), ReasoningTrack,  # type: ignore[misc]
                                               "the reasoning track (observe / propose)"))

        # guaranteed by DomainPackage.__post_init__; reported so the author sees the task used
        self.passed("DK020", f"{p.default_task!r} of {sorted(p.tasks)}")

    # ── DK030-DK032: environment ──
    def check_environment(self) -> None:
        if self.env is None or self.blocked_by == "DK013":
            return

        def reset() -> None:
            self.state = self.env.reset()
            if not self._conforms("DK015", self.state, RuntimeState, "the state type (world_key / same_world)"):
                return
            first, second = self.env.export_full_state(), self.env.export_full_state()
            if not isinstance(first.world_key(), WorldKey):
                self.failed("DK030", "state.world_key() must return a shared.comparison_keys."
                            "WorldKey (use kit.keys.world_key)")
                return
            if first.world_key() != second.world_key() or not first.same_world(second):
                self.failed("DK030", "export_full_state() is not stable between two calls with "
                            "no attempt in between: world_key()/same_world() must be a pure "
                            "function of the world content")
                return
            self.passed("DK030")
        self._guard("DK030", "environment.reset()", reset)
        if self.state is None:
            return

        def observe() -> None:
            first = self.env.observe()
            second = self.env.observe()
            if first is second and first is not None and not isinstance(first, (str, int, float, bool, tuple, frozenset)):
                self.failed("DK031", "observe() returned the SAME object twice: return a fresh "
                            "deep copy (kit.EnvironmentBase does this for you)")
                return
            if first is self.env.export_full_state():
                self.failed("DK031", "observe() returned the authoritative state object itself; "
                            "the public observation must be a separate copy")
                return
            self.passed("DK031")
        self._guard("DK031", "environment.observe()", observe)

    def check_refusal(self) -> None:
        if self.head is None:
            return

        def refusal() -> None:
            fresh = self.package.environment()
            try:
                returned = fresh.execute_skill(self.head)
            except InfrastructureFaultError as error:
                if error.fault.message.startswith("refused:"):
                    self.passed("DK032", error.fault.message)
                else:
                    self.failed("DK032", "the refusal fault's message must begin with 'refused:' "
                                "(shared/faults.py); kit.EnvironmentBase does this",
                                error.fault.message)
                return
            self.failed("DK032", "execute_skill before reset() must raise "
                        "InfrastructureFaultError('refused: ...'); it returned a value instead",
                        f"returned {type(returned).__name__}")
        self._guard("DK032", "environment.execute_skill()", refusal)

    # ── DK040-DK043: plan ──
    def check_plan(self) -> None:
        if self.services is None or self.track is None or self.state is None or self.blocked_by:
            return

        def plan() -> None:
            self.track.sync(self.state)
            result = self.services.plan(self.track.state, self.state)
            if not isinstance(result, PlannerResult):
                self.failed("DK040", "services.plan() must return PlanFound / NoPlan / "
                            "PlannerFailure (shared.planner_result); kit.bfs_plan returns "
                            "exactly those", f"got {type(result).__name__}")
                self.block("DK040")
                return
            self.passed("DK040", type(result).__name__)

            def deterministic() -> None:
                again = self.services.plan(self.track.state, self.state)
                if again != result:
                    self.failed("DK042", "two calls of services.plan() on the same state "
                                "returned different results; planning must be a pure function "
                                "of the symbolic state")
                else:
                    self.passed("DK042")
            if isinstance(result, PlannerFailure):
                self.failed("DK041", f"the planner reported an infrastructure failure on the "
                            f"initial state: {result.error}")
                return
            if isinstance(result, NoPlan):
                deterministic()
                self.warned("DK041", f"no plan on the initial state ({result.reason}); nothing "
                            f"to ground. If the task should be solvable, check applicable()/plan()")
                return
            assert isinstance(result, PlanFound)
            if not result.plan:
                deterministic()
                self.warned("DK041", "the plan is empty on the initial state — is the goal "
                            "already satisfied?")
                return
            head = result.plan[0]
            if not self._conforms("DK016", head, RuntimeCall, "the call type (skill / cost / key / canonical)"):
                return
            if copy.copy(head) != head:                 # a frozen dataclass copies to an equal value
                self.failed("DK018", "two equal calls must compare equal (==): use a frozen "
                            "dataclass for the call type")
                self.block("DK018")
                return
            self.passed("DK018")
            deterministic()                             # only meaningful once calls compare by value
            ungrounded = self.services.ground(self.state, head)
            if ungrounded is not None:
                self.failed("DK041", "the plan's first call names an identity the initial state "
                            "lacks; plan() must enumerate calls from state.identities() only",
                            str(ungrounded))
                return
            self.head = head
            self.passed("DK041", str(head))
            if result.model_version is not None and result.model_version != self.services.model_version:
                self.failed("DK090", "PlanFound.model_version differs from services.model_version; "
                            "stamp the same ModelVersion on both",
                            f"{result.model_version} vs {self.services.model_version}")
            else:
                self.passed("DK090")
        self._guard("DK040", "services.plan()", plan)

        examples = self.package.examples
        if examples is None or examples.ungrounded_call is None:
            self.warned("DK043", "no examples declared: add examples=DomainExamples("
                        "ungrounded_call=<a call naming an identity the initial state lacks>, "
                        "inapplicable_call=<a grounded call whose preconditions fail in the "
                        "initial state>) to DomainPackage(...) (app.domain_package) so "
                        "ground()/evaluate() rejections are checked")
        else:
            def ungrounded() -> None:
                verdict = self.services.ground(self.state, examples.ungrounded_call)
                if isinstance(verdict, UngroundedCall):
                    self.passed("DK043", verdict.reason)
                else:
                    self.failed("DK043", "services.ground(state, examples.ungrounded_call) must "
                                "return an UngroundedCall; either the example names only known "
                                "identities or ground() does not check identities",
                                f"got {verdict!r}")
            self._guard("DK043", "services.ground()", ungrounded)

    # ── DK050-DK060: evaluate / predict ──
    def check_evaluate_and_predict(self) -> None:
        if self.head is not None:
            def evaluate() -> None:
                verdict = self.services.evaluate(self.track.state, self.head)
                if not isinstance(verdict, CallValidation):
                    self.failed("DK050", "services.evaluate() must return ValidatedCall / "
                                "SymbolicallyInapplicable / ... (shared.skills)",
                                f"got {type(verdict).__name__}")
                    self.block("DK050")
                    return
                self.passed("DK050", type(verdict).__name__)
                if not isinstance(verdict, ValidatedCall):
                    self.failed("DK051", "the planner's own first call is not applicable in the "
                                "state it planned from; plan() and applicable() disagree",
                                getattr(verdict, "reason", ""))
                    self.block("DK051")
                elif verdict.call != self.head:
                    self.failed("DK051", "ValidatedCall.call must be the call that was evaluated")
                else:
                    self.passed("DK051")
            self._guard("DK050", "services.evaluate()", evaluate)

            def predict() -> None:
                prediction = self.services.predict(self.track.state, self.state, self.head)
                if not isinstance(prediction, Prediction):
                    self.failed("DK060", "services.predict() must return shared.contracts.Prediction",
                                f"got {type(prediction).__name__}")
                    return
                if prediction.symbolic_key is not None and not isinstance(prediction.symbolic_key, SymbolicKey):
                    self.failed("DK060", "Prediction.symbolic_key must be a SymbolicKey (kit.keys.symbolic_key)")
                    return
                if prediction.world_key is not None and not isinstance(prediction.world_key, WorldKey):
                    self.failed("DK060", "Prediction.world_key must be a WorldKey (kit.keys.world_key)")
                    return
                if prediction.symbolic_key is None and prediction.world_key is None:
                    self.warned("DK060", "the prediction carries no key on either basis, so what "
                                "the world actually did after a successful call will never be "
                                "checked against what the model predicted")
                    return
                self.passed("DK060")
            self._guard("DK060", "services.predict()", predict)

        examples = self.package.examples
        if self.track is None or self.state is None or self.blocked_by:
            return
        if examples is None or examples.inapplicable_call is None:
            self.warned("DK052", "no examples.inapplicable_call declared: add examples="
                        "DomainExamples(..., inapplicable_call=<a grounded call whose "
                        "preconditions fail in the initial state>) to DomainPackage(...) so "
                        "evaluate() rejections are checked")
        else:
            def inapplicable() -> None:
                if self.services.ground(self.state, examples.inapplicable_call) is not None:
                    self.failed("DK052", "examples.inapplicable_call must be GROUNDED (known "
                                "identities) but symbolically inapplicable; this one is ungrounded")
                    return
                verdict = self.services.evaluate(self.track.state, examples.inapplicable_call)
                if isinstance(verdict, SymbolicallyInapplicable):
                    self.passed("DK052", verdict.reason)
                else:
                    self.failed("DK052", "services.evaluate(initial symbolic state, "
                                "examples.inapplicable_call) must return SymbolicallyInapplicable",
                                f"got {verdict!r}")
            self._guard("DK052", "services.evaluate()", inapplicable)

    # ── DK070-DK071: execution ──
    def _episode(self, policy: OrchestrationPolicy, *, use_track: bool) -> Tuple[Any, EpisodeResult]:
        config = OrchestrationConfig(policy=policy, executive_step_budget=self.executive_budget)
        loop = assemble_loop(self.package, config=config, use_reasoning_track=use_track)
        return loop, loop.run()

    def _check_episode(self, code: str, policy: OrchestrationPolicy, *, use_track: bool) -> None:
        label = f"{policy.value}" + (" with the reasoning track" if use_track else "")

        def run() -> None:
            loop, episode = self._episode(policy, use_track=use_track)
            if not isinstance(episode.outcome, EpisodeOutcome):
                self.failed(code, f"[{label}] the episode did not end with a typed EpisodeOutcome")
                return
            for entry in episode.history.entries:
                json.dumps(entry.canonical())            # every trace entry serializes
            bad = [d for d in episode.discrepancies if not isinstance(d, ExecutionDiscrepancy)]
            if bad:
                self.failed(code, f"[{label}] monitor() returned something other than typed "
                            f"ExecutionDiscrepancy values", f"{type(bad[0]).__name__}")
                return
            summary = (f"[{label}] {episode.outcome.value}: {episode.reason}; "
                       f"{loop.executive_steps_charged} executive steps, "
                       f"{len(episode.discrepancies)} discrepancies")
            if episode.outcome is EpisodeOutcome.FAULTED:
                faults = [f for e in episode.history.entries for f in e.faults]
                where = faults[-1] if faults else None
                # lead with the author-side source; a runtime wrapper's own path is evidence
                # for details, not a headline the author can act on
                source = where.source if where and not where.source.startswith(("runtime/", "app/")) else ""
                self.failed(code,
                            f"[{label}] the episode FAULTED{' in ' + source if source else ''}: "
                            f"{where.message}. A fault means a component broke its contract; "
                            f"fix that component" if where else
                            f"[{label}] the episode FAULTED: {episode.reason}",
                            f"kind={where.kind} source={where.source!r} detail={where.detail!r}" if where else "")
                return
            if (episode.outcome is EpisodeOutcome.HALTED_REPEATED_FAILURE
                    and policy is OrchestrationPolicy.ADVISORY_TWO_TRACK
                    and self.package.recovery_provider is None):
                self.warned(code, f"[{label}] the episode halted on a repeated physical failure "
                            f"and the package declares no recovery_provider, so "
                            f"advisory_two_track cannot escape it; declare one (a callable "
                            f"ExecutionDiscrepancy -> calls) if the domain should recover", summary)
                return
            self.passed(code, summary + " (a typed halt is a valid outcome; only a FAULTED "
                                        "episode fails this check)")
        self._guard(code, f"[{label}] the executive loop", run)

    def check_execution(self) -> None:
        if self.env is None or self.services is None or self.track is None or self.blocked_by:
            return
        self._check_episode("DK070", OrchestrationPolicy.SYMBOLIC_PRIMARY, use_track=False)
        self._check_episode("DK070", OrchestrationPolicy.ADVISORY_TWO_TRACK, use_track=False)
        if self.package.reasoning_track is None:
            self.skipped("DK071", "no reasoning track declared (optional)")
        else:
            self._check_episode("DK071", OrchestrationPolicy.ADVISORY_TWO_TRACK, use_track=True)

    def fill_missing(self, *, include_cli: bool) -> None:
        """Every catalogue code appears: a check that could not run is SKIPPED, naming why."""
        present = {f.code for f in self.findings}
        reason = (f"not run: fix {self.blocked_by} first" if self.blocked_by
                  else "not run: an earlier check failed (see the first FAIL above)")
        for code, _ in CATALOGUE:
            if code in present or (code in CLI_CODES and not include_cli):
                continue
            self.skipped(code, reason)


def validate_domain(package: DomainPackage, *, executive_budget: int = 50) -> ValidationReport:
    """Run every check on an already-constructed `DomainPackage`."""
    checks = _Checks(package, executive_budget=executive_budget)
    checks.check_contracts()
    checks.check_environment()
    checks.check_plan()
    checks.check_refusal()
    checks.check_evaluate_and_predict()
    checks.check_execution()
    checks.fill_missing(include_cli=False)
    return ValidationReport(package.name, tuple(checks.findings))


# ── CLI-level checks: the registry and the package directory ──────────────────────────

def registry_line(name: str) -> Tuple[str, str]:
    """The exact two lines an author adds to `domains/registry.py`: the import and the entry."""
    alias = f"_{name.upper()}"
    return (f"from domains.{name} import DOMAIN as {alias}", f'    "{name}": {alias},')


def lookup(name: str, registry: Mapping[str, DomainPackage]) -> Tuple[Optional[DomainPackage], List[Finding]]:
    """Resolve a name through the static registry (no dynamic import)."""
    if name not in registry:
        import_line, entry = registry_line(name)
        return None, [Finding(
            "DK001", Status.FAIL, _TITLES["DK001"],
            f"{name!r} is not in domains/registry.py. If domains/{name}/ does not exist yet, "
            f"create it first (python -m maaos create-domain {name}). Then add `{import_line}` "
            f"beside the other imports and the entry `{entry.strip()}` inside the "
            f"MappingProxyType({{...}}) literal (registered: {sorted(registry) or 'none'})",
        )]
    package = registry[name]
    if not isinstance(package, DomainPackage):
        return None, [
            Finding("DK001", Status.PASS, _TITLES["DK001"]),
            Finding("DK002", Status.FAIL, _TITLES["DK002"],
                    f"REGISTRY[{name!r}] must be the DOMAIN = DomainPackage(...) your package exports",
                    f"got {type(package).__name__}"),
        ]
    if package.name != name:
        return package, [
            Finding("DK001", Status.PASS, _TITLES["DK001"]),
            Finding("DK002", Status.FAIL, _TITLES["DK002"],
                    f"REGISTRY key {name!r} does not match DomainPackage.name {package.name!r}; "
                    f"they must be equal"),
        ]
    return package, [Finding("DK001", Status.PASS, _TITLES["DK001"]),
                     Finding("DK002", Status.PASS, _TITLES["DK002"])]


#: MIRRORS of the guard's constants in tests/test_no_backend_imports.py (the authority; the
#: DK3 test asserts each mirror EQUALS its original and that both scanners agree on probe
#: trees). Backend/framework roots only `environment.py` may import:
BACKEND_ROOTS: FrozenSet[str] = frozenset({
    "functional_layer", "legacy", "middleware_layer", "model_layer", "utils",
    "shared_skills", "skill_executor_push", "box_push_env",
    "multi_agent_box_push_env", "box_push_centralized", "box_push_per_step",
    "minigrid", "pettingzoo", "gymnasium", "dspy", "torch", "numpy",
})
#: ... except these, which no door line can ever exempt (legacy trees, LM frameworks):
NEVER_EXEMPT_ROOTS: FrozenSet[str] = frozenset({
    "legacy", "middleware_layer", "model_layer", "utils", "dspy", "torch",
})
#: dynamic-import roots banned everywhere:
DYNAMIC_ROOTS: FrozenSet[str] = frozenset({"importlib", "imp", "pkgutil", "runpy"})
COMPOSITION_ROOTS: FrozenSet[str] = frozenset({"runtime", "app", "maaos"})
ALLOWED_SYMBOLIC_ROOTS: FrozenSet[str] = frozenset({"shared", "kit"})
#: raw-text markers the guard bans (spelled by concatenation because the guard's own text
#: scan covers this file too; the guard's comment names this spelling)
_TEXT_MARKERS: Tuple[str, ...] = ("sys" + ".path", "sys" + ".modules", "__import" + "__")


def _imports(path: pathlib.Path, package: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                if node.level > len(base):
                    yield package, node.lineno
                    continue
                prefix = ".".join(base[: len(base) - (node.level - 1)] if node.level > 1 else base)
                if node.module:
                    yield f"{prefix}.{node.module}", node.lineno
                else:
                    for alias in node.names:
                        yield f"{prefix}.{alias.name}", node.lineno
            elif node.module:
                if node.module == package:
                    for alias in node.names:
                        yield f"{package}.{alias.name}", node.lineno
                else:
                    yield node.module, node.lineno


def _enumerated_doors(guard: pathlib.Path) -> FrozenSet[str]:
    """`DOMAIN_ENVIRONMENT_MODULES` parsed from the guard's AST (a commented-out line is not
    an entry)."""
    if not guard.is_file():
        return frozenset()
    tree = ast.parse(guard.read_text(encoding="utf-8"), filename=str(guard))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DOMAIN_ENVIRONMENT_MODULES" for t in node.targets
        ):
            return frozenset(
                n.value for n in ast.walk(node.value)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            )
    return frozenset()


def check_layout(name: str, *, repo_root: pathlib.Path = _REPO_ROOT) -> List[Finding]:
    """DK080/DK081 — module roles inside `domains/<name>/`, explained in the author's terms."""
    pkg_dir = repo_root / "domains" / name
    if not pkg_dir.is_dir():
        return [Finding("DK080", Status.SKIPPED, _TITLES["DK080"],
                        f"domains/{name}/ does not exist (a domain declared elsewhere is not layout-checked)"),
                Finding("DK081", Status.SKIPPED, _TITLES["DK081"], f"domains/{name}/ does not exist")]
    package = f"domains.{name}"
    siblings = {p.stem for p in pkg_dir.glob("*.py")}
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    problems: List[str] = []
    door_needs_exemption = False
    for path in sorted(pkg_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(repo_root).as_posix()
        role = path.name if path.parent == pkg_dir else "other"
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in _TEXT_MARKERS):
            problems.append(f"{rel}: do not manipulate the module search path or the module "
                            f"cache and do not call the dynamic import builtin (the import "
                            f"guard forbids dynamic imports everywhere)")
        for module, lineno in _imports(path, package):
            top = module.split(".")[0]
            if top in DYNAMIC_ROOTS:
                problems.append(f"{rel}:{lineno} imports {module} — dynamic imports are "
                                f"forbidden everywhere; import what you need statically")
                continue
            if top in BACKEND_ROOTS:
                if role == "environment.py" and top in NEVER_EXEMPT_ROOTS:
                    problems.append(f"{rel}:{lineno} imports {module} — an environment module is "
                                    f"a simulator binding, never an LM binding or a legacy tree; "
                                    f"no guard line can exempt this")
                elif role == "environment.py":
                    door_needs_exemption = True
                else:
                    problems.append(f"{rel}:{lineno} imports {module} — a backend/framework may "
                                    f"be imported from environment.py only"
                                    + (" (the composition module wires components, it does not "
                                       "load the backend)" if role == "__init__.py" else ""))
                continue
            if role == "__init__.py":
                continue                                # composition role: everything else is allowed
            if top in COMPOSITION_ROOTS:
                problems.append(f"{rel}:{lineno} imports {module} — only __init__.py may import "
                                f"the runtime/app layer; keep {path.name} to shared, kit and siblings")
            elif module == package or (module.startswith(package + ".")
                                       and module[len(package) + 1:].split(".")[0] not in siblings):
                problems.append(f"{rel}:{lineno} imports {module} — import sibling MODULES "
                                f"(`from .types import ...`), never the package or a name "
                                f"defined in __init__.py")
            elif module.startswith(package + "."):
                member = module[len(package) + 1:].split(".")[0]
                if role == "environment.py" and member == "model":
                    problems.append(f"{rel}:{lineno} imports model — environment.py is the backend "
                                    f"boundary and must not import the symbolic model")
                elif role != "environment.py" and member == "environment":
                    problems.append(f"{rel}:{lineno} imports environment — the symbolic side must "
                                    f"never reach the environment (no feasibility oracle)")
            elif top == "domains":
                problems.append(f"{rel}:{lineno} imports {module} — a domain package must not "
                                f"import another domain")
            elif role != "environment.py" and top not in stdlib | ALLOWED_SYMBOLIC_ROOTS:
                problems.append(f"{rel}:{lineno} imports {module} — {path.name} may import only "
                                f"the standard library, shared, kit and sibling modules")
    findings = []
    if problems:
        findings.append(Finding("DK080", Status.FAIL, _TITLES["DK080"],
                                "fix these imports: " + "; ".join(problems)
                                + f" (see {GUIDE} §Module roles)"))
    else:
        findings.append(Finding("DK080", Status.PASS, _TITLES["DK080"]))
    if door_needs_exemption:
        door = f"domains/{name}/environment.py"
        listed = door in _enumerated_doors(repo_root / "tests" / "test_no_backend_imports.py")
        findings.append(Finding(
            "DK081", Status.PASS if listed else Status.FAIL, _TITLES["DK081"],
            "" if listed else
            f"environment.py imports a backend/framework, so the import guard must name it: add "
            f"\"{door}\", to DOMAIN_ENVIRONMENT_MODULES in tests/test_no_backend_imports.py. "
            f"This is the one edit outside domains/{name}/ and domains/registry.py that a "
            f"backend-wrapping domain needs; a domain whose environment.py imports no "
            f"backend/framework needs no line under tests/ at all",
        ))
    else:
        findings.append(Finding("DK081", Status.PASS, _TITLES["DK081"],
                                details="environment.py imports no backend/framework; no guard line needed"))
    return findings


def check_lazy_backend(name: str, *, repo_root: pathlib.Path = _REPO_ROOT) -> Finding:
    """DK082 — `import domains.<name>` in a fresh interpreter loads no backend module."""
    script = (
        "import json, sys\n"
        f"import domains.{name}\n"
        f"roots = {sorted(BACKEND_ROOTS)!r}\n"
        "print(json.dumps(sorted(m for m in sys." + "modules if m.split('.')[0] in roots)))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(repo_root), SDL_VIDEODRIVER="dummy")
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=repo_root, env=env,
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Finding("DK082", Status.SKIPPED, _TITLES["DK082"],
                       f"could not start a fresh interpreter: {error}")
    if completed.returncode != 0:
        tail = completed.stderr.strip().splitlines()[-1:] or ["no error text"]
        return Finding("DK082", Status.FAIL, _TITLES["DK082"],
                       f"`import domains.{name}` failed in a fresh interpreter: {tail[0]}",
                       completed.stderr.strip()[-600:])
    loaded = json.loads(completed.stdout.strip().splitlines()[-1])
    if loaded:
        return Finding("DK082", Status.FAIL, _TITLES["DK082"],
                       f"importing domains/{name} loads the backend ({loaded[0]}, ...): move the "
                       f"backend import INSIDE make_environment() in environment.py so the "
                       f"package imports offline", ", ".join(loaded))
    return Finding("DK082", Status.PASS, _TITLES["DK082"])


def validate_named(
    name: str, registry: Mapping[str, DomainPackage], *, executive_budget: int = 50,
    repo_root: pathlib.Path = _REPO_ROOT,
) -> ValidationReport:
    """The CLI entry: registry lookup, then every check, then the package layout."""
    package, findings = lookup(name, registry)
    if package is None:
        return ValidationReport(name, tuple(findings))
    report = validate_domain(package, executive_budget=executive_budget)
    layout = check_layout(name, repo_root=repo_root)
    lazy = (check_lazy_backend(name, repo_root=repo_root)
            if (repo_root / "domains" / name).is_dir()
            else Finding("DK082", Status.SKIPPED, _TITLES["DK082"], f"domains/{name}/ does not exist"))
    return ValidationReport(name, tuple(findings) + report.findings + tuple(layout) + (lazy,))


__all__ = [
    "BACKEND_ROOTS",
    "author_frame",
    "CATALOGUE",
    "CLI_CODES",
    "DYNAMIC_ROOTS",
    "Finding",
    "GUIDE",
    "NEVER_EXEMPT_ROOTS",
    "Status",
    "ValidationReport",
    "check_layout",
    "check_lazy_backend",
    "lookup",
    "registry_line",
    "validate_domain",
    "validate_named",
]
