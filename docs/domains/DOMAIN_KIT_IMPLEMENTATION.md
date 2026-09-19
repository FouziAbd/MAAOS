# Domain kit — implementation record (DK0–DK5)

Post-R6 maintenance program requested by the project owner (plan approved 2026-09-18,
executed 2026-09-19, one phase per pull request). Design record:
`docs/decisions/DK1_DOMAIN_PACKAGE.md`. Author guide: `docs/domains/ADDING_A_DOMAIN.md`.

Everything below is implemented and tested unless marked otherwise. Frozen V1 behavior,
`build_loop`, the runner CLI, the trace format and both headless demo transcripts
(`docs/refactor/baseline/demo_*.txt`) are unchanged at every phase.

## Success criterion

> A developer unfamiliar with MAAOS can add a small deterministic domain by following
> `docs/domains/ADDING_A_DOMAIN.md` alone, without editing anything under `shared/`,
> `runtime/`, `kit/`, `app/`, or `tests/` other than the files `create-domain` generated for
> them, and without reading or understanding `ExecutiveLoopManager` or any other runtime
> internal.

Two deliberate, recorded exceptions (ADR-DK1 guard decision B; the suite-count pin rule):
a domain whose `environment.py` imports a banned framework adds ONE enumerated line to
`tests/test_no_backend_imports.py` (a pure-Python domain adds none), and every new test file
moves the pinned suite size in `docs/refactor/REFACTOR_STATUS.md` (under `docs/`). The guide
names both.

Evidence: the mechanical proof (DK4, `tests/fixture_lamp/`), the human-path proof (DK5
usability gate, below), and `python -m maaos validate-domain` as the continuous check.

## Phase table

| Phase | PR | Delivered | Suite (pinned) |
|---|---|---|---|
| DK0 | #15 | `.claude/skills/domain-kit-phase`, `.claude/skills/add-domain`, `.claude/agents/domain-author-reviewer` (a dry run found 7 instruction defects, fixed in the PR's second commit) | 850 |
| DK1 | #16 | `app/domain_package.py`, `app/assembly.py`, `domains/` (+ `registry.py`, `box_push/`), guard decisions A/B + ADR, `kit/`/`maaos/` reserved | 885 |
| DK2 | #17 | `kit/` (keys, protocols, environment, track, services, planning, comparator) proven equivalent beside the untouched probe; ADR "DK2 — kit extraction record" | 927 |
| DK3 | #18 | `app/validation.py` (catalogue DK001–DK090), `maaos/cli.py` (`validate-domain`, `list-domains`); guard-parity proof | 971 |
| DK4 | #19 | `maaos/scaffold.py` + templates (`create-domain`); `tests/fixture_lamp/` generated verbatim (A) then changed through extension points only (B); review corrections (C) | 992 |
| DK5 | #20 | `docs/domains/ADDING_A_DOMAIN.md`, this record, README/CLAUDE.md/rule/NEXT_DOMAIN updates, `tests/test_dk5_docs.py`, the usability gate | 1001 |
| fix | this PR | the four actionable WARNs of the post-merge `/consistency-check all` (§"Post-program fix") | 1002 |

## DK1 — declaration, assembly, guard decisions

- `DomainPackage` (frozen generic record; author-facing refusals at construction) and
  `assemble_loop` (explicit one-component keyword overrides; provenance passed through;
  the environment reaches the loop only). `domains/box_push/` delegates every factory to
  `app.box_push_v1.compose`; `domains/box_push/environment.py` imports the adapter lazily.
- Guard A: `domains`/`maaos` join `COMPOSITION_PACKAGES`; per-module roles enforced by
  `domain_role_violations` (relative imports resolved; laundering through `__init__` banned).
  Guard B: enumerated `DOMAIN_ENVIRONMENT_MODULES` exemption minus `NEVER_EXEMPT_ROOTS`
  (legacy trees, `dspy`, `torch`); `sys.modules` joins the text ban.
- Tests: `tests/test_dk1_domain_package.py` — both baseline transcripts reproduced cycle by
  cycle through `assemble_loop`; role probes fail closed; `import domains` loads no backend.
- Reviews (as reported in PR #16): test-reviewer PASS, architecture-reviewer PASS (all WARNs applied).
- Debt: `DEBT-DK1` (the adapter under two module names) with its cleanup item in the ADR.

## DK2 — the kit

- Extracted from BoxPush ∩ probe, with four recorded BoxPush-only extractions (`bfs_plan`,
  the case-(c) trio) and two documented conveniences (ADR "DK2 — kit extraction record").
- `tests/test_dk2_kit.py` (42): the same one-integer domain rebuilt from the kit matches the
  untouched probe entry by entry under both policies, with and without an echo track.
- Reviews (as reported in PR #17): test-reviewer PASS, architecture-reviewer PASS (all WARNs applied). Deferred: a
  backend re-read hook for external mutable simulators (owner choice).

## DK3 — validate-domain

- `validate_domain` / `validate_named` with a stable catalogue; every check under its own
  guard; blocked dependents SKIPPED; every code in every report; names resolved through the
  static registry only; layout and lazy-backend checks mirror the guard and are proven
  equivalent on probe trees (`tests/test_dk3_validation.py`, 44 tests).
- BoxPush: 28 PASS, 0 WARN, 0 FAIL, 2 SKIPPED (the optional advisory checks).
- Reviews (as reported in PR #18): architecture-reviewer PASS, test-reviewer WARN (applied), domain-author-reviewer
  WARN on message quality (applied: the validator is no longer greener than the suite).

## DK4 — create-domain and the second-domain proof

- `python -m maaos create-domain <name> [--target DIR]` writes new files only.
- Proof: commit A (`9a2a01d`) = `tests/fixture_lamp/` byte-identical to the generator's output AT THAT COMMIT (the templates evolved in commit C and the `.py` structure pin tracks them); commit B (`0f72d66`)
  = changed only through the `# TODO(author)` extension points into a two-lamp domain with a
  stuck switch and `Nudge` as recovery advice. **Measured author work A→B (from `git diff 9a2a01d 0f72d66 -- tests/fixture_lamp`, as reported in PR #19): 4 files,
  +54/−33 lines, 21 of 30 functions/classes changed.** symbolic_primary halts after three
  typed failures; advisory_two_track recovers and reaches the goal. Nothing under
  `runtime/`, `shared/`, `kit/` or `app/` changed in commits A/B.
- Commit C (reviews): traversal-proof targets, reserved names, a typed declaration that
  passes the mypy gate, DK016 for a field shadowing a contract method, an author-facing
  message when a registered domain is half-edited. Verified: scaffold + two registry lines
  + the count pin leaves the full suite green (994 in the scratch copy).
- Reviews (as reported in PR #19): test-reviewer WARN (applied), domain-author-reviewer WARN (applied; built a
  working domain of its own with zero gate failures).

## DK5 — the guide and the usability gate

- `docs/domains/ADDING_A_DOMAIN.md`: complete on its own; headings match every anchor the
  validator and the templates reference (`tests/test_dk5_docs.py`); every validation code
  documented; the guide never names a runtime internal.
- `README.md`, `CLAUDE.md`, `.claude/rules/refactor-architecture.md` (paths), and
  `docs/refactor/NEXT_DOMAIN.md` (dated note; fields stay `Unknown`) updated.

### Usability gate (blocking)

The `domain-author-reviewer` agent, given only the guide and a scratch copy of the tree,
builds a working domain of its own choosing from `create-domain` to both policies.

Run 2026-09-19 on this branch (the reviewer chose a docking robot: a robot, a door with a
jammed latch the model does not know about, a charger; recovery `Unjam` then `OpenDoor`).

| Measure | Result |
|---|---|
| outcome | working domain under both policies: symbolic_primary `halted_repeated_failure` after 3 typed failures; advisory_two_track `goal_reached` in 7 executive steps |
| `validate-domain` | 28 PASS, 0 WARN, 0 FAIL, 2 SKIPPED at every stage (untouched scaffold, after the coherent edit, final) |
| files touched | 5 generated files edited (`types.py`, `model.py`, `environment.py`, `__init__.py`, the generated test); 0 files created; the 2 registry lines; the count-pin line in `docs/refactor/REFACTOR_STATUS.md` (the guide names it); **no guard line needed** (pure Python); **0 other files** |
| functions written or changed | 30 (types 12, model 8, environment 5, `__init__` 1, test 4) |
| contents opened outside the guide | **none** — nothing under `runtime/`, `app/`, `kit/`, `shared/`; not even the lamp example |
| validator messages it could not act on | none |
| blockers (three-attempt rule) | none |
| gate failures | **0** |
| verdict | WARN: working domain, zero gate failures; the one exploratory step it needed was that `history.entries` holds a decision-only entry (the halt / request_proposal) with `execution is None` — the guide and the test template now say so and list the decision vocabulary |

Guide/scaffold gaps it reported were applied in this phase: the trace-entry cardinality and
the `ExecutiveDecision` values, no-effect recovery calls, the 2 SKIPPED in the quick start, the
count-pin delta, the `__init__` docstring's import statement, the test template's wording.
The gate is therefore PASSED on the success criterion (no edit outside generated files beyond
the registry and the docs pin; no runtime internal read).

### Independent final review

`architecture-reviewer`, fresh brief (code and ADR only): PASS — 0 FAIL, 7 WARN (all
documentation-level, applied in this phase), 5 DEFERRED (listed below); no permanent FAIL
condition triggered. Its two git checks it could not run itself were run before merge:
`git diff ecff53f --stat -- shared runtime symbolic nl domain app/box_push_v1.py app/comparator.py functional_layer`
is empty, and commits `9a2a01d`/`0f72d66` touch nothing under `runtime/`, `shared/`, `kit/`, `app/`.
`test-reviewer` on DK5: WARN, applied (every `§` reference resolves; the record is pinned
against a placeholder; README shows the registry step).

## Post-program fix (2026-09-19, `/domain-kit-phase fix`)

`/consistency-check all` after PR #20 merged: PASS, 0 FAIL, 6 WARN, 4 DEFERRED(owner). The
four actionable WARNs fixed here:

1. **Physical state belongs in the authoritative state.** The guide, the environment template
   and the lamp fixture told authors to keep a designed physical condition backend-private;
   `export_full_state` is the sole canonical truth (Decision 4) and the repeated-failure key
   and `same_world` were blind to such a fact. Now: `stuck` is a field of the lamp `State`
   (in `canonical()`), `project()` drops it (optimism lives in the projection, as in BoxPush),
   `apply_world` predicts `Nudge` clearing it, and the guide/template say so. Lamp outcomes
   unchanged (same executed sequences, three typed failures, recovery, goal); what changed is
   evidence-level and intended: `observe()`/`world_key()` now carry `stuck`, and `Nudge` is a
   world-changing success the monitor predicts, instead of an unchanged-world one.
2. **No marker-string evasion in production code.** `app/validation.py` is the guard's one
   enumerated string-only exemption (`TEXT_SCAN_STRING_ONLY`); for it the guard runs an AST
   check (no `sys.path`/`sys.modules` reachable from its own code: direct, aliased, chained,
   `from sys import`, `__dict__`, `getattr`/`vars`) and the file spells those two markers
   plainly in strings; the dynamic-import builtin has no such exemption, so that third marker
   stays concatenated. A probe pins that the exemption is load-bearing and that each access
   spelling is caught.
3. `README.md`: `app/` sentence amended for the `domains/` composition packages.
4. `tests/test_p3_nl.py`: the module-scope dspy/legacy scan is recursive over `tests/`.

Recorded, not fixed (pre-existing or design-level): `ui` is not a banned import root; the
validator reads the guard's door set from the test file (parity pinned; a shared non-test
module could hold it); a domain `__init__.py` may import a sibling domain; the generated test
imports the public `runtime.loop.EpisodeOutcome` (a re-export from `app.assembly` would make
the "no runtime internal" claim literal).

## Deferred (owner-scheduled, not accepted indefinitely)

- `DEBT-DK1`: one canonical import path for the BoxPush adapter (ADR cleanup item).
- A D4-style backend re-read hook on `kit.EnvironmentBase` for external mutable simulators.
- The DK1 known limitation: a sibling simulator module imported by both `environment.py`
  and `model.py` is invisible to an import scan (documented in the ADR and the guide's rules).
- STRIPS/IR generalization (`shared/skill_ir.py`, `symbolic/planner.py::Universe`) — a
  separate owner decision; the kit targets the `DomainServices` seam.
