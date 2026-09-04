---
name: v1-regression
description: Verify that the current MAAOS tree still preserves the accepted deterministic offline Symbolic-Twin BoxPush V1 behavior.
disable-model-invocation: true
---

# MAAOS V1 Regression Gate

This is a read/execute verification workflow. Do not edit product code.

Read:

- `CLAUDE.md`
- `docs/decisions/P0_V1_DECISIONS.md`
- `docs/supervisor/SUPERVISOR_P0_P4_CONTRACT.md`
- `docs/implementation/P0_P4_IMPLEMENTATION.md`
- current acceptance traces/tests.

Run:

```bash
python -B -m unittest discover -s tests -t .
```

Then verify from tests/traces/current runner code that the accepted BoxPush V1
scenario still preserves:

- `SYMBOLIC_PRIMARY` expected halt behavior;
- `ADVISORY_TWO_TRACK` expected recovery/completion behavior;
- the designed physical discrepancies;
- separate discrepancy/divergence/fault evidence;
- policy-independent execution;
- offline/default execution without a live LM.

Do not invoke `--nl live`.

If a safe headless runner option is already implemented, it may be used.
Inspect the runner/help first; do not invent CLI flags.

Report exact commands, pass/fail/skip results, acceptance evidence, and any
behavior drift.
