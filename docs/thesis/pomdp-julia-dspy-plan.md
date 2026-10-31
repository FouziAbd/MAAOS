# Teaching MAAOS to Plan Under Uncertainty

MAAOS should enter POMDP territory through a new Domain-Kit package built on its newest domain, cooperative_grid: the designed hidden door jam becomes a state variable with a Bernoulli prior, SHAKE becomes a noisy Tiger-style sensing action and the joint PULL may slip, yielding a centralized skill-level POMDP of at most 49 states that exact Julia solvers handle easily, after which the same machinery scales to a BoxPush-PO flagship with hidden weight, stale pose and lane blockage (577 states under joint actions). The LLM should write neither Julia nor probabilities; it should emit a typed, factored JSON model of structure plus named parameters with weak priors, which a deterministic compiler turns into one concrete `SparseTabularPOMDP` for SARSOP, NativeSARSOP or QMDP (or a generative model for POMCP and DESPOT), while a fitter estimates the numbers from backend logs and Python drives Julia through juliacall once per decision, with StableRNG seeds and iteration budgets so traces stay byte-identical. DSPy's GEPA optimizer, fed a cascaded metric that returns textual feedback (compile, normalization, held-out log-likelihood, then planner-in-the-loop return and discrepancy rate), is the best-supported way to improve the generator, with the local gemma4:e4b as task model and a stronger reflection model. The literature leaves a clear gap: classical Dec-POMDP and MPOMDP solvers assume hand-built models and hand-designed structure, LLM multi-agent planners keep the LLM in the per-step loop and repair plans rather than models, and LLM-generated POMDP work is single-agent ([POMDP Coder](https://arxiv.org/html/2505.02216v2), [Pinductor](https://arxiv.org/html/2605.13740v1)). Two prerequisites gate everything: the owner must record the POMDP domain as the "real next domain", because project rules forbid probabilistic semantics and Julia compilation otherwise ([v1-scope.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/.claude/rules/v1-scope.md#L19-L36)), and the `dspy-ai==3.1.0` pin must be replaced, since it is a meta-package that actually resolves to dspy 3.3.1 or 3.4.0 ([PyPI dspy-ai](https://pypi.org/project/dspy-ai/)). The largest unknown is not solver capacity but whether a ~4B local model can write correct structure at all, because Pinductor found a threshold-like dependence on model capability, with its weaker Qwen3-14B model earning near-zero reward.

## MAAOS is a deterministic MMDP one belief away from a POMDP

Today MAAOS plans over exact state. Each cycle, the loop copies `export_full_state()` into the symbolic track, runs a deterministic breadth-first planner, enacts only the head of the plan and re-plans ([runtime/loop.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/runtime/loop.py#L1-L11), [loop sync and plan head](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/runtime/loop.py#L213-L220), [symbolic/planner.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/symbolic/planner.py#L1-L141)). "Belief" is a projection of the authoritative snapshot, which the belief module describes as "exact, never dead-reckoned", plus executive-tracked fluents such as `in_pose` that it updates from typed execution outcomes ([symbolic/belief.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/symbolic/belief.py#L1-L19)). Every environment already exposes a public `observe()` channel, yet nothing in the runtime reads it except one validator aliasing check ([environment contract](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/contracts/environment.py#L1-L54), [app/validation.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/app/validation.py#L396-L407)), and the frozen observation contract keeps BoxPush's 3×3 egocentric view "PRESERVED for later partial-observation milestones" while hiding it from both tracks ([shared/observation.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/observation.py#L1-L64)).

Formally, this is a **deterministic multi-agent MDP (MMDP), which is P-complete**. Its natural partially observable upgrade is a **multi-agent POMDP (MPOMDP): one POMDP over pooled observations, which is PSPACE-complete**, not a Dec-POMDP, whose finite-horizon problems are NEXP-complete even for a small number of agents ([Oliehoek & Amato 2016](https://www.ccs.neu.edu/home/camato/publications/OliehoekAmato16book.pdf), [Bernstein, Zilberstein & Immerman](https://arxiv.org/abs/1301.3836)). The repo already reached this conclusion for its own BoxPush runner, calling it "effectively a single-agent POMDP over the joint skill space, not a Dec-POMDP" ([BoxPush_Centralized_POMDP.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/BoxPush_Centralized_POMDP.md#L9-L21)). Because free communication cannot hurt, an MPOMDP's value upper-bounds the Dec-POMDP value of the same model, and every comparison with published numbers must say which of the two it reports.

The architecture already has the three seams a POMDP needs, but each carries a V1 obligation that must be relaxed. A belief belongs in a new `SymbolicTrack`, "the belief-holding symbolic seam" whose `record_outcome` is "evidence intake only", yet whose `sync` today means "adopt the authoritative state" ([tracks.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/contracts/tracks.py#L32-L48)). An external solver belongs behind `DomainServices.plan`, where the plan-every-cycle lifecycle already suits a receding-horizon solver and `PlannerFailure(timed_out=True)` ([planner_result.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/planner_result.py#L98-L119)) already routes solver timeouts to the fault path, although DK042 requires two calls on the same state to return the same plan, so every sampling solver must be seeded, and reseeded before each call ([domain.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/contracts/domain.py#L80-L91), [DK042](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/app/validation.py#L446-L452)). Observations would enter through `observe()`, but prediction and monitoring compare keys for equality, `Prediction` carries no distribution, and the IR's single `outcome_label` comes with its own warning that "adding an outcome DISTRIBUTION will require a schema change" ([Prediction](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/contracts/domain.py#L62-L68), [skill_ir.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/skill_ir.py#L1-L146)). Without those changes, every unlucky stochastic draw would surface as an execution discrepancy.

The governance gate is explicit and comes first. CLAUDE.md puts belief reconciliation, stochastic transitions, calibrated uncertainty and partial-observation production semantics out of scope "unless explicitly requested as a new domain requirement" ([CLAUDE.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/CLAUDE.md#L253-L270)), `v1-scope.md` extends the same ban to "Julia MDP/POMDP compilation", and NEXT_DOMAIN.md still lists Observability and Uncertainty as "Unknown", with an instruction to replace them "when a real next domain is chosen" ([NEXT_DOMAIN.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/refactor/NEXT_DOMAIN.md#L1-L32)). The supervisor's self-contained plan already sketches the destination: P5 adds a probabilistic/DBN IR, P6 a Julia compiler ("MDP baseline first; POMDP interface when partial observations are introduced"), P8 learning and model revision, and P9 DSPy optimization with held-out evaluation, all under the rule that "the editable probabilistic model is structured data/AST, not unrestricted Julia source" ([supervisor plan](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/supervisor/Symbolic_Twin_BoxPush_Implementation_Plan_Self_Contained_v5.docx)). The four steps below follow that roadmap and answer the owner's four questions in order.

| Step | Owner's question | Proposed default | Exit gate before the next step | Supervisor phase |
|---|---|---|---|---|
| 1. Environment | Which POMDP env first, and which prompts | CoopGrid-Jam-PO as a new package, then BoxPush-PO; a seeded ground-truth wrapper, a belief-holding track and an optional `observe()` path | Seed and determinism tests pass; true-model policies are solved; hiddenness is pinned by tests; V1 demos are unchanged | P5, plus the plan's "first genuinely partially observable BoxPush experiment" |
| 2. Julia planning and generation prompts | How to run POMDPs.jl from Python; how to prompt for solver-ready models | JSON IR compiled into `SparseTabularPOMDP`; NativeSARSOP/QMDP offline, POMCP/DESPOT online; juliacall for experiments, offline policy artifacts for CI | The UAI07 box-pushing tables round-trip exactly; a hand-written IR matches the true model; LLM IRs pass all gates | P6 |
| 3. Learning with DSPy | How to improve from experience and data | GEPA on the generator with a cascaded metric; a fitter owns the numbers; a model library and SIMBA rules for the advisor | Held-out gains over zero-shot and BootstrapFewShot on unseen variants | P8, P9 |
| 4. Benchmark and position | What prior work does, what MAAOS does better | A three-tier evaluation with eight pre-registered hypotheses | Paired-seed results with confidence intervals | P9 held-out evaluation |

## Step 1 — Build CoopGrid-Jam-PO first, then BoxPush-PO, as new seeded domains

### Four candidate environments, and why the door jam goes first

**cooperative_grid is the lowest-friction base for a first POMDP.** It is the newest domain, merged in PR #22 and native to the Domain Kit. Its backend is a 9×6 PettingZoo grid in which PULL opens the door only when agents A and B pull from the two handle cells in the same step, the door is closed and it is not jammed, while SHAKE on a handle clears the jam; the code calls `jammed_at_start` "the designed hidden condition" ([grid_env.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/cooperative_grid/grid_env.py#L1-L221)). The symbolic model is deliberately optimistic and its `project()` drops the jam ([model.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/domains/cooperative_grid/model.py#L1-L139)), `recover()` advises `ClearJam` after `CooperateOpen` fails repeatedly ([`__init__.py`](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/domains/cooperative_grid/__init__.py#L1-L60)), and tests already pin that the hidden condition is absent from the projection, that it is the only world difference, and that the domain halts under `symbolic_primary` but reaches the goal after recovery under the advisory policy ([tests](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/tests/test_domain_cooperative_grid.py#L100-L280)).

The partially observable variant, CoopGrid-Jam-PO, samples the jam from a Bernoulli prior, lets SHAKE free a jam only with probability q while returning a "rattle" reading of limited accuracy (which also requires redefining `ClearJam`'s outcome, because today's adapter reports success exactly when the door is no longer jammed), and lets the joint PULL slip, so a failed pull could come from either the jam or a slip. Because `CooperateOpen` is "one joint PULL step" and `ClearJam` is "one SHAKE step" ([environment.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/domains/cooperative_grid/environment.py#L1-L138)), **the skill-level transition and observation models follow exactly from the wrapper's parameters plus two deterministic `Goto` refusals imposed by the one-cell corridor** (A cannot reach handle_right while B holds handle_left, nor B handle_left while A holds handle_right), which makes KL and value-gap metrics exact rather than estimated. Belief visibly matters even at this size. Under a 0.5 prior, a 0.1 pull slip, a 0.7 shake success and a 0.85 rattle accuracy (arithmetic under these proposed parameters), one failed pull raises P(jam) to 0.91; a shake followed by "rattle_free" drops it to 0.06, while a shake followed by "rattle_jam" leaves it at 0.68. At each point the solver chooses between pulling again and shaking again, which is Tiger's listen-or-open trade-off, and it computes the answer that today's hand-written recovery rule only approximates.

**BoxPush-PO is the flagship, and there is a real case for starting there.** It has the richest formal assets in the repo: a centralized POMDP write-up, an RDDL skill model whose own note says "make HEAVY a hidden state and add an observation fluent revealed only after a push" ([box_push_skills.rddl](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/rddl/box_push_skills.rddl#L142-L148)), a FOND domain whose `push` has a `oneof` outcome over unknown weight ([FOND PDDL](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/pddl/box_push_domain_fond.pddl#L1-L73)), and a natural-language description that calls itself the "sole input" ([box_push_problem_description.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/box_push_problem_description.md#L3-L8)), with six documented "specification gaps" that work as a grading rubric ([BoxPush_Skill_PDDL_RDDL.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/BoxPush_Skill_PDDL_RDDL.md#L1-L60)). It also owns the project's signature failure. In the V1 demo, `Push(agent_0; box_1)` fails three times because agent_0 stands behind the already-delivered heavy box while the symbolic belief still holds `in_pose(agent_0, box_1)` ([acceptance trace](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/implementation/acceptance_traces.md#L102-L113), [P0 decisions](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/decisions/P0_V1_DECISIONS.md#L939-L945)); `symbolic_primary` halts after 7 executive and 42 primitive steps, whereas `advisory_two_track` reaches the goal after 9 and 62 thanks to the deterministic `RecoveryProposer` rule in `nl/recovery.py`, which re-issues `GotoPushPose` without calling any language model ([RecoveryProposer](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/nl/recovery.py#L3-L8), [advisory demo](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/refactor/baseline/demo_advisory_two_track.txt#L1-L14), [symbolic demo](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/refactor/baseline/demo_symbolic_primary.txt#L1-L12)). In BoxPush-PO, pose becomes an exclusive, partially observed factor, so a failed push is evidence spread over three explanations (the box is heavy, the lane is blocked, or the agent is not in pose) and the livelock turns into a belief update. The legacy centralized runner's hand-written prompt already encodes an information-gathering policy in English, telling the team to send "exactly ONE agent to goto_push_pose+push to TEST its weight" and that "HEAVY IS STICKY" ([box_push_centralized.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/env/box_push_centralized.py#L69-L296)); a solved BoxPush-PO should rediscover those rules, which makes a crisp test of belief-space planning. The costs are real: the frozen V1 package forces a new package, the multi-step procedural skills force Monte Carlo estimation of skill-level models, and the RDDL has never been machine-validated even though pyRDDLGym 2.7 is already pinned ([validation status](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/BoxPush_Skill_PDDL_RDDL.md#L62-L80), [requirements.txt](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/requirements.txt#L12-L14)).

The remaining candidates rank lower. UAI07 Cooperative Box Pushing is a calibration case rather than a MAAOS domain: it has 100 states, 0.9 action success and exactly MAAOS's primitive actions, but its large box is pushed side by side where MAAOS requires a strict tandem ([Seuken & Zilberstein](https://arxiv.org/pdf/1206.5295), [MADP file](https://github.com/MADPToolbox/MADP/blob/master/problems/boxPushingUAI07.dpomdp.gz), [BoxPush env](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/env/multi_agent_box_push_env.py#L1-L346)). CST has a Dec-POMDP write-up whose code declares `Discrete(3)` actions against seven in the spec ([CST_POMDP.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/cooperative_search_transport/CST_POMDP.md#L1-L178), [multi_agent_env.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/cooperative_search_transport/env/multi_agent_env.py#L74-L76)), and toy rescue states its probabilities in prose but draws them from Python's global `random` and ignores `seed` ([toy_rescue_env.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/toy_rescuce_env/env/toy_rescue_env.py#L113-L130)).

| Candidate | Hidden or stochastic elements | Skill-level size under joint actions (design arithmetic) | Ground truth | Main friction |
|---|---|---|---|---|
| **CoopGrid-Jam-PO (default first)** | jam prior, noisy rattle, pull slip | places {hall, handle_left, handle_right, goal}² × {closed-jammed, closed-free, open} = 48 states plus a terminal state; 36 joint actions; 16 joint observations; 504 reachable states at the primitive level | exact, from wrapper parameters and the corridor's two Goto refusals | contract extensions only |
| **BoxPush-PO (flagship second)** | weight, pose, lane blockage, push slip, confusable failure labels | 4 delivered × 4 heavy × 9 pose × 4 lane = 576 states plus a goal state; 49 joint actions (64 with a probe action); 25 joint observations | Monte Carlo over procedural skills | frozen V1 backend; bigger |
| RDDL-POMDP BoxPush | HEAVY hidden plus an observation fluent | ≤4,096 states before reachability pruning; 81 joint actions | the RDDL model | RDDL never validated; no Julia RDDL parser |
| CST-PO | target location and identity, detector with decoys | 225–900 states, 64 joint actions, 16 joint observations | Monte Carlo | spec and code disagree |
| UAI07 calibration | 0.9 success per agent | 100 states, 16 joint actions, 25 joint observations | exact `.dpomdp` file | different heavy-box geometry |

**The default is to declare both CoopGrid-Jam-PO and BoxPush-PO as the real next domains in NEXT_DOMAIN.md** (Observability = partial, Uncertainty = stochastic, Concurrency = sequential joint skills), to build CoopGrid-Jam-PO end to end first as the wiring test, and to design every artifact (IR schema, compiler, bridge, metric) so that BoxPush-PO drops in as the second domain.

### A seeded wrapper keeps ground truth exact and out of the planner's reach

Stochasticity and hidden-variable sampling belong in a seeded PettingZoo `ParallelEnv` wrapper around the deterministic backends, which are not seeded today: cooperative_grid's `reset` ignores its seed, and BoxPush's seed is "observationally inert because no BoxPush code consumes `np_random`" ([box_push_v1.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/domain/box_push_v1.py#L5-L11)). The wrapper owns an `np.random.Generator` seeded in `reset(seed=…)`, samples hidden variables from an explicit prior, applies slips before forwarding actions by turning a PULL or SHAKE into NOOP with the slip probability, computes noisy readings such as the rattle from the backend's privileged snapshot, and exports the same parameter object as the ground-truth model. It injects the hidden variables through the backends' own hooks (cooperative_grid's `jammed_at_start` constructor keyword, and an override of BoxPush's hard-coded `_get_initial_object_states()`, which sets each box's `required_agents`), since neither backend's `reset()` reads `options` ([grid_env.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/cooperative_grid/grid_env.py#L83-L165), [box_push_env.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/env/box_push_env.py#L78-L118)). Two convenient off-the-shelf wrappers are wrong for this job. MiniGrid's `StochasticActionWrapper` draws from NumPy's global RNG and hard-codes a random-action range of 6 ([MiniGrid wrappers](https://github.com/Farama-Foundation/Minigrid/blob/main/minigrid/wrappers.py)), and Gymnasium's `StickyAction` repeats the previous action rather than staying put, which makes the last action part of the Markov state ([Gymnasium](https://github.com/Farama-Foundation/Gymnasium/blob/main/gymnasium/wrappers/stateful_action.py)). PettingZoo's `parallel_seed_test` and `check_environment_deterministic_parallel` bring the wrapper under the same deterministic-test discipline as the rest of the suite ([PettingZoo seed_test](https://github.com/Farama-Foundation/PettingZoo/blob/main/pettingzoo/test/seed_test.py)).

**The true parameters must never reach the planner.** CLAUDE.md forbids any "hidden rollout, or another procedural environment oracle" in symbolic planning ([CLAUDE.md invariants](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/CLAUDE.md#L141-L163)), so the planner may only plan over the LLM-generated, data-fitted model, and true-model SARSOP and QMDP policies exist solely as evaluation references.

### Three contract extensions turn projection into belief

The first extension is an optional loop path that calls `env.observe()` after each attempt and routes the typed observation to the symbolic track. V1 domains do not opt in, so the byte-pinned demos stay identical. The new domain must also override the Kit's default `_observe`, which returns `state.canonical()`, because today cooperative_grid's `observe()` publishes the door's `jammed` flag ([kit/environment.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/kit/environment.py#L117-L131)), and it must redefine `ClearJam`'s outcome as described above, so that neither channel leaks the jam. The cheaper alternative, projection discipline alone, is weaker than it looks: the loop still hands the full exact `post_state` to `record_outcome`, so hiddenness would rest on a convention that one careless import could break.

The second is a belief-holding track whose `sync` projects only observable content, as cooperative_grid's `project()` already does for the jam, and whose update step performs exact Bayes over the small hidden space or holds a handle to a Julia updater. The legacy belief framework is worth mining for its interface (update, get, uncertainty and reset, an estimator registry, and a split between observable and internal fields) but not for its estimators, because the particle filter calls itself a "stub BaseBeliefUpdater" and the reward channel that grid dead reckoning thresholds is documented as "structurally invalid as a move-success observable" ([particle_filter_updater.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/legacy/middleware_layer/belief_updaters/particle_filter_updater.py#L1-L108), [section18.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/handoff/section18.md#L408-L436)).

The third makes prediction and monitoring probabilistic. `Prediction` must carry an outcome distribution or at least its support, the monitor should raise a discrepancy only for outcomes outside that support or below a likelihood threshold, and the three-strike halt "per (pre-state world key, grounded call)" needs a belief-aware replacement registered in `POLICY_FACTORIES`, because under stochastic outcomes repeated failure is evidence rather than a reason to stop ([orchestration_config.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/orchestration_config.py#L48-L53), [policies.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/runtime/policies.py#L54-L182)). The new domain must also introduce calibrated probabilities explicitly, since V1's `ConfidenceReport` is "never a probability over world dynamics" ([reports.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/reports.py#L46-L63)). The mechanics follow the Kit (`create-domain`, two registry lines, `validate-domain`, edits to four modules and a new entry in `DOMAIN_ENVIRONMENT_MODULES`), and the pinned count of "1032 tests" must change in the same commit ([README](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/README.md#L63-L73), [REFACTOR_STATUS.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/refactor/REFACTOR_STATUS.md#L51)).

### Sequential calls versus joint actions sets the solver's bill

This decision is easy to miss. The literature's multi-agent POMDPs choose one action per agent at every step, but the supervisor contract requires "deterministic sequential executive decision/execution behavior", in which "a high-level joint skill may internally coordinate multiple agents" ([supervisor contract](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md#L165-L172)). The two encodings compare as follows.

| | E1: sequential grounded calls | E2: joint per-agent tuples |
|---|---|---|
| Action set | One executive call per cycle | One skill per agent per cycle |
| Observation | The outcome of that call only | One outcome per agent |
| CoopGrid-Jam-PO size | 6 `Goto` + 2 `CooperateOpen` + 2 `ClearJam` = 10 calls, 4 observation symbols | 36 joint actions, 16 joint observations |
| BoxPush-PO action growth | 18 calls at three agents, 28 at four | 343 joint actions at three agents, 2,401 at four |
| Fits | The current executive, unchanged | PettingZoo's parallel API, the legacy centralized runner and the Dec-POMDP benchmarks |
| Cost | Parallelism, so longer makespans | Exponential growth in actions and observations |

Point-based backups scale with the product of the action and observation counts, so **E1 is a tractability lever that MAAOS gets for free, paid for in makespan**. The default is E1, with E2 added when the supervisor's P7 concurrency phase opens and wherever results must be comparable with published joint-action benchmarks.

### Two prompts the environment needs on day one

**The first prompt is the natural-language "sole input" description**, kept separate from the parameter file in line with the repo's precedent: the BoxPush PDDL/RDDL models were derived "entirely from the natural-language problem description", a text that calls itself the "sole input" ([box_push_problem_description.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/box_push_problem_description.md#L3-L8)), and "the environment source code is never used as input" ([BoxPush_Skill_PDDL_RDDL.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/BoxPush_Skill_PDDL_RDDL.md#L1-L60)). The default withholds the numbers so the fitter must estimate them, reserving stated numbers for an ablation that tests transcription. The typed interface blocks the generator also consumes (entities, skills, observations and reward) should be rendered deterministically from the domain package's types, so the prompt cannot drift from the code. The draft below is my composition from the backend facts above.

```text
COOPERATIVE DOOR, PARTIALLY OBSERVABLE  (sole input for model generation)

Two agents, A and B, start at the left and right ends of a corridor. A heavy door in the
corridor wall leads to a goal room whose bottom row holds the goal cells. Two handle cells
lie in the corridor, one on each side of the door. The team succeeds when both agents stand
on goal cells; the episode is cut off after 200 primitive steps.

Skills (the executive runs one skill per decision cycle; a joint skill moves both agents):
  Goto(agent, place), place in {handle_left, handle_right, goal}; an agent standing on no
    named place is in the hall. Goal cells can only be reached while the door is open, and
    the corridor is one cell wide, so a Goto that would have to pass the partner fails.
  CooperateOpen(agent, door, partner): both agents, standing on different handles, pull in
    the same step. The door opens only if it is closed and not jammed. Even a free door does
    not always open: the joint pull sometimes slips and nothing happens.
  ClearJam(agent, door): the agent on a handle shakes the door. Shaking sometimes frees a
    jammed door. The shaking agent then feels a rattle that usually, but not always, tells
    the truth about whether the door is still jammed.

Hidden: whether the door starts jammed is decided at random at the start of each episode and
is never shown. A failed pull looks the same whether a jam or a slip caused it.

Observed after every skill: both agents' places, whether the door is open, the skill outcome
(ok | fail; ClearJam reports ok whenever the shake was performed), and after ClearJam the
rattle reading (rattle_jam | rattle_free).

Rewards: -0.01 per agent per cycle, an extra -0.05 per shake, +1 per agent when both reach
the goal. Discount 0.95.
```

**The second prompt is the belief-aware advisory request for the NL track.** Today's SkillSelector sends `objective`, `goal`, `situation=belief.rendered()`, `decision_space` and `format` ([skill_selector.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/nl/skill_selector.py#L19-L53)), and the seam requires fields built from typed data that are "never rendered grids, beliefs, or rewards" ([nl/seam.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/nl/seam.py#L22-L83)), so a typed, rounded posterior field is a deliberate contract extension for the new domain. The evidence says it pays: BSE, which gave an LLM only an external Bayes filter's posterior, lifted success on Tiger from 80.0% to 95.0% over 40 paired seeds, though a separate run of the same GPT-4o configuration reached 84.0% ([BSE](https://arxiv.org/html/2609.10036)), and a textual belief template cut GPT-4's rounds-to-completion from 28.3 to 12.3 in Li et al.'s search-and-rescue game ([Li et al.](https://ar5iv.labs.arxiv.org/html/2310.10701)).

```python
# Sketch: SkillSelector.build_request (nl/skill_selector.py) plus one typed, rounded posterior
# field. Everything under nl/ renders BoxPush types today (InterpretedTask, SemanticBelief,
# skill_menu(), FORMAT_INSTRUCTIONS) and cooperative_grid declares reasoning_track=None, so
# CoopGrid-Jam-PO needs its own task interpreter, belief, menu and format renderers.
request = NLRequest.of(
    "skill_selector",
    objective=task.task.description,
    goal=", ".join(sorted(str(l) for l in task.goal_literals)),
    situation=belief.rendered(),        # observable facts and recent typed outcomes only
    posterior=posterior.rendered(),     # e.g. "P(door jammed)=0.91 after 1 failed CooperateOpen"
    decision_space=coopgrid_skill_menu(),   # rendered from domains/cooperative_grid/types.py Op
    format=COOPGRID_FORMAT_INSTRUCTIONS,    # one call in Call.__str__ form, e.g. "ClearJam(A, door)"
)
```

### Questions to settle before writing the domain

| Question | Options on the table | Proposed default |
|---|---|---|
| Which domain is declared the "real next domain"? | CoopGrid-Jam-PO; BoxPush-PO; both | Declare both; build CoopGrid-Jam-PO first |
| How are multi-agent decisions encoded? | E1 sequential calls; E2 joint tuples | E1 now; E2 with P7 concurrency and for literature comparisons |
| How do observations reach the belief? | Projection discipline; new optional `observe()` path | New optional path, so hiddenness is structural |
| What are the true parameters? | jam prior, shake success, rattle accuracy, pull slip, optional move slip | 0.5, 0.7, 0.85, 0.1, no move slip, all treated as sweepable knobs |
| Does the joint pull slip once or per agent? | Joint 0.1 (success 0.9); independent per agent (0.81) | Record one choice explicitly; the UAI07 file uses products (0.81) |
| Do nonterminal observations open decision epochs (a supervisor open question)? | Yes; no | No: one epoch per executive cycle |
| Is there an initial observation? | None; one at reset | None; the initial belief is the prior, matching pyRDDLGym's `reset()` convention ([pyRDDLGym env](https://github.com/pyrddlgym-project/pyRDDLGym/blob/main/pyRDDLGym/core/env.py)) |
| Does the LLM see the numbers? | Withheld; stated | Withheld; stated only in a transcription ablation |

## Step 2 — Let the LLM write a typed model and let Julia's POMDPs.jl plan

### POMDPs.jl 1.0 offers a solver for every MAAOS size class

The ecosystem is stable and maintained: **POMDPs.jl 1.0.0** has master commits as recent as June 2026, alongside **POMDPTools 1.1.0** and **QuickPOMDPs 0.2.15** ([POMDPs.jl](https://github.com/JuliaPOMDP/POMDPs.jl), [General registry](https://github.com/JuliaRegistries/General)). A model is either explicit, with distributions over enumerable spaces, or generative, with samples from `gen`, and that choice decides which solvers apply; the docs warn that implementing `gen` "will limit which solvers you can use" ([def_pomdp.md](https://github.com/JuliaPOMDP/POMDPs.jl/blob/master/docs/src/def_pomdp.md)). Multi-agent support is thin. MultiAgentPOMDPs.jl defines only a `JointMDP` with no joint POMDP type ([MultiAgentPOMDPs.jl](https://github.com/JuliaPOMDP/MultiAgentPOMDPs.jl)), FactoredValueMCTS plans only for multi-agent MDPs ([FactoredValueMCTS.jl](https://github.com/JuliaPOMDP/FactoredValueMCTS.jl)), and **no registered Julia Dec-POMDP solver exists**. MAAOS's MPOMDP is therefore an ordinary `POMDP` over sequential calls or joint tuples, and decentralized baselines must come from MADP (C++, last commit October 2020) or the *Algorithms for Decision Making* book code ([MADP](https://github.com/MADPToolbox/MADP), [decisionmaking-code](https://github.com/algorithmsbooks/decisionmaking-code)).

| Model regime | First choice | Alternatives | Defaults to override for reproducibility |
|---|---|---|---|
| Tiny fixtures (Tiger, CoopGrid-Jam-PO unit tests) | IncrementalPruning (exact) | PBVI | none |
| Up to roughly 10⁴–10⁵ states with a small observation set (both first domains) | NativeSARSOP 0.1.4 | SARSOP.jl 0.6.0 (an MIT wrapper around the GPL-2.0 APPL binary; supports MOMDPs); QMDP and FIB as baselines | NativeSARSOP's `max_time=1.0`, and the same 1 s cap in its default `BlindLowerBound` and `FastInformedBound` init bounds, make results machine-dependent, so set `max_steps`, a large `max_time` and init bounds with `max_time=Inf` and a finite `max_iter`; SARSOP.jl writes `policy.out` and `model.pomdpx` to the working directory |
| Only door or box attributes hidden, positions observed | SARSOP.jl on a MOMDP | NativeSARSOP on the flat POMDP | MOMDPs.jl 0.1.2 needs Julia 1.10 |
| 10⁵–10⁹ states with discrete observations (BoxPush-PO at 3+ agents under E2; primitive level) | ARDESPOT 0.3.8, with bounds from the MDP relaxation | BasicPOMCP 0.3.12; POMCGraphSearch 0.2.2 (offline finite-state controllers, ICAPS 2025) | DESPOT's `T_max=1.0` and `MersenneTwister(rand(UInt32))` need `T_max=Inf`, a finite `max_trials` and a seeded MersenneTwister; POMCP's `GLOBAL_RNG` needs a `StableRNG`; reseed both with `Random.seed!(planner, seed)` before each decision |
| Large or continuous observation spaces | AdaOPS 0.6.1 or POMCPOW 0.3.11 (both need an observation pdf) | PFT-DPW | seed the RNG (AdaOPS defaults to `MersenneTwister(rand(UInt32))`, POMCPOW to `GLOBAL_RNG`); for AdaOPS `T_max=Inf` with a finite `max_trials` (POMCPOW has no `T_max`; its `max_time` already defaults to `Inf`) |
| MDP relaxation and bounds | SparseValueIterationSolver | FVMCTSSolver on a `JointMDP` for 3–4 agents | none |

Sources for the table: [SARSOP.jl](https://github.com/JuliaPOMDP/SARSOP.jl), [NativeSARSOP.jl](https://github.com/JuliaPOMDP/NativeSARSOP.jl), [ARDESPOT.jl](https://github.com/JuliaPOMDP/ARDESPOT.jl), [BasicPOMCP.jl](https://github.com/JuliaPOMDP/BasicPOMCP.jl), [POMCPOW.jl](https://github.com/JuliaPOMDP/POMCPOW.jl), [AdaOPS.jl](https://github.com/JuliaPOMDP/AdaOPS.jl), [POMCGraphSearch.jl](https://github.com/ori-goals/POMCGraphSearch.jl), [MOMDPs.jl](https://github.com/JuliaPOMDP/MOMDPs.jl).

Published numbers put both first domains far below any solver ceiling. SARSOP solved Tag (870 states) in 6 s and RockSample(7,8) (12,545 states) in 400 s ([SARSOP, RSS 2008](https://www.roboticsproceedings.org/rss04/p9.pdf)), and in the DESPOT study SARSOP stayed competitive at 247,808 states but reported nothing at 7.4 million, where DESPOT scored 18.64 against POMCP's 12.23 ([DESPOT](https://arxiv.org/abs/1609.03250)). Primitive-level 12×12 BoxPush is another matter, with roughly 6.3×10⁹ states and 6⁸ ≈ 1.7 million possible 3×3 views per agent, and it is online-only with a Julia-side simulator. Solve times for MAAOS's own models have not been measured.

**The optimistic twin stays in the architecture as the planner's relaxation.** The deterministic, fully observable BFS twin is an MMDP/QMDP-style relaxation, so it can serve as POMCP's rollout policy, as DESPOT's lower bound by rolling out its policy, and as an upper bound via the MDP value. This mirrors the admissible state-revealing heuristics in approximate MAA*, whose authors note that "revealing the state is too optimistic" ([IJCAI 2024](https://www.ijcai.org/proceedings/2024/0745.pdf)), and the gap between the twin's optimistic value and the realized value then measures what partial observability costs. If BoxPush-PO keeps its skills deterministic and hides only initial facts such as box weights, it falls into the deterministic-Dec-POMDP class, where IDPP has scaled to more than 10 million states on a multi-agent Canadian-traveler task and to about 2.8 million on a box-delivery task ([Det-Dec-POMDP, AAAI 2026](https://arxiv.org/html/2508.21595v1)).

### Compile the LLM's JSON into one concrete Julia type

**The LLM should emit a typed JSON IR, and a deterministic compiler should produce the Julia model.** The alternatives compare as follows.

| Representation | LLM reliability | Verifiability | Solver fit | Parameter learning |
|---|---|---|---|---|
| **JSON IR, then compiler (default)** | Highest: schema-constrained, small per-component calls | Static checks; diffable; JSON-Patch repairs | Compiles to tables for SARSOP/QMDP and to a generative model for POMCP/DESPOT | Named parameter slots make Beta/Dirichlet fitting trivial |
| QuickPOMDP Julia code | Lowest for small models | Needs Julia in the repair loop | Native | Numbers live inside code |
| RDDL with observation fluents | Medium | pyRDDLGym can simulate it | No known RDDL-to-POMDPs.jl bridge | Non-fluents |
| Python/Pyro program | High for strong models | Likelihood checks are natural | Poor: Python callbacks in solver loops | Good with named parameters |

The evidence points one way. Automated consistency checks over a JSON intermediate make LLM-generated PDDL domains more consistent, although the JSON choice itself was not ablated ([Smirnov et al.](https://arxiv.org/html/2404.07751v1)); weaker models fail at syntax, with Llama Scout producing only 6.6% syntactically valid PDDL in PDDLCoder against Gemma 4 31b's 92.5% ([PDDLCoder](https://arxiv.org/html/2608.16637v1)); inference could not be run on 22–30% of the PyMC programs GPT-4V wrote for the Stan benchmarks ([BoxLM](https://arxiv.org/pdf/2402.17879)); and no published work has an LLM emit RDDL with observation fluents, Cassandra `.pomdp` files or QuickPOMDPs code. The supervisor plan agrees ("we do not maintain an independent Julia simulator model and an independent DBN model") and asks to "unit-test the generated distribution against a slow reference evaluator of the IR" and to benchmark transition samples per second against a hand-written BoxPush simulator ([supervisor plan](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/supervisor/Symbolic_Twin_BoxPush_Implementation_Plan_Self_Contained_v5.docx)).

**Compiling into one concrete type also saves real time in an optimization loop.** Every `QuickPOMDP` carries a fresh `uuid4()` type parameter, so each newly generated model makes Julia JIT-compile every solver method again ([QuickPOMDPs.jl](https://github.com/JuliaPOMDP/QuickPOMDPs.jl)), whereas `SparseTabularPOMDP` is a single fixed type that a sysimage can precompile once, which matters when DSPy generates hundreds of candidates. The sketch below was composed from verified signatures but not executed; it assumes the Python side has enumerated reachable states and that terminal states carry self-loops.

```julia
using JSON3, SparseArrays, POMDPs, POMDPTools

function compile_tabular(path; atol=1e-9)
    J = JSON3.read(read(path, String))
    S, A, O = String.(J.states), String.(J.actions), String.(J.observations)
    si, ai, oi = (Dict(x => i for (i, x) in enumerate(v)) for v in (S, A, O))
    nS, nA, nO = length(S), length(A), length(O)
    T = [spzeros(nS, nS) for _ in 1:nA]            # T[a][s, sp]
    Z = [spzeros(nS, nO) for _ in 1:nA]            # Z[a][sp, o]
    R = zeros(nS, nA)                              # R[s, a] = E[r | s, a]; the R[s,sp] struct comment is stale
    for t in J.T; T[ai[t.a]][si[t.s], si[t.sp]] += t.p; end
    for z in J.Z; Z[ai[z.a]][si[z.sp], oi[z.o]] += z.p; end
    for r in J.R; R[si[r.s], ai[r.a]] = r.r; end
    for a in 1:nA, s in 1:nS                       # reject malformed tables loudly
        abs(sum(T[a][s, :]) - 1) < atol || error("T row (s=$(S[s]), a=$(A[a])) sums to $(sum(T[a][s, :]))")
        abs(sum(Z[a][s, :]) - 1) < atol || error("Z row (sp=$(S[s]), a=$(A[a])) not normalised")
    end
    b0 = sparsevec([si[x.s] for x in J.b0], [x.p for x in J.b0], nS)
    term = Set{Int}(si[s] for s in J.terminals)
    return SparseTabularPOMDP(T, R, Z, b0, term, Float64(J.discount)), (S, A, O)
end
```

`SparseTabularPOMDP`'s docstring says `R[s, a]` while a stale struct comment says `R[s,sp]`; the code settles it, because `reward(p, s, a)` reads `p.R[s, a]` and the converting constructor fills `R` with the expectation of `reward(m, s, a, sp)` over `sp`, so an arrival reward in the IR must be folded into E[r | s, a] before export, and a unit test should pin that ([sparse_tabular.jl](https://github.com/JuliaPOMDP/POMDPs.jl/blob/master/lib/POMDPTools/src/ModelTools/sparse_tabular.jl)). The same Python compiler can export RDDL for independent simulation in pyRDDLGym, which the supervisor frames as "a validation/interchange mechanism, not runtime infrastructure", and the UAI07 `.dpomdp` file, which no Julia package reads, can enter the same JSON IR through the Python parser pydpomdp ([pydpomdp](https://github.com/laurimi/pydpomdp)).

### Cross the Python–Julia boundary once per decision

**Use juliacall, not PyJulia.** PythonCall/juliacall 0.9.36 shipped on 2026-09-18 and supports Python 3.10+ and Julia 1.10+ ([juliacall on PyPI](https://pypi.org/project/juliacall/), [PythonCall FAQ](https://juliapy.github.io/PythonCall.jl/stable/faq/)); PyJulia's README says development "has transitioned to PythonCall.jl/juliacall" ([pyjulia](https://github.com/JuliaPy/pyjulia)); and the Python `quickpomdps` package (0.1.2, August 2023) depends on PyJulia and installs its Julia dependencies into the global environment, which makes it legacy ([quickpomdps](https://github.com/JuliaPOMDP/quickpomdps)). **The governing rule is to keep every model function in Julia and cross the boundary once per decision, sending the action out and the observation in**, because tree search calls `transition` and `observation` many thousands of times per decision and every Python callback would be a cross-language round trip.

Four arrangements are possible. An in-process juliacall session is the default for experiments and online solvers. An offline solve followed by a pure-Python runtime exports alpha vectors from Julia and performs exact Bayes updates and an argmax in Python, shipping the policy as a byte-pinned artifact the way `symbolic/pddl_gen.py` already ships PDDL ([pddl_gen.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/symbolic/pddl_gen.py#L1-L15)), and it is the default for CI and V1-style tests. A `julia --project` subprocess exchanging JSON gives isolation, and a long-lived daemon built on DaemonMode.jl, HTTP.jl or ZMQ.jl can serve parallel DSPy workers ([DaemonMode.jl](https://github.com/dmolina/DaemonMode.jl)). A PackageCompiler sysimage passed through `PYTHON_JULIACALL_SYSIMAGE` cuts startup ([juliacall docs](https://juliapy.github.io/PythonCall.jl/stable/juliacall/)), whereas Julia 1.12's experimental `--trim` requires code free of dynamic dispatch ([Julia 1.12 highlights](https://julialang.org/blog/2025/10/julia-1.12-highlights/)) and is therefore unlikely to work with solvers that keep `Any`-typed fields. The sketches below are composed and were not executed.

```julia
# maaos_pomdp_bridge.jl  (loaded once per Python process)
using POMDPs, POMDPTools, NativeSARSOP, StableRNGs, Random
include("compile_tabular.jl")

mutable struct Session; m; policy; up; b; end

function make_session(path; max_steps=10_000)
    m, _ = compile_tabular(path)
    solver = NativeSARSOP.SARSOPSolver(max_time=600.0, max_steps=max_steps, verbose=false,
        init_lower=NativeSARSOP.BlindLowerBound(bel_res=1e-2, max_time=Inf, max_iter=10_000),
        init_upper=NativeSARSOP.FastInformedBound(bel_res=1e-2, max_time=Inf, max_iter=10_000))
    policy = solve(solver, m)                        # step budgets everywhere; 600 s is only a safety net
    up = updater(policy)                             # DiscreteUpdater for alpha-vector policies
    Session(m, policy, up, initialize_belief(up, initialstate(m)))
end

plan_step(S::Session) = action(S.policy, S.b)       # pure read; juliacall maps jl.f_b to f!, so '!' names are callable too
observe_step(S::Session, a, o) = (S.b = update(S.up, S.b, a, o); nothing)  # throws on impossible o
belief_vector(S::Session) = [pdf(S.b, s) for s in states(S.m)]

# Online variant (ParticleFilters 0.6 syntax; ARDESPOT/AdaOPS envs stay on 0.5); for large models pass the fixed
# generative struct, since transition() on a SparseTabularPOMDP slices a CSC row on every call:
# planner = solve(POMCPSolver(tree_queries=10_000, max_time=Inf, max_depth=40, c=20.0,
#                             rng=StableRNG(seed)), m)
# up = BootstrapFilter(m, 5_000; rng=StableRNG(seed + 1), postprocess=refill_consistent)  # refill_consistent(bp, a, o, b, bb, rng)
# Random.seed!(planner, seed); a = action(planner, b)  # reseed per decision: DK042 compares repeated plan() calls
```

```python
# Lives outside the guarded packages, like the existing DSPy live seam, and is injected
# through DomainServices.plan. Julia indices are 1-based.
from juliacall import Main as jl

jl.seval('include("maaos_pomdp_bridge.jl")')
session = jl.make_session("artifacts/coopgrid_jam_po.tables.json")

def plan(symbolic_state, identities):
    a = int(jl.plan_step(session)) - 1               # one boundary crossing per decision
    return PlanFound((GROUNDED_CALLS[a],))           # receding horizon: the loop enacts the head

def record_observation(action_index, obs_index):
    jl.observe_step(session, action_index + 1, obs_index + 1)
```

```python
# CI path: Julia solves offline, the policy ships as a byte-pinned artifact,
# and the runtime stays pure Python (numpy is banned in guarded packages).
def belief_update(b, a, o, T, Z):
    bp = [Z[a][sp][o] * sum(T[a][s][sp] * b[s] for s in range(len(b))) for sp in range(len(b))]
    total = sum(bp)
    if total == 0.0:
        raise ObservationOutsideModel(a, o)          # surfaces as a typed ExecutionDiscrepancy
    return [x / total for x in bp]

def best_action(b, alphas):                          # [(action_index, vector)] in Julia's alphavectors order: first max wins, as in POMDPTools
    return max(alphas, key=lambda av: sum(x * y for x, y in zip(av[1], b)))[0]
```

The `total == 0.0` branch is more than defensive coding. POMDPTools' `DiscreteUpdater` raises "Failed discrete belief update: new probabilities sum to zero" when an observation is impossible under the model ([discrete.jl](https://github.com/JuliaPOMDP/POMDPs.jl/blob/master/lib/POMDPTools/src/BeliefUpdaters/discrete.jl)), so **that error is a model-mismatch detector** and should become a typed discrepancy exactly as backend refusals already do; for particle filters, ParticleFilters 0.6 adds a `postprocess` hook for refilling depleted beliefs ([depletion docs](https://github.com/JuliaPOMDP/ParticleFilters.jl/blob/master/docs/src/depletion.md)). `action_info(planner, b)` returns the chosen action plus diagnostics for POMCP, POMCPOW, DESPOT and MCTS, including the search tree when `tree_in_info=true`, which is useful raw material for explanations, while `stepthrough`, `HistoryRecorder` and `RolloutSimulator` evaluate against a model inside Julia rather than drive the Python environment. Placement follows existing precedent: the import guard does not name `juliacall`, but it bans numpy and dynamic imports in guarded packages ([test_no_backend_imports.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/tests/test_no_backend_imports.py#L29-L71)), and the Kit's DK082 rule that "importing the package loads no backend" implies lazy binding at the composition layer ([app/validation.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/app/validation.py#L157)).

### Byte-identical traces demand seeds, budgets and pinned toolchains

MAAOS's demos and acceptance traces are byte-pinned, so the Julia side needs its own discipline. One exact Julia version should be pinned with its Manifest committed, because Julia 1.13, released 2026-09-10, replaced the hash function with RapidhashNano, which can change `Dict` iteration order and therefore tie-breaking, and the default RNG streams are documented as unstable across versions ([Julia 1.13 highlights](https://julialang.org/blog/2026/09/julia-1.13-highlights/), [StableRNGs.jl](https://github.com/JuliaRandom/StableRNGs.jl)). Runs should use `PYTHON_JULIACALL_THREADS=1`, seed every solver and filter explicitly instead of relying on `GLOBAL_RNG` or `MersenneTwister(rand(UInt32))` defaults, reseed online planners before each decision with `Random.seed!(planner, seed)` so that repeated `plan()` calls agree, budget by iterations rather than wall-clock time, and log only discrete indices and rounded floats. Conflicting packages need separate environments: ARDESPOT accepts ParticleFilters 0.4–0.5 and AdaOPS only 0.5, while BasicPOMCP and POMCPOW accept 0.5–0.6 ([ParticleFilters.jl](https://github.com/JuliaPOMDP/ParticleFilters.jl)), and SARSOP.jl and NativeSARSOP both define a `SARSOPSolver`.

CI is the harder constraint. The single job is "OFFLINE BY CONSTRUCTION", runs Python 3.12 from `uv.lock`, and is scanned by tests for forbidden strings and services ([offline-tests.yml](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/.github/workflows/offline-tests.yml#L1-L31), [test_r6_tooling.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/tests/test_r6_tooling.py#L53-L169)), and running juliacall inside it would conflict because juliapkg fetches Julia and its packages on first use. The clean split keeps Julia out of the default job entirely, commits compiled tables and alpha-vector policies as byte-pinned artifacts replayed in pure Python, and adds a separate opt-in job that uses `julia-actions/setup-julia` with a pinned Manifest to regenerate and verify those artifacts, following the same pattern by which `MAAOS_LIVE_LM` keeps live-LM tests opt-in and requiring a matching update to `test_r6_tooling`.

### Prompts must be designed backwards from what the solver consumes

The model-generation literature converges on one design in which the LLM proposes a structured model, an automatic harness scores it, and a search over candidates is driven by concrete counterexamples; pure one-shot generation lost in every study that measured it. Decomposition works, as NL2Plan's stepwise pipeline solved 10 of 15 tasks against 2 of 15 for zero-shot chain-of-thought ([NL2Plan](https://arxiv.org/html/2405.04215v2)). A single in-context example is decisive, since LLM+P fell to 0% without one against 90% on Blocksworld with it ([LLM+P](https://arxiv.org/pdf/2304.11477)). Meaningful names matter, because Pinductor's performance "drops across environments" when they are replaced by less informative labels, although it "degrades gracefully", as the abstract puts it ([Pinductor](https://arxiv.org/html/2605.13740v1)), and focused edits beat rewrites, with PDDLCoder's in-place edits reaching 89.6% success against 56.6% (60 of 106 test problems) for a rigid, fixed-order pipeline that regenerates the whole PDDL file for each change, while using 57.3% of its output tokens ([PDDLCoder](https://arxiv.org/html/2608.16637v1)). The documented failures are just as clear. Three syntax-correction rounds lifted DeepSeek-R1's executability in Text2World from 72.3% to 89.1% while effect F1 rose only 8.5 points, and an LLM judge agreed with humans at κ = 0.10 ([Text2World](https://arxiv.org/html/2502.13092v1)); GPT-4o's PDDL problems were 94.4% solvable but only 24.8% correct ([Planetarium](https://arxiv.org/html/2407.03321v2)).

On numbers, the evidence says **the LLM should write structure and a fitter should write probabilities**. Verbalized confidence is overconfident ([Xiong et al.](https://arxiv.org/abs/2306.13063)), POMDP Coder's own authors attribute "the sometimes overly broad distributions proposed by the LLM" to "the coverage metric indirectly rewarding broader distributions" ([POMDP Coder](https://arxiv.org/html/2505.02216v2)), and the 2025–2026 trend in PoE-World, OneLife and PO-PDDL fits parameters by maximum likelihood or empirical frequencies ([PoE-World](https://arxiv.org/html/2505.10819v3), [PO-PDDL](https://arxiv.org/html/2606.15654v1)). The supervisor's own requirements for model-generating prompts are strict and compatible with all of this:

> Prompts that generate or revise the probabilistic model must describe the schema, not merely ask for Julia code. They should require the model to: declare all state, observation, object, skill, and interaction types before use; for each skill, list exactly the variables it can affect and the variables on which each outcome/effect/observation model depends; use only the permitted expression/distribution vocabulary; represent concurrency through active-skill dependencies and explicit interaction fragments when joint effects are correlated; emit named outcomes, probability models, duration models, effects, and observations separately; mark unknown or unsupported details explicitly rather than inventing them; produce typed model patches for revisions instead of rewriting unrelated parts of the model; pass deterministic validation: schema/type checks, probability normalization, parent/expression consistency, acyclicity within each DBN slice, and effect ownership/conflict checks. — [supervisor plan sec. 4.5](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/supervisor/Symbolic_Twin_BoxPush_Implementation_Plan_Self_Contained_v5.docx)

What makes a generated model "suit the planners" is concrete. The table maps each solver-side need to the prompt rule that produces it and the deterministic check that enforces it before Julia ever sees the model.

| What the Julia side consumes | Prompt rule that produces it | Deterministic check before Julia |
|---|---|---|
| Finite, enumerable states, actions and observations for SARSOP, QMDP, PBVI | Typed factored variables with finite domains; stay at the skill level; a state budget | Enumerate reachable states; count against the budget |
| Normalized T and Z rows | Exhaustive, mutually exclusive modes whose probabilities are named parameters | Row sums equal 1 after substituting priors (`compile_tabular` fails loudly) |
| O(o ∣ a, s′), matching `observation(m, a, sp)` and pyRDDLGym's observation fluents | Observation rules conditioned on the next state and the action | Parent check: observation expressions reference only primed variables and actions ([pyRDDLGym levels](https://github.com/pyrddlgym-project/pyRDDLGym/blob/main/pyRDDLGym/core/compiler/levels.py)) |
| No zero-likelihood logged events (discrete updaters raise errors; particle filters deplete) | Named noise parameters on every observation; the self-check traces sample trajectories | Coverage gate on held-out logs |
| An observation pdf for POMCPOW, AdaOPS and particle filters | Distributions, not deterministic functions | pdf evaluable for every (a, s′, o) |
| An explicit initial belief and initial-observation convention | A factored prior with named parameters | Initial belief sums to 1; no initial observation |
| Terminal states, discount and horizon | Reward and termination copied from the specification, never invented | Terminal set non-empty; discount below 1 for discounted offline solvers |
| A goal reachable from every start state, so policies are not trivial | Optimism rule: reachability from the prior's support | Graph search over the support |
| One concrete Julia type across candidates, so no re-JIT | Numbers as parameters, never as code | Compile only to `SparseTabularPOMDP` or a fixed generative struct |
| An observed/hidden split for MOMDP solvers | Per-variable observability flags | Emit a MOMDP when the hidden part is small |
| An action set consistent with the executive | Declared action encoding (E1 or E2) | Action names match the grounded-call vocabulary |

### Generation, reference and repair prompts

The generation prompt below is the research draft adapted in three places: it targets `SparseTabularPOMDP` instead of QuickPOMDPs code, it generalizes R3 to cover both action encodings, and it adds R12 (finiteness) and R13 (action encoding) for solver-suitability. It is untested, and its expected effectiveness is extrapolated from single-agent and classical-PDDL evidence.

```text
You are a POMDP modeling engineer. You convert an environment specification and logged
evidence into a FACTORED, MULTI-AGENT POMDP MODEL written ONLY as JSON that validates against
<OUTPUT_SCHEMA>. A deterministic compiler (not you) turns your JSON into (a) a Python
generative simulator used to score the model against logged trajectories and (b) a Julia
POMDPs.jl model: a SparseTabularPOMDP for offline solvers and a generative model for online
solvers. A statistical fitter (not you) estimates every numeric parameter from data. YOUR JOB
IS STRUCTURE: which variables exist, which are hidden, which outcomes are possible, and which
named parameters govern them.

HARD RULES
R1 Vocabulary. Use only the types, objects, variables and skill names in <ENTITY_SCHEMA>,
   <SKILL_INTERFACE>, <OBSERVATION_INTERFACE>. If you need a new variable, add it to
   "new_variables" with a one-line justification that cites evidence ids.
R2 Factoring. The state is a product of typed variables indexed by entities (per agent, per
   box, per door). Mark each variable observable: "full" | "none" | "partial".
R3 Interaction. Give each agent's skills with preconditions over its own and shared
   variables. Interactions between agents appear ONLY in joint skills (sequential encoding) or
   in "joint_rules" (joint encoding), e.g. a cooperative push needs >= 2 distinct agents in
   pose on the same box.
R4 Stochasticity. Every non-deterministic effect is an exhaustive, mutually exclusive "modes"
   list whose probabilities are NAMED PARAMETERS with a prior {"Beta":[a,b]} or
   {"Dirichlet":[...]} of total pseudo-count <= 2 unless <ENV_DESCRIPTION> states the
   probability. Never hard-code a number you were not given.
R5 Keep guaranteed effects deterministic (a single mode) when the description or the backend
   guarantees them.
R6 Observations. For every skill (and joint rule), give observation rules mapping (next state,
   action) to a distribution over symbols from <OBSERVATION_INTERFACE>, parameterized by named
   noise parameters. Observations must never reveal a "none" variable unless a rule
   explicitly says so (e.g. a push attempt reveals the box weight).
R7 Initial belief. A factored prior over hidden variables with named parameters; list every
   independence assumption.
R8 Reward/termination. Copy them from <REWARD_SPEC>; do not add shaping.
R9 Optimism (reachability). From every state in the initial belief's support, at least one
   action sequence must reach the goal with non-zero probability. When evidence shows a skill
   failing, add a failure mode or lower its prior. Do NOT delete the skill.
R10 Generalize. Write rules over types and relations. Never mention specific coordinates, time
   steps or object ids from the trajectories unless they are fixed features of the instance.
R11 Declare every modeling assumption in "assumptions" and every parameter the fitter must
   estimate in "parameters". Put open questions for the human in "open_questions".
R12 Finiteness. Every variable has a finite, enumerated domain. Stay at the skill level of
   <SKILL_INTERFACE>: no coordinates, paths or geometry. Reachable states < <STATE_BUDGET>.
R13 Action encoding. Follow <ACTION_ENCODING>: "sequential" (one grounded skill call per
   cycle) or "joint" (one skill per agent per cycle, interactions in "joint_rules").

PROCEDURE (reason in <scratchpad>, then output the JSON only)
S1 State factors and hidden variables.   S2 Per-agent skills and preconditions.
S3 Joint skills / joint rules.           S4 Transition modes per skill / joint rule.
S5 Observation rules.                    S6 Reward and termination (copied).
S7 Initial belief.                       S8 Assumptions, parameters, open questions.
S9 SELF-CHECK. Answer each question; fix the model if any answer is "no":
   [ ] every referenced variable is declared   [ ] every mode list is exhaustive
   [ ] every probability is a named parameter with a prior
   [ ] each of the first 3 trajectories in <EXAMPLE_TRAJECTORIES> gets non-zero probability
       (trace them step by step)
   [ ] each record in <DISCREPANCY_EVIDENCE> is produced by some mode or observation
   [ ] the goal is reachable (R9)   [ ] no rule refers to specific coordinates or times (R10)
   [ ] every domain is finite and the state budget holds (R12)
```

The user message fills the tagged blocks with the sole-input text as `<ENV_DESCRIPTION>`; `<ENTITY_SCHEMA>`, `<SKILL_INTERFACE>`, `<OBSERVATION_INTERFACE>` and `<REWARD_SPEC>` rendered from the domain package; `<ACTION_ENCODING>` and `<STATE_BUDGET>`; the deterministic Kit model or RDDL as `<PRIOR_MODEL>`; about five `<EXAMPLE_TRAJECTORIES>` stratified to include failures and carrying post-hoc true state where logged; aggregated typed `<DISCREPANCY_EVIDENCE>`; and Tiger written in the same schema as `<CANONICAL_EXAMPLE>`. Each choice has published precedent in POMDP Coder's five data samples with an instruction against overfitting, Pinductor's "rules over memorization" and LLM+P's decisive in-context example. For BoxPush-PO, the six documented specification gaps (explore targeting, weight discovery, simultaneous action, reward magnitudes, blocked and waiting-partner outcomes, in-pose persistence) double as the expected contents of `open_questions`.

The reference model for CoopGrid-Jam-PO below is my adaptation of the draft schema. It serves three purposes at once: the gold IR for Step 2's exit gate, the fixture for compiler tests, and a candidate second in-context exemplar.

```json
{
  "schema_version": "maaos-pomdp/0.1",
  "types": ["agent", "door", "place"],
  "variables": [
    {"name": "at", "args": ["agent"], "domain": ["hall", "handle_left", "handle_right", "goal"], "observable": "full"},
    {"name": "door_open", "args": ["door"], "domain": "bool", "observable": "full"},
    {"name": "jammed", "args": ["door"], "domain": "bool", "observable": "none"}
  ],
  "new_variables": [],
  "agents": {"type": "agent", "action_encoding": "sequential", "noop": "wait"},
  "skills": [
    {"name": "goto", "args": {"a": "agent", "x": "place", "d": "door"},
     "precondition": "x != hall & at(a) != x & (x = goal ? door_open(d) : forall q != a: at(q) != x)",
     "cases": [
       {"when": "at(a) = hall & ((a = A & x = handle_right & at(B) = handle_left) | (a = B & x = handle_left & at(A) = handle_right))",
        "modes": [{"p": "1", "effects": []}]},
       {"when": "otherwise", "modes": [{"p": "1", "effects": ["at(a)=x"]}]}]},
    {"name": "cooperate_open", "args": {"a": "agent", "d": "door", "q": "agent"},
     "precondition": "a != q & at(a) in {handle_left, handle_right} & at(q) in {handle_left, handle_right} & at(a) != at(q) & !door_open(d)",
     "cases": [
       {"when": "jammed(d)", "modes": [{"p": "1", "effects": []}]},
       {"when": "!jammed(d)", "modes": [
         {"p": "p_pull_opens", "effects": ["door_open(d)=1"]},
         {"p": "1 - p_pull_opens", "effects": []}]}]},
    {"name": "clear_jam", "args": {"a": "agent", "d": "door"},
     "precondition": "at(a) in {handle_left, handle_right} & !door_open(d)",
     "cases": [
       {"when": "jammed(d)", "modes": [
         {"p": "p_shake_frees", "effects": ["jammed(d)=0"]},
         {"p": "1 - p_shake_frees", "effects": []}]},
       {"when": "!jammed(d)", "modes": [{"p": "1", "effects": []}]}]}
  ],
  "joint_rules": [],
  "observations": [
    {"observer": "a", "symbol": "outcome", "on": "act=cooperate_open(a,d,q)",
     "dist": {"ok": "door_open'(d) ? 1 - eps_obs : eps_obs",
              "fail": "door_open'(d) ? eps_obs : 1 - eps_obs"}},
    {"observer": "a", "symbol": "rattle", "on": "act=clear_jam(a,d)",
     "dist": {"rattle_jam": "jammed'(d) ? acc_rattle : 1 - acc_rattle",
              "rattle_free": "jammed'(d) ? 1 - acc_rattle : acc_rattle"}}
  ],
  "reward": {"copy_of": "REWARD_SPEC"},
  "termination": "forall a: at(a) = goal",
  "initial_belief": [{"var": "jammed(d)", "dist": {"Bernoulli": "p_jam_prior"}}],
  "parameters": [
    {"name": "p_pull_opens",  "prior": {"Beta": [1.8, 0.2]}, "fit": "counts"},
    {"name": "p_shake_frees", "prior": {"Beta": [1, 1]},     "fit": "counts"},
    {"name": "acc_rattle",    "prior": {"Beta": [1.5, 0.5]}, "fit": "counts"},
    {"name": "p_jam_prior",   "prior": {"Beta": [1, 1]},     "fit": "counts"},
    {"name": "eps_obs",       "prior": {"Beta": [0.1, 1.9]}, "fit": "counts"}
  ],
  "assumptions": ["goto is deterministic at the skill level but has no effect when the partner blocks the one-cell corridor (A to handle_right while B holds handle_left, B to handle_left while A holds handle_right)",
                  "the rattle reading depends only on the door state after the shake"],
  "open_questions": ["can a shake re-jam a free door?"]
}
```

Under the joint encoding, `cooperate_open` becomes a `joint_rule` in which two distinct agents on different handles choose pull on the same door in the same cycle, which is exactly how the draft schema writes BoxPush's cooperative push. The repair prompt receives the current model, a staged validation report (schema, vocabulary, normalization, compile, reachability), a fit report that flags parameters stuck at a boundary, lacking data or in conflict with their prior, at most five conditions × five samples of lowest-likelihood counterexamples linked to their discrepancy records, and a history of past patches with metric deltas to prevent cycles. It labels each failure as syntax, missing variable, missing mode, wrong precondition, wrong joint rule, observation model, initial belief or parametric, and its system message is short:

```text
You repair a POMDP model JSON. Output ONLY: {"diagnosis": [...], "patch": <RFC 6902 JSON Patch>,
"expected_effects": {...}, "new_assumptions": [...]}.
Prefer the SMALLEST structural change that (1) gives every listed counterexample non-zero
probability, (2) keeps all previously-passing checks passing, and (3) respects R1-R13 of the
generation rules. Do NOT edit numeric prior values or fitted values: the fitter owns numbers.
You may add or remove parameters, modes, variables, observation rules or joint rules. If a
failure is purely parametric (the structure already allows the observed outcome but the
fitted probability is low), write diagnosis "parametric", produce no patch for it, and say
what data would resolve it.
```

This is the supervisor's "typed model patches" requirement expressed as JSON Patch, and it mirrors the plan's sec. 4.4 division of labor, in which an LLM "may propose such hypotheses" while "statistical/model-selection code decides whether the evidence supports parameter or structure changes".

### Questions to settle on the Julia side

| Question | Options on the table | Proposed default |
|---|---|---|
| How do Python and Julia connect, and who owns the process? (a supervisor open decision) | juliacall in-process; offline artifact plus pure-Python runtime; subprocess; daemon | Offline artifacts for CI and deterministic tests; juliacall for experiments and online solvers |
| Which SARSOP? | SARSOP.jl (MIT wrapper around the GPL-2.0 APPL binary, MOMDP support); NativeSARSOP (pure Julia) | NativeSARSOP by default; SARSOP.jl as a cross-check and for MOMDPs |
| Which Julia version? | 1.10 LTS; 1.12; 1.13 | One exact version plus a committed Manifest; no upgrade across 1.13's hash change mid-study |
| What role does the POMDP planner play among the peers? | Replaces the BFS in the new domain; three-way comparison; recovery-only | Replaces the BFS behind `DomainServices.plan`; the twin stays as rollout policy, bound and baseline |
| Who writes numbers? | LLM; fitter; LLM priors plus fitter | Fitter, with LLM priors capped at pseudo-count 2 |
| Where does the belief live? | Python exact Bayes; Julia updater | Python for tabular models (auditable, CI-safe); Julia particle filters only for online solvers |
| When does the system halt under stochastic failure? | Keep the three-strike rule; belief-aware policy | A belief-aware policy that halts on zero-likelihood observations, not on repeats |
| How is the primitive-level BoxPush simulator built? | Skill level only; a hand-written Julia struct parameterized by IR data | Skill level first; the Julia struct only when online primitive planning is needed |

## Step 3 — Learn from experience with DSPy while a fitter owns the numbers

### Fix the dependency pin and the Ollama route before optimizing anything

The repo pins `dspy-ai==3.1.0` ([requirements.txt](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/requirements.txt#L7)), but `dspy-ai` is a ~1 KB meta-package that requires only `dspy>=3.1.0`. **The lockfile therefore resolves dspy 3.3.1 with gepa 0.1.4 and litellm 1.99.0, and a fresh pip install now gets dspy 3.4.0**, released 2026-09-25 UTC, though its git tag is dated 2026-09-24 US Eastern ([PyPI dspy-ai](https://pypi.org/project/dspy-ai/), [uv.lock](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/uv.lock)). Version 3.4.0 runs LMs through a new native engine, lm15: with the default `engine="auto"`, an `ollama_chat/...` model with `api_base="http://localhost:11434"` sends `POST /chat/completions` with no JSON mode ([dspy 3.4.0 release](https://github.com/stanfordnlp/dspy/releases/tag/3.4.0), [lm.py](https://github.com/stanfordnlp/dspy/blob/3.4.0/dspy/clients/lm.py)), while Ollama serves its OpenAI-compatible API under `/v1` ([Ollama docs](https://docs.ollama.com/api/openai-compatibility)). Passing `engine="litellm"` restores the native `/api/chat` route, and JSON-adapter calls again send `format:"json"` (plain ChatAdapter calls send none), a behavior verified against a mock server rather than a live Ollama instance. The fix is exact `dspy` and `gepa` pins, the optuna extra if MIPROv2 is used, and an explicit engine, which requires 3.4.0, because the locked 3.3.1 has no `engine` parameter and would forward `engine=` with the request kwargs.

A structural fix matters even more. The live seam wraps every NL request in one generic `_OneField` Predict, so DSPy is only a transport ([box_push_v1_nl_live.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/functional_layer/custom_env/box_push/env/box_push_v1_nl_live.py#L1-L42)), and optimizers, which tune per-module instructions and demos, have nothing to tune. The remedy is a set of per-module typed signatures (the supervisor already lists them, including a `ModelHypothesisGenerator` that turns a trace deviation plus a model slice into a typed hypothesis) inside an offline, opt-in optimization harness outside the guarded packages, with compiled programs saved as JSON and replayed through `RecordedLM` fixtures so that default tests stay deterministic ([nl/seam.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/nl/seam.py#L22-L83)). Because `Refine` and `BestOfN` force temperature 1.0 and the NL runtime config refuses any temperature other than 0 ([runtime_config.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/nl/runtime_config.py#L1-L43), [refine.py](https://github.com/stanfordnlp/dspy/blob/3.4.0/dspy/predict/refine.py)), those modules belong to offline generation, not to the runtime track.

### A cascaded metric turns every candidate model into a score and a critique

**Every optimizer decision below depends on one metric function, so it deserves the most care.** DSPy's contract is `metric(gold, pred, trace, pred_name, pred_trace)`, which may return `dspy.Prediction(score, feedback, objective_scores)`, and GEPA passes the feedback text verbatim to its reflection model ([metrics docs](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/diving-deeper/metrics-and-evaluation.md), [gepa.py](https://github.com/stanfordnlp/dspy/blob/3.4.0/dspy/teleprompt/gepa/gepa.py)). The scalar alone "gates acceptance and determines the final candidate", while named objective scores only shape parent and merge selection through `frontier_type` ([GEPA overview](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/api/optimizers/GEPA/overview.md)), so any exploitable weakness in the scalar is a direct risk.

The metric should run from cheap to expensive. It first parses and compiles, returning 0 with the first compiler errors as feedback on failure, plus zero-valued objective scores, since under `frontier_type="hybrid"` GEPA raises an error when no example reports them and otherwise averages each objective only over the examples that do; it then checks structure (normalization, coverage of every action and observation, reachability); it next scores prediction as held-out log-likelihood with an ε floor, normalized against a reference model and naming the worst-predicted steps in its feedback; it then runs the solved Julia policy in the wrapped backend over fixed seeds to measure success and return; and it finally counts discrepancies, quoting the typed events. The supervisor's list of DSPy signals ("task success, valid command rate, symbolic applicability, useful information acquisition, missed ambiguity, precondition/guard violations, unnecessary NL calls, translation residual quality, divergence classification, and recovery outcomes") is a ready menu for `objective_scores`. Four guards keep the metric honest: proper scoring rules instead of coverage, which rewards diffuse distributions; pairing the discrepancy rate with success, since a model can lower discrepancies by steering the planner away from risky skills; never echoing held-out layouts in feedback; and keeping LLM judges out of the gating score. Common random numbers (the same seeds for every candidate), rollout caching keyed by model hash, variant and seed, and DSPy's own cache keep costs down.

```python
# Sketch; `harness` stands for MAAOS code that does not exist yet. Not executed.
import dspy

lm_task = dspy.LM("ollama_chat/gemma4:e4b", api_base="http://localhost:11434", api_key="ollama",
                  temperature=0.0, seed=42, cache=True, engine="litellm")  # dspy>=3.4.0 only; keeps /api/chat
lm_reflect = dspy.LM("<strong hosted model>", temperature=1.0, max_tokens=32000)
dspy.configure(lm=lm_task)

class GeneratePOMDP(dspy.Signature):
    """Write the factored multi-agent POMDP as JSON valid against maaos-pomdp/0.1. Structure
    only: every probability is a named parameter with a weak prior; a fitter owns the numbers."""
    env_spec: str = dspy.InputField(desc="sole-input description plus typed interface blocks")
    trajectory_excerpt: str = dspy.InputField(desc="about 5 logged steps, stratified to include failures")
    discrepancies: str = dspy.InputField(desc="aggregated typed ExecutionDiscrepancy records")
    prior_model: str = dspy.InputField(desc="deterministic Kit model, RDDL, or previous POMDP JSON")
    pomdp_spec: PomdpSpec = dspy.OutputField()     # Pydantic model mirroring the JSON schema

def pomdp_metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
    report = harness.validate(pred.pomdp_spec)                   # schema, vocabulary, normalization, reachability
    if not report.ok:
        return dspy.Prediction(score=0.0, feedback=report.first_errors(5),   # "hybrid" needs objective_scores on every path
                               objective_scores={"loglik": 0.0, "return": 0.0, "no_discrepancy": 0.0})
    fitted = harness.fit(pred.pomdp_spec, gold.train_logs)       # Beta/Dirichlet posteriors from counts
    ll = harness.heldout_loglik(fitted, gold.heldout_logs)       # epsilon-floored, normalized to a reference
    ret, disc = harness.rollouts(fitted, gold.seeds)             # Julia policy run in the wrapped backend
    score = 0.2 + 0.3 * ll.normalized + 0.4 * ret.normalized + 0.1 * (1 - disc.rate)
    return dspy.Prediction(score=score,
                           feedback="\n".join(ll.worst(5) + disc.quotes(5)),
                           objective_scores={"loglik": ll.normalized, "return": ret.normalized,
                                             "no_discrepancy": 1 - disc.rate})

optimizer = dspy.GEPA(metric=pomdp_metric, max_metric_calls=300, reflection_lm=lm_reflect,
                      num_threads=2, track_stats=True, gepa_kwargs={"frontier_type": "hybrid"})
compiled = optimizer.compile(dspy.ChainOfThought(GeneratePOMDP), trainset=train, valset=val)
compiled.save("artifacts/pomdp_generator.json")  # commit with dataset hashes, dspy/gepa versions, Ollama digest
```

### GEPA leads the optimizer menu; the fitter keeps the numbers

| Optimizer | What it tunes | Data it needs | Fits MAAOS when | Watch-outs |
|---|---|---|---|---|
| **GEPA (default)** | Instructions, and module code through `dspy.Flex`, driven by textual feedback | Small sets work | Improving the generator and the advisor | Reflection cost, including metric calls outside `max_metric_calls`; the scalar gates acceptance; the docs disagree on whether `reflection_lm` is required, so set it explicitly |
| MIPROv2 | Instructions and demos by Bayesian search | 200+ examples for long runs | Many logged episodes exist | Needs the optuna extra since 3.2 |
| BootstrapFewShot / KNNFewShot | Demos from passing traces, or per-input nearest demos | ~10 examples, or a trainset plus an embedder | Building a model library | Demo tuning "tends to overfit" |
| SIMBA / InferRules | Appended natural-language rules | At least one batch | Recurring discrepancy patterns in the advisor | Rules can encode spurious correlations |
| Refine / BestOfN | Inference-time retries with hints | none | Offline generation only | Forces temperature 1.0 |
| `optimize_anything` / Flex | The model artifact or the pipeline code itself | An evaluator | Evolving the IR directly, POMDP-Coder style | Experimental |
| BootstrapFinetune / BetterTogether / DPO / GRPO | Weights | Hundreds of scored traces | Prompt-level gains have plateaued | Needs an external trainer; no DPO optimizer ships in DSPy 3.4.0; GRPO runs through Arbor on multiple GPUs |

Sources for the table: [choosing-an-optimizer](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/diving-deeper/choosing-an-optimizer.md), [gepa-in-depth](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/diving-deeper/gepa-in-depth.md), [flex](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/diving-deeper/flex.md), [optimize_anything](https://gepa-ai.github.io/gepa/blog/2026/02/18/introducing-optimize-anything/).

The case for GEPA rests on published numbers. On Qwen3-8B, GEPA improved the aggregate by **+9.62 points** against +2.61 for MIPROv2 and +3.68 for GRPO, using 1,839–7,051 rollouts per benchmark versus 24,000 for GRPO, though not uniformly, since GRPO won on AIME-2025 and GEPA with merging hurt IFBench ([GEPA](https://arxiv.org/html/2507.19457v2)). DSPy's ALFWorld tutorial took gpt-4o-mini from **19% to 72%** by prompt-optimizing a GPT-4o teacher and then distilling ([games tutorial](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/tutorials/games/index.ipynb)). The closest analogue to optimizing an LLM-to-formal-model generator from planner failures is textual-gradient prompt optimization of LLM-to-PDDL agents, which contributed **+37 points** in an ablation on MAT-THOR ([hierarchical prompt optimization](https://arxiv.org/abs/2602.21670)), and PDDLCoder implements its model-generation agent as a DSPy ReAct program. **No published study applies DSPy optimizers to POMDP generation, and none reports results with a ~4B task model**, so the gains must be measured rather than assumed. Budgets need to be explicit: GEPA's `auto="light"` preset with one predictor and a 20-example validation set already means 460 metric calls ([gepa.py](https://github.com/stanfordnlp/dspy/blob/3.4.0/dspy/teleprompt/gepa/gepa.py)), each call here is a generation, a Julia compile, a fit and several rollouts that together take hours, and 150–400 metric calls over 8–20 validation variants is a workable range. GEPA also re-invokes the metric with `pred_name` for every reflection-minibatch example outside the `max_metric_calls` count, so the metric should be memoized on the spec hash and example id.

The unmerged `f-model-generation` branch already built a generate-validate-fit-evaluate-feedback loop around GPT-4o writing Pyro world models ([world_model_generator.py](https://github.com/FouziAbd/MAAOS/blob/7d6a81591bae84ba493f1d12acc739e05848742b/model_layer/maintenance/world_model_generator.py#L222-L297), [model_manager.py](https://github.com/FouziAbd/MAAOS/blob/7d6a81591bae84ba493f1d12acc739e05848742b/model_layer/maintenance/model_manager.py#L24-L57)). Its mechanics transfer: accept-only-if-better with rollback maps onto GEPA's strict-improvement acceptance, "negative memory" of rejected attempts remains useful, and its separate expand, reduce and refine operators with explicit acceptance criteria become structural operators arbitrated by held-out likelihood, all under fixed seeds and temperature 0. Its representation does not transfer, because torch, on which Pyro is built, and the whole `model_layer` tree are forbidden imports in the guarded packages, and generated code runs through a bare `exec` ([dynamic_loader.py](https://github.com/FouziAbd/MAAOS/blob/7d6a81591bae84ba493f1d12acc739e05848742b/model_layer/maintenance/dynamic_loader.py#L114)), and neither does its evaluation, which scored models on the same data it fitted them to ([dynamic_loader.py](https://github.com/FouziAbd/MAAOS/blob/7d6a81591bae84ba493f1d12acc739e05848742b/model_layer/maintenance/dynamic_loader.py#L137-L143)).

### Seven places where experience and data improve the system

| Learning surface | What improves | Experience or data used | Tool | Cost and caveat |
|---|---|---|---|---|
| Parameters | Outcome and observation probabilities, priors | Logged outcome counts with post-hoc state | Beta/Dirichlet fitter with no LLM; alternatively Bayes-adaptive planning, as in FV-POMCP's Dirichlet counts ([FV-POMCP](https://arxiv.org/abs/1404.1140)) | Cheap; flag parameters with no data or a fit stuck at 0 or 1 |
| Structure | Missing modes, variables, observation rules, joint rules | Zero- or low-likelihood steps and typed discrepancy records | Repair prompt producing a JSON Patch, over a candidate pool with Thompson or UCB1 selection | Medium; errors in a generated model mislead the search ([CWM notes](https://en.papernotes.org/ICLR2026/code_intelligence/code_world_models_for_general_game_playing/)) |
| Generator instructions | How the LLM decomposes and names things | The cascaded metric across environment variants | GEPA with a reflection model | 150–400 metric calls; hours |
| Generator exemplars | In-context demos and `prior_model` seeds | Past generations that passed the gates | BootstrapFewShot with a threshold; KNNFewShot over a model library | Cheap; demos overfit more than instructions |
| Advisory proposer | Belief-aware skill choice and recovery | Divergences, refusals, discrepancy clusters | SIMBA or InferRules; offline Refine | Medium; temperature-1 sampling stays offline |
| Solver configuration | Tree queries, depth, exploration constant, bounds | Rollouts on fixed seeds | Grid search, then freeze | Cheap; must remain iteration-budgeted |
| Weights | A local model that writes better structure | Hundreds of scored (better, worse) generations | BootstrapFinetune, BetterTogether, external DPO | Expensive; the DSPy docs call fine-tuning "the last lever, not the first" |

The data is already in the traces. `TraceEntry` records pre- and post-state, the selected call, the execution result, discrepancies, divergences, the NL proposal, coverage and confidence ([trace_schema.py](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/shared/trace_schema.py#L43-L73)), and the authoritative backend supplies post-hoc true state in simulation, which is the privileged signal POMDP Coder needs and Pinductor does without. Examples should be inputs-only, since DSPy optimizers can start from "only 5 or 10 examples" ([optimizers.md](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/optimizers.md)) even though the docs advise "aim for at least 300 examples" ([overview.md](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/overview.md)); splits should run by environment variant (jam priors, slip rates, agent counts), never by time step; and the test set should hold unseen variants, agent counts and obfuscated names. Every optimized program should be committed with the dataset hashes, the dspy, gepa and litellm versions and the Ollama model digest ([saving and loading](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/diving-deeper/saving-and-loading.md)). Refinement stops once all gates pass and held-out likelihood gains stay below ε for k rounds, once no CriticAL-style posterior-predictive test remains significant after Bonferroni correction ([CriticAL](https://arxiv.org/html/2411.06590)), or when the budget runs out.

The capability risk is concrete, although the evidence for a hard threshold is thin. Pinductor reports that Qwen3-14B fails to cross "the threshold needed to synthesize a usable world model", but that rests on one weaker model earning near-zero reward on two sparse-reward tasks, LAVA and UNLOCK, and it still won 10% of LAVA episodes ([Pinductor](https://arxiv.org/html/2605.13740v1)). Gemma 4 31b reached only 61.3% top-level (L3) success in PDDLCoder (65 of 106 test problems) ([PDDLCoder](https://arxiv.org/html/2608.16637v1)). gemma4:e4b is far smaller than either, so it should fill schema-typed JSON fragments through per-component calls or leave structure to a stronger model.

### Questions to settle on learning

| Question | Options on the table | Proposed default |
|---|---|---|
| Which model writes structure? | gemma4:e4b; a larger local model; a hosted frontier model | Measure first with a 2×2 of model size against architecture on CoopGrid-Jam-PO |
| Is a hosted reflection model acceptable? | Yes (cost and privacy trade-off); local only | Yes for offline optimization; the runtime stays local |
| Which DSPy version? | Hold the lock at 3.3.1; move to 3.4.0 | Exact `dspy==3.4.0` and `gepa==0.1.4` with `engine="litellm"` |
| How big is the optimization budget? | `auto` presets; explicit `max_metric_calls` | 150–400 metric calls on 8–20 validation variants |
| What varies across train, validation and test? | Layouts, priors, slip rates, agent counts, name obfuscation | Split by variant; hold out agent counts and obfuscated names |
| How do default tests replay optimized programs? | `RecordedLM` fixtures; skip in CI | Saved JSON program plus `RecordedLM` fixtures; live optimization stays opt-in |
| When should weights change? | Never; after a plateau | After prompt-level gains plateau and several hundred scored generations exist |

## Step 4 — Benchmark against classical and LLM planners and claim the empty quadrant

### Classical solvers presuppose the model MAAOS wants to generate

The canonical Cooperative Box Pushing Dec-POMDP is small, with two agents, 100 states, four actions and five front-cell observations per agent, and actions that succeed with probability 0.9 ([Seuken & Zilberstein](https://arxiv.org/pdf/1206.5295)), yet exact solutions still stop near horizon 5, at **V\*(3) = 66.081, V\*(4) = 98.593613 and V\*(5) = 107.729851** ([RS-MAA*, IJCAI 2023](https://www.ijcai.org/proceedings/2023/0600.pdf)). At horizon 100, approximate MAA* brackets the optimum between a lower bound of 2431.4 and an upper bound of 2453.4 ([IJCAI 2024](https://www.ijcai.org/proceedings/2024/0745.pdf)).

Scale comes only from structure that a person supplies by hand. MacDec-POMDP's O-MBDP used macro-actions to handle a 50×50 navigation-among-movable-obstacles grid (5×10⁷ states) at horizon 100 in 4,723 s ([MacDec-POMDP, JAIR 2019](https://lis.csail.mit.edu/pubs/amato-konidaris-jair19.pdf)). Factored statistics took FV-POMCP to 10 agents in an MPOMDP ([FV-POMCP](https://arxiv.org/abs/1404.1140)) and FV-MCTS-MaxPlus to 48 agents, but only in fully observable MMDPs with expert-defined coordination graphs ([FV-MCTS](https://arxiv.org/pdf/2101.04788)). FDMAP solves a team POMDP with SARSOP and projects it onto agents, handling box pushing with 3 agents, 59,049 states and 324 joint actions ([FDMAP](https://icaps20subpages.icaps-conference.org/in.bgu.ac.il/en/natural_science/cs/Documents/ICAPS2020-DMAP-WS-Papers/A%20Factored%20Approach%20To%20Solving%20Dec-POMDPs.pdf)), and deterministic-dynamics methods reached more than 10 million states ([Det-Dec-POMDP](https://arxiv.org/html/2508.21595v1)). Every family assumes the model is given: the MacDec-POMDP authors call full model knowledge "often impractical", FFSPC lists automatic discovery of scopes as future work ([FFSPC](https://www.ifaamas.org/Proceedings/aamas2013/docs/p563.pdf)), and no classical result scales agents, horizon and state space at once under tight coupling. **MAAOS's typed schema already supplies the scopes, interaction graph and macro-actions that these methods leave to a domain expert**, which is where it can compete; beating exact solvers on their canonical benchmarks is not.

### LLM multi-agent planners repair plans, not models

Almost every LLM multi-agent system puts the LLM in the per-step decision loop. In Chen et al.'s BoxNet, the nearest published analogue to BoxPush, a hybrid in which a central LLM proposes and local LLMs check reached 75.6% average success against 52.1% for a single central planner and 19.4% for fully decentralized dialog, with a rules-based verifier feeding errors back into the prompt ([Chen et al.](https://arxiv.org/html/2309.15943)). LLaMAR's plan-act-correct-verify loop reached 0.62 success on two-agent MAP-THOR against 0.34 for ReAct and 0.25 for CoELA ([LLaMAR](https://arxiv.org/html/2407.10031)). LaMMA-P adds classical PDDL planning and reached 0.93 against SMART-LLM's 0.70 on compound tasks, but "assumes fully observable, static environments" ([LaMMA-P](https://arxiv.org/html/2409.20560)), and PARTNR found LLMs "unable to recover from learned skill failures", with a "300% increase in extraneous effort" under decentralized planning ([PARTNR](https://arxiv.org/html/2411.00081)).

The 2025–2026 work splits into two threads that have not met. Embodied-cooperation systems such as CoBel-World, whose structured beliefs cut communication by 64–79%, still update beliefs through LLM reasoning at run time ([CoBel-World](https://arxiv.org/abs/2509.21981)), while the LLM-generated POMDP models solved by formal planners (POMDP Coder, Pinductor and PO-PDDL) are all single-agent, as is BSE, which filters a hand-specified model and leaves the action choice to the LLM. Only game-playing work generates multi-agent, partially observable models: PIANIST beat an LLM-as-policy baseline 66.6% to 33.3% on GOPS, and Code World Models beat or matched Gemini 2.5 Pro used as a policy in 9 of 10 games ([PIANIST](https://arxiv.org/html/2411.15998v1), [CWM](https://arxiv.org/html/2510.04542)). MAAOS's own history agrees with the warning. The legacy BoxPush runner silently rewrote malformed LLM outputs and DSPy exceptions to `explore` ([section18.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/docs/handoff/section18.md#L55-L62)), the KAZ analysis found that "the LLM-based planner generates actions without respecting the hard tactical constraints" ([ZOMBIE_ATTACK_FAILURE_ANALYSIS.md](https://github.com/FouziAbd/MAAOS/blob/63df772b9a6ab86dc2ea3d7fddeec26c5a4ede69/ZOMBIE_ATTACK_FAILURE_ANALYSIS.md#L1-L354)), and a NeurIPS 2025 position paper warns that LLM multi-agent systems risk "revisiting problems the MAS literature has already addressed" ([La Malfa et al.](https://arxiv.org/abs/2505.21298)).

| Work | Agents and observability | What the LLM does | Formal machinery | Belief | Learns the model from failures |
|---|---|---|---|---|---|
| IMBDP, RS-MAA*, approximate MAA* | 2, Dec-POMDP | nothing | Exact or approximate Dec-POMDP search | Policy trees, occupancy states | No: hand-built model |
| MacDec-POMDP | 2–4, Dec-POMDP | nothing | Option-level dynamic programming | none | No: hand-designed macro-actions |
| FV-POMCP | up to 10, MPOMDP | nothing | Factored POMCP | Particles | Parameters only (Dirichlet) |
| FDMAP | 3, team POMDP | nothing | SARSOP, then projection | Team belief | No |
| Chen et al. (BoxNet) | 4–32, mostly full | Per-step planner | Rules verifier | State-action history | No: plan repair |
| LLaMAR | 1–5, partial | Planner, actor, corrector, verifier | none | Textual joint memory | No: plan repair |
| LaMMA-P | heterogeneous, full | Allocator, PDDL problem writer | Fast Downward | none | No |
| POMDP Coder, Pinductor | 1, partial | Writes T, O, R and initial-state programs | Belief-space A* | Particles | Yes: coverage or likelihood |
| PIANIST, CWM | 2+ players, imperfect information | Writes game-model code | MCTS or ISMCTS | Information sets, inference functions | CWM: unit tests from transitions |
| **MAAOS (proposed)** | 2 to N, MPOMDP | Writes typed IR structure; advises | POMDPs.jl solvers | Exact or particle, calibrated | Yes: typed discrepancies plus fitted parameters |

### Eight falsifiable claims where MAAOS can do better

The research supports eight hypotheses, each a prediction with a named baseline rather than a result. The claim that no prior work occupies this quadrant rests on a limited number of targeted searches and stays provisional until a dedicated search confirms it.

| # | Claim | Mechanism | Primary metric | Baselines |
|---|---|---|---|---|
| H1 | A correct model can be acquired from the typed schema | LLM writes structure, fitter writes numbers | Exact reproduction of the UAI07 tables; value gap V_true(π\*_true) − V_true(π\*_gen) | Hand-written model; POMDP-Coder-style coverage repair; Pinductor-style likelihood repair; tabular Dirichlet learning |
| H2 | Typed discrepancies repair structure faster | A discrepancy is a failing unit test that names the skill, arguments and refusal | Backend episodes to reach a target likelihood; repeat-discrepancy rate | Free-text re-prompting (LLaMAR corrector style); Bayes-adaptive parameter learning |
| H3 | The optimistic twin is a useful bound and rollout policy | The twin is a determinized MMDP relaxation | POMCP/DESPOT value at a fixed budget; the optimism gap | Random or heuristic rollouts; QMDP |
| H4 | Model once, plan many | LLM calls scale with regenerations, not with steps × agents | LLM calls and tokens per episode at matched success, reported with solver CPU time | ReAct; a LLaMAR-style loop; Chen et al.'s central and hybrid planners |
| H5 | Beliefs are calibrated and auditable | Solver-side exact or particle belief | Brier score and NLL on hidden variables; time to identify them | Li et al.'s textual belief; CoBel-World-style symbolic belief |
| H6 | A ~4B local model suffices when given structure | The LLM writes schema-constrained fragments | Success and fidelity in a 2×2 of LLM size × architecture | The same LLM as a per-step policy; a frontier-API reference |
| H7 | The system halts with evidence under model mismatch | Typed evidence channels plus a probabilistic monitor | False-completion rate; detection latency; share of failures explained | Fixed-model POMCP; an LLM-only planner |
| H8 | Structure can be generated automatically | The schema supplies scopes, coordination graphs and macro-actions | Value at N agents against hand-designed structure | FV-MCTS with a hand-built graph; MacDec options; FDMAP |

The evidence behind these claims is uneven. H1 and H2 generalize POMDP Coder's and CWM's single-agent and game results, H4 follows from the per-step LLM cost that LLaMAR and Hypothetical Minds report ([Hypothetical Minds](https://arxiv.org/html/2407.07086)), and H5 extends BSE's single-agent Tiger result (95% in one run and 84% in another, against 80%). H8 is the weakest, although an LLM-derived coordination graph already helped MARL on a cooperative push task with models as small as 1.5B ([graph priors](https://arxiv.org/html/2604.17191v1)). Three claims should not be made at all: beating exact Dec-POMDP solvers on tiny benchmarks, reporting MPOMDP values as though they were Dec-POMDP values, and anything about perception-heavy settings, where PARTNR's success fell from 0.57 to 0.30 when non-privileged perception replaced privileged perception.

### A three-tier evaluation keeps the claims honest

Each tier answers a different question. The formal anchor runs canonical Box Pushing and MAAOS's own PO domains, comparing the LLM-generated model plus a POMDPs.jl solver against the true model plus the same solver. There, the flattened centralized UAI07 model yields an MPOMDP value that must equal or exceed the Dec-POMDP V\*, with exact Dec-POMDP values coming from MADP or the book code; reward conventions must be normalized first, since the MADP file keys rewards on state and action and pays 99.8 for the joint push even though the box moves only with probability 0.81 ([MADP file](https://github.com/MADPToolbox/MADP/blob/master/problems/boxPushingUAI07.dpomdp.gz)); and the file's discount of 1.0 with finite horizons calls for FiniteHorizonPOMDPs.jl's `fixhorizon` wrapper, which adds the stage to the state but keeps `discount = 1.0`, so SARSOP-style solvers need a discount just below 1 (NativeSARSOP's blind lower bound divides by `1 - γ`) or a dedicated finite-horizon solver ([FiniteHorizonPOMDPs.jl](https://github.com/JuliaPOMDP/FiniteHorizonPOMDPs.jl)). The LLM-planner anchor is Chen et al.'s BoxLift, whose hidden box weights make it naturally partially observable, scaled from 2 agents upward. The external anchor is MAP-THOR, which has published baselines, or the symbolic mode of C-WAH.

Baselines should share the local LLM wherever possible: a random policy, the scripted "heavy is sticky" heuristic, `symbolic_primary` and `advisory_two_track`, an LLM-only policy, true-model QMDP, SARSOP and POMCP, the generated model with the same solvers, a tabular model learned from the same data budget, and MAPPO reported as return against environment steps. Four families of metrics complete the picture: task metrics (success, return, executive and primitive steps); normalized return ℛ = (R_gen − R_rand) / (R_true − R_rand) ([GIF-MCTS](https://arxiv.org/html/2405.15383v1)); model fidelity (held-out log-likelihood, KL on reachable pairs, value gap); and belief calibration and cost (Brier and NLL on hidden variables, plus LLM calls, tokens and wall-clock time split between LLM and solver). The protocol uses 30–100 paired-seed episodes per condition, with BSE's 40 as a reasonable minimum, a temperature-0 fixed-seed local model because two runs of BSE's identical GPT-4o configuration at temperature 0.3 gave 84.0% and 95.0% on Tiger, pre-registered hypotheses, and ablations of typed versus free-text discrepancies, DSPy optimization, POMDP versus the determinized twin, and solver versus LLM policy. Name-obfuscated and rule-perturbed variants are essential, because canonical Box Pushing is famous enough for a model to recall, and its side-by-side heavy push would mislead any model that assumes it describes MAAOS.

### Questions to settle on evaluation

| Question | Options on the table | Proposed default |
|---|---|---|
| MPOMDP only, or also decentralized execution? | MPOMDP; Dec-POMDP via MADP or the book code; FDMAP-style projection | MPOMDP, clearly labeled; Dec-POMDP numbers only on tiny instances |
| Which external LLM benchmark? | BoxNet/BoxLift; MAP-THOR; C-WAH symbolic | BoxLift first, as the closest to BoxPush; MAP-THOR later |
| Re-implement LLM baselines with the local model? | Re-implement; quote published numbers | Re-implement ReAct and a LLaMAR-style loop on the same model; quote the rest with caveats |
| Pre-register the hypotheses? | Yes; no | Yes, H1–H8 with metrics, seeds and stopping rules |
| How is contamination controlled? | Obfuscated names; perturbed rules; both | Both, on UAI07 and on BoxPush |

## Conclusion

The research changes the shape of the problem more than its difficulty. The first POMDP MAAOS needs is Tiger-sized and the Julia solvers that handle it are mature; what is genuinely new is a division of labor in which the LLM owns structure, a fitter owns numbers, Julia owns decisions and the backend owns truth. That split reconciles three things that could have pulled against each other (the supervisor's typed-IR rule, the optimistic-twin invariant and DSPy optimization), because the twin survives as the relaxation that bounds and guides the solver, the IR stays small enough to validate and diff, and every number that matters is estimated rather than asserted. It also gives "discrepancy" a precise probabilistic meaning, an observation the current model considers (nearly) impossible, and that single event crashes a discrete belief update, depletes a particle filter, fails a coverage gate, becomes GEPA's reflection feedback and seeds the repair prompt. One typed signal serving five consumers is MAAOS's structural advantage over both lineages in the literature.

Two findings should reorder priorities. First, the sequential-executive contract, which looks like a limitation beside joint-action MPOMDPs, is a tractability lever: grounded calls grow polynomially with team size where joint actions grow exponentially, so the agent scaling that classical MPOMDP solvers struggle with may come cheaply, at a price in makespan that should be measured. Second, the binding risk sits upstream of Julia. Pinductor's threshold-like dependence on model capability, in which its one weaker model (Qwen3-14B) earned near-zero reward, and PDDLCoder's 61.3% success rate with a 31B model mean a ~4B local model may not write correct structure unaided, so the first experiment should be the 2×2 of model size against architecture on CoopGrid-Jam-PO, before any BoxPush-scale investment. If gemma falls below the threshold, a stronger model writes structure while gemma keeps advice and schema filling, and every other step of the plan stands unchanged.
