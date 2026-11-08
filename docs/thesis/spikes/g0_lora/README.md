# G0 Route B — LoRA fine-tuning of the gemma4:e4b base checkpoint

Thesis phase T2c (owner decision after Route A, 2026-11-08). Spike code, opt-in only; nothing here
runs in the offline suite. Route A (`../g0_dspy/`) showed that prompt optimization alone gives no
valid CoopGrid-Jam-PO model, with JSON well-formedness as the blocker. Route B trains a small LoRA
add-on so that writing the T1 IR becomes the model's habit, then measures it on the same test.

- Base: `google/gemma-4-e4b-it` (Apache-2.0, not gated), the checkpoint behind ollama's
  `gemma4:e4b` (same architecture, 8.0B raw parameters, hidden size 2560, 131072 context; ollama
  serves it as Q4_K_M).
- Runtime: a separate virtual environment `~/.venvs/maaos-ft` (CUDA 12.8 PyTorch for the RTX 5070 Ti,
  transformers, peft, trl, bitsandbytes, accelerate), so the project's pinned environment is untouched.
  The model is loaded 4-bit (nf4) for both training and evaluation; the base model is evaluated in
  the same runtime as the control, so the comparison isolates the fine-tuning.

| File | Role |
|---|---|
| `make_data.py` | Expands the five T2b families to 277 training examples (chat format: the T2 format rules plus the description, answered by the gold model as indented JSON). Drops any variant that shares a name with a validation item (47 dropped). CoopGrid-Jam-PO is in no file. |
| `data/` | `train.jsonl`, `val.jsonl` (the 10 T2b validation items), `stats.json`. |
| `common.py` | Loading the 4-bit base (optionally with an adapter) and the chat template. |
| `train_lora.py` | QLoRA training, loss on the assistant turn only (rank 16, alpha 32, attention and MLP projections of the language model, 2 epochs, lr 2e-4, batch 1 x 8 accumulation). |
| `generate_eval.py` | Generates on the 10 validation items (seed 1) and 10 seeded test runs (temperature 0.7, top-p 0.95, top-k 64), scored strictly and after `json_repair` with the Route A metric and the T2 rubric. |
| `results/` | One JSON per condition with every reply and score. |

Run (from this directory):

```bash
python3 -m venv ~/.venvs/maaos-ft
~/.venvs/maaos-ft/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128
~/.venvs/maaos-ft/bin/pip install transformers peft trl bitsandbytes accelerate datasets json_repair huggingface_hub
python3 make_data.py
~/.venvs/maaos-ft/bin/python generate_eval.py --name base
~/.venvs/maaos-ft/bin/python train_lora.py --out adapters/r16
~/.venvs/maaos-ft/bin/python generate_eval.py --name lora_r16 --adapter adapters/r16
```

The Hugging Face token is read from `~/.cache/huggingface/token`; it is never stored in the repository.

## Results (2026-11-08)

`python3 summarize.py` (base = the untrained checkpoint in the same runtime):

| condition | val valid | test rubric /12 (best) | test valid | seconds per reply |
|---|---|---|---|---|
| base | 0/10 | 3.6 (4) | 0/10 | 86 |
| lora_r16 | 9/10 | 9.8 (11) | 0/10 | 204 |

Fine-tuning fixed JSON well-formedness completely and brought the unseen test domain's structure
close to correct, but every test model still has 1-6 rule errors (most often an undeclared `door`
constant in the hidden prior). Details: `docs/thesis/THESIS_IMPLEMENTATION.md`, Phase T2c.
