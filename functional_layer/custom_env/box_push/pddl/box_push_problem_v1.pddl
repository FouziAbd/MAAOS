;; GENERATED FROM domain/box_push_v1.py::DOMAIN_IR by symbolic/pddl_gen.py — DO NOT
;; HAND-EDIT. Regenerate via `python -m symbolic.pddl_gen` (or the regeneration test
;; will fail on any drift between this file and the frozen IR).

(define (problem box-push-v1-deliver-both)
  (:domain box-push-skills-v1)
  (:objects
    agent_0 agent_1 - agent
    box_0 box_1 - box
    delivery_zone - zone
  )
  (:init
    (different agent_0 agent_1)
    (different agent_1 agent_0)
    (discovered box_0)
    (discovered box_1)
    (heavy box_0)
    (light box_1)
    (pending box_0)
    (pending box_1)
  )
  (:goal (and (delivered box_0) (delivered box_1)))
)
