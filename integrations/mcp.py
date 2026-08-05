from __future__ import annotations


class KnowledgeMcpServer:
    """MCP-shaped read-only contract; it exposes no file or write tool."""

    _TOOLS = (
        {"name": "knowledge.search", "description": "Search approved knowledge context"},
        {"name": "knowledge.read_context", "description": "Read task-scoped knowledge context"},
        {"name": "knowledge.get_schema", "description": "Read knowledge metadata schema"},
        {"name": "knowledge.health", "description": "Check reader health"},
    )

    def tools(self) -> tuple[dict[str, str], ...]:
        return self._TOOLS

    def call(self, name: str, arguments: dict[str, object], *, gateway) -> object:
        if name not in {tool["name"] for tool in self._TOOLS}:
            raise PermissionError("MCP tool is not allowed")
        method = {
            "knowledge.search": "query_knowledge",
            "knowledge.read_context": "get_context",
            "knowledge.get_schema": "get_schema",
            "knowledge.health": "health",
        }[name]
        return getattr(gateway, method)(**arguments)
