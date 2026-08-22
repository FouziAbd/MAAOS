# MAAOS — Symbolic-Twin BoxPush V1

A multi-agent executive architecture where a **deliberately optimistic symbolic planner** and
an **LLM reasoning track** run as peers over an authoritative grid-world backend — and their
disagreements are the point. The symbolic model plans without geometry; the backend refuses
what physics forbids; every refusal surfaces as a typed `ExecutionDiscrepancy` routed through
an orchestrator that decides — per policy — whether to halt with evidence or recover on the
LLM's advice. Nothing is ever silently patched to make a plan work.

**Status: P0-P4 complete** — five tagged baselines (`p0-v1-freeze` … `p4-v1-orchestrator`),
closed by a three-auditor hostile final audit at 0 FAIL. The full record:
[`docs/implementation/P0_P4_IMPLEMENTATION.md`](docs/implementation/P0_P4_IMPLEMENTATION.md).

## Watch it run

```bash
cd functional_layer/custom_env/box_push/env
python box_push_v1_run.py                             # pygame window, no LLM needed
python box_push_v1_run.py --policy symbolic_primary   # watch the designed halt instead
python box_push_v1_run.py --nl live                   # live DSPy proposals every cycle (local Ollama)
```

The demo episode is the architecture's thesis: the optimistic 5-step plan executes, the final
`Push` fails three times in the backend (the symbolic model can't see the reason — by design),
and then the two policies split. `SYMBOLIC_PRIMARY` halts with the discrepancy history rather
than strengthening the model; `ADVISORY_TWO_TRACK` asks the NL track, whose re-establishment
advice — executed through the same validation gates as any call — completes the task. With
`--nl live`, the pinned local model (`gemma4:e4b` via DSPy) proposes a skill every cycle and
each proposal is recorded as typed evidence (`agrees` / `contradiction` / confidence) beside
the symbolic decision.

## Architecture

```
shared/     frozen typed contracts (P0): skills, IR, StateSnapshot, results, channels, traces
domain/     the frozen BoxPush V1 instance (DOMAIN_IR, projection, tasks, golden keys)
symbolic/   applicability (literal membership ONLY), BFS planner, monitor-side predictor,
            dual-basis monitor, exact-state belief (P2)
nl/         the LLM peer track behind an offline seam: parser, interpreters, selector,
            one-attempt repair, translator with residual, recovery proposer (P3)
runtime/    policy-free executor, track comparator, pure orchestrator, executive loop (P4)
functional_layer/custom_env/box_push/env/box_push_v1_adapter.py
            the P1 adapter: V1Environment over the authoritative backend
```

Boundaries are enforced, not conventional: fail-closed import guards (backend, dspy, and
`runtime` unreachable from the reasoning tracks; predictor unreachable from planning), typed
constructors that refuse illegal states, and three evidence channels with exactly one producer
each (`ExecutionDiscrepancy` / `TrackDivergence` / `InfrastructureFault`).

## Tests and evidence

```bash
python -B -m unittest discover -s tests -t .    # 632 tests, offline, deterministic, ~0.5s
```

- 285 checked-in mutation-harness mutants across five harnesses, all killed
  (`docs/implementation/p{0..4}_mutation_harness.py`).
- Mechanical pins: the documented suite count equals live discovery; a tree-wide
  citation-drift guard; byte-pinned human-readable acceptance traces
  ([`docs/implementation/acceptance_traces.md`](docs/implementation/acceptance_traces.md)).
- Live-LLM integration is opt-in only: `MAAOS_LIVE_LM=1 python -B -m unittest tests.test_p3_live_lm`.

## Documentation

| Document | Content |
|---|---|
| [`docs/implementation/P0_P4_IMPLEMENTATION.md`](docs/implementation/P0_P4_IMPLEMENTATION.md) | The 21-section implementation record (claims-audited) |
| [`docs/decisions/P0_V1_DECISIONS.md`](docs/decisions/P0_V1_DECISIONS.md) | The 16 frozen V1 decisions + deferral registers |
| [`docs/handoff/section18.md`](docs/handoff/section18.md) | The semantic handoff + the full process narrative (revisions 21a-21n) |
| [`docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`](docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md) | The authoritative milestone specification |

## Legacy code

`middleware_layer/`, `model_layer/agent.py`, the KAZ/CST environments, and the original
LLM-driven runner (`box_push_centralized.py`) predate V1 and are preserved as reference —
the legacy runner's silent-fallback patterns are exactly what the V1 typed contracts forbid,
and the partial-observability belief machinery is capital for post-V1 milestones (its known
defects are recorded in section18 before any revival).

Python 3.12, Linux/WSL2; dependencies pinned exactly in `requirements.txt`.
