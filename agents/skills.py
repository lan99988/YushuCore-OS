from __future__ import annotations

from agents.sdk import SkillSpec


def skills_for_domain(domain: str) -> tuple[SkillSpec, SkillSpec]:
    return (
        SkillSpec(
            skill_id=f"{domain}_analysis",
            name=f"{domain.title()} Analysis",
            domain=domain,
            required_permissions=("read_knowledge",),
            risk_level="low",
        ),
        SkillSpec(
            skill_id=f"{domain}_review",
            name=f"{domain.title()} Review",
            domain=domain,
            required_permissions=("propose_change",),
            risk_level="medium",
        ),
    )
