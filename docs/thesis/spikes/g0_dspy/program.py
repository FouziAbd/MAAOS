"""The DSPy generator for the G0 study (spike code, opt-in, needs a local ollama).

`ModelStructureGenerator` maps a plain-language domain description to the T1 skill-IR JSON. Its
instructions are the format rules of the T2 prompt (`../g0_structure/prompt.md`), without the
worked example: worked examples are what the optimizers choose.
"""
from __future__ import annotations

import pathlib

import dspy
from dspy.utils.exceptions import AdapterParseError

HERE = pathlib.Path(__file__).resolve().parent
_PROMPT = (HERE.parent / "g0_structure" / "prompt.md").read_text()
RULES = _PROMPT[: _PROMPT.index("EXAMPLE (a different domain)")].strip()


class WriteModel(dspy.Signature):
    __doc__ = RULES

    description: str = dspy.InputField(desc="the environment description, the sole input")
    model_json: str = dspy.OutputField(
        desc='one JSON object {"domain": {...}, "problem": {...}} in the MAAOS skill-IR format, nothing else')


class ModelStructureGenerator(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.write = dspy.Predict(WriteModel)

    def forward(self, description: str) -> dspy.Prediction:
        # A reply without DSPy's field markers is still the model's answer: keep its raw text so the
        # metric (and GEPA's feedback) sees what the model wrote instead of a bare parse failure.
        try:
            return self.write(description=description)
        except AdapterParseError as e:
            return dspy.Prediction(model_json=e.lm_response or "")


def local_lm(model: str = "gemma4:e4b", temperature: float = 0.7) -> dspy.LM:
    return dspy.LM(f"ollama_chat/{model}", api_base="http://localhost:11434", api_key="",
                   temperature=temperature, max_tokens=8192, num_ctx=32768, cache=False)


class TextLM(dspy.LM):
    """dspy.LM whose call returns plain strings. Through ollama, gemma4:e4b replies come back as
    {"text": ..., "reasoning_content": ...} dicts, which GEPA's instruction proposer cannot strip."""

    def __call__(self, *args, **kwargs):
        outs = super().__call__(*args, **kwargs)
        return [o.get("text", "") if isinstance(o, dict) else o for o in outs]


def reflection_lm(model: str = "gemma4:e4b") -> dspy.LM:
    return TextLM(f"ollama_chat/{model}", api_base="http://localhost:11434", api_key="",
                  temperature=1.0, max_tokens=8192, num_ctx=32768, cache=False)
