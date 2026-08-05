from __future__ import annotations

from dataclasses import dataclass

from agents.sdk import AgentResponse, AgentSDK

@dataclass(frozen=True)
class FutureAgentSpec:
    agent_id: str
    name: str
    domain: str
    permissions: tuple[str, ...]
    autonomy_level: int
    active: bool = False


def future_agent_catalog() -> tuple[FutureAgentSpec, ...]:
    return (
        FutureAgentSpec("health_agent", "Health Agent", "health", ("read_knowledge",), 1),
        FutureAgentSpec("research_agent", "Research Agent", "research", ("read_knowledge",), 1),
        FutureAgentSpec("file_agent", "File Agent", "utility.file", ("read_knowledge",), 1),
        FutureAgentSpec("calendar_agent", "Calendar Agent", "utility.calendar", ("read_knowledge",), 1),
        FutureAgentSpec(
            "communication_agent",
            "Communication Agent",
            "utility.communication",
            ("read_knowledge",),
            1,
        ),
    )


def _future_response(context, *, agent_id: str, domain: str, capability: str) -> AgentResponse:
    sdk = AgentSDK(agent_id=agent_id, domain=domain)
    return sdk.response(
        summary=f"{agent_id} is registered as a future {capability} skeleton",
        findings=[],
        proposals=[],
        next_actions=["Remain inactive until explicit Phase 4/5 activation", "Use Runtime and Gateway only"],
        reason="Future Agent skeleton is read-only and has no external execution permission.",
        evidence=[],
        confidence=0.2,
    )


def health_agent_handler(context) -> AgentResponse:
    return _future_response(context, agent_id="health_agent", domain="health", capability="health")


def research_agent_handler(context) -> AgentResponse:
    return _future_response(context, agent_id="research_agent", domain="research", capability="research")


def file_agent_handler(context) -> AgentResponse:
    return _future_response(context, agent_id="file_agent", domain="utility.file", capability="file")


def calendar_agent_handler(context) -> AgentResponse:
    return _future_response(context, agent_id="calendar_agent", domain="utility.calendar", capability="calendar")


def communication_agent_handler(context) -> AgentResponse:
    return _future_response(
        context,
        agent_id="communication_agent",
        domain="utility.communication",
        capability="communication",
    )


def future_handler_map() -> dict[str, object]:
    return {
        "health_agent_handler": health_agent_handler,
        "research_agent_handler": research_agent_handler,
        "file_agent_handler": file_agent_handler,
        "calendar_agent_handler": calendar_agent_handler,
        "communication_agent_handler": communication_agent_handler,
    }
