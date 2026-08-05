from __future__ import annotations

from dataclasses import dataclass

from .models import SelfModelLayer, SelfModelNode


@dataclass(frozen=True)
class SelfModelAccessPolicy:
    _matrix: dict[SelfModelLayer, frozenset[str]] | None = None

    def __post_init__(self) -> None:
        if self._matrix is None:
            object.__setattr__(
                self,
                "_matrix",
                {
                    SelfModelLayer.IDENTITY: frozenset({"authorized_read"}),
                    SelfModelLayer.VALUE: frozenset({"read", "propose"}),
                    SelfModelLayer.PRINCIPLE: frozenset({"read", "propose"}),
                    SelfModelLayer.PREFERENCE: frozenset({"read", "analyze", "propose"}),
                    SelfModelLayer.BEHAVIOR_PATTERN: frozenset({"read", "analyze", "propose"}),
                    SelfModelLayer.EXPERIENCE: frozenset({"read", "analyze", "propose"}),
                },
            )

    def allowed(self, layer: SelfModelLayer, operation: str) -> bool:
        return operation in self._matrix.get(layer, frozenset())


class SelfModelReader:
    def __init__(self, policy: SelfModelAccessPolicy | None = None) -> None:
        self.policy = policy or SelfModelAccessPolicy()

    def read(
        self,
        nodes: list[SelfModelNode] | tuple[SelfModelNode, ...],
        *,
        operation: str = "read",
        authorized_identity: bool = False,
    ) -> tuple[SelfModelNode, ...]:
        visible: list[SelfModelNode] = []
        for node in nodes:
            requested_operation = "read" if operation == "read" else operation
            if node.layer is SelfModelLayer.IDENTITY and authorized_identity:
                requested_operation = "authorized_read"
            if self.policy.allowed(node.layer, requested_operation):
                visible.append(node)
        return tuple(visible)

    def request_update(self, node: SelfModelNode, *, agent_id: str, reason: str) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("reason is required")
        if not self.policy.allowed(node.layer, "propose"):
            raise PermissionError("self model layer cannot receive agent proposals")
        return {
            "proposal_type": "self_model_update",
            "target_id": node.node_id,
            "target_layer": node.layer.value,
            "agent_id": agent_id,
            "reason": reason,
            "status": "pending_human_review",
            "approved": False,
        }


class SelfModelGatewayReader:
    """Reads Self Model through a temporary Gateway grant only."""

    def __init__(
        self,
        gateway,
        policy: SelfModelAccessPolicy | None = None,
        *,
        approved_agents: tuple[str, ...] = (),
    ) -> None:
        self._gateway = gateway
        self._reader = SelfModelReader(policy)
        self._approved_agents = frozenset(approved_agents) | {"personal_intelligence_engine"}

    def read_for_agent(
        self,
        *,
        task: str,
        agent_id: str,
        credential: str,
        resource_path: str,
        max_sensitivity: str,
        operation: str = "read",
        authorized_identity: bool = False,
    ) -> tuple[SelfModelNode, ...]:
        if agent_id not in self._approved_agents:
            raise PermissionError("agent is not an approved Self Model reader")
        context = self._gateway.get_context_with_access_grant(
            task,
            agent_id=agent_id,
            credential=credential,
            resource_path=resource_path,
            max_sensitivity=max_sensitivity,
        )
        raw_nodes = list(context.knowledge) + list(context.experience) + list(context.principles)
        nodes: list[SelfModelNode] = []
        for raw in raw_nodes:
            layer_value = raw.metadata.get("self_model_layer", raw.type)
            try:
                layer = SelfModelLayer(layer_value)
            except ValueError:
                continue
            nodes.append(
                SelfModelNode(
                    node_id=raw.id,
                    layer=layer,
                    content=raw.body,
                    source=raw.path,
                    sensitivity=raw.sensitivity,
                    status=raw.status,
                    metadata=dict(raw.metadata),
                )
            )
        return self._reader.read(
            nodes,
            operation=operation,
            authorized_identity=authorized_identity,
        )
