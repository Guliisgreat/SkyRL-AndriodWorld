"""
Android runtime module for managing Docker containers and environment communication.

This module provides:
- ContainerManager: Manages a pool of Docker containers running Android emulators
- RuntimeClient: HTTP client for communicating with container FastAPI servers
"""

from .container_manager import ContainerManager
from .runtime_client import RuntimeClient

__all__ = ["ContainerManager", "RuntimeClient"]
