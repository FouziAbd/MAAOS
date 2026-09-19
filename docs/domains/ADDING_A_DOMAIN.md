# Adding a domain to MAAOS

This guide is complete on its own. You do not need to read the runtime to add a domain,
and you do not need to edit anything under `shared/`, `runtime/`, `kit/`, `app/` or `tests/`
other than the files the generator writes for you. If a step here forces you to open one of
those packages, that is a bug in this guide — please report it.

Everything is offline and deterministic: no language model, no network.

## What you get and what you write

MAAOS runs a domain as two peers over an authoritative environment: an **optimistic symbolic
planner** (yours, a few functions) and an optional **advisory reasoning track**. The runtime
(planning cycle, budgets, typed evidence, trace, two orchestration policies) is generic and
already written. A domain supplies:

| You write | Where | Size in practice |
|---|---|---|
| the value types: `State`, `Call`, `Task` | `types.py` | ~60 lines |
| the symbolic model: `project`, `apply`, `applicable`, `plan` (+ optional `apply_world`) | `model.py` | ~60 lines |
| the environment: `_reset`, `_attempt`, `_is_terminal` | `environment.py` | ~30 lines + your backend |
| the declaration: tasks, examples, recovery advice | `__init__.py` | ~30 lines |

Everything mechanical — refusals, typed results, the symbolic track, the monitor, the
comparator, loop assembly — comes from `kit/` and `app/` with sensible defaults.

## Quick start

```bash
python -m maaos create-domain warehouse            # writes domains/warehouse/ + tests/test_domain_warehouse.py
```

Add the two lines it prints to `domains/registry.py` (by hand; nothing edits that file):

```python
from domains.warehouse import DOMAIN as _WAREHOUSE          # beside the other imports
    "warehouse": _WAREHOUSE,                                  # inside the MappingProxyType({...}) literal
```

Then, before changing anything:

```bash
python -m maaos validate-domain warehouse          # the untouched scaffold: 28 PASS, 0 WARN, 0 FAIL
                                                   # (2 SKIPPED: the optional reasoning-track checks)
python -B -m unittest tests.test_domain_warehouse  # the generated test: OK
```

Now edit the `# TODO(author)` points in `types.py`, `model.py`, `environment.py` and
`__init__.py`. **The four files must agree before the package can import**, so change them
as one coherent step, then validate again. Repeat until your domain is what you meant, then
add your designed physical failure to the generated test (see below).

Finally run the whole offline suite and update its pinned size (the one thing outside your
package the suite asks of you, and it lives under `docs/`):

```bash
python -B -m unittest discover -s tests -t .
# then edit the single line "Current offline suite: N tests, deterministic and offline"
# in docs/refactor/REFACTOR_STATUS.md to the number the run printed (the difference is
# the number of tests in your generated test file)
```

## Module roles

A domain package has three roles, enforced by the import guard and explained by
`validate-domain` (check DK080). Keep them and you never need to think about the runtime's
boundaries.

| Module | Role | May import | Must never import |
|---|---|---|---|
| `__init__.py` | composition: declares `DOMAIN` | `app`, `kit`, `shared`, siblings | a backend or framework |
| `environment.py` | the backend boundary | `kit`, `shared`, `.types`, **your backend/simulator** | `model`, `app`, `runtime`, an LM framework (`dspy`, `torch`) |
| `types.py`, `model.py`, anything else | the symbolic side | stdlib, `shared`, `kit`, sibling **modules** (`from .types import State`) | `environment`, `app`, `runtime`, a backend, another domain, the package itself (`from . import DOMAIN`) |

Why: the symbolic side must never be able to ask the environment whether an action is
feasible. That is the point of the architecture — a symbolically applicable call that fails
physically is *evidence*, and the runtime reports it as such.

Two more rules that follow from this:

- **Import your backend inside `make_environment()`**, not at the top of `environment.py`,
  so `import domains.warehouse` stays offline (check DK082). If the backend is a framework
  the guard bans everywhere else (`numpy`, `pettingzoo`, `gymnasium`, `minigrid`), you add
  ONE line to the guard: `"domains/warehouse/environment.py",` in
  `DOMAIN_ENVIRONMENT_MODULES` in `tests/test_no_backend_imports.py` (check DK081 tells you
  exactly when). A pure-Python domain needs no such line. `dspy`/`torch`/legacy trees can
  never be imported from a domain.
- **No dynamic imports** anywhere (`importlib`, `__import__`, `sys.path` manipulation).

## What you write

### Value types (`types.py`)

Three frozen dataclasses. The runtime handles them without interpreting them; it only calls
the members below. Keep those names for **methods** and never name a dataclass **field** the
same (a field called `key` would silently shadow `Call.key()` — `validate-domain` reports
this as DK016).

#### RuntimeState

Your `State` is the authoritative world as a value.

| Member | Meaning |
|---|---|
| `canonical() -> dict` | the WORLD content, JSON-serializable; put episode bookkeeping (tick counters) OUTSIDE it |
| `world_key() -> WorldKey` | `kit.world_key(self.canonical())` |
| `same_world(other) -> bool` | `self.canonical() == other.canonical()` |
| `identities() -> frozenset[str]` | the names of the objects that exist |

#### RuntimeCall

Your `Call` is one grounded action.

| Member | Meaning |
|---|---|
| `skill` (property) | the action name; `str()` of it labels the observation |
| `cost` (property) | plan cost, usually `1` |
| `key() -> str` | deterministic serialization (the repeated-failure key) |
| `canonical() -> dict` | trace serialization |
| `identities() -> frozenset[str]` | the names of the objects the call acts on |
| `__str__` | how the call prints in reports |
| value equality (`==`) | provided by a frozen dataclass — required (check DK018) |

#### TaskContract

Your `Task` is the goal as a pure test over a `State`.

| Member | Meaning |
|---|---|
| `is_satisfied_by(state) -> bool` | the goal test; no environment access |
| `canonical() -> dict` | trace serialization |

### The symbolic model (`model.py`)

The model is deliberately **optimistic**: it decides from the symbolic state alone and does
not know what can go wrong physically. Never add a feasibility check, a reachability search,
or an environment query here.

| Member | Meaning |
|---|---|
| `model_version` (property) | a `ModelVersion`; bump `revision` when the model changes |
| `project(state) -> SymbolicState` | authoritative → symbolic (leave detail behind) |
| `apply(sym, call) -> SymbolicState` | the deterministic INTENDED effect |
| `applicable(sym, call) -> ValidatedCall \| SymbolicallyInapplicable` | preconditions over the symbolic state |
| `plan(sym, identities) -> PlanFound \| NoPlan \| PlannerFailure` | `kit.bfs_plan(...)` does the search; enumerate candidate calls from `identities` (a flat set of names — carry object kinds in the symbolic state if you have several) |
| `apply_world(state, call) -> State` (optional) | the intended effect on the authoritative state, so the monitor can also compare what the world did |

Your `SymbolicState` needs `canonical()` and `symbolic_key()` (`kit.symbolic_key(...)`).

#### DomainServices

You do not implement this contract yourself. `kit.DerivedDomainServices(MODEL,
apply_world=MODEL.apply_world)` derives all five runtime operations from your model:

| Operation | Derived as |
|---|---|
| `plan` | `MODEL.plan(sym, state.identities())` — the authoritative state is read for identities only |
| `ground` | identity membership: every identity the call names must exist in the state |
| `evaluate` | `MODEL.applicable` |
| `predict` | the keys of `MODEL.apply(...)` and, if given, `apply_world(...)` |
| `monitor` | a failed applicable call → `EXECUTION_FAILURE_OF_APPLICABLE_SKILL`; a success whose realized keys differ from the prediction → `STATE_EFFECT_MISMATCH` |

#### SymbolicTrack

You do not implement this either. `kit.ProjectionTrack(MODEL.project)` is the exact-projection
track every fully observable domain uses: `sync` re-projects the authoritative state,
`record_outcome` stores evidence and never patches the projection.

### The environment (`environment.py`)

#### Environment

Subclass `kit.EnvironmentBase[State, Call]`, set `call_type = Call`, write three hooks:

| Hook | Meaning |
|---|---|
| `_reset(seed) -> State` | the initial authoritative state; reinitialize your backend here |
| `_attempt(call, pre) -> result` | ONE executive attempt against your backend |
| `_is_terminal(state) -> bool` | when no further attempt is possible (the goal is not terminal by itself) |
| `_observe(state)` (optional) | the public observation; default: the state's `canonical()`, deep-copied |
| `__init__` (optional) | call `super().__init__()` and keep a simulator handle or configuration (e.g. which switch starts stuck). Physical FACTS — a stuck switch, a jammed latch — belong in `State.canonical()` like everything else the environment reports; `project()` is what keeps them from the model |

Inside `_attempt`:

- return `self.succeeded(call, pre, post)` when the intended effect was realized;
- return `self.failed(call, pre, post, failure_class=...)` otherwise: when the world changed
  the class is derived (`PARTIAL_EXECUTION`); when it did not, choose
  `FailureStateClass.UNCHANGED` (the backend attempted and changed nothing) or
  `BACKEND_REJECTED_BEFORE_TRANSITION` (it declined before attempting) — the kit never assumes;
- call `self.note_primitive_steps(n)` as primitive backend steps run;
- if your backend breaks mid-attempt, raise `self.mid_attempt_fault(kind, message)`; an
  ordinary exception escaping `_attempt` becomes the typed backend fault automatically;
- a physical failure the model does not know about is EXPECTED — it is what the runtime reports.

The base supplies the contract's mechanics: the reset-before-use refusal, the post-terminal
refusal, malformed and ungrounded calls returned (not raised), typed results, the provenance
of mid-attempt faults. The state you return in `post` becomes the authoritative state (a
value-state model; a domain wrapping an external mutable simulator derives its state value
inside `_attempt` from a fresh read). That state is the sole source of truth for the runtime:
every physical fact goes into it, including the ones your designed failure depends on — the
optimism lives in `project()`, which drops them, never in hiding them from `State`.

### The declaration (`__init__.py`)

`DOMAIN` is one `app.domain_package.DomainPackage`:

| Field | Meaning |
|---|---|
| `name` | must equal the registry key |
| `tasks`, `default_task` | named `Task` values; the default is what `validate-domain` runs |
| `environment` | the factory `make_environment` |
| `services` | `lambda task: DerivedDomainServices(MODEL, apply_world=MODEL.apply_world)` |
| `symbolic_track` | `lambda: ProjectionTrack(MODEL.project)` |
| `recovery_provider` | `recover`, see below (optional) |
| `comparator` | `lambda: DefaultProposalComparator[Call, AdvisoryProposal]()` (needed only with a reasoning track) |
| `reasoning_track` | optional, see below |
| `examples` | `DomainExamples(ungrounded_call=..., inapplicable_call=...)` — recommended, they enable two checks |

#### Recovery advice

`recover(discrepancy) -> tuple[Call, ...]` is consulted under the `advisory_two_track`
policy after the SAME (state, call) has failed physically three times. The calls it returns
are ADVICE: they run in order, through the same gates as any call, before the planner runs
again. `discrepancy.call` is the failed call; the environment's hidden reason is not visible.
Return `()` to advise nothing (the advisory policy then halts like the symbolic-primary one;
`validate-domain` warns about this).

#### ReasoningTrack

Optional. An advisory track has `observe(state, last_action_label, last_outcome)` and
`propose(task) -> proposal` where the proposal exposes `call`, `coverage`, `confidence`
(`shared.contracts.AdvisoryProposal`). Its proposals are evidence compared against the
symbolic choice; they never execute anything by themselves. **A declared track must be
offline** — MAAOS's default tests and `validate-domain` never reach a live model; the only
live seam in the repository is BoxPush's opt-in runner flag.

#### ProposalComparator

Needed whenever a reasoning track is declared. `kit.DefaultProposalComparator` reports the
frozen divergence kinds (no proposal / proposal without a call / different action); its
BoxPush-style arms (a domain equivalence rule, a confidence threshold, translation residuals)
are opt-in constructor arguments.

## Validate

```bash
python -m maaos validate-domain <name> [--budget N]
```

Every check has a code, a one-line title and, on FAIL/WARN, a message naming the file,
function or contract member to fix. Every code appears in every report; a check that could
not run is SKIPPED with the reason. Exit status 1 means at least one FAIL.

| Code | Checks | If it fails |
|---|---|---|
| DK001 / DK002 | registered; the registered object is your `DOMAIN` with a matching name | add the printed registry lines |
| DK010–DK017 | services, symbolic track, comparator, environment, task, state, call, reasoning track satisfy their contracts | the message lists the missing member, or the field that shadows a method |
| DK018 | calls compare by value | make `Call` a frozen dataclass |
| DK020 | the default task is declared | — |
| DK030 | `reset` returns a state with a stable `world_key` | keep bookkeeping out of `canonical()` |
| DK031 | `observe()` does not alias the state | return a copy (the kit base does) |
| DK032 | execute before reset is a `"refused:"` fault | use the kit base |
| DK040–DK042 | `plan` returns a typed result, deterministically, with grounded heads | use `kit.bfs_plan`; enumerate calls from identities |
| DK043 / DK052 | your examples are rejected as intended | fix the example or the check it exercises |
| DK050 / DK051 | `applicable` returns a typed verdict and accepts the plan's own head | `plan` and `applicable` must agree |
| DK060 | `predict` returns typed keys | use `kit.symbolic_key` / `kit.world_key` |
| DK070 | a bounded episode under each policy ends with a typed outcome | a FAULTED episode names the component that broke its contract; a typed halt is a valid outcome |
| DK071 | an advisory episode with your declared track | — |
| DK080 | module roles | fix the imports listed |
| DK081 | the backend door is enumerated in the guard | add the one line it quotes (backend-wrapping domains only) |
| DK082 | importing the package loads no backend | move the backend import inside `make_environment()` |
| DK090 | services and plan stamp the same model version | — |

A WARN does not fail validation; it names something worth doing (declare examples, declare
recovery advice).

## The designed physical failure

A domain is interesting when the environment can refuse what the model admits. Give your
world one such condition (a stuck switch, a wrong key, a blocked path): a field of `State`
that `_attempt` honours and `project()` drops, so `applicable` never sees it. Then, under the two policies:

- `symbolic_primary` retries the applicable call, and after three identical failures
  **halts** with the discrepancy history (`EpisodeOutcome.HALTED_REPEATED_FAILURE`) — it never
  patches the model;
- `advisory_two_track` asks your `recover()` after the third failure, executes its advice
  through the same gates, and continues (`EpisodeOutcome.GOAL_REACHED` if the advice worked).

Assert this in the generated test (`tests/test_domain_<name>.py`); the template names the
pieces:

```python
episode = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=OrchestrationPolicy.SYMBOLIC_PRIMARY)).run()
episode.outcome            # EpisodeOutcome.HALTED_REPEATED_FAILURE
episode.discrepancies      # three ExecutionDiscrepancy values, .kind EXECUTION_FAILURE_OF_APPLICABLE_SKILL
episode.history.entries    # one per DECISION: .decision, .selected_call, .execution (None for a
                           # decision that executed nothing — the halt / request_proposal entry)
executed = [e for e in episode.history.entries if e.execution is not None]   # the attempts
```

The decision vocabulary (`from shared.orchestration_config import ExecutiveDecision`):
`EXECUTE`, `REPLAN`, `REQUEST_PROPOSAL`, `HALT`. Three failed attempts under
`symbolic_primary` therefore produce FOUR entries: three `EXECUTE` entries with an
`execution`, then one `HALT` entry whose `execution` is `None`; under `advisory_two_track` the
fourth is `REQUEST_PROPOSAL`, followed by the advised calls.

A recovery call with no symbolic effect (a `Nudge`, an `Unjam`) is fine: `apply` returns
`sym` unchanged, and the planner never chooses it on its own (the search discards a revisited
state), which is exactly what makes it recovery-only. Its PHYSICAL effect — freeing the stuck
switch — is a change to a `State` field, so if you declare `apply_world`, predict that change
there (as the lamp's does); otherwise the monitor reports a world-basis mismatch on the
successful call.

Once you add the failure, the generated "goal under both policies" test must become "goal
under advisory, halt under symbolic-primary" — the halt is the design, not a bug.

## Running an episode

```python
from app.assembly import assemble_loop
from shared.orchestration_config import OrchestrationConfig, OrchestrationPolicy
from domains.warehouse import DOMAIN

loop = assemble_loop(DOMAIN, config=OrchestrationConfig(policy=OrchestrationPolicy.ADVISORY_TWO_TRACK))
episode = loop.run()
print(episode.outcome, episode.reason)
for entry in episode.history.entries:
    print(entry.executive_step, entry.decision, entry.selected_call,
          entry.execution.outcome if entry.execution else None, [d.kind for d in entry.discrepancies])
```

`assemble_loop(DOMAIN, "<task name>")` picks another declared task; `use_reasoning_track=False`
runs a domain with a declared track without it.

## Rules you must respect

- The environment is the sole authority on what physically happens.
- The symbolic model is optimistic: no feasibility, reachability or environment query in
  `applicable`/`plan`.
- Physical failure is evidence (an `ExecutionDiscrepancy`), never a fault; a broken
  component is a fault; an advisory disagreement is a divergence. Do not convert one into
  another.
- Recovery advice goes through the same gates as any call.
- Everything typed and domain-owned: frozen dataclasses, no `dict` state.
- Offline and deterministic by default.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `validate-domain` (or `list-domains`) says `domains/registry.py could not be imported ... at domains/<name>/__init__.py:NN` | the four files disagree while you edit | finish the coherent change (or remove the two registry lines until it imports) |
| DK016 "key must be a METHOD" | a `Call` field named like a contract method | rename the field |
| DK082 "importing ... loads the backend" | a backend import at the top of `environment.py` | move it inside `make_environment()` |
| DK081 asks for a guard line | your `environment.py` imports a banned framework | add the quoted line to `tests/test_no_backend_imports.py` — the one edit outside your package a backend-wrapping domain needs |
| the suite fails `test_the_documented_suite_count_equals_discovery` | your generated test joined the suite | update the pinned line in `docs/refactor/REFACTOR_STATUS.md` |
| DK070 FAULTED "in Environment._attempt ... raised KeyError" | your backend code raised | fix it; the details name your file and line |
| DK051 "plan() and applicable() disagree" | the planner emits a call its own preconditions reject | make both read the same symbolic state |

## Where things live

| Path | What |
|---|---|
| `domains/<name>/` | your domain (generated) |
| `domains/registry.py` | the hand-edited registry |
| `tests/test_domain_<name>.py` | your generated test |
| `kit/` | the defaults you build on (`EnvironmentBase`, `DerivedDomainServices`, `ProjectionTrack`, `bfs_plan`, `DefaultProposalComparator`, keys) |
| `app/domain_package.py`, `app/assembly.py`, `app/validation.py` | the declaration record, loop assembly, the validator |
| `tests/fixture_lamp/` | a complete small example built exactly this way (two lamps, one stuck switch, recovery by `Nudge`) |
| `docs/decisions/DK1_DOMAIN_PACKAGE.md` | the design record of this mechanism |
