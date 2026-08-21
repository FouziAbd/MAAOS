# MCP Policy for MAAOS Claude Code

## Default: no MCP required

P0-P4 is primarily a local repository + supervisor-specification task. Claude Code already has local file/search/shell capabilities, so adding filesystem or generic MCP servers adds complexity without solving a current problem.

Do **not** add MCP merely because it is available.

## Optional GitHub MCP

Consider GitHub MCP later only when the workflow materially needs remote GitHub data/actions such as:

- reading/managing issues
- inspecting PR review discussions
- creating/updating PRs
- coordinating repository metadata not available in the local checkout

Local `git` is sufficient for ordinary branch/diff/history/code work.

## Rule for adding any MCP server

Before adding one, document:

1. exact capability missing from local Claude Code;
2. data/access permissions requested;
3. whether it is needed for P0-P4;
4. failure mode if unavailable;
5. whether project teammates/supervisor need the same configuration.

MCP must never become a hidden dependency for deterministic P0-P4 tests.
