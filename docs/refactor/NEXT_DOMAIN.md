# Next-domain assumptions (R4/R5 inputs)

The supervisor report's Phase 4 (explicit domain composition) and Phase 5
(substitutability probe) defaults depend on what the next real domain looks
like. Status history:

- 2026-09-04 (project owner): all fields `Unknown`; no next real domain specified.
- 2026-09-19: the domain kit (DK0-DK5, `docs/decisions/DK1_DOMAIN_PACKAGE.md`) made
  adding a domain a first-class workflow (`docs/domains/ADDING_A_DOMAIN.md`) by extracting
  mechanisms both BoxPush and the R5 probe already implemented; it adds no semantics and
  assumes classical, deterministic, fully observable, sequential domains.
- **2026-11-07 (project owner, supervisor-approved): the real next domain is chosen.** The
  thesis POMDP extension (`docs/thesis/pomdp-plan-time-estimate.md`,
  `docs/thesis/pomdp-julia-dspy-plan.md`, decisions in `docs/thesis/HANDOFF.md`) names two
  partially observable domains, built as **new** domain packages:
  1. `cooperative_grid_po` (CoopGrid-Jam-PO): the door jam is sampled from a prior and hidden,
     the joint pull may slip, the shake frees the jam with some probability and returns a noisy
     rattle reading. Built first, as the wiring test.
  2. `box_push_po_lite` (BoxPush-PO-lite): hidden box weights. The main experiment.

  `domains/box_push` (V1) and `domains/cooperative_grid` stay frozen; the V1 demos and
  acceptance traces remain the byte-identical regression gate.

| Field | Question | Answer (2026-11-07) |
|---|---|---|
| Observability | Fully observable like BoxPush V1, or partial observation? | **Partial.** A hidden door jam (CoopGrid-Jam-PO), later hidden box weights (BoxPush-PO-lite). Hidden variables are held in a belief; the authoritative backend keeps the truth and the planner never reads it. |
| State representation | Typed immutable symbolic state like BoxPush, or something else (relational, continuous, hybrid)? | **Typed immutable symbolic state like BoxPush**, plus hidden factored variables (finite domains) whose values live only in the backend and in a belief distribution. |
| Action model | Grounded discrete skills with typed parameters, or a different action shape (durative, parameterized-continuous)? | **Grounded discrete skills with typed parameters.** One sequential executive call per cycle (the E1 encoding). Skills gain named outcomes with probabilities and per-outcome observations. No durations. |
| Concurrency | Sequential executive like V1, or concurrent/asynchronous track or agent execution? | **Sequential skills, as in V1.** A joint skill still coordinates several agents inside one call. Joint per-agent action tuples (E2) only with the supervisor's P7 concurrency phase. |
| Uncertainty | Deterministic transitions, or stochastic/probabilistic outcomes needing calibrated uncertainty? | **Stochastic outcomes and noisy observations.** Probabilities are named parameters: the LLM proposes structure, a fitter estimates numbers from backend logs; the compiled model is solved offline (NativeSARSOP) and replayed in pure Python by default tests. |

Consequences: the deferred "STRIPS/IR generalization" item from the domain-kit record is
now owner-scheduled (program record `docs/thesis/THESIS_IMPLEMENTATION.md`); the probabilistic
extension is scoped by the thesis exception in `.claude/rules/v1-scope.md`. Contracts are
extended from these two domains' concrete requirements and tests, not in anticipation of
others.

R0-R6 is complete (2026-09-05); the next domain validates the extracted
contracts rather than shaping a refactor phase. Record further changes here
with the date.
