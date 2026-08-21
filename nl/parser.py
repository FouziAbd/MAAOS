"""Typed NL skill-call parsing (Decision 7; §18 item 9's replacement).

`parse_skill_call` accepts EXACTLY the frozen call rendering `GroundedSkillCall.__str__`
produces — `Skill(agent[,agent]; box_k; delivery_zone)` — and returns either the typed call or
a typed `MalformedCall` carrying the raw text and the reason.

THE RULE THIS MODULE EXISTS FOR: malformed output is NEVER silently rewritten into a different
valid skill. The legacy runner's `('explore', None)` default (`box_push_centralized.py::_skill_parser`)
and its `WaitSkill` substitution are exactly what Decision 7 forbids; the V1 NL track routes
every unparseable proposal through `MalformedCall` → typed repair → typed rejection.
"""
from __future__ import annotations

import re
from typing import Union

from shared.ids import AgentId, BoxId, ZoneId
from shared.skills import GroundedSkillCall, MalformedCall, SkillName

#: The frozen surface form. One call per proposal, nothing else on the line.
_CALL_RE = re.compile(r"^\s*([A-Za-z_]+)\s*\(\s*([^()]*?)\s*\)\s*$")

_SKILLS_BY_NAME = {name.value: name for name in SkillName}


def parse_skill_call(text: str) -> Union[GroundedSkillCall, MalformedCall]:
    """One proposal text → typed `GroundedSkillCall`, or typed `MalformedCall`. Total function:
    never raises on bad input, never substitutes a different skill."""
    raw = text if isinstance(text, str) else repr(text)
    match = _CALL_RE.match(raw or "")
    if not match:
        return MalformedCall(
            reason="not a skill call: expected 'Skill(agents; box; zone)' on a single line",
            raw=raw,
        )
    skill_text, args_text = match.group(1), match.group(2)
    skill = _SKILLS_BY_NAME.get(skill_text)
    if skill is None:
        return MalformedCall(
            reason=f"unknown skill name {skill_text!r}; valid: "
                   + ", ".join(sorted(_SKILLS_BY_NAME)),
            raw=raw,
        )

    parts = [p.strip() for p in args_text.split(";")] if args_text.strip() else []
    try:
        agents = tuple(
            AgentId(a.strip()) for a in (parts[0].split(",") if parts else []) if a.strip()
        )
        box = zone = None
        for part in parts[1:]:
            if not part:
                raise ValueError("empty argument slot")
            if part.startswith("box"):
                box = BoxId.parse(part)
            else:
                zone = ZoneId(part)
        return GroundedSkillCall(skill, agents, box, zone)
    except (TypeError, ValueError) as error:
        # the frozen constructor is the arity/type authority; its rejection is the reason
        return MalformedCall(reason=f"{type(error).__name__}: {error}", raw=raw)
