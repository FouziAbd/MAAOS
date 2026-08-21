"""Static guards on the contract / symbolic side of the codebase.

P0_V1_DECISIONS Decision 6 / supervisor :55. The danger is NOT the belief-based BFS inside skill
execution — that one is optimistic by construction. The danger is the exact ground-truth
predicates in the env (`_cell_free_for_box`, `_tandem_feasible`, `_find_tandem`,
`_is_free_for_agent`) and, above all, `_bfs_avoid_boxes`, which becomes an exact reachability
oracle the moment someone passes it the exact grid instead of the belief grid — WITHOUT ANY CHANGE
TO ITS CALL SIGNATURE. A behavioural test cannot catch that; this can.

Two things this guard deliberately does:

1. It DISCOVERS the packages to guard instead of hardcoding them, so a future `symbolic/` or
   `planning/` package is protected the day it is created rather than the day someone remembers
   to add it here. A hardcoded list fails open exactly when it matters.
2. It forbids the symbolic side from importing `runtime`, because repeated-failure bookkeeping
   must not become a hidden symbolic feasibility predicate (:118).

What it CANNOT do: stop someone writing a BFS over `StateSnapshot.static.walls` by hand. The
structural defence against that is `shared/symbolic_state.py` — symbolic reasoning consumes
`SymbolicState` literals, which carry no geometry at all.
"""
import ast
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Backend / framework roots the contract and symbolic side must never depend on.
FORBIDDEN_PREFIXES = frozenset({
    "functional_layer", "middleware_layer", "model_layer",
    "shared_skills", "skill_executor_push", "box_push_env",
    "multi_agent_box_push_env", "box_push_centralized", "box_push_per_step",
    "minigrid", "pettingzoo", "gymnasium", "dspy", "torch", "numpy",
})

#: Dynamic-import escapes that would make the AST scan blind.
FORBIDDEN_DYNAMIC = frozenset({"importlib", "imp", "pkgutil", "runpy"})

#: Pre-existing packages that are NOT part of the V1 contract/symbolic side.
LEGACY_PACKAGES = frozenset({
    "functional_layer", "middleware_layer", "model_layer", "utils", "ui", "tests", "docs",
})

#: Runtime state the symbolic side must not reach (:118).
RUNTIME_PACKAGES = frozenset({"runtime"})


def discovered_guarded_packages(root: pathlib.Path = REPO_ROOT):
    """Every top-level package that is part of the V1 contract/symbolic side.

    `root` is parameterized ONLY so the fail-closed probes can build a throwaway tree in a
    temporary directory. Nothing may write a probe package into the repository working tree: an
    aborted run would leave a package behind that changes discovery for every later run, and it
    would be committable.
    """
    packages = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if entry.name in LEGACY_PACKAGES:
            continue
        # ANY directory containing Python is guarded — requiring __init__.py let a
        # NAMESPACE package (PEP 420) or a plain code directory bypass every guard
        # (consistency-all finding; probe below demonstrates the closed hole)
        if any(entry.rglob("*.py")):
            packages.append(entry.name)
    return packages


def imported_modules(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # relative import — stays inside the package
                continue
            if node.module:
                yield node.module, node.lineno


def python_files(package: str, root: pathlib.Path = REPO_ROOT):
    return sorted((root / package).rglob("*.py"))


def forbidden_import_violations(packages, forbidden, root: pathlib.Path = REPO_ROOT):
    """The single enforcement path, shared by the real checks and the fail-closed probes.

    Routing both through one function is what makes the probes meaningful: a probe that passes
    cannot coexist with a real check that was quietly hardcoded back to ("shared", "domain").
    """
    return [
        f"{path.relative_to(root)}:{lineno} imports {module}"
        for package in packages
        for path in python_files(package, root)
        for module, lineno in imported_modules(path)
        if module.split(".")[0] in forbidden
    ]


def runtime_violations(packages, root: pathlib.Path = REPO_ROOT):
    return forbidden_import_violations(packages, RUNTIME_PACKAGES, root)


def backend_violations(packages, root: pathlib.Path = REPO_ROOT):
    return forbidden_import_violations(packages, FORBIDDEN_PREFIXES, root)


class TestGuardCoverage(unittest.TestCase):
    def test_guard_discovers_the_contract_packages(self):
        """Fails if the guard would silently scan nothing, or miss a package it should cover."""
        discovered = set(discovered_guarded_packages())
        for expected in ("shared", "domain", "runtime"):
            with self.subTest(package=expected):
                self.assertIn(expected, discovered)

    def test_guard_scans_a_meaningful_number_of_files(self):
        total = sum(len(python_files(p)) for p in discovered_guarded_packages())
        self.assertGreater(total, 10, "guard scanned suspiciously few files")


class TestNoBackendImports(unittest.TestCase):
    def test_no_backend_or_framework_imports(self):
        violations = backend_violations(discovered_guarded_packages())
        self.assertEqual(
            violations, [], "contract/symbolic side must not import the backend:\n" + "\n".join(violations)
        )

    def test_no_dynamic_import_escapes(self):
        """`importlib.import_module("multi_agent_box_push_env")` is invisible to an AST scan of
        Import nodes, so the escape hatches are banned outright."""
        violations = []
        for package in discovered_guarded_packages():
            for path in python_files(package):
                for module, lineno in imported_modules(path):
                    if module.split(".")[0] in FORBIDDEN_DYNAMIC:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}"
                        )
                text = path.read_text(encoding="utf-8")
                if "__import__" in text:
                    violations.append(f"{path.relative_to(REPO_ROOT)} uses __import__")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_sys_path_manipulation(self):
        """The backend uses runtime sys.path insertion; the contract side must not, or the import
        guard could be bypassed by making a backend module importable under another name."""
        violations = []
        for package in discovered_guarded_packages():
            for path in python_files(package):
                if "sys.path" in path.read_text(encoding="utf-8"):
                    violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(violations, [])


class TestSymbolicSideCannotReachRuntimeState(unittest.TestCase):
    """:118 — repeated-failure bookkeeping must not become a hidden feasibility predicate."""

    @staticmethod
    def symbolic_side(root: pathlib.Path = REPO_ROOT):
        """DERIVED, so it fails closed. A hardcoded ("shared", "domain") would leave a future
        `symbolic/` or `planning/` package free to import `runtime.executive_history` — i.e. free
        to key applicability on repeated-failure bookkeeping, the exact hidden feasibility
        predicate :118 forbids — and the guard would still pass."""
        return tuple(p for p in discovered_guarded_packages(root) if p not in RUNTIME_PACKAGES)

    def test_the_symbolic_side_is_derived_not_hardcoded(self):
        side = set(self.symbolic_side())
        self.assertIn("shared", side)
        self.assertIn("domain", side)
        self.assertNotIn("runtime", side)

    def test_the_real_tree_has_no_runtime_imports_on_the_symbolic_side(self):
        """Consistency-check P3 WARN 16: `runtime_violations` previously ran ONLY on throwaway
        probe trees, so the :118 ban ("no package may key on repeated-failure bookkeeping") was
        enforced nowhere on the real tree — `nl/` importing `runtime.executive_history` would
        have passed every test while its docstring claimed otherwise. This is the real-tree
        assertion that claim rests on."""
        self.assertEqual(runtime_violations(self.symbolic_side()), [])

    @staticmethod
    def _probe_tree(stack, *, package="symbolic_probe", leak=None):
        """Build a throwaway repo-shaped tree in a temp dir. Never touches the working tree."""
        import tempfile
        root = pathlib.Path(stack.enter_context(tempfile.TemporaryDirectory()))
        for existing in ("shared", "domain", "runtime"):
            (root / existing).mkdir()
            (root / existing / "__init__.py").write_text("", encoding="utf-8")
        pkg = root / package
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        if leak is not None:
            (pkg / "leak.py").write_text(f"import {leak}\n", encoding="utf-8")
        return root

    def test_a_newly_created_symbolic_package_is_discovered_immediately(self):
        """The fail-closed property, and the only form a hardcoded ("shared", "domain") tuple
        cannot survive: a package appears and the guard must cover it with nobody editing here."""
        import contextlib
        with contextlib.ExitStack() as stack:
            root = self._probe_tree(stack)
            discovered = discovered_guarded_packages(root)
            self.assertIn("symbolic_probe", discovered)
            self.assertIn("symbolic_probe", self.symbolic_side(root))

    def test_a_runtime_import_in_a_new_package_is_actually_caught(self):
        """Discovery without enforcement would still fail open."""
        import contextlib
        with contextlib.ExitStack() as stack:
            root = self._probe_tree(stack, leak="runtime.executive_history")
            self.assertTrue(
                runtime_violations(self.symbolic_side(root), root),
                "a runtime import in a newly discovered package went unnoticed",
            )

    def test_a_backend_import_in_a_new_package_is_actually_caught(self):
        """The other half of the guard: the backend/framework scan must be fail-closed too."""
        import contextlib
        for leaked in ("skill_executor_push", "functional_layer.custom_env", "minigrid"):
            with self.subTest(module=leaked), contextlib.ExitStack() as stack:
                root = self._probe_tree(stack, leak=leaked)
                self.assertTrue(
                    backend_violations(discovered_guarded_packages(root), root),
                    f"a {leaked} import in a newly discovered package went unnoticed",
                )

    def test_an_init_less_namespace_package_cannot_bypass_the_guard(self):
        """PEP 420 namespace packages import fine WITHOUT __init__.py — before this round,
        discovery required the marker file, so `oracle/feasibility.py` at repo root would
        have been invisible to every guard. Probe tree, never the real repo."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            probe = root / "oracle"
            probe.mkdir()
            (probe / "feasibility.py").write_text(
                "import functional_layer\n", encoding="utf-8"
            )
            discovered = discovered_guarded_packages(root)
            self.assertIn("oracle", discovered)
            violations = forbidden_import_violations(discovered, FORBIDDEN_PREFIXES, root)
            self.assertTrue(violations)

    def test_no_unguarded_bare_module_sits_at_repo_root(self):
        """A top-level single .py file is importable but belongs to no guarded package.
        Fail-closed: the repo root must contain no bare Python modules at all."""
        bare = [p.name for p in REPO_ROOT.glob("*.py")]
        self.assertEqual(bare, [])

    def test_the_probes_never_write_into_the_repository(self):
        import contextlib
        before = {p.name for p in REPO_ROOT.iterdir()}
        with contextlib.ExitStack() as stack:
            self._probe_tree(stack, leak="runtime")
        self.assertEqual({p.name for p in REPO_ROOT.iterdir()}, before)

    def test_runtime_depends_on_shared_not_the_reverse(self):
        roots = set()
        for path in python_files("runtime"):
            for module, _ in imported_modules(path):
                roots.add(module.split(".")[0])
        self.assertIn("shared", roots)
        self.assertNotIn("runtime", {m.split(".")[0] for p in python_files("shared")
                                     for m, _ in imported_modules(p)})

    #: The stdlib modules domain/ actually uses; a WHITELIST, so `domain -> nl` or
    #: `domain -> symbolic` fails here (the old body only excluded backend+runtime,
    #: quietly under-enforcing the test's own name — consistency-all finding).
    DOMAIN_STDLIB_WHITELIST = frozenset({
        "dataclasses", "enum", "json", "hashlib", "typing", "functools", "itertools",
        "collections", "abc", "math", "re", "__future__",
    })

    def test_domain_imports_only_shared_and_stdlib(self):
        for path in python_files("domain"):
            for module, lineno in imported_modules(path):
                root = module.split(".")[0]
                with self.subTest(file=path.name, module=module):
                    self.assertIn(
                        root,
                        self.DOMAIN_STDLIB_WHITELIST | {"shared", "domain"},
                        f"{path.name}:{lineno} imports {module!r} — outside the declared "
                        f"shared+stdlib surface",
                    )


if __name__ == "__main__":
    unittest.main()
