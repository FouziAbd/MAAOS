# Handoff: thesis plan docs for Claude Code

Written 2026-10-31 in claude.ai (Project "MAAOS") for Claude Code working in this repo.
This branch adds the thesis planning docs. **Nothing here changes code.** Read this file
first, then do the tasks at the end.

## Files on this branch

| File | What it is |
|---|---|
| `docs/thesis/pomdp-plan-time-estimate.md` | The thesis plan: 22 weeks (submission ~2027-03-13), four claims, schedule, risks, plus an extension phase (X1–X11) |
| `docs/thesis/pomdp-julia-dspy-plan.md` | The full research design the plan is based on (long; read sections on demand) |
| `docs/thesis/HANDOFF.md` | This file |

The supervisor's spec is already in the repo:
`docs/supervisor/Symbolic_Twin_BoxPush_Implementation_Plan_Self_Contained_v5.docx`.

## Decisions already made (do not reopen without the user)

1. **Align with the supervisor's spec (v5).** The thesis covers slices of P5, P6, P8 and P9.
   P7 (durations, active skills, event-driven concurrency) is future work.
2. **Extend the existing skill IR, not a new schema.** `shared/skill_ir.py` gains named outcomes
   with probability expressions, per-outcome observations and named parameters. Every V1 domain
   must load unchanged as the single-outcome case.
3. **Canonical DBN view** derived from the IR (parent sets) for validation and fitting.
   RDDL round-trip is future work.
4. **MDP first, then POMDP.** Compile the IR to tables (`SparseTabularPOMDP`); NativeSARSOP in a
   persistent Julia session (juliacall); Python does belief updates and alpha-vector action
   selection; default tests replay saved policies with no Julia. A slow Python reference
   evaluator checks the compiled tables.
5. **Inside the real executive loop, not a separate harness** — for the new domains only:
   planner behind `DomainServices.plan`, belief in a `SymbolicTrack`, optional `observe()` path,
   monitor raises a typed discrepancy on zero/low-likelihood observations, belief-aware failure
   policy instead of the three-strike halt. **V1 demos and traces must stay byte-identical.**
6. **LLM proposes, statistics decides.** The LLM writes structure; a fitter writes numbers;
   repairs are typed patches, provisional until held-out likelihood improves, with rollback.
   DSPy repair module is named `ModelHypothesisGenerator`.
7. **Centralized planner.** One executive sees all agents' observations (an MPOMDP). No
   inter-agent communication is modeled. Sequential executive calls (the V1 rule), not
   joint-action tuples. Label results as MPOMDP, not Dec-POMDP.
8. **Domains:** CoopGrid-Jam-PO first (2–3 week wiring test: hidden jam, pull slip, noisy rattle),
   then BoxPush-PO-lite (hidden box weights) as the main experiment, in **new packages** — the V1
   BoxPush package stays frozen. Fallback: CoopGrid variants.

## Status of approvals

Pending the supervisor's sign-off (email sent ~2026-10-11):
- scope and the 5-month timeline;
- unfreezing `skill_ir` and adding runtime seams for the new domains;
- recording the PO domains as the "real next domain" in `docs/refactor/NEXT_DOMAIN.md`;
- using a stronger hosted LLM if gemma4:e4b cannot write model structure.

**Until the user confirms approval, current project rules still apply:** `CLAUDE.md` and
`.claude/rules/v1-scope.md` forbid probabilistic semantics and Julia compilation. Do not start
POMDP implementation work before that.

## Tasks for Claude Code now

1. Add this short section to `CLAUDE.md` (a pointer only — do not `@`-import the docs):

   ```
   ## Thesis work (POMDP extension) — planning docs
   Plan: docs/thesis/pomdp-plan-time-estimate.md
   Design: docs/thesis/pomdp-julia-dspy-plan.md
   Decisions and approval status: docs/thesis/HANDOFF.md
   Read these before any thesis task. V1 scope rules still apply until the user
   confirms the supervisor's approval.
   ```
2. Check that any test that pins `CLAUDE.md` content or scans for forbidden strings
   (e.g. `tests/test_r6_tooling.py`) still passes, and run the offline suite.
3. Commit on this branch and summarize the change for the user. Do not merge.

## Later, once the user says the supervisor approved

- Update `docs/refactor/NEXT_DOMAIN.md` (Observability = partial, Uncertainty = stochastic,
  Concurrency = sequential skills) and relax `.claude/rules/v1-scope.md` for the new domains only.
- Start week 1–3 work from the schedule in `pomdp-plan-time-estimate.md`.
