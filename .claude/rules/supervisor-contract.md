# Supervisor Contract and Refactor Authority

Use three different authorities for three different questions.

## 1. Realized backend behavior

The existing authoritative BoxPush environment/backend establishes what
physical execution actually does.

Do not invent or rewrite physical semantics during a behavior-preserving
refactor.

## 2. Frozen P0-P4 V1 semantics

These documents define the accepted Symbolic-Twin V1 semantic contract:

- `docs/decisions/P0_V1_DECISIONS.md`
- `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`

The completed P0-P4 implementation and its acceptance evidence are regression
targets.

## 3. Current R0-R6 architecture objective

This document defines the current architectural refactor:

- `docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

It may change internal dependency structure, composition roots, contracts,
policy/comparator/provider injection, and lifecycle organization while
preserving frozen V1 behavior.

It does not authorize speculative future semantics.

## Conflict handling

If an R0-R6 architectural instruction can be satisfied with an adapter while
preserving frozen V1 semantics, prefer the adapter.

If satisfying the clean boundary would materially require changing a frozen V1
decision, public compatibility contract, execution semantics, or trace format,
stop and explain the conflict before changing it.

When code/specification still does not determine a semantic value, mark it
unresolved rather than guessing.
