"""`create-domain` (DK4) — generate a runnable domain skeleton, NEW FILES ONLY.

    python -m maaos create-domain <name> [--target <dir>]

Writes `domains/<name>/{__init__,types,model,environment}.py`, `domains/<name>/README.md`
and `tests/test_domain_<name>.py` from the templates in `maaos/templates/`, then PRINTS the
two registry lines and the next steps. It never edits an existing file (the registry is
hand-edited; the guard's door line, if a backend is imported, is reported by
`validate-domain`). It refuses an existing directory, an invalid or reserved name, and a
name already registered.

The generated domain is a small deterministic switch domain built on the kit; it passes
`validate-domain` unchanged (0 FAIL, 0 WARN), so an author replaces parts incrementally and
re-validates after each edit. Every extension point is marked `# TODO(author)`.

`--target` writes the package elsewhere (the DK4 proof fixture lives under `tests/`); the
generated test then imports the package by its dotted path relative to the repository.
"""
from __future__ import annotations

import keyword
import pathlib
from dataclasses import dataclass
from typing import Container, Dict, List, Optional, Tuple

from app.validation import registry_line

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TEMPLATES = pathlib.Path(__file__).resolve().parent / "templates"

#: template file -> (destination inside the package, or None for the test module)
_PACKAGE_FILES: Tuple[Tuple[str, str], ...] = (
    ("__init__.py.tmpl", "__init__.py"),
    ("types.py.tmpl", "types.py"),
    ("model.py.tmpl", "model.py"),
    ("environment.py.tmpl", "environment.py"),
    ("README.md.tmpl", "README.md"),
)
_TEST_TEMPLATE = "test_domain.py.tmpl"


class ScaffoldError(ValueError):
    """An author-facing refusal; the message says what to change."""


def check_name(name: str, registered: Container[str] = frozenset()) -> None:
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ScaffoldError(
            f"{name!r} is not a valid domain name: use a Python identifier such as "
            f"'warehouse' or 'lamp_grid'"
        )
    if name != name.lower() or name.startswith("_"):
        raise ScaffoldError(f"{name!r}: use a lowercase name without a leading underscore")
    if name in registered:
        raise ScaffoldError(f"{name!r} is already registered in domains/registry.py")


def render(name: str, *, package_import: str, test_module: str) -> Dict[str, str]:
    """The generated files as {relative destination: content}, package files first."""
    files: Dict[str, str] = {}
    substitutions = {
        "__NAME__": name,
        "__PACKAGE_IMPORT__": package_import,
        "__TEST_MODULE__": test_module,
    }

    def fill(template: str) -> str:
        text = (_TEMPLATES / template).read_text(encoding="utf-8")
        for marker, value in substitutions.items():
            text = text.replace(marker, value)
        return text

    for template, destination in _PACKAGE_FILES:
        files[destination] = fill(template)
    files[f"tests/test_domain_{name}.py"] = fill(_TEST_TEMPLATE)
    return files


@dataclass(frozen=True, slots=True)
class Created:
    name: str
    package_dir: pathlib.Path
    written: Tuple[pathlib.Path, ...]
    package_import: str
    registry_lines: Tuple[str, str]

    def next_steps(self, repo_root: pathlib.Path = _REPO_ROOT) -> str:
        rel = [p.relative_to(repo_root).as_posix() if p.is_relative_to(repo_root) else str(p)
               for p in self.written]
        import_line, entry = self.registry_lines
        lines = ["created:"] + [f"  {r}" for r in rel]
        if self.package_import.startswith("domains."):
            lines += [
                "",
                "register it — add to domains/registry.py (by hand; nothing edits it for you):",
                f"  {import_line}",
                f"  {entry.strip()}      # inside the MappingProxyType({{...}}) literal",
                "",
                f"then check it:  python -m maaos validate-domain {self.name}",
            ]
        else:
            lines += ["", f"check it:  validate_domain({self.package_import}.DOMAIN) (not registered — outside domains/)"]
        lines += [
            f"run its test:   python -B -m unittest tests.test_domain_{self.name}",
            "then edit the # TODO(author) points in types.py, model.py, environment.py, __init__.py,",
            "re-validating after each change (docs/domains/ADDING_A_DOMAIN.md).",
        ]
        return "\n".join(lines)


def create_domain(
    name: str,
    *,
    repo_root: pathlib.Path = _REPO_ROOT,
    target: Optional[pathlib.Path] = None,
    registered: Container[str] = frozenset(),
) -> Created:
    """Write the skeleton. Refuses to overwrite anything."""
    check_name(name, registered)
    package_dir = (repo_root / "domains" / name) if target is None else target
    if not package_dir.is_absolute():
        package_dir = repo_root / package_dir
    try:
        rel_pkg = package_dir.relative_to(repo_root)
    except ValueError:
        raise ScaffoldError(f"the target must be inside the repository: {package_dir}") from None
    package_import = ".".join(rel_pkg.parts)
    test_path = repo_root / "tests" / f"test_domain_{name}.py"
    if package_dir.exists():
        raise ScaffoldError(
            f"{rel_pkg.as_posix()}/ already exists; create-domain never overwrites — pick "
            f"another name or remove the directory yourself"
        )
    if test_path.exists():
        raise ScaffoldError(f"{test_path.relative_to(repo_root).as_posix()} already exists; "
                            f"create-domain never overwrites")
    files = render(name, package_import=package_import, test_module=f"tests.test_domain_{name}")
    written: List[pathlib.Path] = []
    package_dir.mkdir(parents=True)
    for destination, content in files.items():
        path = test_path if destination.startswith("tests/") else package_dir / destination
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return Created(name, package_dir, tuple(written), package_import, registry_line(name))


__all__ = ["Created", "ScaffoldError", "check_name", "create_domain", "render"]
