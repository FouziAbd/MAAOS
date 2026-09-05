"""R6 repository tooling (report Phase 6 items 4-5): project metadata, the reproducible
dependency lock, and the offline CI job with its lint / type gates.

Everything here reads checked-in files or runs a local tool; nothing touches the network.
The lockfile is the reproducibility evidence: every runtime pin appears in it at exactly the
pinned version with registry hashes, and CI restores the environment with `uv sync --locked`,
which refuses a stale lock. The ruff gate is run in-process when ruff is installed (CI
installs the dev group), with a non-vacuity probe; the mypy gate is covered by
tests/test_r6_typing.py.
"""
import importlib.util
import pathlib
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_LOCK = _REPO_ROOT / "uv.lock"
_REQUIREMENTS = _REPO_ROOT / "requirements.txt"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "offline-tests.yml"

_HAS_RUFF = importlib.util.find_spec("ruff") is not None


def _normalize(name: str) -> str:
    """PEP 503 name normalization, as the lockfile spells package names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(lines):
    """`name==version` pairs from requirement-style lines; comments and blanks ignored."""
    pins = {}
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        pins[_normalize(name.strip())] = version.strip()
    return pins


class TestProjectMetadataAndPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pyproject = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))

    def test_the_project_pins_python_312_exactly(self):
        """Decision 10: the frozen V1 interpreter."""
        self.assertEqual(self.pyproject["project"]["requires-python"], ">=3.12,<3.13")

    def test_pyproject_dependencies_equal_the_requirements_pins(self):
        """One source of truth spelled twice on purpose (requirements.txt is the documented
        install path; pyproject is what the lock resolves): they must agree exactly, every
        dependency pinned with `==`."""
        from_pyproject = _pins(self.pyproject["project"]["dependencies"])
        from_requirements = _pins(_REQUIREMENTS.read_text(encoding="utf-8").splitlines())
        self.assertEqual(from_pyproject, from_requirements)
        self.assertGreaterEqual(len(from_pyproject), 10)
        for name, version in from_pyproject.items():
            with self.subTest(package=name):
                self.assertTrue(version, f"{name} is not pinned with ==")
                self.assertNotIn("<", version)
                self.assertNotIn(">", version)

    def test_the_dev_group_pins_the_static_tools(self):
        dev = _pins(self.pyproject["dependency-groups"]["dev"])
        self.assertEqual(set(dev), {"mypy", "ruff", "pyyaml"})   # pyyaml: this module's parser
        for tool, version in dev.items():
            with self.subTest(tool=tool):
                self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_the_project_is_not_a_distributable_package(self):
        """A flat multi-package tree: uv manages the environment, never builds the project."""
        self.assertIs(self.pyproject["tool"]["uv"]["package"], False)
        self.assertNotIn("build-system", self.pyproject)

    def test_the_mypy_scope_is_the_r6_gate(self):
        from tests.test_r6_typing import MYPY_TARGETS
        mypy = self.pyproject["tool"]["mypy"]
        self.assertEqual(tuple(mypy["files"]), MYPY_TARGETS)
        self.assertEqual(mypy["follow_imports"], "silent")
        self.assertIs(mypy["ignore_missing_imports"], True)
        self.assertEqual(mypy["python_version"], "3.12")

    def test_ruff_is_lint_only_over_the_default_error_classes(self):
        lint = self.pyproject["tool"]["ruff"]["lint"]
        self.assertEqual(lint["select"], ["E4", "E7", "E9", "F", "W"])
        self.assertNotIn("format", self.pyproject["tool"]["ruff"])
        excluded = set(self.pyproject["tool"]["ruff"]["extend-exclude"])
        self.assertLessEqual({"middleware_layer", "model_layer", "functional_layer"}, excluded)


class TestTheLockIsReproducible(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pyproject = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        cls.lock = tomllib.loads(_LOCK.read_text(encoding="utf-8"))
        cls.packages = {p["name"]: p for p in cls.lock["package"]}

    def test_every_runtime_and_dev_pin_is_locked_at_its_pinned_version(self):
        pins = _pins(self.pyproject["project"]["dependencies"])
        pins.update(_pins(self.pyproject["dependency-groups"]["dev"]))
        for name, version in pins.items():
            with self.subTest(package=name):
                self.assertIn(name, self.packages, f"{name} is not in uv.lock")
                self.assertEqual(self.packages[name]["version"], version)

    def test_every_locked_distribution_carries_registry_hashes(self):
        """Transitive closure with hashes — the report's "complete environment lock"."""
        self.assertGreater(len(self.packages), 50)         # the transitive closure, not just pins
        for name, package in self.packages.items():
            if package.get("source", {}).get("virtual") is not None:
                continue                                    # the project itself (package=false)
            with self.subTest(package=name):
                self.assertIn("registry", package.get("source", {}))
                hashes = [w["hash"] for w in package.get("wheels", [])]
                if "sdist" in package:
                    hashes.append(package["sdist"]["hash"])
                self.assertTrue(hashes, f"{name} is locked without a hash")
                self.assertTrue(all(h.startswith("sha256:") for h in hashes))

    def test_the_lock_targets_python_312(self):
        self.assertEqual(self.lock["requires-python"], "==3.12.*")

    def test_the_lock_names_the_project_as_virtual(self):
        self.assertEqual(self.packages["maaos"]["source"], {"virtual": "."})


class TestTheOfflineWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
        (cls.job,) = cls.workflow["jobs"].values()
        cls.runs = [step["run"] for step in cls.job["steps"] if "run" in step]

    def test_it_runs_on_push_and_pull_request(self):
        triggers = self.workflow.get("on", self.workflow.get(True))   # PyYAML parses `on` as True
        self.assertEqual(set(triggers), {"push", "pull_request"})

    def test_it_restores_the_locked_environment_and_runs_the_offline_suite(self):
        self.assertEqual(self.job["env"]["SDL_VIDEODRIVER"], "dummy")
        self.assertTrue(any(run.strip() == "uv sync --locked" for run in self.runs))
        self.assertTrue(any(
            "python -B -m unittest discover -s tests -t ." in run for run in self.runs
        ))
        setup = [s for s in self.job["steps"] if str(s.get("uses", "")).startswith("astral-sh/setup-uv")]
        self.assertEqual(len(setup), 1)
        self.assertEqual(setup[0]["with"]["python-version"], "3.12")

    def test_it_runs_the_lint_and_type_gates_on_the_core(self):
        self.assertTrue(any(run.strip() == "uv run ruff check shared runtime app" for run in self.runs))
        self.assertTrue(any(run.strip() == "uv run mypy" for run in self.runs))

    def test_it_never_touches_a_live_model_or_a_service(self):
        """Scanned on the PARSED job (env, steps, with, run) — comments may name what the job
        must not do; the executable content may not."""
        executable = yaml.safe_dump(self.job).lower()
        for forbidden in ("maaos_live_lm", "ollama", "--nl live", "openai", "anthropic",
                          "api_key", "dspy"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, executable)
        self.assertNotIn("services", self.job)
        self.assertNotIn("container", self.job)


@unittest.skipUnless(_HAS_RUFF, "ruff is not installed (the CI job installs it)")
class TestTheLintGate(unittest.TestCase):
    def _ruff(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--config", str(_PYPROJECT), *args],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=300,
        )

    def test_the_core_passes_the_lint_gate(self):
        completed = self._ruff("shared", "runtime", "app")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_the_gate_reports_a_violation(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = pathlib.Path(scratch, "r6_lint_violation.py")
            path.write_text("import os\n\ndef f():\n    return undefined_name\n", encoding="utf-8")
            completed = self._ruff(str(path))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("F401", completed.stdout)
        self.assertIn("F821", completed.stdout)


if __name__ == "__main__":
    unittest.main()
