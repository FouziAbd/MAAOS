# ADR-T1 — Probabilistic, domain-generic skill IR

- Status: Proposed
- Date: 2026-11-07
- Scope: thesis phase T1 (design only; implemented in T3, consumed by T4 and T5). Covered by the
  "Thesis exception" in `.claude/rules/v1-scope.md`.

## Context

The thesis (`docs/thesis/pomdp-plan-time-estimate.md`, decision 2 in `docs/thesis/HANDOFF.md`)
extends the existing skill IR rather than adding a second schema: named outcomes with probability
models, observations per outcome, and named parameters. Every V1 domain must load unchanged as the
single-outcome case. The owner decided on 2026-11-07 to generalize the IR **in place** first,
because it is BoxPush-bound today. That takes up the "STRIPS/IR generalization" item deferred in
`docs/domains/DOMAIN_KIT_IMPLEMENTATION.md`.

Evidence from the current code:

- `shared/skill_ir.py` `SkillIR.signature` is a `shared.skills.SkillSignature`, whose name is the
  BoxPush `SkillName` enum and whose parameter types are the BoxPush `ParameterType` enum.
  `SkillIR.__post_init__` accepts only `TYPE_UNIVERSE` (agent, box, zone) and the
  `_SIGNATURE_TO_IR_TYPES` expansion. `DomainIR.__post_init__` requires
  `s.signature is REGISTRY.get(s.name)`. `bind`/`unbind` build `AgentId`, `BoxId`, `ZoneId`, and
  `resolve()` falls back to the BoxPush `REGISTRY`.
- Only `domain/box_push_v1.py` builds a `DomainIR`. `symbolic/` (applicability, planner, predictor,
  monitor, belief, `pddl_gen`) consumes it. `domains/cooperative_grid`, `tests/fixture_lamp`,
  `tests/probe_counter.py` and `kit/` never import `shared.skill_ir`. They plan with `kit.bfs_plan`
  over their own call types.
- `outcome_label` is one scalar. The module docstring already states that an outcome distribution
  "will require a schema change".
- Byte pins the change must not move: `GOLDEN_DOMAIN_DIGEST = "b41503536b3bcbe1"` in
  `tests/test_contract_invariants.py`, which also checks it in a subprocess under
  `PYTHONHASHSEED=12345`. Other tests pin the hashing scheme (`tests/test_domain_freeze.py`), the
  V1 `.pddl` files against `symbolic.pddl_gen.v1_artifacts()` (`tests/test_p2_pddl.py`), both demo
  transcripts (`tests/test_r0_characterization.py`) and the acceptance traces
  (`tests/test_v1_acceptance.py`).
- Surface pins: every public class in a `shared` module is exported from `shared/__init__.py`
  (`tests/test_observation_contract.py`). Every class with `canonical()` is listed in
  `tests/test_canonical_faithfulness.py`. No identifier in the production packages contains
  `probe` or `counter` (`tests/test_r5_probe.py`).
- The partially observable domain needs constructs the V1 cooperative_grid model checks in Python
  (`domains/cooperative_grid/model.py`, `Model.applicable`): "the handle is taken", "the door is
  not open", "the agent stands on a handle", "the goal needs an open door". It also needs the
  hidden jam, the noisy rattle, the pull slip, and the two corridor refusals of `Goto`.

## Decision

### 1. Two kinds of domain, one IR

A `DomainIR` is either a **registry domain** or a **declared domain**.

- **Registry domain (V1, BoxPush).** Every skill's signature is a `SkillSignature` from the frozen
  `REGISTRY`. The current checks stay exactly as they are: the agent/box/zone universe, the
  signature expansion, registry identity, `bind`/`unbind` and the `resolve()` fallback to the
  registry. A registry domain **may not use any field added by this ADR**. Construction raises
  `ValueError` otherwise. `symbolic/` therefore never meets semantics it would silently ignore.
- **Declared domain (new).** Every skill's signature is a new
  `ActionSignature(name: str, parameters: Tuple[ActionParameter, ...], cost: int = 1)`, with
  `ActionParameter(name: str, type: str)`. The name is an identifier, and no packing or agent-pair
  expansion happens. `SkillIR.parameters` and `parameter_types` must equal the signature's names
  and types, in order. Types must be members of `DomainIR.types`, which is checked by `DomainIR`
  because the domain owns its universe.
- A domain that mixes the two kinds raises `ValueError`.
- `DomainIR.types` keeps its default `TYPE_UNIVERSE`. Predicate and skill type checks read
  `self.types` instead of the module constant. For BoxPush the two are the same tuple, so its
  behavior does not change.
- For declared-domain skills, `bind`/`unbind` raise `TypeError`. A new
  `SkillIR.bind_values(values: Sequence[str]) -> Dict[str, str]` binds positionally. Each domain
  package maps its own call type to that value tuple. For example, cooperative_grid_po maps
  `Call.op` plus its fields.
- On a declared domain, `resolve()` returns the skill or raises `KeyError`. It never consults the
  registry.

### 2. New declarations on `DomainIR` (all default to empty)

- `constants: Tuple[ObjectDecl, ...]`, with `ObjectDecl(name, type)`. These are named objects
  that skills may mention, as PDDL `:constants` are. Lifted arguments may name a skill parameter
  or a constant.
- `parameters: Tuple[ParameterDecl, ...]`, with
  `ParameterDecl(name, prior, value: Optional[...] = None, note="")`. The prior is a
  `BetaPrior(a, b)` or a `DirichletPrior(alphas)`, and every number is a positive rational.
  `value` is the given or fitted value: one probability for a Beta parameter, a tuple summing to 1
  for a Dirichlet. When `value` is absent, consumers use the prior mean. The pseudo-count cap of 2
  for LLM-written priors is a generation rule, enforced by the generator and not by the IR.
- `observation_channels: Tuple[ObservationChannelDecl, ...]`, with
  `ObservationChannelDecl(name, symbols)`. The first symbol is the channel's default. It is
  reported when no observation case applies and when the action is inapplicable.
- `PredicateDecl.observable: bool = True`. `False` marks a hidden predicate, which lives only in
  the backend and in a belief.

### 3. New fields on `SkillIR` (all default to empty)

- `negative_preconditions: Tuple[Predicate, ...]`, as in PDDL `:negative-preconditions`.
- `outcomes: Tuple[Outcome, ...]`, with `Outcome(label, effects)`. When outcomes are present,
  `SkillIR.effects` must be empty and `outcome_label` must name one of them: the **nominal
  outcome**. The deterministic relaxation keeps only nominal outcomes, which is exactly the
  optimistic twin, so it stays derivable from the same IR. With no outcomes, the skill is the V1
  case: one deterministic outcome `outcome_label` with `effects`.
- `outcome_cases: Tuple[OutcomeCase, ...]`, a decision list with
  `OutcomeCase(when: Tuple[Atom, ...], distribution)`. The first case whose `when` holds in the
  pre-state applies. The last case must have an empty `when`, so the list is exhaustive and
  exclusive by construction. A skill with exactly one outcome needs no cases.
- `observation_cases: Tuple[Tuple[str, Tuple[ObservationCase, ...]], ...]`, one decision list per
  channel the skill reports on. Each has the shape `ObservationCase(when, distribution)`. A
  channel's `when` atoms are evaluated on the **post-state** and the bound parameters only. This
  is O(o | a, s′), the `observation(m, a, sp)` convention of POMDPs.jl. A channel the skill does
  not list reports its default symbol.
- **Atoms** are the following:
  - `LiftedLiteral(predicate: Predicate, positive: bool = True)`.
  - `ParameterEquals(parameter, constant)`, allowed only in case conditions.
- **Wildcard.** An argument `"*"` ranges over every object of the declared argument type.
  - In a negative precondition it means "no grounding holds". For example, `not at(*, place)`
    means the place is free.
  - In a negative effect it means "delete every grounding". For example, `not at(agent, *)`
    leaves every place before `at(agent, place)` is added.
  - It is allowed nowhere else.
- **Distributions** come in three forms, each normalized by construction:
  - `Deterministic(label)`;
  - `Bernoulli(p, then_label, else_label)`, where `p` names a Beta parameter or is a rational
    constant;
  - `Categorical(parameter, labels)`, over a Dirichlet parameter of matching arity.

  The labels are outcome labels in outcome cases and channel symbols in observation cases. One
  parameter may appear in several cases. For example, rattle accuracy is used in both branches,
  with the labels swapped.
- **Hidden predicates may not appear in preconditions**, positive or negative. Applicability, and
  with it the executive's validation gate, reads only what the planner can know. Hidden
  predicates may appear in outcome cases, effects and observation cases.

### 4. Problem records

`ProblemIR` lives in `shared/skill_ir.py` with:

- `name`;
- `domain`, the domain name;
- `objects`, extra `ObjectDecl`s beyond the domain constants;
- `init`, the observable ground literals true at reset; static predicates are given here too;
- `hidden_prior: Tuple[HiddenPrior, ...]`, where `HiddenPrior(literal, p)` makes the hidden ground
  literals independent Bernoullis;
- `goal`, a conjunction of ground literals;
- `rewards: RewardModel(step, skills, goal)`, all rational constants copied from the
  specification: `step` per cycle, `skills` as an extra amount per skill name, `goal` on arrival;
- `discount`, a rational in the open interval from 0 to 1.

Ground literals reuse the `Predicate` canonical shape, with object names as arguments.

### 5. Semantics the compiler and reference evaluator implement (T4)

**State and actions.**
- A state is the set of true ground literals of the fluent predicates, observable and hidden.
  Static predicates come from `init` and never change.
- Actions are all groundings of the skills over the objects, in a deterministic order: skill
  order, then lexicographic argument order.

**Transition, for a state s and an action a.**
- If any precondition fails in s, the action is inapplicable. Then s′ = s, every channel reports
  its default symbol, and the reward is `step`.
- Otherwise the first matching outcome case gives a distribution over outcomes.
- Each outcome's effects apply deletes first, then adds, as in PDDL. V1 skills have no literal
  that is both added and deleted, so ordering cannot matter for them.

**Observation.** It is the pair of the observable fluent literals of s′ and the per-channel
symbols, each drawn from its channel's first matching observation case on s′.

**Reward.** R(s, a) = `step` + `skills[a]` + `goal` × P(s′ satisfies the goal | s, a), for any s
that is not a goal state. This folds the arrival reward into E[r | s, a], the form POMDPTools'
`SparseTabularPOMDP` stores. Goal states are absorbing, with zero reward and default
observations.

**Initial belief.** The observable `init` combined with the product of the hidden priors.
Reachable states are enumerated from the support of that belief.

**The derived DBN view (`pomdp/dbn.py`).** It is a function of the IR, never stored:
- the parents of each skill's outcome are the literals and equalities in its outcome cases and
  preconditions;
- the children are the predicates its outcome effects touch;
- the observation parents are the literals in its observation cases, read on s′.

Its checks: no hidden predicate in a precondition; no literal both added and deleted within one
outcome; every observation parent is a post-state literal; and every effect predicate is a
declared fluent. A two-slice model with these rules has no intra-slice edges, so acyclicity holds
by construction.

### 6. Canonical form is the LLM schema

- `canonical()` emits a new key only when its value differs from the default. For BoxPush the
  canonical JSON, and therefore the digest, is byte-identical.
- A new `DomainIR.from_canonical(data)` and `ProblemIR.from_canonical(data)` rebuild the
  records. For a registry domain, skill signatures are looked up by name in `REGISTRY`.
- Required property: `from_canonical(x.canonical()).digest() == x.digest()` for BoxPush and for
  every declared fixture. The result is equal by digest, not object-equal:
  `PredicateDecl.description` and `Provenance.note` are not canonical, which is unchanged V1
  behavior.
- The canonical JSON is the single exchange format for the LLM generator, typed repair patches
  and the committed fixtures. Rationals are written as strings (`"9/10"`) and read with
  `fractions.Fraction`, so the reference evaluator stays exact.

Shape of a declared skill and distributions (CoopGrid-Jam-PO, `ClearJam`):

```json
{
  "name": "ClearJam",
  "parameters": ["agent", "place", "door"],
  "parameter_types": ["agent", "place", "door"],
  "preconditions": [{"name": "at", "args": ["agent", "place"]},
                    {"name": "handle", "args": ["place"]}],
  "negative_preconditions": [{"name": "open", "args": ["door"]}],
  "effects": [],
  "outcome_label": "freed",
  "outcomes": [
    {"label": "freed", "effects": [{"predicate": {"name": "jammed", "args": ["door"]},
                                    "positive": false}]},
    {"label": "unchanged", "effects": []}
  ],
  "outcome_cases": [
    {"when": [{"literal": {"name": "jammed", "args": ["door"]}, "positive": true}],
     "distribution": {"bernoulli": {"p": {"parameter": "shake_success"},
                                    "then": "freed", "else": "unchanged"}}},
    {"when": [], "distribution": {"deterministic": "unchanged"}}
  ],
  "observation_cases": {
    "status": [{"when": [], "distribution": {"deterministic": "ok"}}],
    "rattle": [
      {"when": [{"literal": {"name": "jammed", "args": ["door"]}, "positive": true}],
       "distribution": {"bernoulli": {"p": {"parameter": "rattle_accuracy"},
                                      "then": "rattle_jam", "else": "rattle_free"}}},
      {"when": [], "distribution": {"bernoulli": {"p": {"parameter": "rattle_accuracy"},
                                                  "then": "rattle_free", "else": "rattle_jam"}}}
    ]
  },
  "cost": 1, "dependencies": [], "observations": [], "predicted_world_effects": [],
  "provenance": {"source": "...", "model_version": "..."}
}
```

A `ParameterEquals` atom is written `{"equals": ["agent", "A"]}`. A rational constant
probability is written `{"value": "1/2"}`.

### 7. The true-model IR of CoopGrid-Jam-PO (the T4 and T5 fixture)

The partially observable domain chooses a call vocabulary that this IR expresses exactly. It
differs from the V1 cooperative_grid on purpose: that package stays frozen, and this is a new one.

| Skill | Preconditions | Outcomes and cases | Observations |
|---|---|---|---|
| `Goto(agent, place)` | `handle(place)`; not `at(*, place)` | `arrived` {not `at(agent, *)`, `at(agent, place)`}, nominal; `refused` {}. Cases: [`agent = A`, `place = handle_right`, `at(B, handle_left)`] gives `refused`; [`agent = B`, `place = handle_left`, `at(A, handle_right)`] gives `refused`; otherwise `arrived` | status: [`at(agent, place)`] gives `ok`, otherwise `fail` |
| `Enter(agent, door)` | `open(door)`; not `at(agent, goal)` | `arrived` {not `at(agent, *)`, `at(agent, goal)`}, deterministic | status `ok` |
| `CooperateOpen(agent, door, partner)` | `at(agent, handle_left)`, `at(partner, handle_right)`; not `open(door)` | `opened` {`open(door)`}, nominal; `stuck` {}. Cases: [`jammed(door)`] gives `stuck`; otherwise Bernoulli(`pull_success`, `opened`, `stuck`) | status: [`open(door)`] gives `ok`, otherwise `fail` |
| `ClearJam(agent, place, door)` | `at(agent, place)`, `handle(place)`; not `open(door)` | as in the JSON above | status `ok`; rattle as above |

- **Declarations.**
  - Types: `agent`, `place`, `door`.
  - Constants: `A`, `B` (agent); `handle_left`, `handle_right`, `goal` (place); `door` (door).
  - Predicates: `at(agent, place)` and `open(door)` are fluent and observable; `handle(place)` is
    static; `jammed(door)` is fluent and **hidden**.
  - An agent with no `at` literal is in the hall.
- **Channels.** `status` {`none`, `ok`, `fail`} and `rattle` {`none`, `rattle_jam`,
  `rattle_free`}.
- **Parameters.** These are the true values from the design defaults:
  - `jam_prior` Beta(1, 1), value `1/2`;
  - `pull_success` Beta(1, 1), value `9/10`, a single joint slip;
  - `shake_success` Beta(1, 1), value `7/10`;
  - `rattle_accuracy` Beta(1, 1), value `17/20`.
- **Problem.**
  - `init` = {`handle(handle_left)`, `handle(handle_right)`}, with both agents in the hall and the
    door closed.
  - `hidden_prior` = {`jammed(door)` ~ `jam_prior`}.
  - `goal` = {`at(A, goal)`, `at(B, goal)`}.
  - `rewards`: `step` −1/50 (−0.01 per agent per cycle), `ClearJam` −1/20, `goal` 2 (+1 per
    agent).
  - `discount` 19/20.
- **Grounded actions.**
  - `Goto` has 6 groundings (2 agents × 3 places), of which 4 are ever applicable;
    `Enter` has 2; `CooperateOpen` has 4, of which 2 are ever applicable; `ClearJam` has 6,
    of which 4 are ever applicable.
  - Inapplicable groundings stay in the action set as self-loops. The compiler may drop actions
    that are inapplicable in every reachable state, and must report how many it dropped.
- **Ground-truth check.** The two corridor refusals are the design's reading of the backend. The
  G-W3 empirical check in T5, which compares the seeded wrapper's frequencies with the compiled
  tables, is what confirms them. If it disagrees, the fixture is wrong, not the backend.
- **The T2 spike's description.** It must use this call vocabulary: `Goto` to handles, `Enter`
  for the goal, and `ClearJam` naming its handle.

## Alternatives considered

- **A second schema module** next to an untouched `skill_ir.py`. Rejected by handoff decision 2
  and by the owner on 2026-11-07, because the LLM, the fitter and the executive would drift
  between two models.
- **Free probability expressions** (`Param`, `OneMinus`, `Product`) checked for summing to 1.
  Rejected. They need symbolic or sampled identity checks, give the LLM more ways to be wrong,
  and lose the conjugate Beta/Dirichlet counting the fitter relies on. Three normalized
  distribution forms cover both thesis domains.
- **Exhaustive parent-assignment tables** instead of decision lists. Rejected: the table grows as
  2^k in the number of parents, while a decision list with a mandatory default case is compact,
  exclusive and exhaustive.
- **Multi-valued state variables (SAS+)** instead of boolean predicates with a wildcard delete.
  Deferred. They are cleaner for enumeration, but the V1 IR is STRIPS, and the wildcard delete
  plus negative preconditions express "one place per agent" and "the handle is free" with a
  smaller change.
- **Existential preconditions or disjunction**, such as "on some handle". Rejected for now. The
  partially observable domain names the handle in the call instead (`ClearJam(agent, place,
  door)`), which keeps preconditions conjunctive.
- **Julia, RDDL or Python code as the primary model.** Rejected: the supervisor's rule is
  structured data, not code (design doc, Step 2). RDDL export is extension package X8.

## Consequences

- BoxPush and the V1 `symbolic/` package see no change. Registry domains cannot use the new
  fields, and their canonical form and digest are unchanged.
- The kit domains (`cooperative_grid`, `tests/fixture_lamp`) are unaffected. They still do not use
  the IR.
- `cooperative_grid_po` uses the IR for the compiler and the evaluator (T4). In T5 its kit model
  is written to agree with the nominal (optimistic) relaxation, and a test pins that agreement.
- Typed repair patches (weeks 6–8) operate on the canonical JSON.
- Each structural change bumps `ModelVersion.revision` and is recorded with `ModelPatch`, which is
  unchanged.
- New debt, with its cleanup:
  - **DEBT-T3-REGISTRY:** two validation paths inside `DomainIR`. Cleanup: `box_push_po_lite`
    (weeks 9–11) is a declared domain, and the registry path is then reviewed for retirement.
  - **DEBT-T1-SAS:** boolean predicates only. Cleanup: revisit SAS+ variables if
    `box_push_po_lite` needs them for pose.

## Code/schema impact

- **`shared/skill_ir.py`:** gains `ActionParameter`, `ActionSignature`, `ObjectDecl`,
  `BetaPrior`, `DirichletPrior`, `ParameterDecl`, `ObservationChannelDecl`, `LiftedLiteral`,
  `ParameterEquals`, `Deterministic`, `Bernoulli`, `Categorical`, `Outcome`, `OutcomeCase`,
  `ObservationCase`, `HiddenPrior`, `RewardModel` and `ProblemIR`, plus the `WILDCARD` constant.
  `SkillIR`, `PredicateDecl` and `DomainIR` get the new fields with empty defaults, plus
  `bind_values`, `from_canonical` and the `is_registry_domain` property. `shared` stays
  stdlib-only.
- **`shared/__init__.py`:** exports the new public names.
- **`tests/test_canonical_faithfulness.py`:** `CASES` entries for every new class with
  `canonical()`.
- **No change** to `domain/`, `symbolic/`, `nl/`, `runtime/`, `kit/`, `app/`, `domains/`, the
  PDDL artifacts or any trace.

## Acceptance evidence (T3)

- **Existing tests, unchanged and passing:** the golden digest (`tests/test_contract_invariants.py`,
  including the hash-seed subprocess), `tests/test_domain_freeze.py`,
  `tests/test_prediction_and_monitoring.py`, `tests/test_p2_pddl.py`, the demo transcripts
  (`tests/test_r0_characterization.py`), the acceptance traces (`tests/test_v1_acceptance.py`),
  and ruff and mypy on the gate.
- **New `tests/test_t3_skill_ir.py`:**
  - BoxPush canonical JSON has none of the new keys, and its `from_canonical` round trip has an
    equal digest.
  - A registry domain that uses any new field raises.
  - A mixed domain raises.
  - The CoopGrid-Jam-PO fixture above builds, and its round trip has an equal digest.
  - Each of these raises `ValueError`: a hidden predicate in a precondition; a wildcard outside
    the two allowed places; `ParameterEquals` outside a case; a last case that is not
    unconditional; an unknown outcome label or channel symbol; an undeclared parameter; a
    Bernoulli over a Dirichlet parameter; a Dirichlet value that does not sum to 1; a duplicate
    outcome label; a nominal label that is not an outcome; outcomes declared together with V1
    `effects`; and an undeclared constant or type.
  - `bind_values` binds positionally, and `bind`/`unbind` raise `TypeError` on a declared skill.
- **Suite-count pin** updated in `docs/refactor/REFACTOR_STATUS.md` in the same change set.
