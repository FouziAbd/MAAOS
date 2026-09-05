# MAAOS — Claude Code Project Instructions

## Project status

MAAOS Symbolic-Twin BoxPush V1 implementation phases **P0-P4 are complete**
and frozen.

The behavior-preserving architectural refactor **R0-R6 is complete and
audited PASS** (2026-09-05). The refactor program is closed.

The repository is in **maintenance**:

- completed P0-P4 behavior remains the regression baseline;
- completed R0-R6 architecture remains the supported architecture;
- do not reopen or reimplement an R-phase unless explicitly requested to fix
  a discovered regression against its recorded acceptance criteria;
- the next substantive architectural validation comes from a real next domain
  (owner inputs in `docs/refactor/NEXT_DOMAIN.md`), not from speculative
  abstraction work.

Do not confuse these names:

- `P0-P4` = the completed/frozen Symbolic-Twin V1 implementation milestone.
- `R0-R6` = the completed refactoring phases from the supervisor/Codex review.
- Future product/research phases such as `P5+` remain out of scope unless the
  project owner explicitly requests them.

Refactor status and final audit record:

`docs/refactor/REFACTOR_STATUS.md`
`docs/refactor/REFACTORING_IMPLEMENTATION.md`

Architectural authority (the completed R0-R6 objective):

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

Do not hard-code a permanent expected test count. The live count is pinned in
`docs/refactor/REFACTOR_STATUS.md` and checked mechanically by the suite.

## Authority and source of truth

Use this precedence when reasoning about the codebase:

1. Existing authoritative backend/environment implementation establishes
   realized low-level physical execution behavior.
2. `docs/decisions/P0_V1_DECISIONS.md` defines frozen V1 semantic decisions.
3. `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md` defines the accepted P0-P4
   Symbolic-Twin V1 behavior and architectural invariants.
4. `docs/supervisor/MAAOS_code_review_and_refactoring_report.md` defines the
   completed R0-R6 architectural objective and remains the architectural
   authority.
5. Existing tests, acceptance traces, and implementation documentation
   characterize the accepted implementation and provide regression evidence.

The R0-R6 report changed internal composition, interfaces, dependency
direction, and lifecycle organization. It does **not** silently override frozen
V1 behavior, and neither may any later maintenance change.

If a requested change conflicts materially with a frozen V1 semantic decision
or with the audited R0-R6 architecture, stop and explain the conflict rather
than changing the frozen behavior.

Never invent domain behavior when code/specification does not establish it.

## Central architectural rule

Generalize mechanisms and extension points from concrete requirements;
generalize domain semantics only when a real domain requires them.

Extend the delivered architecture incrementally; do not rewrite it.

Keep state/action/result types typed and domain-owned. Do not replace them with
a universal `dict[str, Any]` framework.

Do not implement speculative future machinery merely to make the architecture
look general.

## Permanent V1 invariants

These must remain true at all times:

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
- Do not weaken or delete existing tests merely to make a change pass.
- Preserve existing CLI/import/serialized-trace compatibility where practical;
  adapt around incompatibilities rather than silently changing external
  formats.

## Maintenance discipline

Normal work is regression protection, consistency checking, and documentation
that describes actual behavior. After each coherent behavior-sensitive change:

```bash
python -B -m unittest discover -s tests -t .
```

Also run the static gates used by CI (`ruff check shared runtime app`,
`mypy`) when touching `shared/`, `runtime/`, or `app/`.

## R-phase discipline (only when a phase is explicitly reopened)

`/refactor-phase Rn` remains available, but it is not the normal workflow.
Use it only when the project owner explicitly asks to fix a discovered
regression against a recorded R-phase acceptance criterion. Then implement
exactly **one refactor phase at a time**.

Before editing for a reopened phase:

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

Also run focused tests/static checks required by the reopened phase.

At phase completion report:

- files changed;
- tests added/changed;
- commands run;
- full/focused results;
- behavior differences, if any;
- remaining known debt and which later R-phase owns it;
- whether the reopened phase acceptance criteria are satisfied.

## Supported architecture

The architecture delivered by R0-R6 is:

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

The generic runtime must not interpret BoxPush vocabulary such as agent, box,
zone, or geometry semantics.

Variable components are injected through narrow typed contracts under
`shared/contracts/`: environment, tracks, comparator, recovery provider,
policy, and domain services. Composition happens in `app/`.

Policies decide; they do not execute the backend.

Comparators report evidence; they do not select or execute actions.

Track proposal, recovery proposal, and orchestration authority are distinct
concepts.

When a policy requests both proposals, the loop performs the comparison
before the final policy decision (R3). Preserve this lifecycle.

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

The test-only synthetic probe domain under `tests/` (R5) is allowed because
it validates architectural substitutability; it is not production semantic
functionality. When a real next domain is chosen, extend contracts from its
concrete requirements and tests, not in anticipation of them.

## Legacy code

`middleware_layer/`, `model_layer/`, and pre-V1 runners are research/reference
material, not alternative supported Symbolic-Twin runtimes.

Do not use legacy structure as architectural precedent.

Do not move/delete large legacy package trees unless the project owner
explicitly requests the recorded post-R6 relocation as a separate reviewable
hygiene change (see `.claude/rules/legacy-packages.md`).

## Documentation

Documentation must describe actual implemented behavior.

Keep the supervisor's refactoring report unchanged as a source artifact.

Do not rewrite the historical
`docs/implementation/P0_P4_IMPLEMENTATION.md` as if R0-R6 were part of the
original P0-P4 implementation. R0-R6 work, and any later regression fix to
it, is recorded in:

`docs/refactor/REFACTORING_IMPLEMENTATION.md`

## Primary manual workflows

Normal maintenance workflows:

- `/v1-regression`
- `/consistency-check all` (or `v1` / `refactor`)
- `/run-v1`
- `/refactor-audit` only when a re-audit is actually needed

Available but not the normal next workflow:

- `/refactor-phase Rn` — only for an explicitly requested regression fix to a
  recorded phase
- `/refactor-doc` — only after such a fix, to update the refactor record
- `/refactor-preflight` — historical; it ran once before R0

The old P0-P4 implementation workflows are retired.
