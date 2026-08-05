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

    @classmethod
    def for_phase4(cls) -> "SkillCatalog":
        catalog = cls.for_phase3()
        for skill in (
            SkillSpec("knowledge_import", "Knowledge Import", "knowledge", ("read_knowledge", "propose_change"), "medium"),
            SkillSpec("knowledge_audit", "Knowledge Audit", "knowledge", ("read_knowledge", "propose_change"), "medium"),
            SkillSpec("body_running_analysis", "Running Analysis", "body", ("read_knowledge", "use_tools"), "medium"),
            SkillSpec("body_recovery_prediction", "Recovery Prediction", "body", ("read_knowledge", "use_tools"), "medium"),
            SkillSpec("study_spaced_repetition", "Spaced Repetition", "study", ("read_knowledge", "propose_change"), "medium"),
            SkillSpec("study_knowledge_mapping", "Knowledge Mapping", "study", ("read_knowledge", "propose_change"), "medium"),
            SkillSpec("study_exam_analysis", "Exam Analysis", "study", ("read_knowledge", "propose_change"), "medium"),
        ):
            catalog.register(skill)
        return catalog

    def for_domain(self, domain: str) -> tuple[SkillSpec, ...]:
        return tuple(skill for skill in self._skills if skill.domain == domain)

    def register(self, skill: SkillSpec) -> None:
        if not skill.skill_id.strip():
            raise ValueError("skill_id is required")
        if any(existing.skill_id == skill.skill_id for existing in self._skills):
            raise ValueError(f"Skill already registered: {skill.skill_id}")
        self._skills = (*self._skills, skill)

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
