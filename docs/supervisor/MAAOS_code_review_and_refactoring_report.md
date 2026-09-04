# MAAOS Code Review and Refactoring Report

## Purpose

This report reviews the current Symbolic-Twin BoxPush V1 implementation and gives a concrete refactoring plan. The objective is not to add speculative features to BoxPush. It is to preserve the validated deterministic, fully observable V1 behaviour while making the architecture genuinely extensible for later domains.

The central design rule is:

> Generalize mechanisms and extension points now; generalize domain semantics only when a real domain requires them.

In particular, the current milestone should not implement hypothetical belief reconciliation, probabilistic transitions, or partial-observation semantics. It should ensure that those capabilities could later be added without rewriting the executive loop.

## Executive assessment

The repository is a strong V1 research implementation. Its most successful aspects are the typed evidence channels, explicit symbolic abstraction, fail-closed validation, deterministic offline test suite, separation of predictions from authoritative execution, and comprehensive documentation of intended V1 behaviour.

The main architectural limitation is that several components are separated into files but are not yet interchangeable through explicit interfaces. The runtime still knows about the BoxPush domain and concrete implementations. The orchestration configuration looks abstract, but new policies require modifying a central enum and decision function. The symbolic–NL comparator is effective for the current action-level experiment, but it contains BoxPush-specific equivalence rules and its result is produced too late to inform the action-selection decision.

Therefore, the next work should be a behaviour-preserving extraction of stable interfaces—not a large rewrite and not an attempt to anticipate all future domain semantics.

## Part I — Conceptual issues and proposed solutions

### 1. The module boundaries are clear in the documentation, but incomplete as executable contracts

The environment interface in `shared/backend_contract.py` is relatively clear. It gives a backend implementer a small set of required operations. Equivalent formal contracts do not exist for the symbolic track, NL track, comparator, recovery provider, domain definition, or orchestration policy.

At present, a developer implementing one of these components must inspect `runtime/loop.py` to discover which concrete attributes and functions are expected. This is workable for one implementation but is not a clean public extension interface.

**Proposed solution:** define narrow `Protocol` interfaces for components that are expected to vary, and make `ExecutiveLoopManager` receive concrete implementations through constructor injection. Keep each protocol limited to behaviour currently understood. Do not add methods for hypothetical capabilities.

### 2. The runtime contains domain knowledge

`runtime/loop.py` imports BoxPush domain objects and concrete symbolic/NL functions. This means the executive algorithm cannot be reused with a different state or action type without editing the runtime.

**Proposed solution:** make the core runtime generic over domain-owned state, action, and execution-result types. Introduce a domain adapter or `DomainBundle` containing the model, projection, validation, prediction, and action-equivalence operations required by the runtime. The runtime should treat state and actions as opaque typed values.

Generality here means “the runtime does not contain BoxPush vocabulary.” It does not require replacing all domain types with `dict[str, Any]`; that would weaken rather than improve the design.

### 3. Orchestration is a closed switch rather than an extensible strategy

`shared/orchestration_config.py` defines a policy enum, while `runtime/orchestrator.py` implements the policy branches in one `decide()` function. The function is pure and well isolated, which is a good foundation, but a new policy still requires modifying central code.

**Proposed solution:** represent each orchestration strategy as an implementation of an `OrchestrationPolicy` protocol. Preserve the current behaviour as `SymbolicPrimaryPolicy` and `AdvisoryTwoTrackPolicy`.

A policy should operate only on an immutable `OrchestrationContext` and return a typed decision. It must not call the backend directly. Decisions should be a discriminated union such as `Execute`, `Replan`, `RequestTrackInput`, `AskUser`, and `Halt`, rather than an enum combined with optional fields that can form illegal states.

Policies may have different information costs. Symbolic-primary need not call the NL model every cycle. A two-stage policy interface should allow a policy to declare which track inputs it needs before making the final decision.

### 4. The symbolic–NL comparison is sound for V1 but not positioned as a reusable component

`runtime/comparator.py` handles the present BoxPush action-proposal comparison clearly and has good tests. It distinguishes contradiction, coverage gap, translation residual, confidence mismatch, and benign abstraction mismatch.

Its current limitations are:

- It compares only action proposals. That is appropriate for BoxPush V1, but the class/function name should not imply a universal comparison of everything represented by the tracks.
- The rule treating different agent bindings as a benign mismatch is a BoxPush abstraction rule embedded in the runtime.
- The confidence threshold is a fixed global value rather than explicit configuration.
- Divergence payloads rely heavily on display strings rather than machine-actionable fields.
- A malformed proposal returns early, so other evidence associated with it may be lost.
- Most importantly, the real NL proposal and comparison are produced after orchestration has selected the action. The comparison is therefore mainly telemetry and cannot inform that cycle's policy decision.

**Proposed solution:** make the current implementation an explicitly scoped `BoxPushActionComparator` conforming to a generic `ProposalComparator` protocol. Move action-equivalence rules behind a domain-owned `ActionEquivalence` interface. Produce the comparison before the final policy decision and include it in `OrchestrationContext`.

Do not implement belief-state comparison now. If a future domain needs comparison along multiple dimensions, add independently testable components such as `StateEstimateComparator` or `ConstraintComparator`, aggregated by a small `CompositeComparator`. The current milestone should create only the composition mechanism and the action comparator that can actually be validated.

### 5. The present “advisory” path is less general than its name suggests

The NL proposal used for ordinary per-cycle comparison is obtained after the action has already been selected. Recovery is supplied by the deterministic function in `nl/recovery.py`. This is valid as a V1 scripted recovery demonstration, but it should not be described internally as a completely general peer-track arbitration mechanism.

**Proposed solution:** distinguish three concepts explicitly:

1. a track proposal;
2. a recovery proposal;
3. an orchestration policy deciding what authority each proposal has.

Define a `RecoveryProvider` protocol and make the deterministic V1 recovery provider one implementation. The same execution validation gates must continue to apply to recovery calls.

### 6. Generality that cannot yet be semantically tested

It is impossible to validate the semantics of partial observability, calibrated uncertainty, temporal reasoning, or belief reconciliation in the current deterministic fully observable domain. Adding production implementations now would create false confidence.

**Proposed solution:** test architectural substitutability rather than hypothetical semantics:

- contract tests using fake tracks, policies, comparators, and environments;
- a tiny test-only probe domain whose state and action types have no boxes, agents, zones, or geometry;
- import-boundary tests proving that the core runtime does not import BoxPush modules;
- tests proving that unknown domain evidence passes through the runtime without being interpreted or discarded.

A minimal counter domain with `Increment` and `Stop` actions is sufficient. It is an architectural test fixture, not a second product domain.

### 7. Secondary correctness and maintainability findings

These are separate from the abstraction work but should be addressed while the affected boundaries are being changed:

- The BoxPush adapter's observation path should not return nested mutable objects that alias authoritative backend state. Return immutable snapshots or a defensive deep copy.
- Malformed or unexpected backend return values should be converted into the correct typed infrastructure/execution failure rather than allowing a bare `AttributeError` to escape.
- `NLProposal` currently encodes a runtime invariant using two optional fields. Replace it with a discriminated result type so static typing can prove whether the proposal is grounded or malformed.
- The current snapshot has substantial static-type-checking failures even though runtime tests pass. Establish an incremental type-checking baseline for the architectural core and prevent regressions there.
- Direct dependencies are pinned, but there is no complete environment lock with transitive hashes. Add a reproducible development/test environment and CI workflow before the project grows further.
- Clearly quarantine the pre-V1 `middleware_layer`, `model_layer`, and old environment code. It is useful research material, but it should not appear to be an alternative supported runtime.

## Part II — Target architecture

The desired dependency direction is:

```text
                 concrete BoxPush domain
               / symbolic / NL implementations
                              |
                              v
shared contracts <- runtime core <- injected policy/comparator/provider
                              |
                              v
                    authoritative environment
```

The runtime core may import shared contracts. It must not import `domain.box_push_v1`, concrete `symbolic` functions, concrete `nl` functions, or the BoxPush adapter.

Suggested minimal contracts:

```python
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT")
ExecutionT = TypeVar("ExecutionT")


class Environment(Protocol[StateT, ActionT, ExecutionT]):
    def reset(self, seed: int | None = None) -> StateT: ...
    def observe(self) -> StateT: ...
    def execute(self, action: ActionT) -> ExecutionT: ...
    def is_terminal(self) -> bool: ...


class ReasoningTrack(Protocol[StateT, ActionT]):
    def propose(self, context: "TrackContext[StateT]") -> "TrackProposal[ActionT]": ...


class ProposalComparator(Protocol[StateT, ActionT]):
    def compare(
        self,
        symbolic: "TrackProposal[ActionT]",
        natural_language: "TrackProposal[ActionT]",
        state: StateT,
    ) -> "ComparisonReport": ...


class OrchestrationPolicy(Protocol[StateT, ActionT]):
    def required_inputs(
        self,
        context: "PreliminaryContext[StateT, ActionT]",
    ) -> "TrackRequest": ...

    def decide(
        self,
        context: "OrchestrationContext[StateT, ActionT]",
    ) -> "OrchestratorDecision[ActionT]": ...
```

These signatures are illustrative. Before adopting them, fit them to the current typed result channels and retain useful existing invariants. Avoid introducing a generic framework larger than the code it replaces.

The runtime cycle should become:

```text
observe and synchronize
    -> build preliminary context
    -> ask policy which track inputs are required
    -> acquire requested proposals
    -> compare proposals when both are present
    -> build complete orchestration context
    -> policy decides
    -> validate selected call
    -> execute through the sole executor/backend path
    -> predict/monitor/classify results
    -> append typed trace and history
```

Infrastructure-fault handling and the rule that only the backend determines physical success must remain unchanged.

## Part III — Concrete implementation instructions

### Phase 0: Protect the current baseline

1. Run and record the existing offline suite and headless demo before refactoring.
2. Add characterization tests for both current policies, including the exact number and order of executive decisions in the accepted scenario.
3. Do not alter the BoxPush domain model, projection, planner optimism, discrepancy rules, or accepted trace semantics during the interface extraction.

Acceptance criteria:

- All currently passing tests still pass.
- The accepted BoxPush scenario reaches the same outcome under each policy.
- The same three designed physical discrepancies remain visible; none is silently patched.

### Phase 1: Introduce contracts without changing behaviour

1. Add protocols for the environment, symbolic track, NL track, proposal comparator, recovery provider, and orchestration policy under `shared/` or a new small `shared/contracts/` package.
2. Use generic domain-owned types for state, action, and execution result. Do not use `Any` as the primary abstraction mechanism.
3. Add immutable `PreliminaryContext` and `OrchestrationContext` dataclasses.
4. Add typed decision variants. Each variant must contain all required data, so `Execute` cannot exist without an executable action.
5. Adapt the existing implementations to these interfaces without changing their algorithms.

Acceptance criteria:

- Existing components satisfy the protocols under static checking.
- No protocol contains a BoxPush-specific field name.
- No speculative belief, probability, or temporal method is added.

### Phase 2: Extract orchestration policies

1. Replace the policy branch in `runtime/orchestrator.py` with concrete `SymbolicPrimaryPolicy` and `AdvisoryTwoTrackPolicy` classes.
2. Keep the policy configuration as data, but do not use a closed enum as the implementation dispatch mechanism. A registry may map configuration names to policy factories at the application boundary.
3. Make `ExecutiveLoopManager` accept a policy object.
4. Keep all backend execution in the executor. Policies return decisions only.
5. Implement `required_inputs()` so symbolic-primary can avoid unnecessary NL calls and two-track policies can request them.

Acceptance criteria:

- Adding a test policy requires no edits to `runtime/loop.py`.
- Policies can be unit-tested as pure transformations of context into decisions.
- A policy cannot call the environment through its public interface.

### Phase 3: Correct the comparison lifecycle

1. Define a generic proposal-comparator protocol.
2. Rename or wrap the current comparator as `BoxPushActionComparator`.
3. Extract the different-agent-binding rule into a BoxPush `ActionEquivalence` implementation.
4. Move the configurable confidence threshold out of the module-level constant. Preserve the raw confidence and its source; do not imply it is calibrated.
5. Replace divergence-only display strings with structured fields identifying the compared aspect, classification, severity, and evidence references. Keep a human-readable summary.
6. Do not return early merely because a proposal is malformed; retain every applicable independent finding.
7. Reorder the cycle so requested NL evidence and the comparison report exist before the final policy decision.

Acceptance criteria:

- The comparator contains no direct backend calls and does not choose an action.
- The generic runtime contains no rules mentioning agents, boxes, or zones.
- The orchestration policy receives the comparison report.
- Current V1 divergence classifications remain covered by tests.
- A test demonstrates that a policy can react to a contradiction, while symbolic-primary can intentionally ignore it.

### Phase 4: Make domain composition explicit

1. Introduce a `DomainBundle` or equivalent application-level composition object containing only the domain services the runtime needs.
2. Remove direct imports of BoxPush globals and concrete track functions from `runtime/loop.py`.
3. Construct the BoxPush application in a composition root—the demo/runner or a dedicated factory—not inside the runtime core.
4. Add an automated import rule forbidding runtime-core imports from BoxPush and legacy packages.

#### User input and default assumptions for Phase 4

This phase can normally be completed without direct user input. Unless the project owner specifies otherwise, use these conservative defaults:

- Use explicit Python constructor injection. Do not introduce dynamic plugin discovery or a configuration language merely to perform this refactor.
- Assemble the `DomainBundle` and concrete components in the existing BoxPush runner or a small dedicated factory.
- Avoid moving package directories unless a move is necessary to enforce the dependency direction.
- Preserve existing public imports with compatibility wrappers where practical.
- Preserve current command-line behaviour and trace serialization. If an internal type changes, add an adapter rather than silently changing an external format.
- Keep track acquisition synchronous and policy-controlled: the policy declares which inputs it requires, and the loop obtains them before final selection.

Stop and request a user decision only if implementation reveals one of the following:

- The intended architecture requires symbolic and NL tracks to execute concurrently or asynchronously rather than through synchronous policy-controlled acquisition.
- Preserving an existing public constructor, import path, CLI option, or serialized trace conflicts materially with the clean boundary.
- The project owner expects modules to be discovered dynamically from configuration or third-party packages rather than assembled in Python.
- A known next domain imposes a concrete requirement incompatible with the proposed `DomainBundle` contract.
- A frozen V1 decision would have to be changed rather than adapted around.

If the next domain is known, a short description of its observability, action model, concurrency, and uncertainty would be useful validation input, but it is not required to finish this phase. In the absence of that information, optimize for a narrow, typed composition boundary and backward compatibility—not speculative features.

Acceptance criteria:

- `runtime/` imports only shared contracts and domain-independent runtime helpers.
- The BoxPush runner assembles concrete environment, domain services, tracks, comparator, recovery provider, and policy.
- Changing one injected implementation does not require editing the loop.

### Phase 5: Prove architectural substitutability

1. Create a test-only counter domain with immutable state and actions unrelated to BoxPush.
2. Run a short executive cycle using fake symbolic/NL tracks and a fake environment.
3. Add contract tests for proposal acquisition order, comparison-before-decision, typed decisions, unknown evidence preservation, and execution validation.
4. Add a composite-comparator aggregation test using fake comparator components. Do not add unused production belief comparators.

#### User input and default assumptions for Phase 5

No direct user input should normally be required. The probe domain is an architectural test fixture, not a scientific model or a new supported application. Use the following default design:

- Immutable state containing a current integer and a target integer.
- Domain actions `Increment` and `Stop`.
- A deterministic transition that increments the value and terminates at the target.
- Minimal fake symbolic and NL tracks with programmable proposals.
- No agents, boxes, zones, geometry, belief state, probability model, language-model call, rendering, or external dependency.
- Keep the probe entirely under `tests/` unless repository conventions require a test-support package.

The probe must test only architectural properties. Its behaviour must not be used to define production semantics, and no production component should contain a special case for it.

Request user input only if the repository's rules forbid test-only domain fixtures, or if the user wants the next real domain—not a synthetic probe—to serve as the architectural validation. Otherwise, create the probe and its contract tests autonomously.

Acceptance criteria:

- The same runtime loop executes the probe domain without BoxPush imports or conditionals.
- The test-only domain does not need to imitate boxes, agents, zones, or geometry.
- Unknown domain-specific evidence survives tracing and policy delivery unchanged.

### Phase 6: Correctness and repository hygiene

1. Make observations immutable or defensively copied at the backend boundary; add a mutation test proving the caller cannot mutate backend state.
2. Normalize unexpected backend responses into the established typed fault channel; add malformed-return tests.
3. Replace `NLProposal(call=None, malformed=...)`-style optional combinations with grounded/malformed variants.
4. Add CI for the offline unit tests, formatting/linting, import-boundary checks, and type checking of the refactored core.
5. Introduce standard project metadata and a reproducible dependency-lock workflow. Keep live-model tests opt-in.
6. Mark legacy packages clearly as unsupported/reference-only, or move them under an explicit `legacy/` namespace in a separate, reviewable change.

Acceptance criteria:

- Mutating a returned observation cannot alter authoritative state.
- No raw attribute/type exception escapes for a malformed backend result.
- The core contracts, runtime, and new policies pass static type checking.
- CI runs without network or a live LM for the default test job.

## Part IV — Instructions suitable for an AI code generator

The following prompt can be supplied to an AI coding agent. It should be executed one phase at a time, with review after each phase.

> Refactor MAAOS to make the runtime extensible while preserving all Symbolic-Twin BoxPush V1 behaviour. Work incrementally; do not perform a wholesale rewrite. Before editing, read `CLAUDE.md`, the applicable `.claude/rules/`, `docs/decisions/P0_V1_DECISIONS.md`, `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`, `runtime/loop.py`, `runtime/orchestrator.py`, `runtime/comparator.py`, `shared/backend_contract.py`, `shared/orchestration_config.py`, `shared/divergence.py`, `shared/reports.py`, `nl/track.py`, and the relevant tests.
>
> Preserve these invariants: the backend remains the sole authority for physical execution; the symbolic model remains deliberately optimistic; execution discrepancies, track divergences, and infrastructure faults remain separate typed channels; recovery actions pass through the same validation and execution path; offline tests never require a live LM; the accepted BoxPush outcomes and designed discrepancies do not change.
>
> Implement only the assigned phase from this report. Introduce narrow typed protocols and dependency injection for components expected to vary. Keep state and action types domain-owned and use Python generics where they improve type safety. Do not create a universal dictionary-based state/action API. Do not implement speculative belief reconciliation, probabilistic reasoning, partial observability, calibrated-confidence logic, or temporal reasoning.
>
> Keep BoxPush-specific semantics in BoxPush components. In particular, agent/box/zone fields and the benign agent-binding equivalence rule must not appear in the generic runtime or generic comparator contract. Make current behaviour an explicit implementation such as `SymbolicPrimaryPolicy`, `AdvisoryTwoTrackPolicy`, and `BoxPushActionComparator`.
>
> For Phase 4, default to explicit Python dependency injection, backward-compatible imports and CLI/trace behaviour, minimal package movement, and synchronous policy-controlled track acquisition. Ask the user before proceeding only if true concurrent/asynchronous tracks are required, public compatibility must be broken, dynamic third-party discovery is required, a known next domain contradicts the proposed boundary, or a frozen V1 decision must change. For Phase 5, autonomously create a minimal deterministic counter domain under the tests; do not ask the user to design it and do not turn it into production functionality.
>
> Add or update tests before changing behaviour-sensitive code. After each coherent change, run `python -B -m unittest discover -s tests -t .`. Also run the relevant focused test modules and static checks. Report files changed, tests added, commands run, and any remaining type errors. Do not weaken or delete existing tests merely to make the refactor pass. Stop and explain if an existing frozen V1 decision conflicts with the requested architecture.

For best results, append exactly one phase from Part III to that prompt rather than asking an AI agent to implement all phases in one pass.

## Definition of completion

The refactoring is complete when all of the following are true:

- Existing BoxPush behaviour and evidence traces remain valid.
- The executive loop has no BoxPush imports or BoxPush conditionals.
- Policies, tracks, comparators, and recovery providers are injected through explicit contracts.
- Comparison occurs before the final policy decision whenever the policy requests both proposals.
- Adding a policy or comparator does not require modifying the executive loop.
- A non-BoxPush test domain runs through the same loop.
- No unsupported future semantic machinery was added merely for appearance of generality.
- The refactored architectural core is covered by contract tests, import-boundary tests, and static type checking.

The next substantive domain should then be treated as a validation of these abstractions. Where that domain exposes a missing concept, extend the relevant contract based on concrete requirements and tests rather than trying to predict all future needs during BoxPush V1.
