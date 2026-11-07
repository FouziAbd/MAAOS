# Thesis POMDP extension — implementation record (phases T0-T5, weeks 1-3)

Running record of the thesis work approved on 2026-11-07. The plan is
`docs/thesis/pomdp-plan-time-estimate.md`, the design `docs/thesis/pomdp-julia-dspy-plan.md`,
the fixed decisions `docs/thesis/HANDOFF.md`, and the scope of what may change is the
"Thesis exception" in `.claude/rules/v1-scope.md`. This file describes actual state: a phase is
"planned" until its dated "done" entry below says otherwise.

Cadence (owner rule, 2026-11-07): one phase per turn; every phase ends with a dated summary
here and in chat, then a stop for owner approval. Every phase starts on a **new** branch cut
from `origin/main` (T0 used `thesis/plan-docs`; from T1 on, never a reused branch).

## Success criterion (gate G-W3, end of T5)

1. A hand-written true-model IR of CoopGrid-Jam-PO (sequential-call encoding E1; jam prior 0.5,
   joint pull slip 0.1, shake success 0.7, rattle accuracy 0.85) compiles to T/Z/R tables that the
   slow Python reference evaluator reproduces row for row, and the seeded wrapper's empirical
   frequencies agree with those tables within a pinned tolerance.
2. NativeSARSOP solves the MDP relaxation and the POMDP; the saved tables and alpha-vector policies
   are committed artifacts that the default offline suite replays in pure Python with no Julia.
3. `python -m maaos validate-domain cooperative_grid_po` reports 0 FAIL.
4. V1 is byte-identical: golden domain digest `b41503536b3bcbe1`
   (`tests/test_contract_invariants.py`), both demo transcripts (`docs/refactor/baseline/`),
   `docs/implementation/acceptance_traces.md`, the V1 PDDL artifacts; ruff/mypy gates clean; the
   suite-count pin in `docs/refactor/REFACTOR_STATUS.md` updated in the same change set.
5. G0 recorded below: which model writes model structure.

## Phase table

| Phase | Week | Deliverable | Gate | Status |
|---|---|---|---|---|
| T0 | 1 | Open the gate: `NEXT_DOMAIN.md`, `v1-scope.md` thesis exception, `CLAUDE.md`, `refactor-architecture.md`, `HANDOFF.md` status, this record | suite unchanged (1032 OK); doc needles intact; pushed | **done 2026-11-07** |
| T1 | 1 | ADR `docs/decisions/T1_PROBABILISTIC_SKILL_IR.md`: generalize `shared/skill_ir.py` in place (domain-supplied type universe and signature source, BoxPush defaults) and extend it (named outcomes with normalized distributions, deterministic or Bernoulli; per-channel observations; Beta-prior parameters; hidden predicates; initial belief); canonical form = the LLM JSON schema; derived DBN view | owner accepts the ADR | **done 2026-11-07; ADR Accepted (PR #26 merged)** |
| T2 | 1 | Spikes, no production code: pinned Julia project under `julia/` (one exact 1.10 LTS version, committed Manifest; POMDPs, POMDPTools, NativeSARSOP, JSON3, StableRNGs) with a Tiger solve; LLM structure spike, gemma4:e4b vs gemma3:27b-cloud through local ollama, 10 samples each, scored against the ADR's draft schema | G0 recorded here | **done 2026-11-07; G0 half-decided: gemma4:e4b cannot write the structure; the stronger model is blocked on an Ollama sign-in** |
| T3 | 2 | `shared/skill_ir.py` generalized and extended per the ADR; `shared/__init__.py` exports; canonical-faithfulness cases; new tests | golden digest, demos, traces, PDDL unchanged; mypy/ruff clean | planned |
| T4 | 2-3 | `pomdp/` package (stdlib + `shared` only, added to the ruff/mypy gates and the import guard): DBN view, state enumeration, table compiler (JSON matching the Julia reader), `fractions`-exact reference evaluator, exact belief update and alpha-vector replay; CoopGrid-Jam-PO and the lamp example as IR fixtures, Tiger as a table-level fixture only (its rewards depend on the hidden state, which the T1 reward model does not express; see the T2 entry); `julia/` bridge (opt-in `MAAOS_JULIA=1`) | compiled tables equal the evaluator on every row; Tiger policy replays without Julia | planned |
| T5 | 3 | Seeded PO wrapper `functional_layer/custom_env/cooperative_grid/grid_env_po.py`; `domains/cooperative_grid_po/` via `create-domain` (jam hidden by projection and by `_observe`; rattle reading in the state, set on shake; `ClearJam` succeeds iff the shake was performed); committed true-model tables and MDP/POMDP policies; still `ProjectionTrack` + `bfs_plan` in this phase | G-W3 | planned |

Weeks 4-5 (planner seam, belief track, `observe()` path, likelihood-based discrepancy,
belief-aware policy) get their own plan after G-W3.

## Owner decisions (2026-11-07, planning session)

- IR coupling: `shared/skill_ir.py` is BoxPush-bound today (registry signature identity,
  agent/box/zone type universe, `bind`/`unbind` on BoxPush ids) and the kit domains never use it.
  Decision: generalize it **in place** with BoxPush defaults, then add the probabilistic fields;
  this takes up the "STRIPS/IR generalization" item deferred in
  `docs/domains/DOMAIN_KIT_IMPLEMENTATION.md`. Rejected: a second schema module.
- Spike model: gemma4:e4b against `gemma3:27b-cloud` via the local ollama (the description
  leaves the machine); a hosted API only if neither writes structure.
- Cadence: one phase per turn with a stop for approval; fresh branch from `main` per phase.

## Debt (owner-scheduled, each with a named cleanup)

- DEBT-T3-REGISTRY: BoxPush's `DomainIR` keeps the frozen-registry identity check behind the
  default path. Cleanup: `box_push_po_lite` (weeks 9-11) must use the generic signature path.
- DEBT-T5-THREE-STRIKE: the repeated-failure counter keyed on the pre-state world key is not
  meaningful under stochastic failures. Cleanup: the belief-aware policy of weeks 4-5.
- DEBT-T1-SAS: the IR has boolean predicates only (no multi-valued state variables). Cleanup:
  decided in extension package X3, where pose becomes a partially observed factor; dated review
  at gate G-W3.
- DEBT-T4-CI: solved artifacts are regenerated by hand under `MAAOS_JULIA=1`. Cleanup: extension
  package X2 (opt-in Julia CI job).

## Phase T0 — done 2026-11-07 (branch `thesis/plan-docs`)

Opened the gate; documentation and rules only, no code.

Files changed:
- `docs/refactor/NEXT_DOMAIN.md`: the five `Unknown` answers replaced (partial observability,
  typed state plus hidden factored variables, grounded discrete skills with one sequential call
  per cycle, sequential skills, stochastic outcomes with named parameters); the two domains named.
- `.claude/rules/v1-scope.md`: "Thesis exception" section (what the ban is lifted for, what stays
  forbidden).
- `CLAUDE.md`: "Out of scope" points at the exception; "Thesis work" section rewritten with the
  approval record, the file map and the byte-identity gate.
- `.claude/rules/refactor-architecture.md`: "Generality limits" names the thesis domains as the
  real domain that requires probabilistic semantics.
- `docs/thesis/HANDOFF.md`: approval status and the "Later" list updated.
- `docs/thesis/THESIS_IMPLEMENTATION.md`: this record.

Tests added/changed: none. Commands and results:
`python -B -m unittest discover -s tests -t .` gave `Ran 1032 tests ... OK (skipped=1)`, the same
as the pre-change baseline; the new docs contain no section-number, PDDL-action or PDDL line
citations (the doc scans in `tests/test_domain_freeze.py`). Gate: PASS. Behavior differences: none. Debt opened: the three items above. Next: T1 (ADR), needs the
owner's go-ahead.

## Phase T1 — done 2026-11-07 (branch `thesis/t1-ir-adr`)

Wrote the design decision record for the probabilistic, domain-generic skill IR; no code.

File added: `docs/decisions/T1_PROBABILISTIC_SKILL_IR.md` (status Proposed). What it decides:
- Two kinds of `DomainIR`: a **registry domain** (BoxPush V1, all current checks kept, may use
  none of the new fields) and a **declared domain** (new `ActionSignature` with string names and
  domain-owned types; positional `bind_values`; `resolve()` never consults the BoxPush registry).
- New declarations: constants, named parameters with Beta priors and optional values,
  observation channels with a default symbol, hidden predicates (`observable=False`).
- New skill fields: negative preconditions, named outcomes with a nominal outcome (the optimistic
  twin is the nominal relaxation), outcome and observation decision lists whose last case is
  unconditional, two normalized distribution forms (deterministic, Bernoulli), a
  `"*"` wildcard allowed only in negative preconditions and negative effects, and the rule that
  hidden predicates never appear in preconditions.
- A `ProblemIR` (objects, observable init, independent hidden priors, goal, rewards, discount).
- The exact compiler/evaluator semantics for T4 and the derived DBN view's checks.
- Canonical JSON = the LLM schema; new keys only when non-default (BoxPush digest unchanged);
  `from_canonical` round-trips by digest.
- The full true-model IR of CoopGrid-Jam-PO, with a call vocabulary the IR expresses exactly
  (`Goto` to handles, `Enter` for the goal, `CooperateOpen`, `ClearJam` naming its handle).
- The T3 acceptance test list.

Tests added/changed: none. Commands and results: `python -B -m unittest discover -s tests -t .`
gave `Ran 1032 tests ... OK (skipped=1)`, unchanged. Gate: the owner's acceptance of the ADR is
pending. Behavior differences: none. Debt opened: DEBT-T1-SAS (boolean predicates only; revisit
for `box_push_po_lite` pose). Open questions for the owner: (1) the PO domain's call vocabulary
differs from V1 cooperative_grid (`Enter`, `ClearJam(agent, place, door)`); (2) the joint pull
slips once (success 9/10), not per agent. Next: T2 (Julia install and Tiger solve; the LLM
structure spike), after acceptance.

### T1 review fixes — 2026-11-07 (same branch)

A high-effort code review of the branch found 10 issues in the record; all were fixed in the ADR:
- hidden static predicates (BoxPush-PO-lite's `heavy(box)`) are now state variables; `init` holds
  observable literals only, `hidden_prior` hidden ones only;
- state, action and observation lists come from the structural support, independent of parameter
  values (values and Bernoulli constants strictly between 0 and 1; actions dropped only on static
  preconditions); artifacts record the ordered lists and the IR digest, and replay checks them;
- a registry domain must keep `types == TYPE_UNIVERSE`, so the agent/box/zone check is not
  loosened;
- declared domains carry their own `provenance` in canonical form; a registry `from_canonical`
  takes it from the caller;
- per-skill observation cases are `ChannelObservations` records with declared, unique channel
  names in declaration order;
- two or more outcomes require outcome cases;
- categorical outcomes and Dirichlet priors are deferred to X3 (no thesis domain needs them);
- `ActionSignature` no longer repeats the parameters;
- this record's T1 row and the DEBT-T1-SAS cleanup trigger were corrected.

Command and result after the fixes: `python -B -m unittest discover -s tests -t .` gave
`Ran 1032 tests ... OK (skipped=1)`, unchanged. The ADR stays Proposed; the gate is still the
owner's acceptance.

## Phase T2 — done 2026-11-07 (branch `thesis/t2-spikes`)

Week-1 spikes. No production code; nothing here runs in the offline suite.

### Julia toolchain

- Julia **1.10.13** (LTS) installed user-locally under `~/.local/opt/julia-1.10.13` from the
  official tarball, SHA-256 verified, no PATH or shell-profile change (steps in `julia/README.md`).
- `julia/Project.toml` + committed `julia/Manifest.toml`: POMDPs 1.0.0, POMDPTools 1.1.0,
  NativeSARSOP 0.1.4, POMDPModels 0.4.22, JSON3 1.14.4, StableRNGs 1.1.0; compat `julia = "1.10"`.
- `julia/tiger.jl`: NativeSARSOP on `POMDPModels.TigerPOMDP` with iteration budgets and no
  wall-clock cap.

| Tiger check | Result |
|---|---|
| value at the uniform initial belief | 19.371368 (the known Tiger value at discount 0.95) |
| same model through `SparseTabularPOMDP` | 19.371368 |
| alpha vectors, two independent solves | 5, identical |
| action at the initial belief | listen |
| mean discounted return, 2000 episodes, `StableRNG(2026)` | 19.4661 |

Finding for T4: Tiger cannot be written in the T1 IR. Its rewards depend on the hidden state
(opening the tiger's door costs 100), and the T1 `RewardModel` holds only constant step, skill and
goal rewards. Tiger is therefore a table-level fixture in T4 (exported from POMDPModels through
`SparseTabularPOMDP`), and the IR fixtures are CoopGrid-Jam-PO and the lamp example. The T4 row
above was corrected. No thesis domain needs state-dependent rewards, so the ADR is unchanged.

### G0 — can the model write the structure?

Files: `docs/thesis/spikes/g0_structure/` (see its README). The prompt gives the T1 format rules,
one worked example of a different domain (a lamp with a hidden fault and a noisy inspection) and
the sole-input description with all probabilities withheld. A 12-point, name-agnostic rubric
scores each reply; the hand-written true model scores 12/12. The standalone validator was checked
by ten deliberate mutations of the true model, each caught. Settings: seeds 1-10, temperature
0.7, context 16384, at most 8192 output tokens, local ollama 0.21.0.

| model | samples | mean score /12 | best | valid against the T1 rules | parsed as JSON | seconds per sample |
|---|---|---|---|---|---|---|
| gemma4:e4b, ollama JSON mode | 10 | 0.8 | 6 | 0 | 3 | 17-66 |
| gemma4:e4b, free text | 10 | 3.3 | 9 | 0 | 6 | 37-64 |
| gemma3:27b-cloud | 0 | - | - | - | - | every call refused: HTTP 401, the machine is not signed in to Ollama |

| rubric check (count of 10) | JSON mode | free text |
|---|---|---|
| parses | 3 | 6 |
| valid against the T1 rules | 0 | 0 |
| exact skill vocabulary | 1 | 6 |
| exactly one hidden variable | 1 | 4 |
| hidden prior is a parameter | 0 | 5 |
| pull stochastic, conditioned on the hidden variable | 0 | 1 |
| shake clears the hidden variable with a parameter | 0 | 1 |
| rattle is a noisy observation of it | 1 | 1 |
| no probability values written | 1 | 6 |
| rewards and discount exact | 0 | 2 |
| corridor refusals modelled | 0 | 0 |
| goal names both agents | 1 | 1 |

What went wrong:
- In JSON mode, 7 of 10 replies are malformed or truncated; several end in a run of blank lines
  up to the token limit, a known failure of constrained JSON decoding with small models.
- In free text, the commonest error is writing a case atom (`{"literal": ..., "positive": ...}`)
  where a precondition (`{"name", "args"}`) belongs (4 of 6 parsed replies), then types used but
  not declared.
- No reply models the corridor refusals, and only one gets the stochastic pull right.

**G0 verdict (half): gemma4:e4b cannot write CoopGrid-Jam-PO's model structure zero-shot**: 0 of
20 replies are valid, and the best is 9 of 12 on semantics with a broken format. This is the
plan's risk 2: a stronger model writes structure and the failure is reported as a finding. The
stronger model's run is blocked until the owner signs this machine in to Ollama (`ollama
signin`); then `MAAOS_LIVE_LM=1 python run_spike.py --models gemma3:27b-cloud --seeds 10` and
`python score.py results` complete G0. Not tried, and out of T2 scope: feeding validator errors
back for repair rounds (the cascaded metric of weeks 6-8), which may rescue the small model.

Two observations for later phases, not changes now:
- Precondition literals and case atoms use different JSON shapes (the V1 canonical form keeps
  `{"name","args"}` for preconditions). A generator-side normalizer, or one validator-feedback
  round, is the cheap fix; it belongs to the generation work of weeks 6-8, not to the IR.
- The two JSON-mode and free-text conditions differ only in decoding, so later model comparisons
  should report both.

Tests added/changed: none; the spike scripts live under `docs/` and pass the import-guard tests.
Commands and results: `julia --project=julia julia/tiger.jl` as above; `python -B -m unittest
discover -s tests -t .` gave `Ran 1032 tests ... OK (skipped=1)`, unchanged. Behavior
differences: none. Debt: none new. Next: T3 (implement the ADR in `shared/skill_ir.py`), which
needs the owner's go-ahead; the G0 cloud run can be finished in parallel once Ollama is signed in.
