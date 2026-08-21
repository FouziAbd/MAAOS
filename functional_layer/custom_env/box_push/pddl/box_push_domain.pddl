;; ===========================================================================
;; SUPERSEDED FOR V1 — REFERENCE / HISTORICAL ARTIFACT, NOT THE V1 MODEL
;;
;; The authoritative V1 symbolic model is `domain/box_push_v1.py::DOMAIN_IR`.
;; P2 RE-ISSUES these files FROM `DOMAIN_IR` rather than hand-editing them, so that the
;; PDDL cannot drift from the frozen IR again. Until then, do not plan against these files.
;;
;; Three recorded divergences from the frozen V1 contract
;; (P0_V1_DECISIONS.md Decision 5, Decision 11, §18 item 1):
;;
;;   1. NO `zone` PARAMETER. Decision 11 freezes `zone` on goto_push_pose / push /
;;      cooperate_push in every layer; these actions have none.
;;   2. `explore` IS STILL AN ACTION and the problem starts `(unexplored ...)`. Decision 5
;;      makes V1 fully observable from initialization: every box is `discovered` at t=0 and
;;      `Explore` leaves the symbolic action set (it stays registry/backend-only).
;;   3. OBJECT IDENTIFIERS DO NOT PARSE. Objects here are `a1 a2 box0 box1`; the frozen
;;      contract uses `agent_0 agent_1 box_0 box_1`, and `BoxId.parse("box0")` RAISES
;;      ValueError. A planner wired to these files fails on every un-lift.
;; ===========================================================================
;; ===========================================================================
;; BoxPush — skill-level classical domain (known weights)
;;
;; Derived ONLY from box_push_problem_description.md. Actions ARE the skills.
;; No grid, no coordinates, no movement primitives. Deterministic / STRIPS.
;;
;; "Known weights" reading: the description says one box is light and one is heavy,
;; so weights are given as facts in the problem instance (prior knowledge). This
;; yields a clean, solvable STRIPS model. The discovery-by-pushing reading is in
;; the FOND variant (box_push_domain_fond.pddl).
;;
;; Pure-positive preconditions: instead of (not (discovered ?b)) / (not (delivered ?b))
;; we use complement predicates (unexplored ?b) / (pending ?b), so the model stays in
;; plain STRIPS that any classical planner accepts. Negative EFFECTS (delete lists) are
;; standard STRIPS and used freely.
;; ===========================================================================
(define (domain box-push-skills)
  (:requirements :strips :typing)

  (:types agent box - object)

  (:predicates
    (discovered ?b - box)          ; a box's location is known (found by explore)
    (unexplored ?b - box)          ; complement of discovered (for a positive precond)
    (delivered  ?b - box)          ; a box is on the goal zone (task sub-goal)
    (pending    ?b - box)          ; complement of delivered (for a positive precond)
    (light      ?b - box)          ; weight facts (given as prior knowledge)
    (heavy      ?b - box)
    (in-pose    ?a - agent ?b - box)   ; agent a is behind box b, ready to push it
    (different  ?a1 - agent ?a2 - agent)) ; distinct-agent pairs (equality substitute)

  ;; explore: an agent searches and discovers a box's location.
  (:action explore
    :parameters (?a - agent ?b - box)
    :precondition (unexplored ?b)
    :effect (and (discovered ?b) (not (unexplored ?b))))

  ;; goto_push_pose: get behind a known, undelivered box.
  (:action goto_push_pose
    :parameters (?a - agent ?b - box)
    :precondition (and (discovered ?b) (pending ?b))
    :effect (in-pose ?a ?b))

  ;; push (light): one agent in pose delivers a LIGHT box.
  (:action push
    :parameters (?a - agent ?b - box)
    :precondition (and (in-pose ?a ?b) (light ?b) (pending ?b))
    :effect (and (delivered ?b) (not (pending ?b)) (not (in-pose ?a ?b))))

  ;; cooperate_push: two distinct agents, both in pose, deliver a HEAVY box.
  ;; The two-agent parameter list encodes the "both at once" rule without needing
  ;; timestep concurrency — it is a joint macro-action.
  (:action cooperate_push
    :parameters (?a1 - agent ?a2 - agent ?b - box)
    :precondition (and (different ?a1 ?a2)
                       (heavy ?b)
                       (in-pose ?a1 ?b) (in-pose ?a2 ?b)
                       (pending ?b))
    :effect (and (delivered ?b) (not (pending ?b))
                 (not (in-pose ?a1 ?b)) (not (in-pose ?a2 ?b))))

  ;; NOTE: the `wait` skill is a no-op and is never needed to reach the goal, so it is
  ;; omitted from this solvable classical domain (an empty-precondition/-effect action is
  ;; also rejected by some PDDL parsers). It is retained in the RDDL model, where a
  ;; per-agent "do nothing this cycle" fluent is meaningful.
)
