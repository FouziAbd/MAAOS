"""The frozen BoxPush V1 domain: instance constants, IR shape, and intentional optimism.

These tests pin `domain/box_push_v1.py` against literals recorded here, i.e. they detect drift in
the FROZEN DOMAIN. They do NOT read the backend, so they cannot by themselves detect a change in
the backend source — `tests/test_backend_freeze_drift.py` does that, by scraping the authoritative
files.
"""
import pathlib
import re
import unittest

from domain.box_push_v1 import (
    AGENT_0,
    AGENT_1,
    BOX_HEAVY,
    BOX_LIGHT,
    DELIVERY_ZONE,
    DOMAIN_IR,
    GOAL_ZONE,
    GRID_HEIGHT,
    GRID_WIDTH,
    MODEL_VERSION,
    P_DELIVERED,
    P_HEAVY,
    P_IN_POSE,
    P_LIGHT,
    P_PENDING,
    TASKS,
    TASK_DELIVER_BOTH,
    TASK_DELIVER_HEAVY,
    TASK_DELIVER_LIGHT,
    initial_state,
)
from shared.ids import BoxId
from shared.skills import SkillName
from shared.state_snapshot import BoxSnapshot


class TestFrozenInstance(unittest.TestCase):
    def test_grid_is_12x12(self):
        self.assertEqual((GRID_WIDTH, GRID_HEIGHT), (12, 12))

    def test_goal_zone_is_column_x1_rows_1_to_10(self):
        """box_push_env.py:39 — GOAL_ZONE = [(1, y) for y in range(1, 11)]"""
        self.assertEqual(GOAL_ZONE, tuple((1, y) for y in range(1, 11)))
        self.assertEqual(len(GOAL_ZONE), 10)

    def test_walls_are_outer_border_only(self):
        """box_push_env.py:84-101 — open arena, no internal dividers."""
        walls = set(initial_state().static.walls)
        self.assertEqual(len(walls), 4 * 12 - 4)      # perimeter, corners counted once
        for x in range(1, 11):
            for y in range(1, 11):
                self.assertNotIn((x, y), walls)

    def test_box_weights_and_positions(self):
        s = initial_state()
        self.assertEqual(s.box(BOX_HEAVY).position, (6, 6))
        self.assertEqual(s.box(BOX_HEAVY).required_agents, 2)
        self.assertTrue(s.box(BOX_HEAVY).is_heavy)
        self.assertEqual(s.box(BOX_LIGHT).position, (8, 4))
        self.assertEqual(s.box(BOX_LIGHT).required_agents, 1)
        self.assertFalse(s.box(BOX_LIGHT).is_heavy)

    def test_agent_starts(self):
        """multi_agent_box_push_env.py:90-91, :107-113 — fixed starts, both facing LEFT (2)."""
        s = initial_state()
        self.assertEqual(s.agent(AGENT_0).position, (10, 10))
        self.assertEqual(s.agent(AGENT_1).position, (10, 9))
        self.assertEqual(s.agent(AGENT_0).direction, 2)
        self.assertEqual(s.agent(AGENT_1).direction, 2)

    def test_nothing_is_delivered_initially(self):
        self.assertFalse(initial_state().all_targets_delivered)

    def test_instance_is_deterministic(self):
        """Nothing is randomized; the backend's seed is observationally inert."""
        self.assertEqual(initial_state().replay_key(), initial_state().replay_key())

    def test_boxes_do_not_start_in_the_goal_zone(self):
        s = initial_state()
        for b in s.boxes:
            self.assertNotIn(b.position, set(GOAL_ZONE))


class TestDomainIR(unittest.TestCase):
    def test_symbolic_action_set_is_the_three_push_skills(self):
        self.assertEqual(
            set(DOMAIN_IR.action_set()),
            {SkillName.GOTO_PUSH_POSE, SkillName.PUSH, SkillName.COOPERATIVE_PUSH},
        )

    def test_explore_is_not_in_the_symbolic_action_set(self):
        """Decision 5: full observability makes discovery unnecessary for planning."""
        self.assertFalse(DOMAIN_IR.has_skill(SkillName.EXPLORE))
        with self.assertRaises(KeyError):
            DOMAIN_IR.skill(SkillName.EXPLORE)

    def test_every_skill_has_provenance_and_model_version(self):
        for s in DOMAIN_IR.skills:
            with self.subTest(skill=s.name):
                self.assertTrue(s.provenance.source)
                self.assertEqual(s.provenance.model_version, MODEL_VERSION)

    def test_every_skill_declares_a_deterministic_outcome_and_effects(self):
        for s in DOMAIN_IR.skills:
            with self.subTest(skill=s.name):
                self.assertTrue(s.outcome_label)
                self.assertTrue(s.effects)

    def test_default_cost_is_one(self):
        for s in DOMAIN_IR.skills:
            with self.subTest(skill=s.name):
                self.assertEqual(s.cost, 1)

    def test_domain_digest_is_content_addressed(self):
        """`digest() == digest()` in one process is the tautology `test_contract_invariants.py`
        names as the reason a whole class of mutations survived. Assert the actual property: the
        digest is a function of the canonical CONTENT."""
        import hashlib, json
        blob = json.dumps(DOMAIN_IR.canonical(), sort_keys=True, separators=(",", ":"))
        self.assertEqual(DOMAIN_IR.digest(), hashlib.sha256(blob.encode("utf-8")).hexdigest())

    def test_undeclared_predicate_is_rejected(self):
        from shared.skill_ir import DomainIR, Effect, Predicate, SkillIR
        from shared.skills import REGISTRY

        bad = SkillIR(
            signature=REGISTRY.get(SkillName.PUSH),
            parameters=("agent", "box", "zone"),
            parameter_types=("agent", "box", "zone"),
            preconditions=(Predicate("not_declared", ("box",)),),
            effects=(Effect(Predicate(P_DELIVERED, ("box",))),),
            provenance=DOMAIN_IR.provenance,
        )
        with self.assertRaises(ValueError):
            DomainIR(
                name="bad",
                model_version=MODEL_VERSION,
                predicates=DOMAIN_IR.predicates,
                skills=(bad,),
                provenance=DOMAIN_IR.provenance,
            )

    def test_effect_referencing_an_undeclared_parameter_is_rejected(self):
        from shared.skill_ir import Effect, Predicate, SkillIR
        from shared.skills import REGISTRY

        with self.assertRaises(ValueError):
            SkillIR(
                signature=REGISTRY.get(SkillName.PUSH),
                parameters=("agent", "box", "zone"),
                parameter_types=("agent", "box", "zone"),
                effects=(Effect(Predicate(P_IN_POSE, ("agent", "ghost"))),),
                preconditions=(),
                provenance=DOMAIN_IR.provenance,
            )


class TestIntentionalOptimism(unittest.TestCase):
    """Decision 6 / supervisor :51-:59. These assertions must NEVER be 'fixed' to make a plan
    executable — they encode the designed discrepancy sources."""

    def test_in_pose_is_non_exclusive(self):
        """GotoPushPose adds in_pose and deletes nothing, so one agent may be in pose for two
        boxes at once. The backend gives an agent one cell. Kept deliberately."""
        goto = DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE)
        deletes = [e for e in goto.effects if not e.positive]
        self.assertEqual(deletes, [], "in_pose must remain non-exclusive in V1")

    def test_goto_push_pose_has_no_reachability_precondition(self):
        """Its only preconditions are discovered + pending — no position, no path, no occupancy."""
        goto = DOMAIN_IR.skill(SkillName.GOTO_PUSH_POSE)
        names = {str(p.name) for p in goto.preconditions}
        self.assertEqual(names, {"discovered", "pending"})

    def test_no_predicate_encodes_geometry_or_feasibility(self):
        forbidden = ("position", "cell", "adjacent", "reachable", "path", "free", "clear",
                     "occupied", "collision", "distance", "blocked")
        for decl in DOMAIN_IR.predicates:
            with self.subTest(predicate=decl.name):
                lowered = str(decl.name).lower()
                for token in forbidden:
                    self.assertNotIn(token, lowered)

    def test_push_requires_light_and_cooperative_push_requires_heavy(self):
        push = DOMAIN_IR.skill(SkillName.PUSH)
        coop = DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH)
        self.assertIn(P_LIGHT, {str(p.name) for p in push.preconditions})
        self.assertIn(P_HEAVY, {str(p.name) for p in coop.preconditions})

    def test_push_delivers_in_one_symbolic_action(self):
        """Push-to-zone (Decision 11): symbolic success is delivered(box). Cell-by-cell movement,
        blocking, partial movement and timeout are backend execution details."""
        push = DOMAIN_IR.skill(SkillName.PUSH)
        adds = {str(e.predicate.name) for e in push.effects if e.positive}
        dels = {str(e.predicate.name) for e in push.effects if not e.positive}
        self.assertIn(P_DELIVERED, adds)
        self.assertIn(P_PENDING, dels)

    def test_cooperative_push_is_one_joint_symbolic_action(self):
        """Decision 1: one executive skill, two agent variables, single delivered effect."""
        coop = DOMAIN_IR.skill(SkillName.COOPERATIVE_PUSH)
        self.assertEqual(coop.parameters, ("agent1", "agent2", "box", "zone"))
        adds = {str(e.predicate.name) for e in coop.effects if e.positive}
        self.assertEqual(adds, {P_DELIVERED})


class TestTaskExamples(unittest.TestCase):
    def test_representative_tasks_exist(self):
        self.assertGreaterEqual(len(TASKS), 3)
        self.assertEqual(len({t.task_id for t in TASKS}), len(TASKS))

    def test_tasks_are_unsatisfied_in_the_initial_state(self):
        s = initial_state()
        for t in TASKS:
            with self.subTest(task=t.task_id):
                self.assertFalse(t.is_satisfied_by(s))

    def test_task_is_satisfied_once_its_boxes_are_delivered(self):
        s = initial_state()
        b = s.box(BOX_HEAVY)
        s = s.with_box(BoxSnapshot(b.box_id, (1, 6), b.required_agents, b.is_target, True))
        self.assertTrue(TASK_DELIVER_HEAVY.is_satisfied_by(s))
        self.assertFalse(TASK_DELIVER_BOTH.is_satisfied_by(s))

    def test_every_task_targets_the_frozen_zone(self):
        for t in TASKS:
            with self.subTest(task=t.task_id):
                self.assertEqual(t.zone, DELIVERY_ZONE)

    def test_task_requires_a_goal(self):
        from shared.task import Task
        with self.assertRaises(ValueError):
            Task(task_id="empty", description="", goal_delivered=(), zone=DELIVERY_ZONE)


class TestRepresentativeTaskContent(unittest.TestCase):
    """`TASK_DELIVER_BOTH` could silently become a single-box task: the existing test only checks
    that it is NOT satisfied by the heavy box alone, which still holds if the light box is the
    only goal."""

    def test_deliver_both_names_both_boxes(self):
        self.assertEqual(set(TASK_DELIVER_BOTH.goal_delivered), {BOX_HEAVY, BOX_LIGHT})

    def test_the_single_box_tasks_name_exactly_one_box_each(self):
        self.assertEqual(TASK_DELIVER_LIGHT.goal_delivered, (BOX_LIGHT,))
        self.assertEqual(TASK_DELIVER_HEAVY.goal_delivered, (BOX_HEAVY,))

    def test_every_task_targets_the_frozen_zone(self):
        for task in TASKS:
            with self.subTest(task=task.task_id):
                self.assertEqual(task.zone, DELIVERY_ZONE)
                self.assertTrue(task.goal_delivered)


class TestLegacyPddlIsMarkedSuperseded(unittest.TestCase):
    """W7. The `.pddl` files predate Decisions 5/11 and disagree with the frozen IR on three
    counts (no `zone`, `explore` still an action, identifiers that `BoxId.parse` REJECTS). They
    stay in the tree as reference artifacts, so they must say so on their face — otherwise the
    next person to wire up a planner points it at a file that cannot round-trip an identifier."""

    PDDL_DIR = pathlib.Path(__file__).resolve().parents[1] / "functional_layer/custom_env/box_push/pddl"

    #: Each artifact must announce, on its face, that it is not the V1 model — and say why.
    REQUIRED_MARKERS = {
        "box_push_domain.pddl": ("SUPERSEDED FOR V1",),
        "box_push_problem.pddl": ("SUPERSEDED FOR V1",),
        "box_push_problem.pddl.soln": ("SUPERSEDED",),
        # The FOND variant's primary divergence is not staleness but SCOPE: it is
        # `:non-deterministic`, which `.claude/rules/v1-scope.md` puts outside V1 entirely.
        "box_push_domain_fond.pddl": ("NOT A V1 ARTIFACT", ":non-deterministic"),
    }

    def test_every_pddl_artifact_announces_that_it_is_not_the_v1_model(self):
        files = sorted(self.PDDL_DIR.glob("*.pddl")) + sorted(self.PDDL_DIR.glob("*.soln"))
        self.assertTrue(files, "no PDDL artifacts found; did the reference files move?")
        self.assertEqual(
            {p.name for p in files}, set(self.REQUIRED_MARKERS),
            "a PDDL artifact was added or removed without deciding how it is marked",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for marker in self.REQUIRED_MARKERS[path.name]:
                with self.subTest(file=path.name, marker=marker):
                    self.assertIn(marker, text)

    def test_the_fond_variant_is_marked_out_of_v1_scope_not_merely_stale(self):
        text = (self.PDDL_DIR / "box_push_domain_fond.pddl").read_text(encoding="utf-8")
        self.assertIn("OUT OF SCOPE", text)
        self.assertIn("oneof", text)
        self.assertIn("v1-scope.md", text)

    def test_the_verified_plan_is_recorded_in_exactly_one_place(self):
        """Two copies with different step ordering used to exist, and §J reasons from the
        ordering."""
        problem = (self.PDDL_DIR / "box_push_problem.pddl").read_text(encoding="utf-8")
        soln = (self.PDDL_DIR / "box_push_problem.pddl.soln").read_text(encoding="utf-8")
        self.assertIn("(goto_push_pose a1 box1)", soln)
        self.assertNotIn("(goto_push_pose a1 box1)", problem)
        self.assertNotIn("(cooperate_push a1 a2 box0)", problem)

    def test_the_identifier_divergence_is_real_and_still_recorded(self):
        """Not a stylistic difference: the legacy identifiers raise."""
        with self.assertRaises(ValueError):
            BoxId.parse("box0")
        self.assertEqual(BoxId.parse("box_0"), BOX_HEAVY)
        self.assertIn(
            "BoxId.parse", (self.PDDL_DIR / "box_push_problem.pddl").read_text(encoding="utf-8")
        )

    def test_documents_use_semantic_pddl_anchors_not_line_numbers(self):
        """Blocker 3 regression guard. Adding the 19-line `;; SUPERSEDED` banner silently shifted
        EVERY `box_push_domain.pddl:NN` citation in both authoritative documents — including the
        one carrying Decision 5's evidence, which landed on a banner rule. Line-only citations into
        these files are therefore banned; cite `:action push` / `(:init …)` instead."""
        docs = pathlib.Path(__file__).resolve().parents[1] / "docs"
        token = re.compile(r"(?P<file>[\w./-]+\.(?:py|pddl|soln))|`:(?P<line>\d+(?:-\d+)?)`")
        offenders = []
        for doc in sorted(docs.rglob("*.md")):
            for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                # (a) the adjacent form, `box_push_domain.pddl:47`
                if re.search(r"\.pddl(?:\.soln)?:\d", line):
                    offenders.append(f"{doc.relative_to(docs)}:{number} (adjacent form)")
                # (b) the bare form whose nearest preceding filename ON THE SAME LINE is a PDDL
                # artifact — the table-row and inline-parenthetical shape. Scoped to one line on
                # purpose: a cross-line prose reference cannot be attributed mechanically without
                # false positives (neighbouring bullets cite `.py` files with the same syntax), so
                # that case is a REVIEW matter, not a test. This guard catches the mechanical
                # regression — a citation that silently retargets when an artifact shifts.
                current = None
                for match in token.finditer(line):
                    if match.group("file"):
                        current = match.group("file")
                    elif current and current.endswith((".pddl", ".soln")):
                        offenders.append(
                            f"{doc.relative_to(docs)}:{number} bare `:{match.group('line')}` "
                            f"after {current}"
                        )
        self.assertEqual(
            offenders, [],
            "brittle PDDL line citations — cite `:action NAME` / `(:init …)` instead:\n"
            + "\n".join(offenders),
        )

    def test_every_section_reference_in_the_docs_resolves(self):
        """Renumbering has silently invalidated cross-references three times: §14→§17 when the
        decisions grew, §17→§18 when Decision 16 was inserted, and a §18.1 collision where the same
        token meant both a heading and a work-item. A dangling pointer in a frozen contract is a
        defect, so check it mechanically."""
        docs = pathlib.Path(__file__).resolve().parents[1] / "docs"
        headings = {}
        for doc in sorted(docs.rglob("*.md")):
            found = set()
            for line in doc.read_text(encoding="utf-8").splitlines():
                m = re.match(r"#{2,4} (\d+)(?:\.(\d+))?[a-z]?\.? ", line)
                if m:
                    found.add(m.group(1))
                    if m.group(2):
                        found.add(f"{m.group(1)}.{m.group(2)}")
            headings[doc] = found
        every = set().union(*headings.values())
        dangling = []
        for doc in sorted(docs.rglob("*.md")):
            for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                for m in re.finditer(r"§(\d+(?:\.\d+)?)", line):
                    if m.group(1) not in every:
                        dangling.append(f"{doc.relative_to(docs)}:{number} §{m.group(1)}")
        self.assertEqual(dangling, [], "dangling section references:\n" + "\n".join(dangling))

    def test_every_pddl_semantic_anchor_cited_in_the_docs_actually_exists(self):
        """The positive half, and the reliable one: an anchor that does not resolve is as broken as
        a shifted line number, and unlike prose proximity this can be checked exactly."""
        docs = pathlib.Path(__file__).resolve().parents[1] / "docs"
        # NOT the FOND variant: `.claude/rules/v1-scope.md` puts it outside V1, and it declares
        # every action name the classical domain does — so an anchor deleted from the classical
        # file would still resolve against a file nothing may plan with.
        artifacts = " ".join(
            p.read_text(encoding="utf-8")
            for p in sorted(self.PDDL_DIR.glob("*.pddl"))
            if not p.name.endswith("_fond.pddl")
        )
        cited = set()
        for doc in sorted(docs.rglob("*.md")):
            cited |= set(re.findall(r"`:action (\w+)`", doc.read_text(encoding="utf-8")))
        self.assertTrue(cited, "no semantic PDDL anchors are cited at all")
        for action in sorted(cited):
            with self.subTest(action=action):
                self.assertIn(f"(:action {action}", artifacts)

    def test_the_frozen_ir_is_named_as_the_authority(self):
        for path in sorted(self.PDDL_DIR.glob("*.pddl")):
            with self.subTest(file=path.name):
                self.assertIn("DOMAIN_IR", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
