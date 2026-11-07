# G0 spike — can a language model write CoopGrid-Jam-PO's model structure?

Thesis phase T2 (week 1, gate G0). Spike code, **opt-in only**: nothing here is run by the
offline suite, and the runner refuses to start without `MAAOS_LIVE_LM=1`. Results and the
verdict are recorded in `docs/thesis/THESIS_IMPLEMENTATION.md`.

| File | Role |
|---|---|
| `description.md` | The sole-input natural-language description (probabilities withheld; rewards stated). Uses the call vocabulary of the T1 ADR. |
| `prompt.md` | The generation prompt: the format rules of the T1 IR, one worked example, the description. |
| `example_lamp.json` | The in-context example: a different domain (a lamp with a hidden fault and a noisy inspection). |
| `coopgrid_jam_po_true.json` | The hand-written true model from the T1 ADR, with the design's true parameter values. Never shown to the model. |
| `validate.py` | Standalone checker of the T1 IR construction rules (a spike prototype, not the T3 implementation). |
| `score.py` | Name-agnostic 12-point structural rubric; the true model (values stripped) must score 12/12. |
| `run_spike.py` | Calls the local ollama once per model and seed; saves raw replies and timings under `results/`. |
| `results/` | Raw replies (`*.txt`), call metadata (`*.meta.json`) and `summary.json`. |

Run (seeds 1-10, temperature 0.7, ollama JSON mode; a `-cloud` model sends the prompt to Ollama's
cloud service):

```bash
cd docs/thesis/spikes/g0_structure
MAAOS_LIVE_LM=1 python run_spike.py --models gemma3:27b-cloud gemma4:e4b --seeds 10
python score.py results
```

The 12 checks: JSON parses; valid against the T1 rules; exact skill vocabulary; exactly one
hidden variable; its prior is a parameter; the pull is stochastic and depends on the hidden
variable; the shake can clear the hidden variable with a parameterised probability; the rattle is
a noisy observation of the hidden variable; no probability values written; rewards and discount
transcribed exactly; the two corridor refusals modelled; the goal names both agents.
