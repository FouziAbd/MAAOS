# julia/ — pinned Julia project for the thesis POMDP work

Outside the guarded Python packages and never used by the default offline suite
(`.claude/rules/v1-scope.md` "Thesis exception"). Solved policies reach the Python side only as
committed artifacts (from phase T4); regeneration is opt-in.

- Julia **1.10.13** (LTS), exactly. `Project.toml` pins `julia = "1.10"` and the committed
  `Manifest.toml` pins every package version: POMDPs 1.0.0, POMDPTools 1.1.0, NativeSARSOP 0.1.4,
  POMDPModels 0.4.22, JSON3 1.14.4, StableRNGs 1.1.0. Do not upgrade across Julia 1.13 (its
  hash change can reorder `Dict` iteration and so break byte-identical artifacts).
- Install used on the owner's machine (no PATH or shell-profile change):

  ```bash
  mkdir -p ~/.local/opt && cd ~/.local/opt
  curl -fsSLO https://julialang-s3.julialang.org/bin/linux/x64/1.10/julia-1.10.13-linux-x86_64.tar.gz
  echo "f2bfa080db29b50a9bf250f69e9acdcfd8b7c49409dee5e55588f986706fb8bd  julia-1.10.13-linux-x86_64.tar.gz" | sha256sum -c -
  tar -xzf julia-1.10.13-linux-x86_64.tar.gz
  ~/.local/opt/julia-1.10.13/bin/julia --project=julia -e 'using Pkg; Pkg.instantiate()'
  ```

- `tiger.jl` — the T2 toolchain check: NativeSARSOP on Tiger with iteration budgets and no
  wall-clock cap, solved twice (alpha vectors must be identical) and once via its
  `SparseTabularPOMDP` conversion (same value). Run from the repository root:

  ```bash
  ~/.local/opt/julia-1.10.13/bin/julia --project=julia julia/tiger.jl
  ```
