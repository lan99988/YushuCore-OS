"""Read-only adapter for the existing Body OS assessment contracts."""

from .plugin import BodyPlugin, BodyPluginError

__all__ = ["BodyPlugin", "BodyPluginError"]
