---
name: add-domain
description: The user-facing workflow for adding a new domain to MAAOS — scaffold it, fill in the domain-specific parts by the guide, validate, register, test, review, run both policies.
argument-hint: new <name>|validate <name>|review <name>
disable-model-invocation: true
---

# Add a Domain

Arguments: `$ARGUMENTS` — one of `new <name>`, `validate <name>`, `review <name>`.
`<name>` must be a lowercase Python identifier (`warehouse`, `lamp_grid`).

## Availability check (do this first)

This workflow depends on the domain kit. Check what exists on the current tree:

- `maaos/scaffold.py` present → `new` is available (DK4 landed);
- `app/validation.py` and `maaos/cli.py` present → `validate` is available (DK3 landed);
- `docs/domains/ADDING_A_DOMAIN.md` present → the author guide exists (DK5 landed).

If a required piece is missing, say exactly which domain-kit phase provides it and stop; do
not improvise a scaffold or a validator by hand.

## Principles the domain must respect (from CLAUDE.md, never optional)

- The environment/backend is the sole authority for physical execution success.
- The symbolic model is deliberately optimistic: `applicable`/`plan` decide from the symbolic
  state alone. Never add reachability, occupancy, feasibility, rollouts, or any environment
  query to applicability or planning. A symbolically applicable call **may** fail physically —
  that failure is typed evidence (`ExecutionDiscrepancy`), not a bug to hide.
- Three evidence channels stay separate and have one producer each: `ExecutionDiscrepancy`
  (monitor), `TrackDivergence` (comparator), `InfrastructureFault` (environment refusals and the
  loop). The domain never manufactures one to simplify control flow.
- Everything is typed and domain-owned: frozen dataclasses for state/call/task, no
  `dict[str, Any]` state.
- Default tests are deterministic and offline. A live LM is opt-in only.
- The only file in a domain package that may import a backend is `environment.py`; only
  `__init__.py` may import `app`/`runtime`; `model.py`/`types.py` import stdlib, `shared`,
  `kit`, and sibling modules only (`from .types import ...`, never `from . import ...`).

## `new <name>`

1. Confirm `domains/<name>/` does not exist and `git status` is clean; work on a fresh branch
   cut from `main` (`git checkout -b domain-<name> main`).
2. Run the scaffold and show its output verbatim:
   ```bash
   python -m maaos create-domain <name>
   ```
   It writes new files only. Add the registry line it prints to `domains/registry.py` by hand.
3. Validate the untouched scaffold — it must pass before any domain logic is written:
   ```bash
   python -m maaos validate-domain <name>
   ```
4. Ask the author for (or read from their description) the domain in these terms only:
   the objects that exist and their identities; the authoritative state fields; the executive
   actions and their parameters; the goal test; the deterministic *intended* effect of each
   action; the ways the backend can refuse or fail. Do not ask about MAAOS internals.
5. If the domain wraps an existing backend (a simulator, a PettingZoo env, a library), send
   `backend-investigator` first with this brief: "Discover the exact realized semantics of
   `<backend path>`: reset/step protocol, action encoding, terminal/success/failure signals,
   partial-execution behavior, what state is exportable, what is observation vs. full state. Do
   not design; report evidence with path:line and mark unresolved semantics." Use its report
   to write `environment.py`; never guess backend behavior.
6. Fill in the generated files in this order, running `validate-domain` after each:
   `types.py` (State/Call/Task, `identities()`), `model.py` (symbolic state, `project`,
   `apply`, `applicable`, `plan`), `environment.py` (`_snapshot`, `_attempt`), then optional
   `DomainExamples` (an ungrounded call, an inapplicable call) and a recovery rule.
   Follow `docs/domains/ADDING_A_DOMAIN.md`; each `validate-domain` FAIL names the file and
   member to fix.
7. Extend the generated `tests/test_domain_<name>.py` with the domain's own designed physical
   failure: one scenario where an applicable call fails in the environment and the episode
   shows discrepancy → recovery (or a typed halt) under `advisory_two_track` and
   `symbolic_primary`. Update the suite-count pin in `docs/refactor/REFACTOR_STATUS.md`.
8. Run the gates: full suite, `ruff check shared runtime app kit domains maaos`, `python -m mypy`,
   `python -m maaos validate-domain <name>`.
9. Run `review <name>` (below). Report files touched, tests added, gate results, review
   verdicts. Do not commit unless asked.

## `validate <name>`

Run `python -m maaos validate-domain <name>`, show the report verbatim, and for each FAIL/WARN
explain the fix in the author's terms (file, function, contract member) — never by pointing
at `runtime/` or `app/` internals. If a message itself is unclear or leaks a runtime frame,
say so explicitly: that is a domain-kit defect to record, not something to work around.

## `review <name>`

1. `architecture-reviewer` with this brief: "Review `domains/<name>/` as a new domain against the
   frozen invariants only: backend authority, optimistic symbolic model with no feasibility
   oracle in `applicable`/`plan` (check that neither reads the environment or authoritative
   geometry), typed evidence channels, `environment.py` as the only backend importer, module
   roles, typed value types, offline determinism. Report PASS/WARN/FAIL with path:line."
2. `test-reviewer` with this brief: "Review `tests/test_domain_<name>.py`: does it prove a designed
   physical failure of an applicable call surfaces as `ExecutionDiscrepancy` (not hidden), both
   policies terminate with typed outcomes, and the count pin is updated? Challenge tests that
   mock away the behavior they claim."
3. Resolve FAILs, record WARNs, and run both policies end to end once more.
