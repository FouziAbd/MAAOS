# Thesis plan and time estimate: MAAOS POMDP work

Revised 2026-10-11 for a 5-month limit (submission by about 2027-03-13) and aligned with the
supervisor's *Symbolic-Twin BoxPush Implementation Plan* (v5). Based on
`claude/pomdp-julia-dspy-plan.md`. Supersedes the 4-month version of 2026-10-10.

Extended 2026-10-15: nothing from the research report is cut any more. The 22-week thesis below is
unchanged; everything previously listed as "cut to future work" is now an **extension phase**
(end of this document), ordered so that whatever is not finished by submission is handed to the
supervisor as ready-to-start work packages.

## Estimates by scope

| Scope | Full-time effort |
|---|---|
| The full plan in the research report (eight hypotheses, three evaluation tiers) | About 12–18 months |
| Earlier scoped MSc version (runtime contract changes, full GEPA study, 577-state BoxPush-PO) | About 5–7 months |
| 4-month version (separate harness, frozen contracts, new JSON schema) | 17 weeks |
| **5-month supervisor-aligned thesis below** | **22 weeks, about 1.5 weeks of buffer** |
| **Extension phase (all remaining work, after or alongside the thesis)** | **About 40–48 weeks** |

## Research question and claims

Can MAAOS acquire a multi-agent POMDP model from natural-language domain knowledge, inside its own
executive architecture, and repair and extend it from execution evidence, so that belief-space
planning beats hand-written recovery and LLM-only control?

1. **Sample efficiency.** With LLM-generated structure and data-fitted parameters, the model reaches
   near-true-model performance with far fewer episodes than a tabular model learned from scratch.
2. **Evidence-driven repair.** When the description leaves out a mechanism, repair driven by typed
   `ExecutionDiscrepancy` evidence from the real monitor restores performance more reliably than
   free-text failure logs or no repair.
3. **Planning benefit.** Belief-space planning inside the executive loop beats the domain's
   hand-written recovery and an LLM-only per-step policy, with far fewer LLM calls than the
   LLM-only policy.
4. **Structure learning.** LLM-proposed structural hypotheses (`ModelHypothesisGenerator`) combined
   with statistical model selection recover an injected missing dependency, measured by
   structural precision/recall (supervisor sec. 4.4, sec. 15.3).

Reported descriptively: belief calibration, solve times, MDP-vs-POMDP value gap (the cost of hidden
information), orchestration-policy comparison, and the effect of LLM size on structure generation.

## Design decisions (aligned with the supervisor plan)

- **One IR, extended — not a new schema.** The existing skill IR (`shared/skill_ir.py`) gains
  multiple named outcomes with probability expressions, per-outcome observations and named
  parameters. Every existing V1 domain must load unchanged as the single-outcome special case
  (supervisor P5). Durations stay out of scope.
- **Canonical DBN view.** A small builder derives parent sets and local conditional models from the
  IR; it backs validation (acyclicity, parent consistency) and the fitter. RDDL round-trip is
  in the extension phase.
- **MDP first, then POMDP** (supervisor P6). The IR compiles to `SparseTabularPOMDP`/MDP tables
  (sec. 8.1 allows standard solvers for small models); NativeSARSOP solves in a persistent Julia
  session; Python updates the belief and picks actions from alpha vectors; default tests replay
  saved policies without Julia. A slow Python reference evaluator of the IR checks the compiled
  tables (sec. 8.4).
- **Inside the real loop, not a separate harness.** For the new domains only: the POMDP planner
  sits behind `DomainServices.plan`, the belief lives in a `SymbolicTrack`, an optional `observe()`
  path feeds it, the monitor raises a typed discrepancy for zero/low-likelihood observations, and
  a belief-aware failure policy replaces the three-strike halt. V1 demos stay byte-identical.
- **LLM proposes, statistics decides** (sec. 4.4). The LLM writes structure; a fitter estimates
  numbers; structural changes are typed patches that stay provisional and are committed only if
  held-out likelihood improves, with rollback otherwise. Model versions are recorded in traces.
- **DSPy with the supervisor's module names.** Typed signatures for the generator and for repair
  (`ModelHypothesisGenerator`); recorded-LM fixtures, temperature 0. Light GEPA is a stretch goal
  (P9).
- **Sequential executive calls** match the supervisor's V1 sequential rule. Future concurrency is
  the supervisor's event-driven active-skill model (P7), not a lockstep joint-action encoding.
- **Domains:** CoopGrid-Jam-PO (hidden jam, pull slip, noisy rattle) for development; BoxPush-PO-lite
  (hidden box weights plus pose dynamics, `box_push_problem_description.md` as the description) as
  the supervisor's first partially observable BoxPush experiment. Fallback: CoopGrid variants.
- **Baselines:** `symbolic_primary` and `advisory_two_track`, the domain's hand-written heuristic,
  an LLM-only per-step policy on the same model, a tabular model learned from the same episodes,
  and the true-model MDP/POMDP as upper bounds. Ablations: no fitting; free-text vs typed repair
  feedback.
- Paired seeds (30–40 per condition) with bootstrap confidence intervals.

## Schedule

| Weeks (dates) | Work | Gate |
|---|---|---|
| 1 (Oct 11–17) | Supervisor sign-off on scope, the 5-month deadline and unfreezing `skill_ir` and runtime seams; `NEXT_DOMAIN.md`; IR extension design; LLM spike (gemma4:e4b and one stronger model, ten samples each); Julia install and a Tiger solve | G0: which model writes structure |
| 2–3 (Oct 18–31) | Extend `skill_ir` (V1 regressions pass); DBN builder; compiler plus reference-evaluator test; CoopGrid-Jam-PO wrapper; solve MDP, then POMDP, on the true model | |
| 4–5 (Nov 1–14) | Integration: planner seam, belief track, `observe()` path, probabilistic discrepancy in the monitor, belief-aware policy; baselines | G1: POMDP runs inside the executive loop |
| 6–8 (Nov 15–Dec 5) | Generation, fitter, tabular learner, learning curves; repair with provisional/commit/rollback; free-text vs typed feedback | G2: claims 1–2 on CoopGrid |
| 9–11 (Dec 6–26) | BoxPush-PO-lite through the same loop: seeded weights, hidden-weight projection, ground truth by enumerating skill outcomes in the backend, experiments | End of week 9: switch to CoopGrid variants if BoxPush is not running |
| 12–13 (Dec 27–Jan 9) | Structure learning: inject a missing dependency, LLM proposes candidates, held-out likelihood/BIC selects; precision/recall | Claim 4 |
| 14 (Jan 10–16) | Light GEPA run on held-out variants, or buffer, or the first extension package (see "Pulling extension work forward") | |
| 15 (Jan 17–23) | Final runs, figures, code freeze | G3: all results in |
| 16 (Jan 24–30) | Buffer | |
| 17–21 (Jan 31–Mar 6) | Writing; full draft to the supervisor by about Feb 20. Background and related work drafted earlier, about one day a week from week 4 | |
| 22 (Mar 7–13) | Corrections, submission, and the handover package (see end) | |

## Coverage of the supervisor roadmap

| Phase | Covered in the thesis | Covered in the extension phase |
|---|---|---|
| P5 Probabilistic/DBN | Stochastic outcomes and observations in the extended IR; canonical DBN view | Duration models; RDDL round-trip (X8, X10) |
| P6 Julia compiler | MDP and POMDP via tables; reference-evaluator equivalence | Generated type-stable generative Julia code; samples/sec benchmark; online solvers; MOMDPs (X1, X3) |
| P7 Temporal/concurrent | — | Active skills, durations, event-driven concurrency, interaction fragments (X10) |
| P8 Learning/revision | Parameter fitting; structure learning on injected dependencies; provisional/committed versions with rollback | Broader structure learning; latent variables; model library (X9) |
| P9 DSPy optimization | Light GEPA on held-out variants (stretch) | Full optimization study; remaining NL modules; fine-tuning (X9) |

## Risks

1. **Unfreezing `skill_ir` and the runtime seams is not approved.** Settle in week 1; fallback is
   the 4-month separate-harness design.
2. **gemma4:e4b cannot write structure.** Known in week 1; a stronger model writes structure and
   the failure is reported as a finding.
3. **Integration overruns (weeks 4–5).** Keep the V1 byte-identical demos as the regression gate;
   if it slips past week 6, take the time from the GEPA week.
4. **BoxPush-PO-lite overruns.** Fallback decided at the end of week 9.
5. **Structure learning yields no clear result.** Report it descriptively; claims 1–3 stand alone.
6. **Less than full-time availability.** Below about 30 hours a week, drop GEPA, then BoxPush.
7. **Writing takes longer than planned.** Mitigated by drafting background and related work from
   week 4.

---

# Extension phase: everything beyond the thesis

Nothing from the research report is dropped. The work below continues the thesis, in dependency
order, and is written so the supervisor (or a follow-on student) can pick up any package from the
handover without re-deriving the design. Estimates are full-time weeks for one person who knows the
codebase; add about 30% for someone new to it.

## Additional libraries and benchmarks the extension brings in

| Library / benchmark | Language | What it is for | Package |
|---|---|---|---|
| BasicPOMCP.jl 0.3.12 | Julia | Online tree search (POMCP) for models too big for SARSOP | X1 |
| ARDESPOT.jl 0.3.8 | Julia | Online DESPOT with MDP-relaxation bounds | X1 |
| POMCPOW.jl 0.3.11, AdaOPS.jl 0.6.1 | Julia | Online solvers for large or continuous observation spaces | X1 |
| ParticleFilters.jl 0.5 / 0.6 | Julia | Particle beliefs for online solvers (version split: ARDESPOT/AdaOPS need 0.5, POMCP/POMCPOW accept 0.6 — separate environments) | X1 |
| POMCGraphSearch.jl 0.2.2 | Julia | Offline finite-state-controller policies (ICAPS 2025) | X1 |
| SARSOP.jl 0.6.0 + MOMDPs.jl 0.1.2 | Julia | Mixed-observability models (positions observed, door/box attributes hidden); SARSOP cross-check | X3 |
| MultiAgentPOMDPs.jl | Julia | `JointMDP` type for joint-action encodings | X4 |
| FactoredValueMCTS.jl | Julia | Factored MCTS for 3–4+ agents with coordination graphs (MMDP relaxation) | X4 |
| FiniteHorizonPOMDPs.jl | Julia | `fixhorizon` wrapper for the finite-horizon UAI07 benchmark | X5 |
| MADP Toolbox (C++) | C++ | Canonical Dec-POMDP benchmark files and exact/approximate Dec-POMDP solvers | X5 |
| *Algorithms for Decision Making* book code | Julia | Dec-POMDP baselines in Julia | X5 |
| pydpomdp | Python | Parses `.dpomdp` files (UAI07 box pushing) into the JSON IR | X5 |
| BoxNet / BoxLift (Chen et al.) | Python | Closest LLM multi-agent benchmark to BoxPush; hidden box weights | X6 |
| MAP-THOR, C-WAH (symbolic mode) | Python | External embodied multi-agent benchmarks with published LLM baselines | X7 |
| MAPPO | Python | Multi-agent RL baseline (return vs environment steps) | X7 |
| pyRDDLGym 2.7 (already pinned) | Python | Independent simulation and validation of exported RDDL | X8 |
| DSPy SIMBA / InferRules, KNNFewShot, BootstrapFinetune / BetterTogether | Python | Advisor rules, model library, weight tuning | X9 |

Rejected on purpose, so the handover does not reopen them: QuickPOMDPs.jl (a fresh type per model
forces re-JIT in optimization loops), PyJulia and the Python `quickpomdps` package (legacy;
juliacall replaces them), MiniGrid's `StochasticActionWrapper` and Gymnasium's `StickyAction`
(break determinism or the Markov property).

## Work packages

| # | Package | Contents | Depends on | Effort | Exit gate |
|---|---|---|---|---|---|
| X1 | **Online solvers and generative Julia model** (P6 remainder) | A fixed, type-stable generative Julia struct parameterized by IR data; benchmark samples/sec against a hand-written simulator; POMCP, DESPOT, POMCPOW/AdaOPS behind `DomainServices.plan`, reseeded per decision with `StableRNG` and iteration budgets; particle-filter beliefs with depletion refill; the optimistic twin as rollout policy and bound | Thesis compiler and bridge | 4 weeks | Online and offline solvers agree on CoopGrid-Jam-PO; DK042 passes with online solvers |
| X2 | **Opt-in Julia CI job** | `julia-actions/setup-julia` with a pinned Manifest; regenerates and verifies the committed tables and alpha-vector policies; matching update to `test_r6_tooling`; default offline job unchanged | Thesis artifacts | 1 week | Artifacts regenerate byte-identically in CI |
| X3 | **Full BoxPush-PO** | Beyond the lite version: lane blockage, push slip, confusable failure labels, pose as a partially observed factor (≈577 states); MOMDP variant via SARSOP.jl/MOMDPs.jl; the six specification gaps as a grading rubric; check that the solved policy rediscovers "heavy is sticky" | BoxPush-PO-lite; X1 for the primitive level | 4 weeks | True-model policy solved; generated model within a set value gap |
| X4 | **Joint-action encoding and agent scaling** (H8) | E2 joint-tuple encoding next to the sequential one; `JointMDP` and FactoredValueMCTS for 3–4 agents; schema-derived coordination graphs vs hand-built ones; makespan vs tractability study | X1, X3 | 4 weeks | Value at N agents vs hand-designed structure, both encodings |
| X5 | **Formal anchor: UAI07 Cooperative Box Pushing** (H1) | Parse the MADP `.dpomdp` file via pydpomdp into the IR; exact table round-trip; reward normalization (the file pays the joint push on state and action); `fixhorizon` plus discount below 1 for SARSOP; MPOMDP values compared against exact Dec-POMDP values from MADP or the book code, always labeled MPOMDP vs Dec-POMDP; obfuscated-name and perturbed-rule variants against recall | Thesis compiler | 3 weeks | Tables round-trip exactly; MPOMDP value ≥ published Dec-POMDP V* |
| X6 | **LLM-planner anchor: BoxNet / BoxLift** (H4) | Port BoxLift into the Domain Kit; re-implement ReAct and a LLaMAR-style loop on the same local model; Chen et al.'s central and hybrid planners as quoted baselines; LLM calls and tokens per episode at matched success | X1 | 3–4 weeks | Paired-seed comparison with confidence intervals |
| X7 | **External anchor and RL baseline** | MAP-THOR or C-WAH symbolic mode; MAPPO trained on CoopGrid-Jam-PO and BoxPush-PO, reported as return vs environment steps | X6 | 5–6 weeks | Results on at least one external benchmark |
| X8 | **RDDL export/import** | Compiler exports RDDL with observation fluents; pyRDDLGym simulates it as an independent check; machine-validate the existing BoxPush RDDL | Thesis IR | 2 weeks | Simulated RDDL matches the IR's reference evaluator |
| X9 | **Full learning study** (P8–P9) | Full GEPA study with the cascaded metric (150–400 metric calls, 8–20 validation variants); per-module typed signatures for the remaining NL modules; SIMBA/InferRules for the advisor; KNNFewShot model library; broader structure learning and latent variables; fine-tuning (BootstrapFinetune / BetterTogether / external DPO) only after prompt-level gains plateau | Thesis generator and fitter | 6–8 weeks | Held-out gains over zero-shot and BootstrapFewShot on unseen variants and agent counts |
| X10 | **Temporal and concurrent execution** (P7) | Duration models; active skills; event-driven concurrency; interaction fragments for correlated joint effects | X1, X4 | 6–8 weeks | Supervisor P7 acceptance criteria |
| X11 | **Remaining hypotheses and pre-registered evaluation** | H3 (twin as bound/rollout), H5 (belief calibration vs textual and CoBel-World-style beliefs), H7 (halting with evidence under model mismatch), H8 (from X4); pre-register metrics, seeds and stopping rules; 30–100 paired seeds per condition | Relevant packages above | 3–4 weeks | Paired-seed results with confidence intervals for H1–H8 |

Total: about 40–48 full-time weeks, consistent with the 12–18 month estimate for the full plan
minus the thesis.

## Suggested order

1. **X2, X5** — cheap, and they strengthen the thesis claims directly (reproducible artifacts; exact
   recovery of a published benchmark).
2. **X1, X8** — finish P5–P6.
3. **X3, X6** — the flagship domain and the closest LLM baseline.
4. **X4, X9, X11** — scaling, full learning study, full evaluation.
5. **X7, X10** — the largest packages; P7 last, as in the supervisor's roadmap.

## Pulling extension work forward

If the thesis runs ahead of schedule, pull packages into the buffer weeks (14 and 16) in this order:
X2 (1 week), the table round-trip half of X5 (1 week), then X8. Never let extension work delay G3
(week 15) or the writing block.

## Handover package for the supervisor (week 22)

- The repo on a tagged commit, with V1 demos byte-identical and all thesis tests green.
- The pinned toolchain: exact Julia version with committed Manifest, `dspy==3.4.0`,
  `gepa==0.1.4`, the Ollama model digest, and this machine's WSL/Windows setup notes
  (`claude/windows-dev-setup.md`).
- Committed artifacts: compiled tables, alpha-vector policies, saved DSPy programs with dataset
  hashes, recorded-LM fixtures.
- A status table for X1–X11: not started / in progress (with branch name) / done, plus the open
  decisions each package needs.
- This document and `claude/pomdp-julia-dspy-plan.md` as the design reference.
