"""Training data for Route B (LoRA fine-tuning of gemma4:e4b's base checkpoint). Spike code.

Expands the five T2b corpus families with more names and option combinations, then writes chat
examples: the user turn is the T2 format rules plus the description (no worked example), the
assistant turn is the gold model as indented JSON. Leakage guards:
  - the T2b validation items, and every entity name they use, are excluded from training;
  - CoopGrid-Jam-PO (the test domain) is in no file here.

    python make_data.py     # writes data/train.jsonl, data/val.jsonl and data/stats.json
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "g0_dspy"))
import corpus as C  # noqa: E402  (the T2b families and the T1 validator)

PROMPT = (HERE.parent / "g0_structure" / "prompt.md").read_text()
RULES = PROMPT[: PROMPT.index("EXAMPLE (a different domain)")].strip()


def user_turn(description: str) -> str:
    return f"{RULES}\n\nENVIRONMENT DESCRIPTION\n{description}"


def chat(item) -> dict:
    return {"id": item["id"], "family": item["family"],
            "messages": [{"role": "user", "content": user_turn(item["description"])},
                         {"role": "assistant", "content": json.dumps(item["model"], indent=1)}]}


def extended():
    items = []
    devs = ["lamp", "pump", "fan", "heater", "printer", "radio", "valve", "kettle", "motor", "boiler",
            "dryer", "router", "speaker", "compressor", "projector", "scanner", "freezer", "blender"]
    for i, (dev, (ins, rep)) in enumerate(itertools.product(devs, itertools.product([True, False], repeat=2))):
        items.append(C.f1_device(i, dev, ins, rep))
    boxes = ["chest", "crate_box", "jar", "trunk", "locker", "safe", "drawer", "tin", "cooler", "hatch",
             "casket", "bin", "vault_box", "caddy", "canister", "cupboard", "toolbox", "hamper"]
    for i, (bx, (snd, slip)) in enumerate(itertools.product(boxes, itertools.product([True, False], repeat=2))):
        items.append(C.f2_lid(i, bx, snd, slip))
    rooms = [["hall_a", "hall_b", "vault"], ["east", "west", "strongroom"], ["foyer", "study", "archive"],
             ["dock", "yard", "store"], ["lobby", "office", "safe_room"], ["porch", "parlor", "cellar"],
             ["deck", "cabin", "hold"], ["atrium", "gallery", "treasury"], ["gate", "court", "keep"]]
    for i, (two, rm, knock) in enumerate(itertools.product([True, False], rooms, [True, False])):
        items.append(C.f3_rooms(i, two, rm, knock=knock))
    crates = ["crate", "barrel", "sofa", "piano", "engine", "statue", "cabinet", "boat", "anvil", "keg",
              "wardrobe", "generator", "bathtub", "organ", "safe_crate", "bell", "trough", "sledge"]
    spots = [["front", "back"], ["north", "south"], ["left_end", "right_end"], ["top", "bottom"],
             ["bow", "stern"], ["head", "foot"]]
    for i, (cr, probe, never) in enumerate(itertools.product(crates, [True, False], [True, False])):
        items.append(C.f4_lift(i, cr, spots[i % len(spots)], probe=probe, heavy_never=never))
    nodes = ["alpha", "beta", "gamma", "delta", "relay", "gateway", "sensor", "edge", "omega", "hub",
             "proxy", "bridge", "mirror", "beacon", "station", "uplink", "cache", "core"]
    for i, (nd, (pg, sure)) in enumerate(itertools.product(nodes, itertools.product([True, False], repeat=2))):
        items.append(C.f5_node(i, nd, pg, sure))
    return items


def _names(item) -> set:
    return {c["name"] for c in item["model"]["domain"]["constants"]} | {item["model"]["domain"]["name"]}


def main() -> None:
    val = [it for it in C.build() if it["split"] == "val"]
    banned_text = {it["description"] for it in val}
    banned_names = set().union(*(_names(it) for it in val)) - {"R", "A", "B", "P", "Q", "Ops", "door"}
    train, dropped = [], 0
    for k, it in enumerate(extended()):
        if it["description"] in banned_text or _names(it) & banned_names:
            dropped += 1
            continue
        errs = C.validate.validate(it["model"])
        if errs:
            raise SystemExit(f"invalid generated model {it['family']} {k}: {errs[:3]}")
        it["id"] = f"{it['family']}-x{k:03d}"
        train.append(it)
    out = HERE / "data"
    out.mkdir(exist_ok=True)
    with open(out / "train.jsonl", "w") as f:
        for it in train:
            f.write(json.dumps(chat(it)) + "\n")
    with open(out / "val.jsonl", "w") as f:
        for it in val:
            f.write(json.dumps(chat(it)) + "\n")
    by_fam = {}
    for it in train:
        by_fam[it["family"]] = by_fam.get(it["family"], 0) + 1
    stats = {"train": len(train), "val": len(val), "dropped_for_leakage": dropped, "train_by_family": by_fam,
             "banned_names": sorted(banned_names)}
    (out / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
