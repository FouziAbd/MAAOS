# MAAOS — Claude Code Project Instructions

## Project status

MAAOS Symbolic-Twin BoxPush V1 implementation phases **P0-P4 are complete**.

The current work is a **behavior-preserving architectural refactor**, named
**Refactor R0-R6**.

Do not confuse these names:

- `P0-P4` = the completed/frozen Symbolic-Twin V1 implementation milestone.
- `R0-R6` = the current refactoring phases from the supervisor/Codex review.
- Future product/research phases such as `P5+` remain out of scope unless the
  project owner explicitly requests them.

Current refactor status is tracked in:

`docs/refactor/REFACTOR_STATUS.md`

Current architectural refactor authority:

`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

## Active implementation

The supported Symbolic-Twin V1 runtime is the code under:

- `shared/`
- `domain/`
- `symbolic/`
- `nl/`
- `runtime/`
- `app/` — composition root; `app.box_push_v1.build_loop` assembles the BoxPush
  environment, tracks, comparator, equivalence, recovery provider and policy over
  the domain-agnostic `runtime/`. The only package that may import both `runtime/`
  and `domain/`
- `functional_layer/custom_env/box_push/env/box_push_v1_adapter.py`
- `functional_layer/custom_env/box_push/env/box_push_v1_run.py`

The active BoxPush V1 runner is:

```bash
cd functional_layer/custom_env/box_push/env
python box_push_v1_run.py
```

Symbolic-primary demo:

```bash
cd functional_layer/custom_env/box_push/env
python box_push_v1_run.py --policy symbolic_primary
```

Live local-LM execution is opt-in only:

```bash
cd functional_layer/custom_env/box_push/env
python box_push_v1_run.py --nl live
```

Default offline regression suite:

```bash
python -B -m unittest discover -s tests -t .
```

Do not hard-code a permanent expected test count. R0-R6 may add tests.

## Authority and source of truth

Use this precedence when reasoning about the refactor:

1. Existing authoritative backend/environment implementation establishes
   realized low-level physical execution behavior.
2. `docs/decisions/P0_V1_DECISIONS.md` defines frozen V1 semantic decisions.
3. `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md` defines the accepted P0-P4
   Symbolic-Twin V1 behavior and architectural invariants.
4. `docs/supervisor/MAAOS_code_review_and_refactoring_report.md` defines the
   current R0-R6 architectural refactoring objective.
5. Existing tests, acceptance traces, and implementation documentation
   characterize the accepted implementation and provide regression evidence.

The R0-R6 report may change internal composition, interfaces, dependency
direction, and lifecycle organization. It does **not** silently override frozen
V1 behavior.

If a requested refactor conflicts materially with a frozen V1 semantic
decision, stop and explain the conflict rather than changing the frozen
behavior.

Never invent domain behavior when code/specification does not establish it.

## Central refactoring rule

Generalize mechanisms and extension points now; generalize domain semantics
only when a real domain requires them.

This is an incremental extraction, not a rewrite.

Keep state/action/result types typed and domain-owned. Do not replace them with
a universal `dict[str, Any]` framework.

Do not implement speculative future machinery merely to make the architecture
look general.

## Permanent V1 invariants

These must remain true throughout R0-R6:

- The backend remains the sole authority for physical execution success.
- The symbolic model remains deliberately optimistic.
- Do not add backend BFS, reachability, collision feasibility, hidden rollout,
  or another procedural environment oracle to symbolic applicability/planning.
- A symbolically applicable grounded skill may fail in the backend, and that
  failure remains visible as typed evidence.
- `ExecutionDiscrepancy`, `TrackDivergence`, and `InfrastructureFault` remain
  separate typed evidence channels.
- A current-cycle infrastructure fault follows the established fail-closed
  routing and must not be turned into a normal competing proposal.
- Recovery calls pass through the same validation and execution path as normal
  selected calls.
- The executor remains policy-independent.
- Default tests remain deterministic and offline.
- Live LM/Ollama/DSPy execution remains opt-in.
- Do not weaken or delete existing tests merely to make a refactor pass.
- Preserve existing CLI/import/serialized-trace compatibility where practical;
  adapt around incompatibilities rather than silently changing external
  formats.

## R0-R6 execution discipline

Implement exactly **one refactor phase at a time**.

Before editing for a phase:

1. Read the exact phase in
   `docs/supervisor/MAAOS_code_review_and_refactoring_report.md`.
2. Read `docs/decisions/P0_V1_DECISIONS.md`.
3. Read `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`.
4. Read the applicable `.claude/rules/`.
5. Inspect the current implementation and relevant tests.
6. Check git status and preserve unrelated user changes.

Do not implement acceptance criteria belonging only to later R-phases unless
the current phase explicitly requires a prerequisite.

Known architectural debt scheduled for a later R-phase is `DEFERRED`, not a
reason to expand the current phase.

After each coherent behavior-sensitive change:

```bash
python -B -m unittest discover -s tests -t .
```

Also run focused tests/static checks required by the assigned phase.

At phase completion report:

- files changed;
- tests added/changed;
- commands run;
- full/focused results;
- behavior differences, if any;
- remaining known debt and which later R-phase owns it;
- whether the assigned phase acceptance criteria are satisfied.

## Current target architecture

The final R0-R6 direction is:

```text
concrete BoxPush/domain implementations
            |
            v
    narrow shared contracts
            |
            v
       runtime core
            |
            v
authoritative environment/backend
```

The generic runtime target must not interpret BoxPush vocabulary such as agent,
box, zone, or geometry semantics.

Expected variable components are injected through narrow typed contracts,
including tracks, comparator, recovery provider, policy, environment/domain
services as introduced by the assigned R-phase.

Policies decide; they do not execute the backend.

Comparators report evidence; they do not select or execute actions.

Track proposal, recovery proposal, and orchestration authority are distinct
concepts.

When a policy requests both proposals, R3 establishes comparison before the
final policy decision. Do not force this lifecycle change before its assigned
phase.

## Out of scope

Unless explicitly requested as a new domain requirement, do not implement:

- belief reconciliation;
- probabilistic/stochastic transitions;
- calibrated uncertainty machinery;
- partial-observation production semantics;
- temporal reasoning/duration models;
- asynchronous/concurrent executive track execution;
- VLM/rendered-image input;
- dynamic third-party plugin discovery for the runtime;
- speculative universal abstractions for future domains.

A test-only synthetic probe domain in R5 is allowed because it validates
architectural substitutability; it is not production semantic functionality.

## Legacy code

`middleware_layer/`, `model_layer/`, and pre-V1 runners are research/reference
material, not alternative supported Symbolic-Twin runtimes.

Do not use legacy structure as architectural precedent for R0-R6.

Do not move/delete large legacy package trees during the refactor unless the
assigned phase explicitly calls for a separate reviewable hygiene change.

## Documentation

Documentation must describe actual implemented behavior.

Keep the supervisor's refactoring report unchanged as a source artifact.

Do not rewrite the historical
`docs/implementation/P0_P4_IMPLEMENTATION.md` as if R0-R6 were part of the
original P0-P4 implementation. Record R0-R6 work in:

`docs/refactor/REFACTORING_IMPLEMENTATION.md`

## Primary manual workflows

Use these project skills when appropriate:

- `/refactor-preflight` (once, before R0)
- `/refactor-phase R0` ... `/refactor-phase R6`
- `/v1-regression`
- `/consistency-check v1|refactor|all`
- `/refactor-doc`
- `/refactor-audit`
- `/run-v1`

The old P0-P4 implementation workflows are retired.
