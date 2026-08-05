from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agents.boundary import phase3_agent_boundary_report
from agents.body import body_agent_handler
from agents.knowledge import knowledge_agent_handler
from agents.project import project_agent_handler
from agents.skills import SkillCatalog
from agents.study import study_agent_handler
from runtime_core.config import AgentHandlerMap, load_agent_definitions
from runtime_core.models import AgentDefinition, RuntimeContext


def phase3_registry_path() -> Path:
    return Path(__file__).with_name("registry.yaml")


def phase3_handler_map() -> dict[str, Callable[[RuntimeContext], object]]:
    return {
        "knowledge_agent_handler": knowledge_agent_handler,
        "body_agent_handler": body_agent_handler,
        "study_agent_handler": study_agent_handler,
        "project_agent_handler": project_agent_handler,
    }


def phase3_skill_catalog() -> SkillCatalog:
    return SkillCatalog.for_phase3()


def phase3_skill_manifest() -> list[dict]:
    return phase3_skill_catalog().manifest()


def phase4_skill_catalog() -> SkillCatalog:
    return SkillCatalog.for_phase4()


def phase4_skill_manifest() -> list[dict]:
    return phase4_skill_catalog().manifest()


def load_phase3_agent_definitions(
    path: str | Path | None = None,
    *,
    handlers: AgentHandlerMap | None = None,
) -> list[AgentDefinition]:
    registry_path = Path(path) if path is not None else phase3_registry_path()
    handler_map = dict(handlers or phase3_handler_map())
    return load_agent_definitions(registry_path, handler_map)
