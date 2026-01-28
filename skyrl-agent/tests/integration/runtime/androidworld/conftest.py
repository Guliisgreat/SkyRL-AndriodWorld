"""
Shared fixtures for error recovery integration tests.

These tests require real Docker containers with Android emulators.
Run with: RUN_DOCKER_TESTS=true pytest tests/integration/runtime/androidworld/test_error_recovery.py -v -s
"""

import os
import sys
import types
import asyncio
import subprocess
import pytest
import pytest_asyncio
import importlib.util
from typing import Tuple, List
from dataclasses import dataclass
from pathlib import Path

# Check prerequisites
DOCKER_AVAILABLE = os.path.exists("/var/run/docker.sock") or os.environ.get("DOCKER_HOST")
RUN_DOCKER_TESTS = os.environ.get("RUN_DOCKER_TESTS", "").lower() == "true"
KVM_AVAILABLE = os.path.exists("/dev/kvm")

# Get paths to the modules we need
_SKYRL_AGENT_ROOT = Path(__file__).parent.parent.parent.parent.parent / "skyrl_agent"
_RUNTIME_ANDROID_PATH = _SKYRL_AGENT_ROOT / "runtime" / "android"

# Module cache
_loaded_modules = {}
_package_initialized = False


def _init_package_structure():
    """Initialize fake package structure for relative imports."""
    global _package_initialized
    if _package_initialized:
        return
    
    # Create fake package hierarchy to avoid triggering skyrl_agent/__init__.py
    if "skyrl_agent" not in sys.modules:
        pkg = types.ModuleType("skyrl_agent")
        pkg.__path__ = [str(_SKYRL_AGENT_ROOT)]
        sys.modules["skyrl_agent"] = pkg
    
    if "skyrl_agent.runtime" not in sys.modules:
        pkg = types.ModuleType("skyrl_agent.runtime")
        pkg.__path__ = [str(_SKYRL_AGENT_ROOT / "runtime")]
        sys.modules["skyrl_agent.runtime"] = pkg
    
    if "skyrl_agent.runtime.android" not in sys.modules:
        pkg = types.ModuleType("skyrl_agent.runtime.android")
        pkg.__path__ = [str(_RUNTIME_ANDROID_PATH)]
        sys.modules["skyrl_agent.runtime.android"] = pkg
    
    _package_initialized = True


def _load_module(module_name: str):
    """Load a module from the android runtime package."""
    full_name = f"skyrl_agent.runtime.android.{module_name}"
    
    if module_name in _loaded_modules:
        return _loaded_modules[module_name]
    
    _init_package_structure()
    
    module_path = _RUNTIME_ANDROID_PATH / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        full_name,
        module_path,
        submodule_search_locations=[str(_RUNTIME_ANDROID_PATH)]
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "skyrl_agent.runtime.android"
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    _loaded_modules[module_name] = module
    return module


def _load_container_manager():
    """Load container_manager module directly (it's self-contained)."""
    if "container_manager" in _loaded_modules:
        return _loaded_modules["container_manager"]
    
    # container_manager.py is self-contained, no separate dependencies
    return _load_module("container_manager")


def _load_runtime_client():
    """Load runtime_client module."""
    if "runtime_client" in _loaded_modules:
        return _loaded_modules["runtime_client"]
    
    # Load container_manager first (runtime_client imports from it)
    _load_container_manager()
    
    return _load_module("runtime_client")


# Skip marker for tests requiring full Docker setup
skip_without_docker = pytest.mark.skipif(
    not (DOCKER_AVAILABLE and RUN_DOCKER_TESTS and KVM_AVAILABLE),
    reason="Docker/KVM tests disabled (set RUN_DOCKER_TESTS=true)"
)


@pytest.fixture(scope="module")
def docker_image():
    """Get Docker image name from environment."""
    return os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:v8")


@pytest.fixture(scope="module")
def container_timeout():
    """Get container startup timeout."""
    return int(os.environ.get("DOCKER_TEST_TIMEOUT", "600"))


@pytest.fixture(scope="module")
def pool_size():
    """Number of main containers to create."""
    return int(os.environ.get("RECOVERY_TEST_POOL_SIZE", "4"))


@pytest.fixture(scope="module")
def buffer_size():
    """Number of backup containers to create."""
    return int(os.environ.get("RECOVERY_TEST_BUFFER_SIZE", "1"))


@pytest_asyncio.fixture(scope="module")
async def container_pool(docker_image, pool_size, buffer_size):
    """Module-scoped fixture that creates a pool of containers."""
    container_manager_module = _load_container_manager()
    ContainerManager = container_manager_module.ContainerManager
    
    manager = ContainerManager(
        docker_image=docker_image,
        temp_path="/tmp/recovery_integration_test",
    )
    
    try:
        containers = await manager.create_pool_parallel(
            pool_size=pool_size,
            buffer_size=buffer_size,
            base_env_id=200,
            max_concurrent=4,
            initial_wait=30.0,
            max_retries=2,
            sample_mode="sequential",
            snapshot="clean",
            train_task_family="android_world",
            val_task_family="android_world",
        )
        
        # Start health monitor to enable health checks during allocation
        # This ensures containers that became unhealthy during pool creation
        # are detected and skipped
        await manager.start_health_monitor(interval=30.0)
        
        yield manager, containers
        
    finally:
        await manager.stop_health_monitor()
        await manager.cleanup()


@pytest_asyncio.fixture
async def runtime_client_factory(container_pool):
    """Factory fixture to create RuntimeClient instances."""
    runtime_client_module = _load_runtime_client()
    RuntimeClient = runtime_client_module.RuntimeClient
    
    clients = []
    
    def _factory(container):
        client = RuntimeClient(container)
        clients.append(client)
        return client
    
    yield _factory
    
    for client in clients:
        await client.close()


@dataclass
class ContainerKiller:
    """Helper class to simulate container failures."""
    
    def kill_server_process(self, container) -> bool:
        """Kill the uvicorn server process inside the container."""
        try:
            result = subprocess.run(
                ["docker", "exec", f"env{container.env_id}", "pkill", "-f", "uvicorn"],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def pause_container(self, container) -> bool:
        """Pause a Docker container."""
        try:
            container.container.pause()
            return True
        except Exception:
            return False
    
    def unpause_container(self, container) -> bool:
        """Unpause a paused Docker container."""
        try:
            container.container.unpause()
            return True
        except Exception:
            return False
    
    def stop_container(self, container, timeout: int = 1) -> bool:
        """Stop a Docker container completely."""
        try:
            container.container.stop(timeout=timeout)
            return True
        except Exception:
            return False
    
    async def wait_until_healthy(self, client, timeout: float = 60.0, poll_interval: float = 2.0) -> bool:
        """Wait until a container becomes healthy again."""
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                if await client.is_healthy():
                    return True
            except Exception:
                pass
            await asyncio.sleep(poll_interval)
        
        return False
    
    async def wait_until_unhealthy(self, client, timeout: float = 30.0, poll_interval: float = 2.0) -> bool:
        """Wait until a container becomes unhealthy."""
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                if not await client.is_healthy():
                    return True
            except Exception:
                return True
            await asyncio.sleep(poll_interval)
        
        return False


@pytest.fixture
def container_killer():
    """Fixture providing ContainerKiller helper."""
    return ContainerKiller()


@dataclass
class TrajectoryTracker:
    """Tracks trajectory execution for testing."""
    containers_used: List[int] = None
    trajectories_completed: List[Tuple[int, int, bool]] = None
    errors: List[Tuple[int, int, str]] = None
    
    def __post_init__(self):
        self.containers_used = []
        self.trajectories_completed = []
        self.errors = []
    
    def record_container_use(self, env_id: int):
        self.containers_used.append(env_id)
    
    def record_completion(self, batch_idx: int, traj_id: int, success: bool):
        self.trajectories_completed.append((batch_idx, traj_id, success))
    
    def record_error(self, batch_idx: int, traj_id: int, error: str):
        self.errors.append((batch_idx, traj_id, error))
    
    def get_unique_containers(self) -> set:
        return set(self.containers_used)
    
    def all_succeeded(self) -> bool:
        return all(success for _, _, success in self.trajectories_completed)


@pytest.fixture
def trajectory_tracker():
    """Fixture providing TrajectoryTracker."""
    return TrajectoryTracker()


async def run_with_timeout(coro, timeout: float, description: str = "operation"):
    """Run a coroutine with a timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"{description} timed out after {timeout}s")


@pytest.fixture
def capture_logs(caplog):
    """Fixture to capture logs for verification."""
    import logging
    caplog.set_level(logging.DEBUG)
    return caplog
