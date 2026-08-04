"""Frozen v3.0 metadata vocabulary for Knowledge Nodes."""

REQUIRED_METADATA_FIELDS = frozenset(
    {
        "id",
        "type",
        "domain",
        "source",
        "confidence",
        "status",
        "agent_access",
        "created",
        "updated",
    }
)

ALLOWED_KNOWLEDGE_TYPES = frozenset(
    {
        "knowledge",
        "principle",
        "model",
        "experience",
        "decision",
        "project",
        "agent_memory",
        "self_model",
        "decision_history",
    }
)

ALLOWED_STATUSES = frozenset(
    {"raw", "candidate", "reviewed", "validated", "permanent", "archived"}
)

ALLOWED_SENSITIVITY_LEVELS = frozenset(
    {"level_0", "level_1", "level_2", "level_3", "level_4"}
)

KNOWN_METADATA_FIELDS = frozenset(
    REQUIRED_METADATA_FIELDS
    | {
        "title",
        "layer",
        "author",
        "importance",
        "tags",
        "relations",
        "attachments",
        "embedding",
        "sensitivity",
        "version",
        "decision_status",
        "decision_date",
        "review_date",
        "agent",
    }
)
