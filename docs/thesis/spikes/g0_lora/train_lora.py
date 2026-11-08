"""QLoRA fine-tuning of google/gemma-4-e4b-it on data/train.jsonl (Route B). Loss on the assistant
turn only. Runs in ~/.venvs/maaos-ft on the local GPU.

    ~/.venvs/maaos-ft/bin/python train_lora.py --out adapters/r16 --epochs 2
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from torch.utils.checkpoint import checkpoint
from transformers import Trainer, TrainingArguments, set_seed

import common

HERE = pathlib.Path(__file__).resolve().parent
TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"


class ChatData(torch.utils.data.Dataset):
    def __init__(self, path, tok, max_len):
        self.rows, skipped = [], 0
        for line in open(path):
            msgs = json.loads(line)["messages"]
            user, assistant = msgs[0]["content"], msgs[1]["content"]
            p_ids = tok(common.prompt_text(tok, user), add_special_tokens=False)["input_ids"]
            f_text = common.full_text(tok, user, assistant)
            f_ids = tok(f_text, add_special_tokens=False)["input_ids"]
            if f_ids[: len(p_ids)] != p_ids:
                raise SystemExit("chat template: the prompt is not a prefix of the full conversation")
            if len(f_ids) > max_len:
                skipped += 1
                continue
            labels = [-100] * len(p_ids) + f_ids[len(p_ids):]
            self.rows.append((f_ids, labels))
        self.skipped = skipped

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        ids, labels = self.rows[i]
        return {"input_ids": ids, "labels": labels}


def collate(batch, pad_id):
    n = max(len(b["input_ids"]) for b in batch)
    ids = torch.full((len(batch), n), pad_id)
    lab = torch.full((len(batch), n), -100)
    att = torch.zeros((len(batch), n), dtype=torch.long)
    for i, b in enumerate(batch):
        k = len(b["input_ids"])
        ids[i, :k] = torch.tensor(b["input_ids"])
        lab[i, :k] = torch.tensor(b["labels"])
        att[i, :k] = 1
    return {"input_ids": ids, "labels": lab, "attention_mask": att}


SOFTCAP = 30.0   # Gemma 4 text_config.final_logit_softcapping, applied exactly as in its forward()
CHUNK = 512


class AnswerOnlyTrainer(Trainer):
    """Cross-entropy on the assistant tokens only, computed chunk by chunk from the final hidden
    states, so the 262k-word logits never exist for the whole sequence at once."""

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs["labels"]
        base = model.get_base_model()
        h = base.model(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"],
                       use_cache=False).last_hidden_state
        h, y = h[:, :-1], labels[:, 1:]
        keep = y != -100
        h, y = h[keep], y[keep]

        def ce(hc, yc):
            logits = base.lm_head(hc).float()
            logits = torch.tanh(logits / SOFTCAP) * SOFTCAP
            return F.cross_entropy(logits, yc, reduction="sum")

        total = sum(checkpoint(ce, h[i:i + CHUNK], y[i:i + CHUNK], use_reentrant=False)
                    for i in range(0, y.numel(), CHUNK))
        return total / y.numel()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="adapters/r16")
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=-1, help="for smoke tests")
    a = ap.parse_args()
    set_seed(a.seed)
    tok, model = common.load(table_in_ram=True)
    data = ChatData(HERE / "data" / "train.jsonl", tok, a.max_len)
    print(f"train examples {len(data)} (skipped over {a.max_len} tokens: {data.skipped})", flush=True)
    for p in model.parameters():          # frozen base, kept in bf16 (no fp32 upcast: RAM is 15 GB)
        p.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05,
                                             target_modules=TARGETS, task_type="CAUSAL_LM"))
    model.print_trainable_parameters()
    out = HERE / a.out
    args = TrainingArguments(output_dir=str(out), per_device_train_batch_size=1, gradient_accumulation_steps=8,
                             num_train_epochs=a.epochs, learning_rate=a.lr, lr_scheduler_type="cosine",
                             warmup_steps=4, logging_steps=1 if a.max_steps > 0 else 5, save_strategy="no", bf16=True,
                             gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
                             report_to=[], seed=a.seed, remove_unused_columns=False, max_steps=a.max_steps)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    trainer = AnswerOnlyTrainer(model=model, args=args, train_dataset=data, data_collator=lambda b: collate(b, pad))
    t0 = time.time()
    trainer.train()
    model.save_pretrained(str(out))
    log = {"args": vars(a), "examples": len(data), "skipped": data.skipped, "seconds": round(time.time() - t0, 1),
           "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2), "history": trainer.state.log_history}
    (out / "train_log.json").write_text(json.dumps(log, indent=1) + "\n")
    print("saved", out, "in", log["seconds"], "s", flush=True)


if __name__ == "__main__":
    main()
