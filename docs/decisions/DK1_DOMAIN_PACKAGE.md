# ADR-DK1 — The domain declaration record, generic assembly, and two guard decisions

- Status: Accepted
- Date: 2026-09-19
- Scope: Domain-kit program phase DK1 (post-R6 maintenance requested by the project
  owner; not a V1 semantic decision — V1 behavior is unchanged)

## Context

R0-R6 left the runtime generic (`runtime/loop.py` names no domain concept; every
component is injected through `shared.contracts`), but adding a domain remained expert
work: the only worked examples are the frozen BoxPush application spread over `domain/`,
`symbolic/`, `nl/`, `app/` and the sys.path-mounted adapter, and the R5 test-only probe
(`tests/probe_counter.py`, 719 lines for a one-integer domain). There is no single object
that says "this is a domain", no generic way to assemble a loop from one, and no place in
the guarded tree where a self-contained domain package could live: the auto-discovering
import guard (`tests/test_no_backend_imports.py`) classifies every top-level package
except `runtime` and `app` as "the symbolic side" and forbids it from importing `runtime`
or `app`, and it bans every backend/framework root everywhere.

The program's success criterion (owner, 2026-09-18):

> A developer unfamiliar with MAAOS can add a small deterministic domain by following
> `docs/domains/ADDING_A_DOMAIN.md` alone, without editing anything under `shared/`,
> `runtime/`, `kit/`, `app/`, or `tests/` other than the files `create-domain` generated
> for them, and without reading or understanding `ExecutiveLoopManager` or any other
> runtime internal.

Governing principle: the kit (DK2) is the extracted intersection of what BoxPush and the
probe already implement by hand; nothing comes from a hypothetical domain. The STRIPS
layer (`shared/skill_ir.py`, `symbolic/planner.py::Universe`) stays untouched: it is pinned
to the BoxPush registry by identity checks, and generalizing it is a separate owner
decision (recorded DEFERRED at the R0-R6 closure).

## Decision

1. **`app/domain_package.py::DomainPackage` is the one object a domain exports.** A frozen
   generic record — name, named tasks + default, and factories for environment, services,
   symbolic track, plus optional recovery provider, comparator, reasoning track and
   validation examples. It is a record, not a registry and not a framework: explicit Python
   composition as `app/box_push_v1.py` performs it, written down once. It lives in `app/`
   because the runtime never consumes it (the supervisor report's "application-level
   composition object", Phase 4 item 1), and imports only `shared`. Malformed declarations
   are refused at construction with author-facing messages (bad name, missing default task,
   a reasoning track without a comparator).

2. **`app/assembly.py::assemble_loop(package, …)` is `build_loop` generalized.** Positional
   parameters mirror `build_loop`; each keyword (`loop_class`, `environment`, `domain`,
   `symbolic_track`, `comparator`, `recovery_provider`) overrides exactly one component;
   `use_reasoning_track=False` assembles without the declared advisory track. It passes
   `provenance` straight through so the loop keeps its own default source string, and it
   constructs the environment itself and hands it to the loop only — no domain factory ever
   receives it. `build_loop`, `compose`, `ExecutiveLoopManager` and the runner are unchanged.

3. **`domains/` is the home of domain packages; BoxPush is declared there without moving.**
   `domains/box_push/__init__.py` exports `DOMAIN`, every factory delegating to
   `app.box_push_v1.compose(task)` so the declaration cannot drift from the accepted
   composition; `domains/box_push/environment.py` is the backend door (below);
   `reasoning_track=None` is structurally forced (the live seam sits under
   `functional_layer/`, which a composition module may not import), so a loop assembled from
   the declaration is offline by construction. Registration is the hand-edited static dict
   `domains/registry.py::REGISTRY`; `domains/__init__.py` is an import surface only and is
   never machine-edited. No `git mv`, no shims, no test-path edits (owner decision
   2026-09-18; report Phase 4 default "avoid moving package directories").

4. **Guard decision A — `domains` and `maaos` join `COMPOSITION_PACKAGES`**
   (`tests/test_no_backend_imports.py`), so they may import `runtime`/`app` like `app`; they
   stay backend-guarded like every package. To keep the `:118` guarantee ("the symbolic side
   must not reach repeated-failure bookkeeping") at least as strong INSIDE a domain package,
   `domain_role_violations` enforces roles per module under `domains/<x>/`:
   - `__init__.py` (composition): may import `runtime`, `app`, the sibling `environment`;
   - `environment.py` (backend boundary): never `runtime`, `app`, `model`, or the package;
   - every other module (symbolic side): stdlib, `shared`, `kit`, and sibling *modules* only
     (`from .types import …` / `from . import types`); never `runtime`, `app`,
     `environment`, a backend root, another domain package, or the package itself
     (`from . import DOMAIN`, `from domains.x import NAME`, `import domains.x` — binding a
     name through `__init__` would launder `runtime` into the symbolic side).
   The role scan resolves relative imports (the base guard skips them) and is proven
   fail-closed on throwaway probe trees for each violation class.

5. **Guard decision B — `domains/<x>/environment.py` is the one backend door.** An
   enumerated, static set `DOMAIN_ENVIRONMENT_MODULES` (asserted equal to
   `{domains/<name>/environment.py for name in REGISTRY}`, never a glob) is exempt from
   `FORBIDDEN_PREFIXES` **minus `NEVER_EXEMPT_ROOTS`**: the legacy roots (`legacy`,
   `middleware_layer`, `model_layer`, `utils`) and the LM frameworks (`dspy`, `torch`) are
   never exempt — an environment module is a simulator binding, never an LM binding (R6 kept
   the dspy seam outside the guarded tree). The dynamic-import ban, the `sys.path` /
   `sys.modules` text ban and the runtime/app ban still apply to these files, and the R6 legacy-boundary scan now
   covers `domains` and `maaos`. This is a *pattern exemption inside the guarded tree*,
   which R6 deliberately avoided for the dspy seam (it moved the seam outside the guarded
   packages instead). It is justified here because a domain's backend is the domain's own
   code — the alternative, keeping every environment outside the guarded tree, would put a
   newcomer's whole domain in unguarded territory — and because the role scan keeps the
   symbolic side of the same package away from that door.

   **Known limitation (recorded, not hidden):** the door is nominal for an *in-package*
   simulator. A hand-written sibling `sim.py` imported by both `environment.py` and
   `model.py` is a backend-to-applicability path the import scan cannot see — the same class
   of limitation the pre-DK1 guard records for a hand-written BFS over `StateSnapshot`. The
   structural defence remains the same as before: symbolic-side code consumes the domain's
   symbolic state, and `validate-domain` (DK3) / the guide (DK5) say so. Making the rule
   structural (sibling sets of `environment.py` and the symbolic side disjoint except
   `types`) is an owner choice for a later phase (DEFERRED).

6. **`kit/` and `maaos/` are reserved now** (docstring-only packages) so the lint/type/guard
   scope strings (`ruff check shared runtime app kit domains maaos`, the mypy `files` list,
   `_PRODUCTION_DIRS`, `FORBIDDEN_ROOTS`, `GUARDED_DIRS`) are edited once, in this phase.
   `kit/` is discovered as symbolic side (may import only `shared`; `runtime/` may never
   import it); `maaos/` is a composition package.

## DEBT-DK1 — the BoxPush adapter under two module names

`domains/box_push/environment.py` imports the adapter as
`functional_layer.custom_env.box_push.env.box_push_v1_adapter` (namespace path from the
repo root; the adapter mounts its own siblings, so no `sys.path` code is needed). The runner
and the tests import the same file as `box_push_v1_adapter` via `sys.path`. Because
`functional_layer/` has no `__init__.py` files, these are **two module objects** and two
`BoxPushV1Adapter` class objects. Same code, same configuration (`BoxPushV1Adapter()` is
the frozen headless instance), and the DK1 test reproduces both baseline transcripts through
the assembled loop — but `isinstance` across the two names is False.

**Cleanup item (owner-scheduled, not accepted indefinitely):** give the BoxPush env
directory one canonical import path — either package `__init__.py` files under
`functional_layer/custom_env/box_push/` with the runner and tests re-pointed to the dotted
path, or a single repo-root-importable shim — so exactly one adapter module exists; pin it
with a test that `sys.modules` holds a single adapter module after a full episode. Until
cleared, no code may rely on adapter `isinstance` identity across the two names.

## DK2 — kit extraction record (2026-09-19)

`kit/` (DK2) is built from the BoxPush ∩ probe intersection — refusal protocol, malformed /
ungrounded arms, identity grounding, result assembly, the exact-projection track, the
key-comparison monitor, the sha256-of-canonical-JSON keys, the PROPOSAL_FORM / ACTION_CHOICE
comparator kinds — with these deliberate exceptions, each justified by a concrete
requirement rather than a hypothetical domain:

| Element | Source | Why it is in the kit |
|---|---|---|
| `kit.planning.bfs_plan` | BoxPush only (`symbolic/planner.py`; the probe plans in closed form) | encodes the frozen planner-result categories where authors err (`NoPlan` vs `PlannerFailure`); state-free signature |
| `EnvironmentBase.note_primitive_steps`, `mid_attempt_fault`, the `_attempt` exception → `BACKEND_API_EXCEPTION` wrap | BoxPush only (adapter case-(c) producers; `runtime/executor.py`) | the `primitive_steps_before_failure=N` key is a runtime-parsed contract (`runtime/loop.py`) otherwise undocumented for authors |
| `EnvironmentBase._observe` default (`canonical()`) | neither (the adapter returns backend observations, the probe a hand-picked mapping) | a fully-observable V1 default, the same assumption `ProjectionTrack` states; overridable |
| `EnvironmentBase.executed` | probe only | per-episode diagnostic; nothing in the kit or runtime reads it |
| `DerivedDomainServices.monitor` catch-all → chained `ValueError` | neither (BoxPush lets non-`ValueError` escapes crash the run) | routes any author error to the loop's established `EXECUTOR_MONITOR_PROTOCOL_FAILURE` conversion instead of an untyped crash; never a discrepancy |
| `DefaultProposalComparator` opt-in arms (`equivalence`, `low_confidence_threshold`, `report_translation_residual`) | BoxPush only | explicit configuration reproducing BoxPush's kinds/order; defaults stay the intersection |

Authority model of `EnvironmentBase`: value-state (the probe's model). A domain wrapping an
external mutable simulator must derive its state value inside `_attempt` from a fresh read
or not use the base as-is; a D4-style re-read hook is DEFERRED until a real such domain
exists (owner choice).

## DK3 — validation catalogue (2026-09-19)

`app/validation.py::validate_domain` / `validate_named` and `python -m maaos validate-domain
<name>` (`maaos/cli.py`). Codes as SHIPPED (the phase spec's provisional "DK003 unregistered
name" is DK001; DK002 is a registered object that is not a `DomainPackage`):

| Code | Check |
|---|---|
| DK001 / DK002 | registry: name registered / value is a `DomainPackage` whose `name` equals the key |
| DK010–DK017 | contracts: services, symbolic track, comparator, environment, task, state, call, reasoning track — missing members listed by name; a field shadowing a contract METHOD is named |
| DK018 | calls compare by value (a frozen dataclass) |
| DK020 | default task declared (guaranteed by the record; reported for visibility) |
| DK030–DK032 | environment: reset returns a state, `export_full_state` stable, `observe()` does not alias, execute-before-reset is a `"refused:"` fault |
| DK040–DK043 | plan: typed result, deterministic, heads grounded, `examples.ungrounded_call` rejected |
| DK050–DK052 | evaluate: typed verdict, head applicable, `examples.inapplicable_call` inapplicable |
| DK060 | predict returns a `Prediction` with typed keys |
| DK070 / DK071 | bounded episodes under both policies without a track / one with the declared track; FAULTED is a FAIL, HALTED_REPEATED_FAILURE without a recovery provider under advisory is a WARN |
| DK080 / DK081 | package layout: module roles + no dynamic import / the backend door is enumerated in the guard (never for an LM framework or a legacy tree) |
| DK082 | `import domains.<name>` in a fresh interpreter loads no backend module (the backend import belongs inside the environment factory) |
| DK090 | services and plan stamp the same model version |

Design rules: every check runs under its own guard (an exception is that check's FAIL with
the text under details, never a traceback headline); a missing precondition is SKIPPED,
never PASS; loops are assembled through `app.assembly.assemble_loop` only; names resolve
through `domains.registry.REGISTRY` only. The role rules and backend roots are a MIRROR of
`tests/test_no_backend_imports.py` (the authority); `tests/test_dk3_validation.py` asserts
the mirrored constants equal the originals and that both scanners agree on probe trees.

## Alternatives considered

- **`DomainPackage` under `shared/contracts/`.** Rejected: the runtime never consumes it;
  `shared/` is "typed contracts only" and the R1 contract package is what the runtime
  composes against.
- **`domains/` on the symbolic side (may not import `runtime`/`app`), composition in
  `app/domains_<x>.py`.** Rejected: it re-splits every domain across two directories, the
  problem this program exists to remove.
- **A registry that `create-domain` appends to, or discovery by scanning `domains/`.**
  Rejected: source mutation is brittle (owner), and discovery/registration hooks are what
  ADR-R4 and the report's Phase 4 defaults forbid.
- **Environment factories outside the guarded tree (runner supplies the env; validation
  takes `--env`).** Rejected: `validate-domain` must be able to instantiate the domain
  itself, and a newcomer's environment would live unguarded.
- **`assemble_loop(**overrides)`.** Rejected: a dict-shaped surface; explicit keywords
  mirror `build_loop`.

## Consequences

- Assembling a loop for any domain is `assemble_loop(REGISTRY[name])`; the caller never
  sees the loop's constructor.
- Adding a domain adds a directory under `domains/`, one line in `domains/registry.py`, and
  one line in `DOMAIN_ENVIRONMENT_MODULES` (the guard's enumerated door) — the latter is a
  test-side edit a scaffold cannot make; DK4's guide and `validate-domain` (DK3 check DK081)
  name it explicitly (DK081).
- Whitelist constants in eight existing tests/config files grew by the new package names;
  none was relaxed (each edit is an extension of an allowlist or a forbidden set).
- BoxPush behavior, `build_loop`, the runner CLI, trace format and the demo transcripts are
  unchanged.

## Code/schema impact

- New: `app/domain_package.py`, `app/assembly.py`, `domains/__init__.py`,
  `domains/registry.py`, `domains/box_push/__init__.py`, `domains/box_push/environment.py`,
  `kit/__init__.py`, `maaos/__init__.py`, `tests/test_dk1_domain_package.py`.
- Extended: `tests/test_no_backend_imports.py` (`COMPOSITION_PACKAGES`,
  `DOMAIN_ENVIRONMENT_MODULES`, `NEVER_EXEMPT_ROOTS`, `exempt_modules` on the single
  enforcement path, `domain_role_violations`), `tests/test_r6_legacy_boundary.py`
  (`GUARDED_DIRS`), `tests/test_r5_probe.py` (`_PRODUCTION_DIRS`, `FORBIDDEN_ROOTS`),
  `tests/test_r4_composition.py` (`FORBIDDEN_ROOTS`), `tests/test_r6_typing.py`
  (`MYPY_TARGETS`), `tests/test_r6_tooling.py` (ruff scope), `pyproject.toml` (mypy files),
  `.github/workflows/offline-tests.yml` (ruff scope), `docs/refactor/REFACTOR_STATUS.md`
  (suite-count pin).
- No trace, serialization, or public-signature change.

## Acceptance evidence

- `tests/test_dk1_domain_package.py`: neutral record + loud refusals; real-tree role and
  backend scans clean; the exempt set equals the registry; probe trees catch each role
  violation class and the laundering case; `assemble_loop(DOMAIN)` matches `compose()`
  component types, the accepted outcomes and discrepancy count, the loop's default
  provenance, and **both baseline transcripts cycle by cycle** (every row, the footer and
  the outcome line, at the accepted R0 granularity) through the R0 renderer;
  `import domains` loads no backend module (subprocess).
- `tests/test_r0_characterization.py` and both headless demos unchanged against
  `docs/refactor/baseline/demo_*.txt`.
- Full offline suite, `ruff check shared runtime app kit domains maaos`, `mypy` green.
