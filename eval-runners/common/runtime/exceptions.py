"""
Exception hierarchy for Android container runtime.

These exceptions provide clear error classification for the dispatcher
to determine appropriate recovery actions.
"""


class ContainerError(Exception):
    """Base class for container-related errors."""
    pass


class ContainerDeadError(ContainerError):
    """
    Raised when container connection fails.
    
    This indicates the container is unresponsive and should be replaced.
    The dispatcher should call release_container(success=False) to trigger
    container replacement via ContainerManager.
    
    Attributes:
        env_id: The environment ID of the failed container
    """
    def __init__(self, env_id: int, message: str = ""):
        self.env_id = env_id
        super().__init__(f"Container env{env_id} is dead: {message}")


class ContainerTimeoutError(ContainerError):
    """
    Raised when container operation times out.
    
    This may be transient (container busy) or permanent (container frozen).
    RuntimeClient's step-level retry should handle transient cases;
    this is raised after retries are exhausted.
    
    Attributes:
        env_id: The environment ID of the timed-out container
    """
    def __init__(self, env_id: int, message: str = ""):
        self.env_id = env_id
        super().__init__(f"Container env{env_id} timeout: {message}")
