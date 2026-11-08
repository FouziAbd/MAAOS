"""Training/validation corpus for the G0 DSPy study (thesis phase T2b). Spike code.

Five domain families, eight variants each. Every variant is a pair: a plain-language description
in the style of the CoopGrid-Jam-PO "sole input" (probabilities withheld, rewards stated) and its
true model in the T1 skill-IR JSON. The test domain, CoopGrid-Jam-PO, is NOT in this corpus.

    python corpus.py            # writes corpus.json and checks every model with the T1 validator
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys
from fractions import Fraction
from typing import Any, Dict, List

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "g0_structure"))
sys.path.insert(0, "")
import validate  # noqa: E402  (the T2 checker of the T1 rules)

B11 = {"beta": ["1", "1"]}


def pred(n, *a):
    return {"name": n, "args": list(a)}


def lit(n, *a, pos=True):
    return {"literal": pred(n, *a), "positive": pos}


def eq(p, c):
    return {"equals": [p, c]}


def eff(n, *a, pos=True):
    return {"predicate": pred(n, *a), "positive": pos}


def det(label):
    return {"deterministic": label}


def bern(param, then, other):
    return {"bernoulli": {"p": {"parameter": param}, "then": then, "else": other}}


def case(when, dist):
    return {"when": when, "distribution": dist}


def skill(name, params, types, *, pre=(), neg=(), effects=(), label="done",
          outcomes=None, cases=None, obs=None):
    s: Dict[str, Any] = {"name": name, "parameters": list(params), "parameter_types": list(types),
                         "preconditions": list(pre), "effects": list(effects), "outcome_label": label}
    if neg:
        s["negative_preconditions"] = list(neg)
    if outcomes:
        s["outcomes"] = outcomes
    if cases:
        s["outcome_cases"] = cases
    s["observation_cases"] = obs or {"status": [case([], det("ok"))]}
    return s


def frac(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def dec(x: Fraction) -> str:
    return f"{float(x):g}"


def domain(name, types, constants, params, channels, predicates, skills):
    return {"name": name, "model_version": f"{name}.r1", "types": types,
            "provenance": {"source": "docs/thesis/spikes/g0_dspy/corpus.py", "model_version": f"{name}.r1"},
            "constants": [{"name": n, "type": t} for n, t in constants],
            "parameters": [{"name": p, "prior": B11} for p in params],
            "observation_channels": [{"name": n, "symbols": s} for n, s in channels],
            "predicates": predicates, "skills": skills}


def problem(name, dom, init, hidden, goal, step, skills_extra, goal_r, disc):
    return {"name": name, "domain": dom, "objects": [], "init": init,
            "hidden_prior": [{"literal": lt, "p": {"parameter": p}} for lt, p in hidden],
            "goal": goal,
            "rewards": {"step": frac(step), "skills": {k: frac(v) for k, v in skills_extra.items()},
                        "goal": frac(goal_r)},
            "discount": frac(disc)}


def reward_text(n_agents, step_each, extras, goal_each, disc, extra_words, goal_words):
    per = "per agent per cycle" if n_agents > 1 else "per cycle"
    parts = [f"{dec(step_each)} {per}"]
    parts += [f"an extra {dec(v)} per {extra_words[k]}" for k, v in extras.items()]
    gw = f"+{dec(goal_each)} per agent {goal_words}" if n_agents > 1 else f"+{dec(goal_each)} {goal_words}"
    return f"Rewards: {', '.join(parts)}, {gw}. Discount {dec(disc)}."


CHANNEL_STATUS = ("status", ["none", "ok", "fail"])
REWARDS = [  # (step each, extra, goal each, discount)
    (Fraction(-1, 100), Fraction(-1, 20), Fraction(1), Fraction(19, 20)),
    (Fraction(-1, 50), Fraction(-1, 10), Fraction(2), Fraction(9, 10)),
    (Fraction(-1, 20), Fraction(-1, 50), Fraction(5), Fraction(49, 50)),
    (Fraction(-1, 100), Fraction(-1, 10), Fraction(1), Fraction(9, 10)),
]


# ── F1: a device with a hidden fault ───────────────────────────────────────────────
def f1_device(i: int, dev: str, inspect: bool, stochastic_repair: bool) -> Dict[str, Any]:
    step, extra, goal_r, disc = REWARDS[i % 4]
    on = "running"
    skills = [skill("Start", ["agent", dev], ["agent", "device"], neg=[pred(on, dev)], label="started",
                    outcomes=[{"label": "started", "effects": [eff(on, dev)]}, {"label": "idle", "effects": []}],
                    cases=[case([lit("faulty", dev)], det("idle")),
                           case([], bern("start_success", "started", "idle"))],
                    obs={"status": [case([lit(on, dev)], det("ok")), case([], det("fail"))]})]
    channels = [CHANNEL_STATUS]
    params = ["fault_prior", "start_success"]
    lines = [f"  Start(agent, {dev}): try to start the {dev}. A faulty {dev} never starts, and even a",
             f"    healthy one sometimes fails to start. The status is ok if the {dev} is running afterwards."]
    if inspect:
        channels.append(("reading", ["none", "looks_faulty", "looks_fine"]))
        params.append("inspect_accuracy")
        skills.append(skill("Inspect", ["agent", dev], ["agent", "device"], label="inspected",
                            obs={"status": [case([], det("ok"))],
                                 "reading": [case([lit("faulty", dev)], bern("inspect_accuracy", "looks_faulty", "looks_fine")),
                                             case([], bern("inspect_accuracy", "looks_fine", "looks_faulty"))]}))
        lines += [f"  Inspect(agent, {dev}): look the {dev} over. The reading (looks_faulty | looks_fine) is",
                  "    usually, but not always, right about whether it is faulty. Status ok."]
    if stochastic_repair:
        params.append("repair_success")
        skills.append(skill("Repair", ["agent", dev], ["agent", "device"], neg=[pred(on, dev)], label="fixed",
                            outcomes=[{"label": "fixed", "effects": [eff("faulty", dev, pos=False)]},
                                      {"label": "unchanged", "effects": []}],
                            cases=[case([lit("faulty", dev)], bern("repair_success", "fixed", "unchanged")),
                                   case([], det("unchanged"))]))
        lines += [f"  Repair(agent, {dev}): work on the stopped {dev}. Repairing sometimes clears a fault and",
                  "    never causes one. Status ok whenever the repair was carried out."]
    else:
        skills.append(skill("Repair", ["agent", dev], ["agent", "device"], neg=[pred(on, dev)],
                            effects=[eff("faulty", dev, pos=False)], label="fixed"))
        lines += [f"  Repair(agent, {dev}): replace the faulty part of the stopped {dev}; afterwards it is",
                  "    certainly not faulty. Status ok."]
    name = f"{dev}-fault-po"
    dom = domain(name, ["agent", "device"], [("R", "agent"), (dev, "device")], params, channels,
                 [{"name": on, "param_types": ["device"], "fluent": True},
                  {"name": "faulty", "param_types": ["device"], "fluent": True, "observable": False}], skills)
    prob = problem(f"start-the-{dev}", name, [], [(pred("faulty", dev), "fault_prior")], [pred(on, dev)],
                   step, {"Repair": extra}, goal_r, disc)
    obs_line = "the skill's status (ok | fail)" + (", and after Inspect the reading" if inspect else "")
    text = "\n".join([
        f"{dev.upper()} WITH A HIDDEN FAULT, PARTIALLY OBSERVABLE",
        "",
        f"One agent, R, must get the {dev} running. The {dev} may have a fault.",
        "",
        "Skills (one skill per decision cycle):",
        *lines,
        "",
        f"Hidden: whether the {dev} is faulty is decided at random at the start and never shown directly.",
        "",
        f"Observed after every skill: whether the {dev} is running, {obs_line}.",
        "",
        reward_text(1, step, {"Repair": extra}, goal_r, disc, {"Repair": "repair"}, f"when the {dev} runs"),
        "",
        "The probabilities are NOT given: model each one as a named parameter.",
    ])
    return {"family": "device", "description": text, "model": {"domain": dom, "problem": prob}}


# ── F2: a container whose lid may be stuck ─────────────────────────────────────────
def f2_lid(i: int, box: str, noisy_sound: bool, open_slips: bool) -> Dict[str, Any]:
    step, extra, goal_r, disc = REWARDS[(i + 1) % 4]
    params = ["stuck_prior", "tap_success"] + (["open_success"] if open_slips else []) \
        + (["sound_accuracy"] if noisy_sound else [])
    open_cases = [case([lit("stuck", box)], det("shut"))]
    open_cases.append(case([], bern("open_success", "opened", "shut") if open_slips else det("opened")))
    tap_obs: Dict[str, Any] = {"status": [case([], det("ok"))]}
    channels = [CHANNEL_STATUS]
    if noisy_sound:
        channels.append(("sound", ["none", "thud", "click"]))
        tap_obs["sound"] = [case([lit("stuck", box)], bern("sound_accuracy", "thud", "click")),
                            case([], bern("sound_accuracy", "click", "thud"))]
    skills = [
        skill("OpenLid", ["agent", box], ["agent", "container"], neg=[pred("open", box)], label="opened",
              outcomes=[{"label": "opened", "effects": [eff("open", box)]}, {"label": "shut", "effects": []}],
              cases=open_cases, obs={"status": [case([lit("open", box)], det("ok")), case([], det("fail"))]}),
        skill("Tap", ["agent", box], ["agent", "container"], neg=[pred("open", box)], label="freed",
              outcomes=[{"label": "freed", "effects": [eff("stuck", box, pos=False)]},
                        {"label": "unchanged", "effects": []}],
              cases=[case([lit("stuck", box)], bern("tap_success", "freed", "unchanged")), case([], det("unchanged"))],
              obs=tap_obs),
    ]
    name = f"{box}-lid-po"
    dom = domain(name, ["agent", "container"], [("R", "agent"), (box, "container")], params, channels,
                 [{"name": "open", "param_types": ["container"], "fluent": True},
                  {"name": "stuck", "param_types": ["container"], "fluent": True, "observable": False}], skills)
    prob = problem(f"open-the-{box}", name, [], [(pred("stuck", box), "stuck_prior")], [pred("open", box)],
                   step, {"Tap": extra}, goal_r, disc)
    slip = "Even a free lid sometimes does not come up." if open_slips else "A free lid always comes up."
    sound = ("    The agent then hears a sound (thud | click) that usually, but not always, tells whether the\n"
             "    lid is still stuck afterwards.") if noisy_sound else "    Nothing else is heard."
    text = "\n".join([
        f"{box.upper()} WITH A STICKY LID, PARTIALLY OBSERVABLE", "",
        f"One agent, R, must open the {box}.", "",
        "Skills (one skill per decision cycle):",
        f"  OpenLid(agent, {box}): lift the closed lid. A stuck lid never opens. {slip}",
        "    The status is ok if the lid is open afterwards.",
        f"  Tap(agent, {box}): tap the closed lid. Tapping sometimes frees a stuck lid and never sticks a free",
        "    one. Status ok whenever the tap was made.",
        sound, "",
        f"Hidden: whether the lid starts stuck is decided at random and never shown directly.", "",
        "Observed after every skill: whether the lid is open, the skill's status (ok | fail)"
        + (", and after Tap the sound." if noisy_sound else "."), "",
        reward_text(1, step, {"Tap": extra}, goal_r, disc, {"Tap": "tap"}, f"when the {box} is open"), "",
        "The probabilities are NOT given: model each one as a named parameter.",
    ])
    return {"family": "lid", "description": text, "model": {"domain": dom, "problem": prob}}


# ── F3: rooms with a possibly locked door, one or two agents ─────────────────────────
def f3_rooms(i: int, two_agents: bool, rooms: List[str], knock: bool) -> Dict[str, Any]:
    step, extra, goal_r, disc = REWARDS[(i + 2) % 4]
    agents = ["P", "Q"] if two_agents else ["P"]
    near, far, vault = rooms
    params = ["locked_prior"] + (["knock_accuracy"] if knock else [])
    goto_cases = []
    lines = [f"  Goto(agent, room), room in {{{near}, {far}}}: walk to a room. A room holds one agent at",
             "    a time, and an agent never goes to the room it is already in."]
    if two_agents:
        goto_cases.append(case([eq("agent", "P"), eq("room", far), lit("in", "Q", near)], det("blocked")))
        lines += [f"    The passage is one person wide: P cannot get past Q into {far} while Q is in {near};",
                  "    such a Goto fails and the agent stays."]
    goto_cases.append(case([], det("moved")))
    skills = [
        skill("Goto", ["agent", "room"], ["agent", "room"], pre=[pred("walkable", "room")], neg=[pred("in", "*", "room")],
              label="moved",
              outcomes=[{"label": "moved", "effects": [eff("in", "agent", "*", pos=False), eff("in", "agent", "room")]}]
              + ([{"label": "blocked", "effects": []}] if two_agents else []),
              cases=goto_cases if two_agents else None,
              obs={"status": [case([lit("in", "agent", "room")], det("ok")), case([], det("fail"))]}),
        skill("EnterVault", ["agent", "door"], ["agent", "door"], pre=[pred("in", "agent", far)],
              neg=[pred("in", "agent", vault)], label="entered",
              outcomes=[{"label": "entered", "effects": [eff("in", "agent", "*", pos=False), eff("in", "agent", vault)]},
                        {"label": "refused", "effects": []}],
              cases=[case([lit("locked", "door")], det("refused")), case([], det("entered"))],
              obs={"status": [case([lit("in", "agent", vault)], det("ok")), case([], det("fail"))]}),
        skill("Unlock", ["agent", "door"], ["agent", "door"], pre=[pred("in", "agent", far)],
              effects=[eff("locked", "door", pos=False)], label="unlocked"),
    ]
    channels = [CHANNEL_STATUS]
    if knock:
        channels.append(("echo", ["none", "dull", "hollow"]))
        skills.append(skill("Knock", ["agent", "door"], ["agent", "door"], pre=[pred("in", "agent", far)],
                            label="knocked",
                            obs={"status": [case([], det("ok"))],
                                 "echo": [case([lit("locked", "door")], bern("knock_accuracy", "dull", "hollow")),
                                          case([], bern("knock_accuracy", "hollow", "dull"))]}))
    name = "vault-rooms-po" + ("-2" if two_agents else "-1") + f"-{near}"
    consts = [(a, "agent") for a in agents] + [(near, "room"), (far, "room"), (vault, "room"), ("door", "door")]
    dom = domain(name, ["agent", "room", "door"], consts, params, channels,
                 [{"name": "in", "param_types": ["agent", "room"], "fluent": True},
                  {"name": "walkable", "param_types": ["room"], "fluent": False},
                  {"name": "locked", "param_types": ["door"], "fluent": True, "observable": False}],
                 skills)
    n = len(agents)
    prob = problem("reach-the-vault", name, [pred("walkable", near), pred("walkable", far)],
                   [(pred("locked", "door"), "locked_prior")], [pred("in", a, vault) for a in agents],
                   step * n, {"Unlock": extra}, goal_r * n, disc)
    who = "Two agents, P and Q, start" if two_agents else "One agent, P, starts"
    text = "\n".join([
        "VAULT BEHIND A DOOR THAT MAY BE LOCKED, PARTIALLY OBSERVABLE", "",
        f"{who} in the corridor. Rooms {near} and {far} lie along it, and the vault lies behind a door",
        f"that opens from {far}. The task succeeds when {'both agents are' if two_agents else 'P is'} in the vault.", "",
        "Skills (one skill per decision cycle):", *lines,
        f"  EnterVault(agent, door): from {far}, step through the door into the vault. A locked door",
        "    refuses entry and the agent stays. An agent in the vault stays there.",
        f"  Unlock(agent, door): from {far}, unlock the door with the key; afterwards it is certainly",
        "    unlocked. Status ok.",
        *([f"  Knock(agent, door): from {far}, knock on the door. The echo (dull | hollow) is usually, but",
           "    not always, dull when the door is locked and hollow when it is not. Status ok."] if knock else []), "",
        "Hidden: whether the door starts locked is decided at random and never shown directly.", "",
        "Observed after every skill: where each agent is (a room, the vault, or the corridor), the skill's",
        "status (ok | fail)" + (", and after Knock the echo." if knock else "."), "",
        reward_text(n, step, {"Unlock": extra}, goal_r, disc, {"Unlock": "unlock"}, "when "
                    + ("both are" if two_agents else "P is") + " in the vault"), "",
        "The probabilities are NOT given: model each one as a named parameter.",
    ])
    return {"family": "rooms", "description": text, "model": {"domain": dom, "problem": prob}}


# ── F4: two agents lift a crate that may be heavy ───────────────────────────────────
def f4_lift(i: int, crate: str, spots: List[str], probe: bool, heavy_never: bool) -> Dict[str, Any]:
    step, extra, goal_r, disc = REWARDS[(i + 3) % 4]
    left, right = spots
    params = ["heavy_prior", "lift_success"] + ([] if heavy_never else ["heavy_lift_success"]) \
        + (["probe_accuracy"] if probe else [])
    heavy_dist = det("dropped") if heavy_never else bern("heavy_lift_success", "lifted", "dropped")
    channels = [CHANNEL_STATUS]
    skills = [
        skill("Approach", ["agent", "spot"], ["agent", "spot"], pre=[pred("grip", "spot")], neg=[pred("at", "*", "spot")],
              label="arrived", outcomes=[{"label": "arrived", "effects": [eff("at", "agent", "*", pos=False),
                                                                          eff("at", "agent", "spot")]}],
              obs={"status": [case([], det("ok"))]}),
        skill("JointLift", ["agent", crate, "partner"], ["agent", "crate", "agent"],
              pre=[pred("at", "agent", left), pred("at", "partner", right)], neg=[pred("raised", crate)],
              label="lifted", outcomes=[{"label": "lifted", "effects": [eff("raised", crate)]},
                                        {"label": "dropped", "effects": []}],
              cases=[case([lit("heavy", crate)], heavy_dist), case([], bern("lift_success", "lifted", "dropped"))],
              obs={"status": [case([lit("raised", crate)], det("ok")), case([], det("fail"))]}),
    ]
    if probe:
        channels.append(("strain", ["none", "strains", "easy"]))
        skills.append(skill("Probe", ["agent", crate], ["agent", "crate"], pre=[pred("at", "agent", left)],
                            label="probed",
                            obs={"status": [case([], det("ok"))],
                                 "strain": [case([lit("heavy", crate)], bern("probe_accuracy", "strains", "easy")),
                                            case([], bern("probe_accuracy", "easy", "strains"))]}))
    name = f"{crate}-lift-po"
    dom = domain(name, ["agent", "spot", "crate"],
                 [("A", "agent"), ("B", "agent"), (left, "spot"), (right, "spot"), (crate, "crate")], params, channels,
                 [{"name": "at", "param_types": ["agent", "spot"], "fluent": True},
                  {"name": "grip", "param_types": ["spot"], "fluent": False},
                  {"name": "raised", "param_types": ["crate"], "fluent": True},
                  {"name": "heavy", "param_types": ["crate"], "fluent": False, "observable": False}], skills)
    prob = problem(f"raise-the-{crate}", name, [pred("grip", left), pred("grip", right)],
                   [(pred("heavy", crate), "heavy_prior")], [pred("raised", crate)],
                   step * 2, {"Probe": extra} if probe else {}, goal_r * 2, disc)
    heavy_txt = ("A heavy crate never comes up." if heavy_never
                 else "A heavy crate comes up less often than a light one.")
    text = "\n".join([
        f"{crate.upper()} THAT MAY BE HEAVY, PARTIALLY OBSERVABLE", "",
        f"Two agents, A and B, must raise the {crate} together. It has two grip spots, {left} and {right}.", "",
        "Skills (one skill per decision cycle):",
        f"  Approach(agent, spot), spot in {{{left}, {right}}}: step to a grip spot. A spot holds one agent,",
        "    and an agent never approaches the spot it already holds. Status ok.",
        f"  JointLift(agent, {crate}, partner): the agent on {left} and the partner on {right} lift together.",
        f"    {heavy_txt} Even a light crate sometimes slips back down. The status is ok if the",
        "    crate is raised afterwards.",
        *([f"  Probe(agent, {crate}): the agent on {left} tests the weight. The feel (strains | easy) is",
           "    usually, but not always, right about whether the crate is heavy. Status ok."] if probe else []), "",
        "Hidden: whether the crate is heavy is decided at random at the start, never changes, and is never",
        "shown directly.", "",
        "Observed after every skill: which spot each agent holds, whether the crate is raised, the skill's",
        "status (ok | fail)" + (", and after Probe the feel." if probe else "."), "",
        reward_text(2, step, {"Probe": extra} if probe else {}, goal_r, disc, {"Probe": "probe"},
                    "when the crate is raised"), "",
        "The probabilities are NOT given: model each one as a named parameter.",
    ])
    return {"family": "lift", "description": text, "model": {"domain": dom, "problem": prob}}


# ── F5: a network node that may be hung ──────────────────────────────────────────────
def f5_node(i: int, node: str, ping: bool, reboot_sure: bool) -> Dict[str, Any]:
    step, extra, goal_r, disc = REWARDS[i % 4]
    params = ["hung_prior", "send_success"] + ([] if reboot_sure else ["reboot_success"]) \
        + (["ping_accuracy"] if ping else [])
    channels = [CHANNEL_STATUS]
    reboot = (skill("Reboot", ["agent", node], ["agent", "node"], effects=[eff("hung", node, pos=False)], label="rebooted")
              if reboot_sure else
              skill("Reboot", ["agent", node], ["agent", "node"], label="recovered",
                    outcomes=[{"label": "recovered", "effects": [eff("hung", node, pos=False)]},
                              {"label": "unchanged", "effects": []}],
                    cases=[case([lit("hung", node)], bern("reboot_success", "recovered", "unchanged")),
                           case([], det("unchanged"))]))
    skills = [
        skill("Send", ["agent", node], ["agent", "node"], neg=[pred("delivered", node)], label="sent",
              outcomes=[{"label": "sent", "effects": [eff("delivered", node)]}, {"label": "lost", "effects": []}],
              cases=[case([lit("hung", node)], det("lost")), case([], bern("send_success", "sent", "lost"))],
              obs={"status": [case([lit("delivered", node)], det("ok")), case([], det("fail"))]}),
        reboot,
    ]
    if ping:
        channels.append(("reply", ["none", "timeout", "pong"]))
        skills.append(skill("Ping", ["agent", node], ["agent", "node"], label="pinged",
                            obs={"status": [case([], det("ok"))],
                                 "reply": [case([lit("hung", node)], bern("ping_accuracy", "timeout", "pong")),
                                           case([], bern("ping_accuracy", "pong", "timeout"))]}))
    name = f"{node}-node-po"
    dom = domain(name, ["agent", "node"], [("Ops", "agent"), (node, "node")], params, channels,
                 [{"name": "delivered", "param_types": ["node"], "fluent": True},
                  {"name": "hung", "param_types": ["node"], "fluent": True, "observable": False}], skills)
    prob = problem(f"deliver-to-{node}", name, [], [(pred("hung", node), "hung_prior")], [pred("delivered", node)],
                   step, {"Reboot": extra}, goal_r, disc)
    reb = (f"  Reboot(agent, {node}): restart the {node}; afterwards it is certainly not hung. Status ok."
           if reboot_sure else
           f"  Reboot(agent, {node}): restart the {node}. A reboot sometimes clears a hang and never causes one.\n"
           "    Status ok whenever the reboot was issued.")
    text = "\n".join([
        f"NETWORK NODE {node.upper()} THAT MAY BE HUNG, PARTIALLY OBSERVABLE", "",
        f"One operator agent, Ops, must deliver a message to the node {node}.", "",
        "Skills (one skill per decision cycle):",
        f"  Send(agent, {node}): send the message. A hung node never receives it, and even a healthy node",
        "    sometimes loses it. The status is ok if the message has been delivered.",
        reb,
        *([f"  Ping(agent, {node}): ping the node. The reply (timeout | pong) is usually, but not always, a",
           "    timeout when it is hung and a pong when it is not. Status ok."] if ping else []), "",
        "Hidden: whether the node starts hung is decided at random and never shown directly.", "",
        "Observed after every skill: whether the message has been delivered, the skill's status (ok | fail)"
        + (", and after Ping the reply." if ping else "."), "",
        reward_text(1, step, {"Reboot": extra}, goal_r, disc, {"Reboot": "reboot"}, "on delivery"), "",
        "The probabilities are NOT given: model each one as a named parameter.",
    ])
    return {"family": "node", "description": text, "model": {"domain": dom, "problem": prob}}


def build() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    devs = ["lamp", "pump", "fan", "heater", "printer", "radio", "valve", "kettle"]
    for i, (dev, (ins, rep)) in enumerate(zip(devs, itertools.cycle(itertools.product([True, False], repeat=2)))):
        items.append(f1_device(i, dev, ins, rep))
    boxes = ["chest", "crate_box", "jar", "trunk", "locker", "safe", "drawer", "tin"]
    for i, (bx, (snd, slip)) in enumerate(zip(boxes, itertools.cycle(itertools.product([True, False], repeat=2)))):
        items.append(f2_lid(i, bx, snd, slip))
    rooms = [["hall_a", "hall_b", "vault"], ["east", "west", "strongroom"], ["foyer", "study", "archive"],
             ["dock", "yard", "store"]]
    for i, (two, rm) in enumerate(itertools.product([True, False], rooms)):
        items.append(f3_rooms(i, two, rm, knock=(i % 2 == 0)))
    crates = ["crate", "barrel", "sofa", "piano", "engine", "statue", "cabinet", "boat"]
    spot_pairs = [["front", "back"], ["north", "south"], ["left_end", "right_end"], ["top", "bottom"]]
    for i, cr in enumerate(crates):
        items.append(f4_lift(i, cr, spot_pairs[i % 4], probe=(i % 2 == 0), heavy_never=(i % 4 < 2)))
    nodes = ["alpha", "beta", "gamma", "delta", "relay", "gateway", "sensor", "edge"]
    for i, (nd, (pg, sure)) in enumerate(zip(nodes, itertools.cycle(itertools.product([True, False], repeat=2)))):
        items.append(f5_node(i, nd, pg, sure))
    for k, it in enumerate(items):
        it["id"] = f"{it['family']}-{k:02d}"
        it["split"] = "val" if k % 4 == 3 else "train"   # 2 of 8 per family held out for validation
    return items


def main() -> None:
    items = build()
    bad = {it["id"]: validate.validate(it["model"]) for it in items}
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        for k, v in bad.items():
            print(k, v[:4])
        sys.exit(1)
    (HERE / "corpus.json").write_text(json.dumps(items, indent=1) + "\n")
    n_train = sum(it["split"] == "train" for it in items)
    print(f"{len(items)} pairs, all valid; train {n_train}, val {len(items) - n_train}")


if __name__ == "__main__":
    main()
