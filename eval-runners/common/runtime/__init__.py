"""
Android runtime module for managing Docker containers and environment communication.

This module provides:
- ContainerManager: Manages a pool of Docker containers running Android emulators
- ContainerInstance: Dataclass representing a single Docker container
- PortAllocationError: Exception raised when port allocation fails
- RuntimeClient: HTTP client for communicating with container FastAPI servers
- ContainerError: Base exception for container-related errors
- ContainerDeadError: Exception raised when container is unresponsive
- ContainerTimeoutError: Exception raised when container operation times out
"""

from .container_manager import ContainerManager, ContainerInstance, PortAllocationError
from .runtime_client import RuntimeClient
from .exceptions import ContainerError, ContainerDeadError, ContainerTimeoutError

__all__ = [
    "ContainerManager",
    "ContainerInstance", 
    "PortAllocationError",
    "RuntimeClient",
    "ContainerError",
    "ContainerDeadError",
    "ContainerTimeoutError",
]
