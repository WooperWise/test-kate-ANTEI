"""Runtime skills loader.

Reads skills/<name>/SKILL.md (YAML frontmatter + markdown body, Anthropic Agent
Skills format) and turns each into a deferred pydantic-ai Capability: the agent
sees a one-line catalog entry; the body is injected via the framework-managed
``load_capability`` tool at runtime. Every injection is logged as ``skill_loaded``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic_ai.capabilities import AbstractCapability

from mito_harness.logging_events import EventBus

logger = logging.getLogger(__name__)


class SkillCapability(AbstractCapability[None]):
    """Capability backed by a SKILL.md file; logs its activation once.

    ``deferred=False`` injects the body into the system prompt (required for
    endpoints like vLLM that reject mid-conversation system messages);
    ``deferred=True`` keeps the Anthropic-style progressive disclosure
    (body arrives via the load_capability tool result).
    """

    def __init__(
        self,
        skill_id: str,
        description: str,
        body: str,
        bus: EventBus | None = None,
        deferred: bool = False,
    ) -> None:
        self.id = skill_id
        self.description = description
        self.defer_loading = deferred
        self._body = body
        self._bus = bus
        self._announced = False

    def get_instructions(self) -> str:
        if self._bus is not None and not self._announced:
            self._announced = True
            self._bus.emit("skill_loaded", payload={"skill": self.id, "chars": len(self._body)})
        return self._body


def parse_skill_file(path: Path) -> tuple[str, str, str]:
    """Parse SKILL.md into (id, description, body); raises on malformed frontmatter."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: missing YAML frontmatter delimited by '---'")
    meta = yaml.safe_load(parts[1]) or {}
    skill_id = str(meta.get("id") or path.parent.name)
    description = str(meta.get("description") or "").strip()
    if not description:
        raise ValueError(f"{path}: frontmatter must contain a non-empty 'description'")
    return skill_id, description, parts[2].strip()


def load_skills(skills_dir: Path, bus: EventBus | None = None, deferred: bool = False) -> list[SkillCapability]:
    """Load every skills/<name>/SKILL.md into a SkillCapability."""
    capabilities: list[SkillCapability] = []
    for skill_path in sorted(skills_dir.glob("*/SKILL.md")):
        skill_id, description, body = parse_skill_file(skill_path)
        capabilities.append(SkillCapability(skill_id, description, body, bus=bus, deferred=deferred))
        logger.info("skill loaded: %s (%d chars, deferred=%s)", skill_id, len(body), deferred)
    return capabilities


def skills_catalog(capabilities: list[SkillCapability]) -> dict[str, str]:
    """Catalog view: id -> description (what agents see before loading)."""
    return {str(c.id): str(c.description) for c in capabilities}


def inject_skills(base_instructions: str, skills: list[SkillCapability]) -> str:
    """Append skill bodies to an agent's system instructions.

    Provider-safe injection: the skill text becomes part of the single leading
    system message (endpoints like vLLM reject mid-conversation system parts),
    while still being loaded from disk at runtime and logged as skill_loaded.
    """
    if not skills:
        return base_instructions
    parts = [base_instructions]
    for skill in skills:
        parts.append(f"# Loaded skill: {skill.id}\n{skill.get_instructions()}")
    return "\n\n---\n\n".join(parts)
