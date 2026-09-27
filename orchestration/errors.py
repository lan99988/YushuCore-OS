from __future__ import annotations


class OrchestrationError(RuntimeError):
    """Base error for orchestration routing and planning contracts."""


class ClassificationError(OrchestrationError):
    """Raised when an injected classifier returns an invalid result."""
