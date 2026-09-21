"""DK5 — the author guide and the documentation that points at it.

Pins:
  - every anchor the validator and the templates reference (`§<Name>`, and the protocol
    names the validator interpolates) exists as a heading in `docs/domains/ADDING_A_DOMAIN.md`;
  - the guide documents every validation code in the catalogue;
  - the guide's quick-start commands are the CLI's real subcommands;
  - CLAUDE.md, README.md and the rule frontmatter name the domain-kit packages and workflow;
  - the guide never tells the author to open a runtime internal.

Offline, read-only.
"""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.validation import CATALOGUE, _MEMBER_OF                         # noqa: E402

GUIDE = _REPO_ROOT / "docs" / "domains" / "ADDING_A_DOMAIN.md"
_REFERENCING = (
    _REPO_ROOT / "app" / "validation.py",
    _REPO_ROOT / "maaos" / "scaffold.py",
    *sorted((_REPO_ROOT / "maaos" / "templates").glob("*.tmpl")),
)


def _headings(text: str) -> set[str]:
    prose = re.sub(r"```.*?```", "", text, flags=re.S)          # `#` inside code fences is not a heading
    return {m.group(1).strip() for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", prose, re.M)}


def _codes_mentioned(text: str) -> set[str]:
    """Every DKnnn in the text, with `DKaaa–DKbbb` ranges expanded."""
    found = set(re.findall(r"DK\d{3}", text))
    for lo, hi in re.findall(r"DK(\d{3})[–-]DK(\d{3})", text):
        found |= {f"DK{n:03d}" for n in range(int(lo), int(hi) + 1)}
    return found


class TestTheGuideAnchorsExist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")
        cls.headings = _headings(cls.text)

    #: every `§` reference is one of: a literal heading name, a quoted heading in another
    #: document (`§"..."`), or an interpolated protocol name (`§{...}`, covered below)
    _ANCHOR = re.compile(r'§(\{[^}]*\}|"[^"]*"|[A-Za-z][A-Za-z ]*[A-Za-z])')
    _ADR_HEADINGS = _headings((_REPO_ROOT / "docs" / "decisions" / "DK1_DOMAIN_PACKAGE.md").read_text(encoding="utf-8"))

    def test_every_section_reference_resolves(self):
        seen = 0
        for path in _REFERENCING:
            text = path.read_text(encoding="utf-8")
            matches = self._ANCHOR.findall(text)
            self.assertEqual(text.count("§"), len(matches), f"{path.name}: an unparseable § reference")
            for anchor in matches:
                seen += 1
                with self.subTest(file=path.name, anchor=anchor):
                    if anchor.startswith("{"):
                        continue                                # interpolated: see the next test
                    if anchor.startswith('"'):          # a quoted heading in the ADR (dated suffix allowed)
                        wanted = anchor.strip('"')
                        self.assertTrue(any(h == wanted or h.startswith(wanted + " (") for h in self._ADR_HEADINGS), wanted)
                    else:
                        self.assertIn(anchor, self.headings)
        self.assertGreaterEqual(seen, 2)

    def test_every_interpolated_protocol_name_is_a_heading(self):
        protocols = set(_MEMBER_OF.values())
        self.assertGreaterEqual(len(protocols), 8)
        for name in protocols:
            self.assertIn(name, self.headings, name)
        self.assertIn("Module roles", self.headings)

    def test_every_validation_code_is_documented(self):
        mentioned = _codes_mentioned(self.text)
        for code, _ in CATALOGUE:
            self.assertIn(code, mentioned, code)

    def test_quick_start_uses_the_real_cli(self):
        for command in ("python -m maaos create-domain", "python -m maaos validate-domain",
                        "domains/registry.py", "python -B -m unittest discover -s tests -t .",
                        "docs/refactor/REFACTOR_STATUS.md"):
            self.assertIn(command, self.text, command)

    def test_the_guide_never_sends_the_author_into_the_runtime(self):
        self.assertIsNone(re.search(r"runtime/[a-z_]+\.py|runtime\.[a-z_]+|from runtime|ExecutiveLoop",
                                    self.text))
        self.assertNotIn("app/box_push_v1.py", self.text)


class TestTheRepositoryPointsAtTheGuide(unittest.TestCase):
    def test_claude_md_names_the_kit_packages_and_the_workflow(self):
        text = (_REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for needle in ("kit/", "domains/", "maaos/", "app/domain_package.py", "app/assembly.py",
                       "app/validation.py", "docs/domains/ADDING_A_DOMAIN.md", "/add-domain",
                       "ruff check shared runtime app kit domains maaos"):
            self.assertIn(needle, text, needle)

    def test_readme_shows_how_to_add_a_domain(self):
        text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for needle in ("python -m maaos create-domain", "python -m maaos validate-domain",
                       "docs/domains/ADDING_A_DOMAIN.md", "kit/", "domains/"):
            self.assertIn(needle, text, needle)

    def test_the_architecture_rule_covers_the_new_packages(self):
        text = (_REPO_ROOT / ".claude" / "rules" / "refactor-architecture.md").read_text(encoding="utf-8")
        for needle in ('"kit/**/*"', '"domains/**/*"', '"maaos/**/*"'):
            self.assertIn(needle, text, needle)

    def test_the_implementation_record_carries_the_gate_evidence(self):
        record = (_REPO_ROOT / "docs" / "domains" / "DOMAIN_KIT_IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertNotIn("PENDING", record)
        for needle in ("## DK1", "## DK2", "## DK3", "## DK4", "## DK5", "Usability gate",
                       "| files touched |", "| functions written or changed |",
                       "| contents opened outside the guide |", "| gate failures |", "| verdict |"):
            self.assertIn(needle, record, needle)
        pinned = re.search(r"Current offline suite: (\d+) tests", (_REPO_ROOT / "docs" / "refactor" / "REFACTOR_STATUS.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(pinned)
        # The phase table carries the pin at the end of each kit change, in order; the LIVE
        # pin lives in REFACTOR_STATUS.md and every later domain moves it WITHOUT a row here
        # (the 2026-09-21 second-domain regression: the first version of this test required
        # the live pin in the table, so following the author guide's pin step broke it).
        table = re.findall(r"^\| (?:DK\d|fix) \| .* \| (\d+) \|$", record, flags=re.M)
        self.assertGreaterEqual(len(table), 7, table)                  # DK0-DK5 and the fixes
        # every row of the phase table is one of those labels — a differently labelled kit
        # row would otherwise drop out of the monotone check silently
        section = record.split("## Phase table", 1)[1].split("\n## ", 1)[0]
        rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| Phase")]
        self.assertEqual(len(rows), len(table), rows)
        pins = [int(n) for n in table]
        self.assertEqual(pins, sorted(pins), pins)                     # monotone, one per row
        self.assertLessEqual(pins[-1], int(pinned.group(1)), (pins[-1], pinned.group(1)))
        self.assertIn("docs/refactor/REFACTOR_STATUS.md", record)      # names the live authority
        self.assertIn("without a row", record)                         # and says domains move it


if __name__ == "__main__":
    unittest.main()
