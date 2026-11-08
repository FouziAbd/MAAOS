# G0 DSPy study — Route A: prompt optimization, no weight change

Thesis phase T2b. Spike code, **opt-in only** (`MAAOS_LIVE_LM=1`, a running local ollama with
`gemma4:e4b`); nothing here runs in the offline suite. It builds on the T2 spike in
`../g0_structure/` (description, format rules, validator, 12-point rubric, true model). Results
and the verdict are recorded in `docs/thesis/THESIS_IMPLEMENTATION.md`.

Question: how far does DSPy optimization of the prompt alone carry the small local model toward
writing CoopGrid-Jam-PO's model structure? Route B (LoRA fine-tuning on the local GPU) is decided
after these results.

| File | Role |
|---|---|
| `corpus.py` | Builds `corpus.json`: 40 description/true-model pairs from five domain families (a device with a hidden fault, a container with a stuck lid, rooms behind a possibly locked door with one or two agents, two agents lifting a possibly heavy crate, a network node that may be hung), eight variants each. Every model passes the T1 validator. 30 train, 10 validation (two per family). **CoopGrid-Jam-PO is not in it**: it is the test domain only. |
| `metric.py` | `compare(gold, reply)`: score in [0, 1] (40% validity against the T1 rules, 60% name-agnostic structural agreement with the gold model) and written feedback for GEPA. |
| `program.py` | `ModelStructureGenerator`, a one-predictor DSPy module whose instructions are the T2 format rules (no worked example; examples are what the optimizers pick); the local LM settings. |
| `run_ladder.py` | The optimizer ladder: `zero_shot`, `fewshot_1`, `fewshot_3` (labelled examples, round-robin over families), `bootstrap` (BootstrapFewShot, demos the model itself wrote that scored >= 0.9), `gepa` (reflective instruction search from `fewshot_3`, gemma4:e4b also as the reflection model). Each rung is scored on the 10 validation pairs and on 10 seeded test runs of CoopGrid-Jam-PO (also with the T2 rubric). |
| `results/` | Per rung: `<rung>.json` (summary, every reply, scores, feedback) and `<rung>.program.json` (the compiled DSPy program). |

Run:

```bash
cd docs/thesis/spikes/g0_dspy
python corpus.py
MAAOS_LIVE_LM=1 python run_ladder.py --rungs zero_shot fewshot_1 fewshot_3 bootstrap
MAAOS_LIVE_LM=1 python run_ladder.py --rungs gepa --gepa-calls 100
```

Settings: temperature 0.7 (as in T2), context 32768, at most 8192 output tokens, seed 1 for
validation items and seeds 1-10 for the test runs, LM cache off.

## Results (2026-11-07, gemma4:e4b)

Strict scores are the headline. "Repaired" re-parses each stored reply with `json_repair` first
(`python rescore.py`); it shows the structure the model got right behind its JSON syntax slips and
is never counted as a valid model.

| rung | val metric | val valid | test metric | test rubric /12 (best) | test valid | val metric, repaired | val valid, repaired | test rubric, repaired (best) | test valid, repaired |
|---|---|---|---|---|---|---|---|---|---|
| zero_shot | 0.30 | 0/10 | 0.24 | 2.5 (6) | 0/10 | 0.36 | 0/10 | 3.3 (6) | 0/10 |
| fewshot_1 | 0.00 | 0/10 | 0.19 | 2.1 (6) | 0/10 | 0.15 | 0/10 | 2.7 (6) | 0/10 |
| fewshot_3 | 0.07 | 0/10 | 0.00 | 0.0 (0) | 0/10 | 0.54 | 1/10 | 4.2 (11) | 0/10 |
| bootstrap | 0.00 | 0/10 | 0.00 | 0.0 (0) | 0/10 | 0.44 | 0/10 | 3.5 (8) | 0/10 |
| gepa | 0.31 | 1/10 | 0.00 | 0.0 (0) | 0/10 | 0.78 | 2/10 | 3.7 (9) | 0/10 |

GEPA: 100 metric calls, 10 proposed instructions, gemma4:e4b as its own reflection model; its
validation score never rose above the starting program's (0.58 on its repair-aware metric), so
the gepa row's difference from fewshot_3 is within run-to-run noise (one sample per item).
