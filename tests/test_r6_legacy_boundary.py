"""R6 (report Phase 6 item 6, owner decision: option (a) — mark the legacy trees as
reference-only) and the post-R6 maintenance that completed the relocation (2026-09-18).

`legacy/` holds the pre-V1 reference trees `middleware_layer/`, `model_layer/`, `utils/`
and `ui/`. They keep their import names (the legacy runners mount `legacy/` on sys.path)
and are importable from the repo root as `legacy.<tree>` too (PEP 420 namespace), so EVERY
one of those names is a banned root on the V1 side. This module pins that boundary: nothing
under `shared/`, `runtime/`, `app/`, or `tests/` imports a legacy root — statically or
through `importlib`/`__import__`; the supported V1 live seam (`build_live_seam`) lives
beside the runner in the sys.path-mounted env dir, outside `legacy/`; the trees sit under
`legacy/` and outside the mypy/ruff gates; and the rule and README say so.
"""
import ast
import pathlib
import tempfile
import tomllib
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where the reference-only trees live, and which trees.
LEGACY_DIR = "legacy"
LEGACY_TREES = ("middleware_layer", "model_layer", "utils", "ui")

#: Import roots the V1 side must not reach: the container AND the trees' own import names.
LEGACY_ROOTS = ("legacy", "middleware_layer", "model_layer", "utils")

#: Legacy modules the V1 side may import. EMPTY since 2026-09-18 (the live NL seam moved
#: beside the runner). Adding a name here is a deliberate owner-level decision.
ALLOWED_LEGACY_IMPORTS = frozenset()

#: The supported V1 live seam (the only dspy binding), its consumers, and the import line.
LIVE_SEAM = "functional_layer/custom_env/box_push/env/box_push_v1_nl_live.py"
RUNNER = "functional_layer/custom_env/box_push/env/box_push_v1_run.py"
LIVE_TEST = "tests/test_p3_live_lm.py"
LIVE_SEAM_IMPORT = "from box_push_v1_nl_live import build_live_seam"

#: The V1 side that must not reach the legacy trees.
GUARDED_DIRS = ("shared", "runtime", "app", "tests")


def _python_files(directory: pathlib.Path):
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def _legacy_imports(path: pathlib.Path):
    """Every legacy module name a source file imports, statically or dynamically."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in LEGACY_ROOTS:
                    yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            # `node.level` excludes relative imports: `from .utils import x` names a sibling,
            # never the legacy `utils` root
            if node.module.split(".")[0] in LEGACY_ROOTS:
                yield node.module, node.lineno
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else None)
            if name in ("import_module", "__import__") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                        and first.value.split(".")[0] in LEGACY_ROOTS:
                    yield first.value, node.lineno


class TestTheV1SideImportsNothingFromTheLegacyTrees(unittest.TestCase):
    def test_the_v1_side_imports_nothing_from_the_legacy_trees(self):
        found = {}
        for directory in GUARDED_DIRS:
            for path in _python_files(_REPO_ROOT / directory):
                for module, lineno in _legacy_imports(path):
                    found.setdefault(module, []).append(
                        f"{path.relative_to(_REPO_ROOT).as_posix()}:{lineno}")
        violations = {m: where for m, where in found.items() if m not in ALLOWED_LEGACY_IMPORTS}
        self.assertEqual(
            violations, {},
            "legacy trees are reference-only; the V1 side imports them here:\n"
            + "\n".join(f"  {m}: {', '.join(w)}" for m, w in sorted(violations.items())),
        )
        # the allowlist is empty, so nothing at all may be found; the scan's non-vacuity
        # (static, from-import, importlib, __import__, lazy in-function, every root name)
        # is carried by the probe test below
        self.assertEqual(found, {})

    def test_the_scan_sees_static_and_dynamic_imports_under_every_legacy_name(self):
        source = (
            "import middleware_layer.x\n"
            "from model_layer.planner import DsPy_planner\n"
            "import legacy.model_layer.agent\n"
            "from utils.logging_utils import setup_logging\n"
            "from .utils import sibling\n"          # relative: NOT a legacy import
            "import importlib\n"
            "def f():\n"
            "    importlib.import_module('model_layer.agent')\n"
            "    importlib.import_module('legacy')\n"
            "    __import__('middleware_layer')\n"
        )
        # a throwaway file OUTSIDE the working tree: an aborted run must never leave a probe
        # module behind in tests/ (it would be discovered, and committable)
        with tempfile.TemporaryDirectory() as tmp:
            scratch = pathlib.Path(tmp) / "__r6_probe__.py"
            scratch.write_text(source, encoding="utf-8")
            modules = {m for m, _ in _legacy_imports(scratch)}
        self.assertEqual(modules, {
            "middleware_layer.x", "model_layer.planner", "legacy.model_layer.agent",
            "utils.logging_utils", "model_layer.agent", "legacy", "middleware_layer",
        })

    def test_the_live_seam_lives_beside_the_runner_outside_the_legacy_trees(self):
        path = _REPO_ROOT / LIVE_SEAM
        self.assertTrue(path.is_file(), LIVE_SEAM)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        self.assertIn("build_live_seam", {n.name for n in tree.body if isinstance(n, ast.FunctionDef)})
        # the dspy binding is lazy (inside the builder): importing the module needs no framework
        module_scope = {
            name for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
            for name in ([a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""])
        }
        self.assertNotIn("dspy", {m.split(".")[0] for m in module_scope})
        # both consumers import it by its env-dir name, lazily
        for consumer in (RUNNER, LIVE_TEST):
            with self.subTest(consumer=consumer):
                self.assertIn(LIVE_SEAM_IMPORT, (_REPO_ROOT / consumer).read_text(encoding="utf-8"))
        # and no copy of it remains under the legacy tree
        self.assertEqual(list((_REPO_ROOT / LEGACY_DIR).rglob("v1_nl_live.py")), [])

    def test_the_legacy_trees_live_under_legacy_and_the_old_roots_are_gone(self):
        from tests.test_no_backend_imports import FORBIDDEN_PREFIXES, LEGACY_PACKAGES
        legacy = _REPO_ROOT / LEGACY_DIR
        self.assertTrue(legacy.is_dir())
        # a plain directory, not a package: `legacy.<tree>` resolves only as a namespace
        self.assertFalse((legacy / "__init__.py").exists())
        for tree in LEGACY_TREES:
            with self.subTest(tree=tree):
                self.assertTrue((legacy / tree).is_dir(), tree)
                self.assertFalse((_REPO_ROOT / tree).exists(), f"{tree} resurrected at the root")
                # NOT skipped by the auto-discovering guard: a resurrected copy is guarded
                self.assertNotIn(tree, LEGACY_PACKAGES)
        # the container is skipped by discovery and banned as an import root
        self.assertIn(LEGACY_DIR, LEGACY_PACKAGES)
        self.assertIn(LEGACY_DIR, FORBIDDEN_PREFIXES)
        for root in LEGACY_ROOTS:
            self.assertIn(root, FORBIDDEN_PREFIXES, root)

    def test_the_legacy_directory_is_outside_the_static_gates(self):
        pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(LEGACY_DIR, pyproject["tool"]["ruff"]["extend-exclude"])
        for target in pyproject["tool"]["mypy"]["files"]:
            self.assertFalse(target == LEGACY_DIR or target.startswith(LEGACY_DIR + "/"), target)

    def test_the_rule_and_the_readme_state_the_boundary_and_the_seam_home(self):
        rule = (_REPO_ROOT / ".claude/rules/legacy-packages.md").read_text(encoding="utf-8")
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for text, label in ((rule, "rule"), (readme, "README")):
            with self.subTest(document=label):
                self.assertIn("legacy/", text)
                for tree in ("middleware_layer", "model_layer"):
                    self.assertIn(tree, text)
                self.assertIn("box_push_v1_nl_live", text)
                self.assertIn("reference", text.lower())
        self.assertIn("REFERENCE-ONLY", readme)
        self.assertIn('"legacy/**/*"', rule)


if __name__ == "__main__":
    unittest.main()
