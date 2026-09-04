"""The application layer (R4 — report Phase 4): concrete BoxPush components that sit ABOVE
the generic runtime, and the composition root that assembles them.

Dependency direction (report Part II):

    app  ->  domain / symbolic / nl / runtime / shared

`app` may import every V1 package; nothing under `runtime/`, `shared/`, `domain/`,
`symbolic/`, or `nl/` may import `app`. Like every guarded package it must never import
the backend — the environment is handed to `build_loop` by its caller (the runner, or a
test), which is the only place backend construction belongs.

Composition is explicit Python: constructor injection through the `shared.contracts`
protocols, no plugin discovery, no configuration language.
"""
