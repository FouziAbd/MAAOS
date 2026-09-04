# Claude Code Setup for MAAOS P0-P4

> **Retired.** This describes the P0-P4 implementation setup. The current Claude Code harness for the R0-R6 refactor is documented in `CLAUDE.md`; start with `/refactor-preflight`, then `/refactor-phase R0`.

## 1. Start from the correct code

Use the branch containing the current BoxPush high-level skill work (`middleware_layer`) as the source baseline. Prefer creating a dedicated implementation branch, for example:

```bash
git checkout middleware_layer
git pull
git checkout -b symbolic-twin-v1
```

Freeze the exact branch/commit in `docs/handoff/section18.md`.

## 2. Install this configuration

Copy the contents of this pack into the repository root so that the repo contains:

```text
CLAUDE.md
.claude/
docs/supervisor/
docs/handoff/
docs/decisions/
docs/claude/
docs/prompts/
```

This pack intentionally replaces the old monolithic `CLAUDE.md` with a shorter P0-P4-oriented root file plus modular `.claude/rules/`. If the repository changed after this pack was generated, manually merge any new factual run/backend notes rather than blindly overwriting them.

## 3. Verify Claude Code sees the configuration

Start Claude Code in the repository root:

```bash
claude
```

Then run:

```text
/doctor
```

Check that project Skills are listed and custom agents are discovered. Claude Code project Skills live in `.claude/skills/<name>/SKILL.md`; custom project agents live in `.claude/agents/`.

## 4. First workflow — do not implement yet

Run:

```text
/handoff-audit
```

Review `docs/handoff/section18.md`. Resolve only genuine ambiguities. The audit should locate exact backend evidence before code generation.

Then run:

```text
/consistency-check all
```

This establishes the baseline inconsistencies.

## 5. Implement one phase at a time

Use:

```text
/implement-phase P0
/consistency-check P0

/implement-phase P1
/consistency-check P1

/implement-phase P2
/acceptance-test create
/consistency-check P2

/implement-phase P3
/consistency-check P3

/implement-phase P4
/acceptance-test run
/consistency-check all
```

Do not ask Claude to implement P0-P4 in a single giant pass.

## 6. Final review/documentation

Run:

```text
/final-audit report
```

Review the findings. If appropriate:

```text
/final-audit fix
```

Then:

```text
/implementation-doc
```

The final document should be `docs/implementation/P0_P4_IMPLEMENTATION.md`.

## 7. Optional completion-test hook

A hook implementation is included at:

`.claude/hooks/task_completed_tests.py`

It is intentionally **not active by default** because the current repository historically did not have a stable automated test command.

After P0/P1 establishes pytest or another stable command:

1. copy `.claude/test-command.example.txt` to `.claude/test-command.txt` and edit it;
2. copy the `TaskCompleted` hook stanza from `.claude/settings.hooks.example.json` into your project/user settings;
3. create `.claude/ENABLE_COMPLETION_TEST_HOOK`.

The hook then blocks task completion when the configured test command fails.

## 8. MCP

Do not configure MCP initially. See `docs/claude/MCP_POLICY.md`.
