# Supervisor Contract and Refactor Authority

Use three different authorities for three different questions.

## 1. Realized backend behavior

The existing authoritative BoxPush environment/backend establishes what
physical execution actually does.

Do not invent or rewrite physical semantics during maintenance or any
behavior-preserving change.

## 2. Frozen P0-P4 V1 semantics

These documents define the accepted Symbolic-Twin V1 semantic contract:

- `docs/decisions/P0_V1_DECISIONS.md`
- `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`

The completed P0-P4 implementation and its acceptance evidence are regression
targets.

## 3. Completed R0-R6 architecture (authority and history)

This document is the architectural specification that the completed R0-R6
refactor (audited PASS, 2026-09-05) was implemented against:

- `docs/supervisor/MAAOS_code_review_and_refactoring_report.md`

It remains the architectural authority for the supported runtime. The
refactor changed internal dependency structure, composition roots, contracts,
policy/comparator/provider injection, and lifecycle organization while
preserving frozen V1 behavior; the record of what was actually done is in
`docs/refactor/REFACTORING_IMPLEMENTATION.md`.

It does not authorize speculative future semantics, and it is not a mandate
for further ongoing refactoring.

Future maintenance must preserve both the frozen V1 semantics (authority 2)
and the completed R0-R6 architecture (this authority) unless the project owner
explicitly changes one of them.

## Conflict handling

If an R0-R6 architectural requirement (including one reopened for a
regression fix) can be satisfied with an adapter while preserving frozen V1
semantics, prefer the adapter.

If satisfying the clean boundary would materially require changing a frozen V1
decision, public compatibility contract, execution semantics, or trace format,
stop and explain the conflict before changing it.

When code/specification still does not determine a semantic value, mark it
unresolved rather than guessing.
