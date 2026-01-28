"""
Android runtime module for managing Docker containers and environment communication.

This module provides:
- ContainerManager: Manages a pool of Docker containers running Android emulators
- ContainerInstance: Dataclass representing a single Docker container
- PortAllocationError: Exception raised when port allocation fails
- RuntimeClient: HTTP client for communicating with container FastAPI servers
"""

from .container_manager import ContainerManager, ContainerInstance, PortAllocationError
from .runtime_client import RuntimeClient

__all__ = [
    "ContainerManager",
    "ContainerInstance", 
    "PortAllocationError",
    "RuntimeClient",
]
