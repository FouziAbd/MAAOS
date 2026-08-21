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
;; BoxPush — problem instance (2 agents, 2 boxes: one heavy, one light)
;;
;; Weights are given as prior knowledge (the "known weights" reading of the
;; description). Locations start UNKNOWN — nothing is discovered — so a valid
;; plan must explore before it can go to a pose and push.
;; ===========================================================================
(define (problem box-push-2agents-2boxes)
  (:domain box-push-skills)

  (:objects
    a1 a2   - agent
    box0 box1 - box)

  (:init
    ;; weights known up front; box0 heavy, box1 light
    (heavy box0)
    (light box1)
    ;; locations unknown (unexplored) and nothing delivered yet (pending)
    (unexplored box0) (unexplored box1)
    (pending box0)    (pending box1)
    ;; distinct-agent pairs (equality substitute for cooperate_push)
    (different a1 a2)
    (different a2 a1))

  (:goal (and (delivered box0) (delivered box1)))
)

;; Verified solvable with pyperplan (BFS): a 7-step plan delivering both boxes.
;;
;; The plan itself lives in ONE place — `box_push_problem.pddl.soln`. An inline copy used to sit
;; here and had DIFFERENT step ordering from the .soln, while `docs/handoff/section18.md` §J
;; reasons from that ordering; the duplicate is removed rather than re-synchronised.
;;
;; The recorded plan is SUPERSEDED for V1: it opens with two `explore` steps that Decision 5
;; removes from the symbolic action set. It records what was verified against THIS file, not a V1
;; plan. P2 re-runs the planner on the artifacts regenerated from DOMAIN_IR.
;;
;; To reproduce:  pyperplan box_push_domain.pddl box_push_problem.pddl
