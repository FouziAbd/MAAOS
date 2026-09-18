"""R6 (report Phase 6 item 6, owner decision: option (a) — mark the legacy trees as
reference-only rather than moving them); post-R6 maintenance 2026-09-18 relocated the live
seam out of `model_layer/`.

`middleware_layer/` and `model_layer/` are pre-V1 reference code. This module pins the
boundary the owner set: nothing under `shared/`, `runtime/`, `app/`, or `tests/` imports
either tree — statically or through `importlib`/`__import__`. The supported V1 live seam
(`build_live_seam`) lives beside the runner in the sys.path-mounted env dir, outside both
trees. It also pins that both trees are excluded from the mypy/ruff gates and that the rule
and README say so.
"""
import ast
import pathlib
import tomllib
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The reference-only trees.
LEGACY_ROOTS = ("middleware_layer", "model_layer")

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
        elif isinstance(node, ast.ImportFrom) and node.module:
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
                    found.setdefault(module, []).append(f"{path.relative_to(_REPO_ROOT)}:{lineno}")
        violations = {m: where for m, where in found.items() if m not in ALLOWED_LEGACY_IMPORTS}
        self.assertEqual(
            violations, {},
            "legacy trees are reference-only; the V1 side imports them here:\n"
            + "\n".join(f"  {m}: {', '.join(w)}" for m, w in sorted(violations.items())),
        )
        # the allowlist is empty, so nothing at all may be found; the scan's non-vacuity
        # (static, from-import, importlib, __import__, lazy in-function) is carried by the
        # probe test below
        self.assertEqual(found, {})

    def test_the_scan_sees_static_and_dynamic_imports(self):
        source = (
            "import middleware_layer.x\n"
            "from model_layer.planner import DsPy_planner\n"
            "import importlib\n"
            "def f():\n"
            "    importlib.import_module('model_layer.agent')\n"
            "    __import__('middleware_layer')\n"
        )
        scratch = _REPO_ROOT / "tests" / "__r6_probe__.py"
        try:
            scratch.write_text(source, encoding="utf-8")
            modules = {m for m, _ in _legacy_imports(scratch)}
        finally:
            scratch.unlink()
        self.assertEqual(modules, {
            "middleware_layer.x", "model_layer.planner", "model_layer.agent", "middleware_layer",
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
        # and no copy of it remains under the legacy trees
        for root in LEGACY_ROOTS:
            self.assertEqual(list((_REPO_ROOT / root).rglob("v1_nl_live.py")), [], root)

    def test_both_trees_exist_and_are_outside_the_static_gates(self):
        pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        for root in LEGACY_ROOTS:
            with self.subTest(tree=root):
                self.assertTrue((_REPO_ROOT / root).is_dir())
                self.assertNotIn(root, pyproject["tool"]["mypy"]["files"])
                self.assertIn(root, pyproject["tool"]["ruff"]["extend-exclude"])

    def test_the_rule_and_the_readme_state_the_boundary_and_the_seam_home(self):
        rule = (_REPO_ROOT / ".claude/rules/legacy-packages.md").read_text(encoding="utf-8")
        readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for text, label in ((rule, "rule"), (readme, "README")):
            with self.subTest(document=label):
                for root in LEGACY_ROOTS:
                    self.assertIn(root, text)
                self.assertIn("box_push_v1_nl_live", text)
                self.assertIn("reference", text.lower())
        self.assertIn("REFERENCE-ONLY", readme)


if __name__ == "__main__":
    unittest.main()
