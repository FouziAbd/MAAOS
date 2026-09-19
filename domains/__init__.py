"""`domains` — one sub-package per domain, each exporting a `DomainPackage` named `DOMAIN`
(DK1 — `docs/decisions/DK1_DOMAIN_PACKAGE.md`).

This module is an import surface only. Registration is explicit and hand-edited in
`domains/registry.py`; nothing here discovers, scans, or mutates anything.

Layout of one domain package `domains/<name>/` and the module ROLES the guard enforces
(`tests/test_no_backend_imports.py::domain_role_violations`):

    __init__.py      composition — declares `DOMAIN = DomainPackage(...)`; the ONLY module
                     that may import `app`, `runtime`, or the sibling `environment`
    environment.py   backend boundary — the ONLY module that may import a backend or
                     framework (its own simulator, `numpy`, the BoxPush adapter, ...); may
                     not import `app`, `runtime`, or `model`
    every other      the symbolic side — `types.py`, `model.py`, ...: stdlib, `shared`, `kit`
    module           and sibling MODULES only (`from .types import ...`); never `app`,
                     `runtime`, `environment`, a backend, or the package itself

`domains/` sits ABOVE the runtime like `app/` (it is a composition package for the guard's
`:118` scan) and is backend-guarded like every other package except through the enumerated
`environment.py` door.
"""
