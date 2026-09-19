"""`maaos` — the command-line entry point: `python -m maaos <command>` (DK3).

A composition-layer package like `app/` (it may import `app`, `runtime`, `domains`),
backend-guarded, and free of dynamic imports: domain names resolve through
`domains.registry.REGISTRY` only. See `maaos/cli.py` for the commands.
"""
