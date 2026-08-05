from __future__ import annotations

from agents.sdk import SkillSpec


_PHASE3_DOMAINS = ("knowledge", "body", "study", "project")


class SkillCatalog:
    def __init__(self, skills: tuple[SkillSpec, ...]) -> None:
        self._skills = skills

    @classmethod
    def for_phase3(cls) -> "SkillCatalog":
        skills: list[SkillSpec] = []
        for domain in _PHASE3_DOMAINS:
            skills.extend(_skills_for_domain(domain))
        return cls(tuple(skills))

    def for_domain(self, domain: str) -> tuple[SkillSpec, ...]:
        return tuple(skill for skill in self._skills if skill.domain == domain)

    def manifest(self) -> list[dict]:
        return [skill.to_dict() for skill in self._skills]


def _skills_for_domain(domain: str) -> tuple[SkillSpec, SkillSpec]:
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


def skills_for_domain(domain: str) -> tuple[SkillSpec, SkillSpec]:
    return SkillCatalog.for_phase3().for_domain(domain)
