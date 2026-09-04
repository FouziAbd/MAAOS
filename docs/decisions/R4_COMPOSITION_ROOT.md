# ADR-R4 — The BoxPush composition root and two accepted compatibility changes

- Status: Accepted
- Date: 2026-09-04
- Scope: Refactor phase R4 (not a V1 semantic decision; V1 behavior is unchanged)

## Context

Report Phase 4 (`docs/supervisor/MAAOS_code_review_and_refactoring_report.md`)
requires that `runtime/` import only shared contracts and domain-independent
runtime helpers, and that the BoxPush application be assembled in a
composition root outside the runtime core. Its default assumptions say to
preserve existing public constructors and import paths "where practical", and
to stop for a user decision when "preserving an existing public constructor,
import path, CLI option, or serialized trace conflicts materially with the
clean boundary".

Two pre-R4 surfaces conflicted with that boundary in a way no adapter inside
`runtime/` could resolve:

1. `runtime.loop.ExecutiveLoopManager(env, task)` composed BoxPush by default:
   its constructor imported `domain.box_push_v1`, `symbolic`, `nl.recovery`,
   and the comparator. That default IS the import Phase 4 removes.
2. `runtime/comparator.py` held `BoxPushActionComparator`, which imports the
   concrete domain equivalence rule and `nl.track.NLProposal`. A re-export
   shim left in `runtime/` would itself be the forbidden import.

Both were presented to the project owner with the R4 completion report and
accepted on 2026-09-04.

## Decision

1. **The generic loop requires injection.** `ExecutiveLoopManager` keeps its
   name, import path, and positional parameters
   `(env, task, config, nl_track, provenance, policy)`, and gains keyword-only
   `domain` (required), `symbolic_track` (required), `comparator` (required
   whenever an `nl_track` is attached), and `recovery_provider` (optional;
   none means no recovery advice exists). Constructing it without `domain=`
   and `symbolic_track=` raises `TypeError` at construction.
2. **The BoxPush composition root is `app.box_push_v1`.** `compose(task)`
   builds the default V1 component set; `build_loop(env, task, config,
   nl_track, provenance, policy, *, loop_class, domain, symbolic_track,
   comparator, recovery_provider)` assembles one loop over a caller-built
   environment. Its positional signature mirrors the old constructor, so
   the migration is a rename at the call site.
3. **The comparator lives in `app.comparator`.** `BoxPushActionComparator`,
   `DEFAULT_COMPARATOR`, `LOW_CONFIDENCE`, and `compare_tracks` keep their
   names; only the module path changed. No shim remains under `runtime/`.
4. **`app/` is the layer above the runtime.** It may import every V1 package;
   nothing under `runtime/`, `shared/`, `domain/`, `symbolic/`, or `nl/` may
   import it, and it never imports the backend (the environment is always
   handed in by its caller).

## Migration to `build_loop`

Before:

```python
from runtime.loop import ExecutiveLoopManager
loop = ExecutiveLoopManager(BoxPushV1Adapter(), TASK_DELIVER_BOTH, config, nl_track=track)
```

After:

```python
from app.box_push_v1 import build_loop
loop = build_loop(BoxPushV1Adapter(), TASK_DELIVER_BOTH, config, nl_track=track)
```

- A subclass of the loop (the established fault-injection seam) is passed as
  `loop_class=`; a `_plan` override now takes the synced snapshot:
  `def _plan(self, snapshot)`.
- Substituting one component is a keyword override on `build_loop`
  (`domain=`, `symbolic_track=`, `comparator=`, `recovery_provider=`).
- The Decision-12 synthetic single-agent instance is
  `build_loop(env, task, domain=BoxPushDomainServices(task, universe=...))`
  instead of assigning the loop's former private `_universe` field.
- `from runtime.comparator import ...` becomes `from app.comparator import ...`.

Every in-repo caller (the runner and the tests) was migrated in the R4 change
set. No out-of-repo caller was known to exist.

## Alternatives considered

- **BoxPush default inside `runtime/`** (a lazy import in the constructor, or a
  shim module). Rejected: it is literally the coupling Phase 4 removes and
  would fail the import-boundary test.
- **Late-bound default via a registration hook** (`app` registers a default
  factory on import). Rejected: import-order dependent, hidden global state,
  and the kind of dynamic discovery the report's default assumptions forbid.
- **Composition module beside the adapter on the sys.path-mounted legacy
  side.** Rejected: unreachable by the import guards and by mypy; a proper
  guarded package is stronger.
- **Universe cached at first sync** (the pre-R4 loop behavior) kept as loop
  state. Rejected: the universe is symbolic vocabulary; `BoxPushDomainServices`
  derives it from the snapshot passed with each plan request, reading that
  snapshot for identities only.

## Consequences

- Adding or replacing a domain, track, comparator, recovery provider, or
  policy is a change at the composition root, never in `runtime/loop.py`.
- The runtime can no longer be run "bare" against BoxPush; `build_loop` is
  the supported entry point, and the runner uses it.
- The R5 probe domain composes its own fakes through the same constructor.
- `docs/implementation/p4_mutation_harness.py` (frozen historical evidence)
  still names `runtime/comparator.py` and no longer applies as-is; it is
  not rewritten.
- `CLAUDE.md`'s "Active implementation" list should name `app/`.

## Code/schema impact

- `runtime/loop.py` — constructor and delegation; no trace-format change.
- `shared/contracts/domain.py` — `DomainServices`, `Prediction`.
- `app/__init__.py`, `app/box_push_v1.py`, `app/comparator.py` (moved).
- `functional_layer/custom_env/box_push/env/box_push_v1_run.py` — uses
  `build_loop`; CLI unchanged.
- Serialized traces, `EpisodeOutcome`, `EpisodeResult`, and the
  `runtime.orchestrator` shim are unchanged.

## Acceptance evidence

- `tests/test_r4_composition.py` — import boundary (recursive allowlist with
  probes), vocabulary scan, composition-root assembly, loud refusal without
  injection, runner-uses-`build_loop` AST check, per-component substitution
  through the unmodified loop, geometry-invariance and per-call identity
  derivation of `plan`.
- `tests/test_no_backend_imports.py` — `app` discovered and backend-guarded;
  the symbolic side may import neither `runtime` nor `app`.
- `tests/test_r0_characterization.py` and both headless demos byte-identical
  to `docs/refactor/baseline/demo_*.txt`.
- Record: `docs/refactor/REFACTORING_IMPLEMENTATION.md` §R4.
