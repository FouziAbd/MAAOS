;; ===========================================================================
;; NOT A V1 ARTIFACT — RESEARCH / REFERENCE ONLY, OUT OF SCOPE FOR P0-P4
;;
;; PRIMARY divergence: this domain is `:non-deterministic` and uses `(oneof ...)`. V1 is
;; deterministic at the symbolic level by decision — see `.claude/rules/v1-scope.md` ("Do not
;; implement stochastic ... FOND ... unless explicitly requested") and P0_V1_DECISIONS Decision 5,
;; which resolves the weight-discovery question in favour of the KNOWN-WEIGHTS reading. Nothing in
;; P0-P4 may plan against this file, and no V1 contract is derived from it.
;;
;; It also diverges structurally from the frozen V1 model: a different predicate set
;; (`weight-known`; no `pending`/`light`), a `wait` action, no `zone` parameter, and object
;; identifiers that the frozen contract rejects (`BoxId.parse("box0")` raises ValueError).
;;
;; The authoritative V1 symbolic model is `domain/box_push_v1.py::DOMAIN_IR`.
;; ===========================================================================
;; ===========================================================================
;; BoxPush — skill-level FOND domain (weight discovered by pushing)
;;
;; The "faithful" reading of the description: a box's weight is UNKNOWN until an
;; agent pushes it. A lone push on an unknown box has two possible outcomes:
;;   - the box was light  -> delivered, and now known light
;;   - the box was heavy  -> not delivered, and now known heavy (must cooperate)
;; This nondeterminism needs Fully-Observable Non-Deterministic planning
;; (:non-deterministic, (oneof ...)) — solved by a contingent/FOND planner
;; (e.g. PRP, myND). Contrast with the deterministic known-weights domain.
;; ===========================================================================
(define (domain box-push-skills-fond)
  (:requirements :strips :typing :equality :non-deterministic)

  (:types agent box - object)

  (:predicates
    (discovered   ?b - box)
    (delivered    ?b - box)
    (weight-known ?b - box)
    (heavy        ?b - box)         ; becomes known only after a push reveals it
    (in-pose      ?a - agent ?b - box))

  (:action explore
    :parameters (?a - agent ?b - box)
    :precondition (not (discovered ?b))
    :effect (discovered ?b))

  (:action goto_push_pose
    :parameters (?a - agent ?b - box)
    :precondition (and (discovered ?b) (not (delivered ?b)))
    :effect (in-pose ?a ?b))

  ;; push on an UNKNOWN-weight box: nondeterministic — reveals the weight.
  (:action push
    :parameters (?a - agent ?b - box)
    :precondition (and (in-pose ?a ?b) (not (weight-known ?b)) (not (delivered ?b)))
    :effect (oneof
              ;; it was light: delivered, weight now known
              (and (delivered ?b) (weight-known ?b) (not (in-pose ?a ?b)))
              ;; it was heavy: no move, weight now known (must cooperate later)
              (and (heavy ?b) (weight-known ?b))))

  ;; once known heavy, only cooperate_push works.
  (:action cooperate_push
    :parameters (?a1 - agent ?a2 - agent ?b - box)
    :precondition (and (not (= ?a1 ?a2))
                       (weight-known ?b) (heavy ?b)
                       (in-pose ?a1 ?b) (in-pose ?a2 ?b)
                       (not (delivered ?b)))
    :effect (and (delivered ?b)
                 (not (in-pose ?a1 ?b)) (not (in-pose ?a2 ?b))))

  (:action wait
    :parameters (?a - agent)
    :precondition ()
    :effect ())
)
