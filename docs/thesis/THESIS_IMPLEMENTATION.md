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
| T2b | 1 | Route A after G0 (owner, 2026-11-07): a 40-pair training corpus and a DSPy optimizer ladder (zero-shot, few-shot, BootstrapFewShot, GEPA) on gemma4:e4b, `docs/thesis/spikes/g0_dspy/` | measured valid-model rate on CoopGrid-Jam-PO | **done 2026-11-08; prompt optimization alone: 0/50 valid; Route B (LoRA) pending the owner** |
| T2c | 1 | Route B (owner, 2026-11-08): QLoRA fine-tuning of `google/gemma-4-e4b-it` (the base of gemma4:e4b) on 277 corpus examples, evaluated against the untrained base in the same runtime, `docs/thesis/spikes/g0_lora/` | valid-model rate on CoopGrid-Jam-PO | **done 2026-11-08; format fixed and structure nearly right (test rubric 9.8/12), 0/10 strictly valid; next step pending the owner** |
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

## Phase T2b — done 2026-11-08 (branch `thesis/t2b-dspy-structure`)

Route A of the owner's plan after G0 (2026-11-07): can DSPy prompt optimization alone make the
local gemma4:e4b write CoopGrid-Jam-PO's model structure? No weight change; Route B (LoRA
fine-tuning on the local RTX 5070 Ti, 12 GB) is decided after this. Files:
`docs/thesis/spikes/g0_dspy/` (see its README). Opt-in only; nothing runs in the offline suite.

What was built:
- `corpus.json`: 40 description/true-model pairs from five domain families (hidden device fault,
  stuck lid, possibly locked vault door with one or two agents, possibly heavy crate lifted by two
  agents, possibly hung network node), eight variants each, every model valid against the T1
  rules; 30 train, 10 validation. CoopGrid-Jam-PO is the test domain only and is in no prompt.
- A DSPy module `ModelStructureGenerator` (one predictor; the T2 format rules as instructions),
  a gold-comparison metric with written feedback, and a five-rung ladder: zero-shot, one and three
  labelled examples, BootstrapFewShot, GEPA (100 metric calls, gemma4:e4b also reflecting).

Results (strict = the reply as written; repaired = re-parsed with `json_repair` first, shown only
to see the structure behind syntax slips; one sample per validation item, ten seeded test runs):

| rung | val metric | val valid | test rubric /12 (best) | test valid | val metric, repaired | val valid, repaired | test rubric, repaired (best) |
|---|---|---|---|---|---|---|---|
| zero_shot | 0.30 | 0/10 | 2.5 (6) | 0/10 | 0.36 | 0/10 | 3.3 (6) |
| fewshot_1 | 0.00 | 0/10 | 2.1 (6) | 0/10 | 0.15 | 0/10 | 2.7 (6) |
| fewshot_3 | 0.07 | 0/10 | 0.0 (0) | 0/10 | 0.54 | 1/10 | 4.2 (11) |
| bootstrap | 0.00 | 0/10 | 0.0 (0) | 0/10 | 0.44 | 0/10 | 3.5 (8) |
| gepa | 0.31 | 1/10 | 0.0 (0) | 0/10 | 0.78 | 2/10 | 3.7 (9) |

**Route A verdict: prompt optimization does not make gemma4:e4b write a valid CoopGrid-Jam-PO
model** — 0 valid test models in 50 strict attempts across all rungs. What the examples do teach
is the structure: with three examples, after syntax repair, test replies reach 11 of 12 rubric
points, and one (seed 2) has a single rule error left (a wrong nominal outcome label). The blocker
is JSON well-formedness: examples make the model copy their compact one-line JSON and slip
(a missing comma, or a precondition written half as a case atom), and one slip voids the reply.
GEPA proposed 10 instructions but its validation score never rose above the starting program's
(0.58 on its repair-aware metric); a 4B model reflecting on its own errors did not find better
instructions within 100 calls. BootstrapFewShot found no self-written demo scoring 0.9 or more.

Harness problems found and fixed during the run (the first runs were discarded):
- demos were dropped by DSPy because they lacked the output field (`model_json`);
- DSPy's field parser raised on replies without its markers; the raw reply is now scored;
- the T2 validator crashed on an object where an argument name belongs (fixed on PR #28);
- GEPA's proposer crashed because ollama returns gemma4 replies as text+reasoning dicts; the
  reflection model is wrapped to return plain text.

Implication for the Route B decision: the remaining failure is output-format consistency, which is
what supervised LoRA fine-tuning on the 30 training pairs targets most directly. Two cheaper
alternatives stay open and can be combined with it: a generator-side `json_repair` plus a
precondition-shape normalizer (turns most near-misses into one-error replies), and a validator-
feedback repair round. The stronger cloud model still waits on `ollama signin`.

Tests added/changed: none. Commands and results: as in the table (`python rescore.py`);
`python -B -m unittest discover -s tests -t .` gave `Ran 1032 tests ... OK (skipped=1)`, unchanged.
Behavior differences: none. Debt: none new. Next: the owner's Route B decision (needs a Hugging
Face account and the Gemma licence accepted), then T3.

## Phase T2c — done 2026-11-08 (branch `thesis/t2c-lora`)

Route B: LoRA fine-tuning of the gemma4:e4b base checkpoint. Files: `docs/thesis/spikes/g0_lora/`
(see its README). Opt-in only; nothing runs in the offline suite; adapter weights are not committed.

Setup:
- Base `google/gemma-4-e4b-it` (Apache-2.0, not gated): the same architecture as ollama's
  `gemma4:e4b` (gemma4, 8.0B raw parameters, hidden size 2560, 131072 context); ollama serves it as
  Q4_K_M. Downloaded with the owner's Hugging Face token, which lives only in
  `~/.cache/huggingface/token`.
- Separate environment `~/.venvs/maaos-ft`, installed by the owner (the project denies `pip install`
  to Claude): torch 2.11.0+cu128, transformers 5.22.2, peft 0.21.2, bitsandbytes 0.50.2, on the local
  RTX 5070 Ti (12 GB, compute capability 12.0).
- Data: the five T2b families expanded to 277 training examples (47 variants dropped for sharing a
  name with a validation item); chat format = the T2 format rules plus the description, answered by
  the gold model as indented JSON. CoopGrid-Jam-PO is in no training file.
- Training: QLoRA (nf4), rank 16, alpha 32, on the language model's attention and MLP projections
  (34.9M trainable parameters), 2 epochs, lr 2e-4, batch 1 x 8 accumulation, loss on the answer only.
  Two memory measures were needed on 12 GB: Gemma 4's 5.6 GB per-layer embedding table stays in system
  RAM behind a row-lookup wrapper during training, and the loss is computed in 512-token chunks with
  Gemma 4's logit soft-cap (30). 70 optimizer steps in 49 minutes, peak GPU 9.3 GB; the training loss
  fell from 0.26 to 0.0004.
- Evaluation: the base and the fine-tuned model in the same runtime (transformers, 4-bit), so only
  the fine-tuning differs; the 10 T2b validation items (seed 1) and 10 seeded CoopGrid-Jam-PO test
  runs; temperature 0.7, top-p 0.95, top-k 64; the Route A metric and the T2 rubric.

| condition | val metric | val valid | test metric | test rubric /12 (best) | test valid | test valid after json_repair | seconds per reply |
|---|---|---|---|---|---|---|---|
| base (control) | 0.40 | 0/10 | 0.34 | 3.6 (4) | 0/10 | 0/10 | 86 |
| LoRA r16 | 0.98 | 9/10 | 0.72 | 9.8 (11) | 0/10 | 0/10 | 204 |

What fine-tuning changed:
- **JSON well-formedness is fixed**: every fine-tuned reply parses; `json_repair` changes nothing.
- **In-family validation is solved**: 9 of 10 validation models are valid (the base: 0).
- **On the held-out test domain the structure is nearly right**: 9.8 of 12 rubric points on average
  (the base: 3.6; Route A's best rung: 2.5 strict, 4.2 after repair); the four skills, their
  parameters, the hidden jam with a parameter prior, the rewards and the goal are right in most runs.
- **But no test model is strictly valid**: each has 1 to 6 rule errors (median 3). The commonest:
  the hidden prior names `door` without declaring it as a constant (6 of 10); an `equals` atom with
  its arguments in the wrong order (3); outcome cases written next to plain effects (3); type errors
  in `CooperateOpen`'s preconditions (2). The stochastic pull is wrong in 5 runs and the shake in 4.
- **A sign of overfitting**: one test model also declares the vault family's hidden `locked`.

Verdict for G0: fine-tuning turns gemma4:e4b from "cannot write the format" into "writes the format
and nearly the right structure on an unseen domain, with a few local rule errors". The remaining
errors are exactly what the validator reports precisely, so a validator-feedback repair round is the
natural next measurement. It is not run here; it is the owner's decision.

Tests added/changed: none. Commands and results: `python3 summarize.py` gives the table above;
`python -B -m unittest discover -s tests -t .` gave `Ran 1032 tests ... OK (skipped=1)`, unchanged.
Behavior differences: none. Debt: none new. Cloud comparison: blocked, since every Ollama cloud model,
including gemma4:31b, now requires paid credits, and `gemma3:27b-cloud` was retired on 2026-07-15.
