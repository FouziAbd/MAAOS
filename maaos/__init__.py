"""`maaos` — reserved for the command-line entry point; DK3 adds `__main__.py`/`cli.py`
(`python -m maaos ...`). Nothing is runnable here yet.

Reserved in DK1 so the lint/type/guard scopes name it once. It is a composition-layer
package like `app/` (may import `app`, `runtime`, `domains`), backend-guarded, and uses no
dynamic import: domain names resolve through `domains.registry.REGISTRY` only.
"""
