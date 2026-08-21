---
paths:
  - "docs/**/*"
  - "README*.md"
  - "CLAUDE.md"
---

# Documentation Rules

Documentation must describe **actual implemented behavior**.

When a behavior is established by code, prefer exact `path -> class/function` references over duplicating internal algorithms in prose.

Always distinguish:

- implemented and tested
- implemented but not acceptance-tested
- planned
- intentionally out of scope for V1
- unresolved domain contract

Do not claim P5+ stochastic/DBN/Julia/concurrency/learning capability merely because interfaces are extensible for it.

Keep these synchronized:

- `docs/handoff/section18.md`
- skill/state/observation schemas
- acceptance traces
- final `docs/implementation/P0_P4_IMPLEMENTATION.md`
