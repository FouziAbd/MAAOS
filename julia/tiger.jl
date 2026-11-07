# T2 spike: solve the Tiger POMDP with NativeSARSOP under iteration budgets (no wall-clock cap),
# twice, plus its SparseTabularPOMDP conversion, and print values for the thesis record.
# Run from the repo root:  ~/.local/opt/julia-1.10.13/bin/julia --project=julia julia/tiger.jl
using POMDPs, POMDPTools, POMDPModels, NativeSARSOP, StableRNGs, Random, Printf

function budgeted_solver()
    NativeSARSOP.SARSOPSolver(;
        max_time=Inf, max_steps=200, precision=1e-6, verbose=false,
        init_lower=NativeSARSOP.BlindLowerBound(; bel_res=1e-2, max_iter=10_000, max_time=Inf),
        init_upper=NativeSARSOP.FastInformedBound(; bel_res=1e-2, max_iter=10_000, max_time=Inf))
end

m = TigerPOMDP()                      # r_listen=-1, r_findtiger=-100, r_escapetiger=10, p_listen_correctly=0.85, discount=0.95
b0 = initialstate(m)
p1 = solve(budgeted_solver(), m)
p2 = solve(budgeted_solver(), m)
same = p1.alphas == p2.alphas && p1.action_map == p2.action_map
t = SparseTabularPOMDP(m)
pt = solve(budgeted_solver(), t)
bt = initialstate(t)

rng = StableRNG(2026)
returns = [simulate(RolloutSimulator(; rng=rng, max_steps=100), m, p1, updater(p1), b0) for _ in 1:2000]

@printf("julia %s\n", VERSION)
@printf("tiger value(b0) = %.6f\n", value(p1, b0))
@printf("tiger value(b0), tabular = %.6f\n", value(pt, bt))
@printf("alpha vectors = %d; deterministic across two solves = %s\n", length(p1.alphas), same)
@printf("action at b0 = %s\n", string(action(p1, b0)))
@printf("mean discounted return, 2000 seeded episodes = %.4f\n", sum(returns) / length(returns))
