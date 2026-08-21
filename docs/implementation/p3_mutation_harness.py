# CHECKED-IN PROCESS EVIDENCE, not part of the test suite (it MUTATES product files and
# restores them). Run manually from the repo root:  python -B docs/implementation/p3_mutation_harness.py
# Every mutation must be KILLED; a survivor is a coverage gap. Bytecode is disabled and
# __pycache__ cleared before every run so same-length edits cannot reuse stale .pyc.
"""P3 NL-track mutation harness."""
import pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
PA, SE, RC, TI, SB, SS, RP, TR, RV, TK, OI = ("nl/parser.py", "nl/seam.py", "nl/runtime_config.py",
    "nl/task_interpreter.py", "nl/semantic_belief.py", "nl/skill_selector.py", "nl/repair.py",
    "nl/translator.py", "nl/recovery.py", "nl/track.py", "nl/observation_interpreter.py")

M = [
 # ── parser: the Decision 7 core ──
 ("N1 unknown skill silently becomes Explore", PA,
  '''    if skill is None:
        return MalformedCall(
            reason=f"unknown skill name {skill_text!r}; valid: "
                   + ", ".join(sorted(_SKILLS_BY_NAME)),
            raw=raw,
        )''',
  '''    if skill is None:
        skill = SkillName.EXPLORE
        parts = ["agent_0"]
        args_text = "agent_0"'''),
 ("N2 constructor rejection swallowed into Wait", PA,
  '''    except (TypeError, ValueError) as error:
        # the frozen constructor is the arity/type authority; its rejection is the reason
        return MalformedCall(reason=f"{type(error).__name__}: {error}", raw=raw)''',
  '''    except (TypeError, ValueError):
        return GroundedSkillCall(SkillName.WAIT, (AgentId("agent_0"),))'''),
 ("N3 raw text dropped from the malformed record", PA,
  '''        return MalformedCall(
            reason="not a skill call: expected 'Skill(agents; box; zone)' on a single line",
            raw=raw,
        )''',
  '''        return MalformedCall(
            reason="not a skill call: expected 'Skill(agents; box; zone)' on a single line",
        )'''),
 ("N4 multi-line proposals accepted", PA,
  '_CALL_RE = re.compile(r"^\\s*([A-Za-z_]+)\\s*\\(\\s*([^()]*?)\\s*\\)\\s*$")',
  '_CALL_RE = re.compile(r"\\s*([A-Za-z_]+)\\s*\\(\\s*([^()]*?)\\s*\\)\\s*")'),
 # ── seam ──
 ("S1 fixture miss invents an empty answer", SE,
  '''        try:
            return table[request.key()]
        except KeyError:
            raise UnrecordedRequestError(request) from None''',
  '''        return table.get(request.key(), "")'''),
 ("S2 request key ignores field values", SE,
  '''        return json.dumps(
            {"module": self.module, "fields": dict(self.fields)},
            sort_keys=True, separators=(",", ":"),
        )''',
  '''        return json.dumps(
            {"module": self.module, "fields": sorted(dict(self.fields))},
            sort_keys=True, separators=(",", ":"),
        )'''),
 # ── runtime config ──
 ("C1 temperature pin dropped", RC,
  '''        if self.temperature != 0.0:''',
  '''        if False and self.temperature != 0.0:'''),
 ("C2 pinned config stops caching", RC,
  "    cache=True,\n)", "    cache=False,\n)"),
 # ── task interpreter ──
 ("T1 residual clauses silently dropped", TI,
  "        else:\n            residual.append(f\"clause outside the V1 vocabulary: {clause!r}\")",
  "        else:\n            pass"),
 ("T2 goal literals come from description keywords not the typed goal", TI,
  '''    goal = frozenset(
        GroundedLiteral("delivered", (str(box),)) for box in task.goal_delivered
    )''',
  '''    goal = frozenset(
        GroundedLiteral("delivered", (str(box),)) for box in list(task.goal_delivered)[:1]
    )'''),
 # ── semantic belief ──
 ("B1 history unbounded", SB,
  "    history = (history + (fact,))[-_HISTORY_LIMIT:]",
  "    history = history + (fact,)"),
 ("B2 facts dead-reckoned instead of re-derived", SB,
  "    return SemanticBelief(facts=state_facts(snapshot), attempt_history=history)",
  "    return SemanticBelief(facts=belief.facts or state_facts(snapshot), attempt_history=history)"),
 # ── selector / repair ──
 ("R1 repair silently retries forever (second attempt)", RP,
  '''        repaired = parse_skill_call(self._seam.complete(self.build_request(malformed)))
        if isinstance(repaired, MalformedCall):''',
  '''        repaired = parse_skill_call(self._seam.complete(self.build_request(malformed)))
        if isinstance(repaired, MalformedCall):
            repaired = parse_skill_call(self._seam.complete(self.build_request(malformed)))
        if isinstance(repaired, MalformedCall):'''),
 ("R2 unrepairable rewritten to the original raw's first word skill", RP,
  '''            return MalformedCall(
                reason=f"unrepairable after one attempt: {repaired.reason} "
                       f"(original problem: {malformed.reason})",
                raw=malformed.raw,
            )''',
  '''            return MalformedCall(reason="unrepairable", raw="")'''),
 # ── translator ──
 ("X1 registry-only skills claim complete coverage", TR,
  '''        coverage = CoverageReport(
            covered=(),
            residual=(
                f"{call.skill.value} is outside the V1 symbolic model (Decision 15): "
                f"the symbolic track can neither plan nor predict it",
            ),''',
  '''        coverage = CoverageReport(
            covered=(call.key(),),
            residual=(),'''),
 # ── recovery ──
 ("V1 recovery invents exploration for unknown discrepancies", RV,
  '''    if discrepancy.kind is not DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL:
        return ()''',
  '''    if discrepancy.kind is not DiscrepancyKind.EXECUTION_FAILURE_OF_APPLICABLE_SKILL:
        from shared.ids import AgentId
        return (GroundedSkillCall(SkillName.EXPLORE, (AgentId("agent_0"),)),)'''),
 ("V2 establishing-skill failure also proposes reestablishment", RV,
  '''    if call.skill not in _CONSUMING:
        return ()''',
  '''    if False:
        return ()'''),
 ("V3 coop recovery drops the second agent", RV,
  '''    return tuple(
        GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (agent,), call.box, call.zone)
        for agent in call.agents
    )''',
  '''    return tuple(
        GroundedSkillCall(SkillName.GOTO_PUSH_POSE, (agent,), call.box, call.zone)
        for agent in call.agents[:1]
    )'''),
 # ── track ──
 ("K1 malformed proposal replaced by a call-shaped default", TK,
  '''        if isinstance(proposed, MalformedCall):
            return NLProposal(
                call=None, malformed=proposed,
                coverage=interpreted.coverage, confidence=None, repaired=False,
            )''',
  '''        if isinstance(proposed, MalformedCall):
            from shared.ids import AgentId
            from shared.skills import SkillName
            proposed = GroundedSkillCall(SkillName.EXPLORE, (AgentId("agent_0"),))'''),
 ("K2 repaired flag always false", TK,
  '''            proposed = self._repair.repair(proposed)
            repaired = not isinstance(proposed, MalformedCall)''',
  '''            proposed = self._repair.repair(proposed)
            repaired = False'''),
 ("K3 translation residual dropped from the merged coverage", TK,
  '''            residual=interpreted.coverage.residual + translated.coverage.residual,''',
  '''            residual=interpreted.coverage.residual,'''),
 # ── Q-series: request-content and truth-of-facts pins (test review FAIL-1..5, W6-W9) ──
 ("Q1 selector ignores the belief", SS,
  "            situation=belief.rendered(),", "            situation=\"\","),
 ("Q2 selector hides the skill menu", SS,
  "            decision_space=skill_menu(),", "            decision_space=\"\","),
 ("Q3 repair asks about an empty string", RP,
  "            raw=malformed.raw,", "            raw=\"\","),
 ("Q4 request key ignores the module", SE,
  '''            {"module": self.module, "fields": dict(self.fields)},''',
  '''            {"fields": dict(self.fields)},'''),
 ("Q5 delivered status inverted in the facts", OI,
  '''        status = "already delivered" if box.delivered else "not delivered yet"''',
  '''        status = "not delivered yet" if box.delivered else "already delivered"'''),
 ("Q6 direction words transposed", OI,
  '''_DIRECTION_WORDS = {0: "right", 1: "down", 2: "left", 3: "up"}''',
  '''_DIRECTION_WORDS = {0: "up", 1: "down", 2: "left", 3: "right"}'''),
 ("Q7 track discards outcomes on observe", TK,
  "        self.belief = update_belief(self.belief, snapshot, last_skill, last_outcome)",
  "        self.belief = update_belief(self.belief, snapshot)"),
 ("Q8 merged covered evidence lost", TK,
  "            covered=interpreted.coverage.covered + translated.coverage.covered,",
  "            covered=interpreted.coverage.covered,"),
 ("Q9 format instructions lose the one-call rule", SS,
  '''    "Answer with EXACTLY ONE skill call on a single line, formatted "''',
  '''    "Answer briefly, formatted "'''),
 ("Q10 full-coverage confidence quietly lowered", TR,
  '''        confidence = ConfidenceReport(
            source="nl", confidence=1.0,''',
  '''        confidence = ConfidenceReport(
            source="nl", confidence=0.7,'''),
 ("Q11 negation guard dropped from the classifier", TI,
  '''    if any(token in _NEGATION_TOKENS or token.endswith("n't") for token in tokens):
        return False''',
  '''    if False:
        return False'''),
 ("Q13 requirement-clause rule dropped from the classifier", TI,
  '''    return _has_stem(tokens, _REQUIREMENT_VERB_STEMS) and _has_stem(
        tokens, _REQUIREMENT_OBJECT_STEMS
    )''',
  '''    return False'''),
 ("Q14 token matching regressed to raw substring containment", TI,
  '''def _has_stem(tokens, stems) -> bool:
    return any(token.startswith(stem) for stem in stems for token in tokens)''',
  '''def _has_stem(tokens, stems) -> bool:
    return any(stem in " ".join(tokens) for stem in stems)'''),
 ("Q15 stale post-banner line citation reintroduced into a contract file", "shared/faults.py",
  "(centralized_dspy_planner.py:106-108 \u2192 the `decided.get(aid, (\"explore\", None))` default in box_push_centralized.py::main).",
  "(centralized_dspy_planner.py:106-108 \u2192 box_push_" + "centralized.py:404)."),
 ("Q16 cannot/no dropped from the negation tokens", TI,
  '''_NEGATION_TOKENS = frozenset({"not", "never", "avoid", "cannot", "no"})''',
  '''_NEGATION_TOKENS = frozenset({"not", "never", "avoid"})'''),
 ("Q12 provenance guard loses primitive_steps via string evasion", SB,
  "_HISTORY_LIMIT = 8",
  "_HISTORY_LIMIT = 8\n_PROVENANCE_PROBE = \"primitive_steps\"  # mutant: banned string in nl/"),
]

def run():
    for cache in ROOT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"],
                          cwd=ROOT, capture_output=True, text=True).returncode == 0

bad = []
for name, rel, old, new in M:
    path = ROOT / rel
    original = path.read_text()
    if old not in original:
        bad.append((name, "ANCHOR")); print(f"ANCHOR??  {name}"); continue
    path.write_text(original.replace(old, new, 1))
    try:
        if run():
            bad.append((name, "SURVIVED")); print(f"SURVIVED  {name}")
        else:
            print(f"killed    {name}")
    finally:
        path.write_text(original)
print(f"\n{len(M)-len(bad)}/{len(M)} killed")
for n, w in bad: print(f"  !! {n}: {w}")
