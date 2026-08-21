#!/usr/bin/env python3
"""Optional Claude Code TaskCompleted hook for MAAOS.

Disabled unless `.claude/ENABLE_COMPLETION_TEST_HOOK` exists.
Reads `.claude/test-command.txt` and blocks task completion (exit 2)
when the configured command fails.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()).resolve()
    claude_dir = project_dir / ".claude"

    if not (claude_dir / "ENABLE_COMPLETION_TEST_HOOK").exists():
        return 0

    command_file = claude_dir / "test-command.txt"
    if not command_file.exists():
        print(
            "Completion test hook is enabled but .claude/test-command.txt is missing.",
            file=sys.stderr,
        )
        return 2

    command = command_file.read_text(encoding="utf-8").strip()
    if not command or command.startswith("#"):
        print("Completion test command is empty.", file=sys.stderr)
        return 2

    subject = payload.get("task_subject", "task")
    print(f"[MAAOS] Verifying before completing: {subject}", file=sys.stderr)
    print(f"[MAAOS] Running: {command}", file=sys.stderr)

    completed = subprocess.run(command, cwd=project_dir, shell=True)
    if completed.returncode != 0:
        print(
            f"P0-P4 completion blocked: test command failed with exit code {completed.returncode}. "
            "Fix the failure or disable the marker intentionally.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
