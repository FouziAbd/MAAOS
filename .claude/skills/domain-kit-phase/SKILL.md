---
name: domain-kit-phase
description: Implement exactly one phase (DK1-DK5) of the approved post-R6 domain-kit program, run its gates and reviews, report, then stop — or `fix` for later kit maintenance under the same gates.
argument-hint: DK1|DK2|DK3|DK4|DK5|fix
disable-model-invocation: true
---

# Implement One Domain-Kit Phase

Target: `$ARGUMENTS`

Accept only one of `DK1`, `DK2`, `DK3`, `DK4`, `DK5`, `fix`. Never two phases in one
invocation. Never begin the next phase after finishing this one: **report and stop**; the
owner approves each phase before the next starts.

The program's spec is the owner-approved plan (kept outside the repository at
`~/.claude/plans/giggly-dazzling-twilight.md`; once DK1 lands, the ADR
`docs/decisions/DK1_DOMAIN_PACKAGE.md` and, from DK5, `docs/domains/DOMAIN_KIT_IMPLEMENTATION.md`
are the in-repo record). The condensed phase specs below are authoritative for scope; the plan
file has the rationale.

## The success criterion every phase serves

> A developer unfamiliar with MAAOS can add a small deterministic domain by following
> `docs/domains/ADDING_A_DOMAIN.md` alone, without editing anything under `shared/`,
> `runtime/`, `kit/`, `app/`, or `tests/` other than the files `create-domain` generated for
> them, and without reading or understanding `ExecutiveLoopManager` or any other runtime
> internal.

Governing principle: the kit is the extracted intersection of what BoxPush
(`app/box_push_v1.py`, `functional_layer/custom_env/box_push/env/box_push_v1_adapter.py`) and
the R5 probe (`tests/probe_counter.py`) already implement by hand. Nothing in it comes from a
hypothetical domain. Semantics stay classical, deterministic, fully observable, sequential.

## Before editing

1. Read `CLAUDE.md`, `.claude/rules/v1-scope.md`, `.claude/rules/refactor-architecture.md`,
   `.claude/rules/testing.md`, `.claude/rules/supervisor-contract.md`.
2. Read the plan file sections §0, §3, §4 (your phase), §5, §7.
3. `git status` must be clean; work on a fresh branch cut from `main`
   (`git checkout -b dk<N>-<slug> main`). Never stack on the previous phase branch.
4. Run the full suite first and note the count:
   `python -B -m unittest discover -s tests -t .`
5. Read every file the phase names before changing it.

## Phase specs (scope; smallest coherent change set only)

### DK1 — contract, assembly, BoxPush declaration, guard decisions
Create `app/domain_package.py` (`DomainPackage`, `DomainExamples`; stdlib+`shared` imports),
`app/assembly.py` (`assemble_loop(package, task_name=None, config=None, nl_track=None,
provenance=None, policy=None, *, loop_class, domain, symbolic_track, comparator,
recovery_provider)` — explicit keywords, no `**overrides`, passes `provenance=None` through so the
loop's default `Provenance.source` is unchanged, never hands the environment to a factory),
`domains/__init__.py` (import surface, docstring only), `domains/registry.py` (static
`REGISTRY` dict, hand-edited), `domains/box_push/__init__.py` (DOMAIN delegating to
`app.box_push_v1.compose(task)`; `reasoning_track=None`), `domains/box_push/environment.py`
(factory importing `functional_layer.custom_env.box_push.env.box_push_v1_adapter` inside the
function; no `sys.path`), ADR `docs/decisions/DK1_DOMAIN_PACKAGE.md` (Accepted; records the
composition-set widening + module-role check, the `environment.py` exemption and why it differs
from the R6 seam decision, `DEBT-DK1` double module object with its cleanup item, the success
criterion). Guard/gate edits, each an extension never a relaxation:
`tests/test_no_backend_imports.py` (`COMPOSITION_PACKAGES` += `domains`, `maaos`; role-aware
forbidden set through the single enforcement path; enumerated `environment.py` exemption from
`FORBIDDEN_PREFIXES` minus legacy roots; fail-closed probes for `model.py -> runtime`,
`model.py -> environment`, `model.py -> numpy`, `environment.py -> model`,
`environment.py -> legacy`, package-laundering via `__init__`), `tests/test_r6_legacy_boundary.py`
`GUARDED_DIRS` += `domains`, `maaos`; `tests/test_r5_probe.py` `_PRODUCTION_DIRS` and
`FORBIDDEN_ROOTS` += `kit`, `domains`, `maaos`; `tests/test_r4_composition.py` `FORBIDDEN_ROOTS`
likewise; `pyproject.toml` mypy files + `tests/test_r6_typing.py::MYPY_TARGETS`;
`.github/workflows/offline-tests.yml` + `tests/test_r6_tooling.py` ruff scope
`shared runtime app kit domains maaos`; suite-count pin. New `tests/test_dk1_domain_package.py`:
no BoxPush tokens in `DomainPackage`; module-role check + probes; `assemble_loop(DOMAIN)` yields
the same component types as `compose()` and the accepted outcomes / 3 discrepancies; **R0
transcripts byte-for-byte through `assemble_loop`**; subprocess: `import domains` loads no
backend module. Unchanged: `build_loop`, runner, every frozen module.

### DK2 — the kit (`kit/`, new top-level package; stdlib+`shared` imports only)
`kit/{__init__,keys,environment,track,services,planning,comparator}.py`. Structural
guarantees to pin by AST/mypy: `bfs_plan` mirrors `symbolic/planner.py:92-141` category for
category and takes no state/environment; `DerivedDomainServices.plan` passes only
`state.identities()`; optional `apply_world` reachable from `predict`/`monitor` only; only
`kit/environment.py` imports `shared.faults` / raises `InfrastructureFaultError` (with the
`"refused:"` and `primitive_steps_before_failure=N` conventions), the kit never catches one; an
author `_attempt` exception becomes `BACKEND_API_EXCEPTION`, never a `FAILURE` result; result
builders never default `failure_class` (derive `PARTIAL_EXECUTION` only when `same_world` is
False) and never set `raw_label`; the derived monitor emits only
`EXECUTION_FAILURE_OF_APPLICABLE_SKILL` / `STATE_EFFECT_MISMATCH` and re-raises author errors as
chained `ValueError`; `DefaultProposalComparator(equivalence=None, low_confidence_threshold=None)`
is the true intersection with opt-in arms; no identifier containing `counter` or `probe`.
`tests/test_dk2_kit.py`: side-by-side equivalence with the untouched probe on its own
scenario; refusal-message conventions; the guarantees above. `tests/test_r5_probe.py`
`PRODUCTION_COMPARATORS` += `DefaultProposalComparator` (whitelist extension). Pin update.

### DK3 — `validate-domain` and the `maaos/` CLI
`app/validation.py` (`validate_domain(package) -> ValidationReport`; checks DK001-DK090 from the
plan §3.6; every FAIL names file/function/contract member, exception text under "details";
`HALTED_REPEATED_FAILURE` without a recovery provider is a WARN with guidance; DK003 for an
unregistered name quotes the exact `domains/registry.py` line), `maaos/{__init__,__main__,cli}.py`
(`python -m maaos validate-domain <name>`; resolves through `domains.registry.REGISTRY`; no
`importlib`). `tests/test_dk3_validation.py`: `box_push` all PASS offline; deliberately broken
in-test packages yield exactly their code and a headline without traceback text; CLI exit codes;
subprocess smoke. Pin update.

### DK4 — `create-domain` and the real second-domain proof
`maaos/scaffold.py` + `maaos/templates/`. Writes **new files only** (`domains/<name>/…`,
`tests/test_domain_<name>.py`), refuses an existing dir / invalid identifier, prints the registry
line and next steps. The generated domain must pass `validate-domain` unchanged. Proof, in two
commits: (A) the generator's output moved verbatim to `tests/fixture_lamp/` (a test re-renders
and diffs); (B) changes only through the documented extension points to a small deterministic
domain with a designed physical failure and a recovery rule. `tests/test_dk4_scaffold.py`:
tempdir scaffold → validate → both policies; fixture runs discrepancy → recovery → goal
through `assemble_loop`; AST import pins per role; subprocess pin that the episode loads no
`domain`/`symbolic`/`nl`/`app.box_push_v1`/`app.comparator`/backend module. Before merge,
`test-reviewer` confirms from `git diff --name-only main...HEAD` that the branch touches nothing
under `runtime/`, `shared/`, `kit/`, `app/`. Record the A→B file/function counts. Pin update.

### DK5 — docs and the usability gate
`docs/domains/ADDING_A_DOMAIN.md`, `docs/domains/DOMAIN_KIT_IMPLEMENTATION.md` (evidence only),
`README.md`, `CLAUDE.md` (active implementation + workflows), `.claude/rules/refactor-architecture.md`
`paths:`, `docs/refactor/NEXT_DOMAIN.md` dated note (fields stay `Unknown`), ADR status. Then the
blocking usability gate: `domain-author-reviewer` with only the guide and a scratch copy goes
from `create-domain <fresh-name>` to a working domain of its own under both policies; the gate
fails if any file outside the generated domain was edited or any step required reading `runtime/`
or `app/`. Its numbers and findings go into the implementation doc; unresolved findings block.

### fix — later kit maintenance
Same gates and reviews as a phase; scope is one recorded regression against the ADR / guide.

## Gates after each coherent change (all must pass before review)

```bash
python -B -m unittest discover -s tests -t .
ruff check shared runtime app            # plus kit domains maaos once they exist
python -m mypy
cd functional_layer/custom_env/box_push/env && \
  SDL_VIDEODRIVER=dummy python box_push_v1_run.py --headless --policy advisory_two_track | diff - ../../../../docs/refactor/baseline/demo_advisory_two_track.txt && \
  SDL_VIDEODRIVER=dummy python box_push_v1_run.py --headless --policy symbolic_primary  | diff - ../../../../docs/refactor/baseline/demo_symbolic_primary.txt
python -m maaos validate-domain box_push  # from DK3 on
```

Update the suite-count pin (`docs/refactor/REFACTOR_STATUS.md`, the single line
`N tests, deterministic and offline`) in the same change set whenever tests are added.

## Reviews before declaring the phase complete

Brief the existing agents; do not edit their definitions.

1. `test-reviewer` — brief: the phase spec above, the files changed, and: "every edit to an
   existing test must be a whitelist extension, never a relaxation; kit helpers must be proven
   equivalent beside the untouched probe, not by rewriting it; check the count pin; for DK4 also
   check `git diff --name-only main...HEAD` touches nothing under runtime/, shared/, kit/, app/".
2. `architecture-reviewer` — brief: the phase spec, the success criterion, and these extra FAIL
   conditions on top of its permanent list: the kit changes any BoxPush trace; a `domains/`
   module-role violation or a package-laundering import; validation reports a runtime frame as the
   headline; a dict-shaped or `Any`-primary kit API; any discovery or registration hook; a fault
   raised or caught anywhere in the kit except `kit/environment.py` raising; a defaulted
   `failure_class`; `assemble_loop` differing from `build_loop` in provenance or components.
3. DK3/DK4/DK5 additionally: `domain-author-reviewer` (message quality / scaffold walkthrough /
   the full usability gate).
4. Resolve every FAIL. Record WARNs. Anything outside the phase is DEFERRED with its owner.

## Stop conditions (explain before changing code)

A required change to frozen V1 semantics, a public constructor/import/CLI/trace format, the
supervisor report, `tests/probe_counter.py`, or any frozen `domain/`, `symbolic/`, `nl/` module;
any need to weaken (rather than extend) a guard test; any kit element not already implemented
by both BoxPush and the probe (except `bfs_plan` and the case-(c) helper, recorded as
"extracted from BoxPush").

## Completion report (then STOP)

- phase; branch; files created/changed;
- tests added/changed (and the new pinned count);
- commands run with results (suite, ruff, mypy, both demo diffs, validate-domain);
- reviewer verdicts (PASS/WARN/FAIL per reviewer) and how each FAIL was resolved;
- behavior differences from `main` (expected: none for BoxPush);
- DEFERRED items and their owner;
- whether the phase is ready to commit / open a PR.

Do not start the next phase. Do not claim completion while any gate or FAIL is open.
