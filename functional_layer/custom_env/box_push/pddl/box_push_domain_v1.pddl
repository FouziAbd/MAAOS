;; GENERATED FROM domain/box_push_v1.py::DOMAIN_IR by symbolic/pddl_gen.py — DO NOT
;; HAND-EDIT. Regenerate via `python -m symbolic.pddl_gen` (or the regeneration test
;; will fail on any drift between this file and the frozen IR).

(define (domain box-push-skills-v1)
  (:requirements :strips :typing)
  (:types agent box zone - object)

  (:predicates
    (delivered ?x0 - box)
    (different ?x0 - agent ?x1 - agent)
    (discovered ?x0 - box)
    (heavy ?x0 - box)
    (in_pose ?x0 - agent ?x1 - box)
    (light ?x0 - box)
    (pending ?x0 - box)
  )

  (:action cooperate_push
    :parameters (?agent1 - agent ?agent2 - agent ?box - box ?zone - zone)
    :precondition (and (different ?agent1 ?agent2) (heavy ?box) (in_pose ?agent1 ?box) (in_pose ?agent2 ?box) (pending ?box))
    :effect (and (delivered ?box) (not (pending ?box)) (not (in_pose ?agent1 ?box)) (not (in_pose ?agent2 ?box)))
  )

  (:action goto_push_pose
    :parameters (?agent - agent ?box - box ?zone - zone)
    :precondition (and (discovered ?box) (pending ?box))
    :effect (and (in_pose ?agent ?box))
  )

  (:action push
    :parameters (?agent - agent ?box - box ?zone - zone)
    :precondition (and (in_pose ?agent ?box) (light ?box) (pending ?box))
    :effect (and (delivered ?box) (not (pending ?box)) (not (in_pose ?agent ?box)))
  )
)
