"""Shared model loading for Route B (runs in the separate ~/.venvs/maaos-ft environment)."""
from __future__ import annotations

import torch
from torch import nn
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

BASE = "google/gemma-4-e4b-it"
BNB = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                         bnb_4bit_compute_dtype=torch.bfloat16)


class CPULookup(nn.Module):
    """Gemma 4's per-layer embedding table is 5.6 GB in bf16 and is only ever read a few rows per
    token. For training it stays in system RAM and only the looked-up rows go to the GPU. The table is
    deliberately not a registered submodule, so no device move or adapter save ever touches it."""

    def __init__(self, inner: nn.Module) -> None:
        super().__init__()
        self.__dict__["inner"] = inner.to("cpu")

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        return self.inner(input_ids.to("cpu")).to(input_ids.device)


def load(base: str = BASE, adapter: str | None = None, table_in_ram: bool = False):
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(base, quantization_config=BNB, device_map={"": 0},
                                                 dtype=torch.bfloat16, low_cpu_mem_usage=True)
    if table_in_ram:
        lm = model.model.language_model
        lm.embed_tokens_per_layer = CPULookup(lm.embed_tokens_per_layer)
        torch.cuda.empty_cache()
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    return tok, model


def prompt_text(tok, user: str) -> str:
    return tok.apply_chat_template([{"role": "user", "content": user}], tokenize=False,
                                   add_generation_prompt=True, enable_thinking=False)


def full_text(tok, user: str, assistant: str) -> str:
    return tok.apply_chat_template([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}],
                                   tokenize=False, enable_thinking=False)
