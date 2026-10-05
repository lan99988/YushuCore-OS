"""Small host-neutral SDK shared by YushuOS and independent plugins."""

from .contracts import Request, Result
from .state import StateStore
from .context import PluginContext

__version__ = "0.3.1"
