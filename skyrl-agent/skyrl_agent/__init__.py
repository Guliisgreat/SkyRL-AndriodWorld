"""
SkyRL Agent package.

Provides lazy imports to avoid loading heavy dependencies (torch, transformers)
when only using lightweight components like container_manager.
"""


def __getattr__(name):
    """Lazy import of heavy components."""
    if name == "AutoAgentRunner":
        from .auto import AutoAgentRunner
        return AutoAgentRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AutoAgentRunner"]
