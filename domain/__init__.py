"""Frozen V1 domain packages.

`box_push_v1` is the P0 domain freeze for BoxPush: the fixed instance, the initial canonical
`StateSnapshot`, the deterministic structured skill IR, and representative task examples.

This package imports ONLY from `shared`. It must never import the backend
(`functional_layer.*`, `shared_skills`) — see P0_V1_DECISIONS Decision 6, enforced by
`tests/test_no_backend_imports.py`.
"""
