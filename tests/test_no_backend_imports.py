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
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Backend / framework roots the contract and symbolic side must never depend on.
FORBIDDEN_PREFIXES = frozenset({
    "functional_layer", "legacy", "middleware_layer", "model_layer", "utils",
    "shared_skills", "skill_executor_push", "box_push_env",
    "multi_agent_box_push_env", "box_push_centralized", "box_push_per_step",
    "minigrid", "pettingzoo", "gymnasium", "dspy", "torch", "numpy",
})

#: Dynamic-import escapes that would make the AST scan blind.
FORBIDDEN_DYNAMIC = frozenset({"importlib", "imp", "pkgutil", "runpy"})

#: Pre-existing packages that are NOT part of the V1 contract/symbolic side. The pre-V1
#: trees (`middleware_layer`, `model_layer`, `utils`, `ui`) live under `legacy/` since
#: 2026-09-18 and are deliberately NOT listed by their old names: a resurrected top-level
#: copy would be discovered and guarded fail-closed, not silently skipped.
LEGACY_PACKAGES = frozenset({"functional_layer", "legacy", "tests", "docs"})

#: Runtime state the symbolic side must not reach (:118).
RUNTIME_PACKAGES = frozenset({"runtime"})

#: The application/composition layer (R4, widened by DK1): the guarded packages that sit
#: ABOVE the runtime and legitimately import it (report Part II dependency direction). They
#: are still guarded against the backend like every other package; they are only excluded
#: from the :118 "symbolic side must not reach runtime" scan, where they do not belong.
#: DK1 (`docs/decisions/DK1_DOMAIN_PACKAGE.md`): `domains` (one declaration package per
#: domain) and `maaos` (the CLI) join `app`. Inside `domains/<x>/` the :118 guarantee is kept
#: PER MODULE by `domain_role_violations` below — only `__init__.py` may reach the runtime.
COMPOSITION_PACKAGES = frozenset({"app", "domains", "maaos"})

#: DK1: the enumerated backend-boundary modules — the ONE file per domain package that may
#: import a backend/framework root (its own simulator, `numpy`, the BoxPush adapter). A static
#: set, never a glob: adding a domain adds a line here, and the DK1 test asserts the set equals
#: `{domains/<name>/environment.py for name in domains.registry.REGISTRY}`. The exemption
#: covers FORBIDDEN_PREFIXES minus NEVER_EXEMPT_ROOTS (legacy trees, LM frameworks), and nothing else: the
#: dynamic-import ban, the sys.path ban and the runtime/app ban still apply to these files.
DOMAIN_ENVIRONMENT_MODULES = frozenset({
    "domains/box_push/environment.py",
})
#: Never exempt, even for the door: the legacy trees, and the LM frameworks — an environment
#: module is a simulator binding, never an LM binding (R6 kept the dspy seam outside the
#: guarded tree; `nl/` may not import it either).
NEVER_EXEMPT_ROOTS = frozenset({"legacy", "middleware_layer", "model_layer", "utils", "dspy", "torch"})

#: DK fix: the one file whose STRINGS may mention the `sys.path` / `sys.modules` markers (it
#: mirrors the text scan for authors and builds a child-interpreter script). Enumerated,
#: never a glob: for it the check is an AST one (`_sys_attribute_access`) — its own code must
#: not be able to reach those attributes. The dynamic-import marker has no such exemption.
TEXT_SCAN_STRING_ONLY = frozenset({"app/validation.py"})


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


def _sys_attribute_access(source: str, attrs) -> bool:
    """True when the CODE (not its strings) can reach `sys.<attr>` for any attr in `attrs`:
    `sys.path`, an alias (`import sys as s; s.path`), a chain (`os.sys.path`),
    `from sys import path`, `sys.__dict__`, or `getattr/setattr/delattr/vars(sys, ...)`."""
    tree = ast.parse(source)
    attrs = set(attrs) | {"__dict__"}
    aliases = {"sys"} | {
        alias.asname for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names if alias.name == "sys" and alias.asname
    }

    def is_sys(node) -> bool:
        return (isinstance(node, ast.Name) and node.id in aliases) or (
            isinstance(node, ast.Attribute) and node.attr == "sys")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in attrs and is_sys(node.value):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "sys" and any(
                a.name in attrs for a in node.names):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
                "getattr", "setattr", "delattr", "vars") and node.args and is_sys(node.args[0]):
            return True
    return False


def forbidden_import_violations(
    packages, forbidden, root: pathlib.Path = REPO_ROOT, *, exempt_modules=frozenset()
):
    """The single enforcement path, shared by the real checks and the fail-closed probes.

    Routing both through one function is what makes the probes meaningful: a probe that passes
    cannot coexist with a real check that was quietly hardcoded back to ("shared", "domain").

    `exempt_modules` (DK1): repo-relative POSIX paths allowed to import `forbidden` roots —
    except the NEVER_EXEMPT_ROOTS, which no exemption reaches. Only `backend_violations`
    passes the enumerated `DOMAIN_ENVIRONMENT_MODULES`; every other check passes nothing.
    """
    violations = []
    for package in packages:
        for path in python_files(package, root):
            rel = path.relative_to(root).as_posix()
            exempt = rel in exempt_modules
            for module, lineno in imported_modules(path):
                top = module.split(".")[0]
                if top in forbidden and not (exempt and top not in NEVER_EXEMPT_ROOTS):
                    violations.append(f"{rel}:{lineno} imports {module}")
    return violations


def runtime_violations(packages, root: pathlib.Path = REPO_ROOT):
    """:118 — and, since R4, the composition layer too: `app` imports `runtime`, so a
    symbolic-side import of `app` would reach repeated-failure bookkeeping transitively."""
    return forbidden_import_violations(packages, RUNTIME_PACKAGES | COMPOSITION_PACKAGES, root)


def backend_violations(packages, root: pathlib.Path = REPO_ROOT, *, exempt_modules=None):
    exempt = DOMAIN_ENVIRONMENT_MODULES if exempt_modules is None else exempt_modules
    return forbidden_import_violations(
        packages, FORBIDDEN_PREFIXES, root, exempt_modules=exempt
    )


# ── DK1: module roles inside a domain package ─────────────────────────────────────────
#: `domains/<x>/` is a composition package for the package-level scan, so the :118 guarantee
#: is re-established PER MODULE here (`docs/decisions/DK1_DOMAIN_PACKAGE.md`, `domains/__init__`):
#:   __init__.py     may import runtime / app / the sibling `environment` (composition role)
#:   environment.py  may import a backend (via DOMAIN_ENVIRONMENT_MODULES); never runtime,
#:                   app, `model`, or the package itself
#:   any other       stdlib, shared, kit and sibling MODULES only; never runtime, app,
#:                   `environment`, a backend root, or the package itself
#: "The package itself" (`import domains.x`, `from domains.x import NAME`, `from . import NAME`
#: where NAME is not a sibling module) is banned for non-init modules because `__init__.py` may
#: import the runtime: binding a name through it would launder `runtime` into the symbolic
#: side without ever spelling it (review W8).
DOMAINS_PACKAGE = "domains"
DOMAIN_ROLE_ALLOWED_ROOTS = frozenset({"shared", "kit"})


def imported_modules_resolved(path: pathlib.Path, package: str):
    """Like `imported_modules`, but RESOLVES relative imports against `package` (the dotted
    name of the module's package) and yields `from . import NAME` as `package.NAME`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                if node.level > len(base):
                    # beyond the top-level package: Python itself refuses this at import
                    # time; report it as the package so it never resolves to an empty root
                    yield package, node.lineno
                    continue
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                prefix = ".".join(base)
                if node.module:
                    yield f"{prefix}.{node.module}", node.lineno
                else:
                    for alias in node.names:
                        yield f"{prefix}.{alias.name}", node.lineno
            elif node.module:
                if node.module.startswith(package + ".") or node.module == package:
                    # `from domains.x import NAME`: NAME may be a sibling module
                    for alias in node.names:
                        yield (f"{node.module}.{alias.name}" if node.module == package
                               else node.module), node.lineno
                else:
                    yield node.module, node.lineno


def domain_role_violations(root: pathlib.Path = REPO_ROOT):
    """Every domain package under `domains/`, checked module by module against its role."""
    violations = []
    domains_dir = root / DOMAINS_PACKAGE
    if not domains_dir.is_dir():
        return violations
    stdlib_names = set(sys.stdlib_module_names) | {"__future__"}
    for pkg_dir in sorted(p for p in domains_dir.iterdir() if p.is_dir()):
        package = f"{DOMAINS_PACKAGE}.{pkg_dir.name}"
        siblings = {p.stem for p in pkg_dir.glob("*.py")}
        for path in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            role = path.name if path.parent == pkg_dir else "other"
            for module, lineno in imported_modules_resolved(path, package):
                top = module.split(".")[0]
                what = None
                if role == "__init__.py":
                    continue                                    # composition role
                if top in RUNTIME_PACKAGES or top == "app" or top == "maaos":
                    what = f"{role} may not import the runtime/composition layer"
                elif module == package:
                    what = "may not import its own package (laundering through __init__)"
                elif module.startswith(package + "."):
                    member = module[len(package) + 1:].split(".")[0]
                    if member not in siblings:
                        what = "may not bind a package attribute through __init__ (laundering)"
                    elif role == "environment.py" and member == "model":
                        what = "environment.py may not import model (backend boundary)"
                    elif role != "environment.py" and member == "environment":
                        what = f"{path.name} may not import environment (symbolic side)"
                elif top == DOMAINS_PACKAGE:
                    what = "may not import another domain package"
                elif role != "environment.py" and top in FORBIDDEN_PREFIXES:
                    what = f"{path.name} may not import a backend/framework root"
                elif role != "environment.py" and top not in (
                    stdlib_names | DOMAIN_ROLE_ALLOWED_ROOTS
                ):
                    what = f"{path.name} may import only stdlib, shared, kit and siblings"
                if what:
                    violations.append(f"{rel}:{lineno} imports {module} — {what}")
    return violations


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
                rel = path.relative_to(REPO_ROOT).as_posix()
                text = path.read_text(encoding="utf-8")
                if rel in TEXT_SCAN_STRING_ONLY:
                    if _sys_attribute_access(text, {"path", "modules"}):
                        violations.append(rel)
                    continue
                # DK1: `sys.modules` too — a domain's `__init__` (composition role) loads the
                # runtime before its siblings run, so `sys.modules["runtime..."]` in a
                # symbolic-side module would be a deterministic escape from the AST scan.
                if "sys.path" in text or "sys.modules" in text:
                    violations.append(rel)
        self.assertEqual(violations, [])

    def test_the_string_only_exemption_is_load_bearing_and_ast_checked(self):
        """The exempt file really mentions the markers in strings (else the exemption is dead),
        and the AST check catches real attribute access."""
        for rel in TEXT_SCAN_STRING_ONLY:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            strings = [n.value for n in ast.walk(ast.parse(text))
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            self.assertTrue(any("sys.path" in s or "sys.modules" in s for s in strings), rel)
            self.assertFalse(_sys_attribute_access(text, {"path", "modules"}), rel)
        caught = (
            "import sys\nsys.path.insert(0, 'x')\n",
            "import sys\nm = sys.modules['runtime']\n",
            "import os\nos.sys.path.insert(0, 'x')\n",              # a chain
            "import sys as s\ns.path.append('x')\n",                # an alias
            "from sys import modules\n",
            "import sys\nsys.__dict__['path']\n",
            "import sys\ngetattr(sys, 'path')\n",
            "import sys\nvars(sys)['modules']\n",
        )
        for source in caught:
            self.assertTrue(_sys_attribute_access(source, {"path", "modules"}), source)
        self.assertFalse(_sys_attribute_access("MARKER = 'sys.path'\n", {"path", "modules"}))
        self.assertFalse(_sys_attribute_access("import sys\nprint(sys.executable)\n", {"path", "modules"}))


class TestSymbolicSideCannotReachRuntimeState(unittest.TestCase):
    """:118 — repeated-failure bookkeeping must not become a hidden feasibility predicate."""

    @staticmethod
    def symbolic_side(root: pathlib.Path = REPO_ROOT):
        """DERIVED, so it fails closed. A hardcoded ("shared", "domain") would leave a future
        `symbolic/` or `planning/` package free to import `runtime.executive_history` — i.e. free
        to key applicability on repeated-failure bookkeeping, the exact hidden feasibility
        predicate :118 forbids — and the guard would still pass."""
        return tuple(
            p for p in discovered_guarded_packages(root)
            if p not in RUNTIME_PACKAGES and p not in COMPOSITION_PACKAGES
        )

    def test_the_symbolic_side_is_derived_not_hardcoded(self):
        side = set(self.symbolic_side())
        self.assertIn("shared", side)
        self.assertIn("domain", side)
        self.assertIn("symbolic", side)
        self.assertIn("nl", side)
        self.assertNotIn("runtime", side)
        # R4: the composition layer is above the runtime, so it is not "the symbolic side"
        # — but it IS still discovered and backend-guarded like every other package
        self.assertNotIn("app", side)
        self.assertIn("app", discovered_guarded_packages())
        # DK1: `domains` and `maaos` are composition packages too; `kit` is symbolic side
        for composition in ("domains", "maaos"):
            self.assertNotIn(composition, side)
            self.assertIn(composition, discovered_guarded_packages())
        self.assertIn("kit", side)

    def test_the_real_tree_has_no_domain_role_violations(self):
        """DK1: inside `domains/<x>/` the :118 guarantee is re-established per module."""
        self.assertEqual(domain_role_violations(), [])

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

    def test_a_composition_import_on_the_symbolic_side_is_actually_caught(self):
        """R4 (test-review F1): `app` imports `runtime`, so `symbolic -> app` would be
        `symbolic -> runtime` by another name. The same scan must catch it."""
        import contextlib
        with contextlib.ExitStack() as stack:
            root = self._probe_tree(stack, leak="app.box_push_v1")
            self.assertTrue(
                runtime_violations(self.symbolic_side(root), root),
                "an app import in a newly discovered symbolic-side package went unnoticed",
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
        shared_roots = {m.split(".")[0] for p in python_files("shared")
                        for m, _ in imported_modules(p)}
        self.assertNotIn("runtime", shared_roots)
        self.assertNotIn("app", shared_roots)          # R4: nor the layer above runtime

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
