"""
Phase 3 & 4: Full Container Integration Tests

These tests require:
- Docker installed and running
- KVM support (for Android emulator)
- Built androidworld:v8 image

Run with:
    RUN_DOCKER_TESTS=true pytest tests/integration/androidworld/test_full_container.py -v -s

Environment variables:
    RUN_DOCKER_TESTS=true          - Enable Docker tests
    ANDROID_DOCKER_IMAGE           - Docker image name (default: androidworld:v8)
    DOCKER_TEST_TIMEOUT            - Container startup timeout in seconds (default: 600)
"""

import pytest
import pytest_asyncio
import asyncio
import os
import time
import requests
from typing import Optional

# Check prerequisites
DOCKER_AVAILABLE = os.path.exists("/var/run/docker.sock") or os.environ.get("DOCKER_HOST")
RUN_DOCKER_TESTS = os.environ.get("RUN_DOCKER_TESTS", "").lower() == "true"
KVM_AVAILABLE = os.path.exists("/dev/kvm")

# Skip marker for tests requiring full Docker setup
skip_without_docker = pytest.mark.skipif(
    not (DOCKER_AVAILABLE and RUN_DOCKER_TESTS),
    reason="Docker tests disabled (set RUN_DOCKER_TESTS=true)"
)

skip_without_kvm = pytest.mark.skipif(
    not KVM_AVAILABLE,
    reason="KVM not available (/dev/kvm not found)"
)


# ==================== Fixtures ====================


@pytest.fixture(scope="module")
def docker_image():
    """Get Docker image name from environment."""
    return os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:v8")


@pytest.fixture(scope="module")
def container_timeout():
    """Get container startup timeout."""
    return int(os.environ.get("DOCKER_TEST_TIMEOUT", "600"))


@pytest.fixture(scope="module")
def docker_client():
    """Create Docker client."""
    try:
        import docker
        return docker.from_env()
    except ImportError:
        pytest.skip("docker-py not installed")
    except Exception as e:
        pytest.skip(f"Cannot connect to Docker: {e}")


# ==================== Phase 3: Container Startup Tests ====================


@skip_without_docker
@skip_without_kvm
class TestContainerStartup:
    """Test Docker container can start and become healthy."""
    
    @pytest.fixture
    def container(self, docker_client, docker_image, container_timeout):
        """Start a container for testing."""
        container = None
        try:
            # Start container
            container = docker_client.containers.run(
                docker_image,
                environment={
                    "SERVER_PORT": "5000",
                    "EMULATOR_PORT": "5574",
                    "GRPC_PORT": "8574",
                    "ENV_ID": "0",
                    "ENV_SAMPLE_MODE": "sequential",
                    "ENV_SNAPSHOT": "clean",
                },
                devices=["/dev/kvm"],
                network_mode="host",
                detach=True,
                auto_remove=False,  # Keep for inspection on failure
                name="test_container_startup",
            )
            
            yield container, 5000  # container, port
            
        finally:
            if container:
                try:
                    container.stop(timeout=10)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
    
    def test_container_starts(self, container):
        """Test container starts without immediate crash."""
        cont, port = container
        
        # Give it a moment
        time.sleep(5)
        
        # Check container is still running
        cont.reload()
        assert cont.status == "running", f"Container not running: {cont.status}"
    
    def test_health_endpoint_eventually_responds(self, container, container_timeout):
        """Test /health endpoint responds within timeout."""
        cont, port = container
        
        start_time = time.time()
        health_ok = False
        last_error = None
        
        while time.time() - start_time < container_timeout:
            try:
                response = requests.get(
                    f"http://localhost:{port}/health",
                    timeout=10
                )
                if response.status_code == 200:
                    health_ok = True
                    break
            except Exception as e:
                last_error = e
            
            time.sleep(10)
        
        assert health_ok, f"Health check failed after {container_timeout}s: {last_error}"
    
    def test_get_n_tasks_responds(self, container, container_timeout):
        """Test /get_n_tasks endpoint responds."""
        cont, port = container
        
        # Wait for health first
        self._wait_for_health(port, container_timeout)
        
        response = requests.get(f"http://localhost:{port}/get_n_tasks", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert "n_tasks" in data
        assert data["n_tasks"] > 0
    
    def _wait_for_health(self, port: int, timeout: int):
        """Wait for container to be healthy."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"http://localhost:{port}/health", timeout=10)
                if response.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(10)
        raise TimeoutError(f"Container not healthy after {timeout}s")


@skip_without_docker
@skip_without_kvm
class TestContainerReset:
    """Test container /reset endpoint with real emulator."""
    
    @pytest.fixture(scope="class")
    def running_container(self, docker_client, docker_image, container_timeout):
        """Start and wait for a healthy container."""
        container = None
        port = 5001  # Use different port to avoid conflicts
        
        try:
            container = docker_client.containers.run(
                docker_image,
                environment={
                    "SERVER_PORT": str(port),
                    "EMULATOR_PORT": "5576",
                    "GRPC_PORT": "8576",
                    "ENV_ID": "1",
                    "ENV_SAMPLE_MODE": "sequential",
                    "ENV_SNAPSHOT": "clean",
                },
                devices=["/dev/kvm"],
                network_mode="host",
                detach=True,
                auto_remove=False,
                name="test_container_reset",
            )
            
            # Wait for healthy
            start_time = time.time()
            while time.time() - start_time < container_timeout:
                try:
                    response = requests.get(f"http://localhost:{port}/health", timeout=10)
                    if response.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(10)
            else:
                raise TimeoutError("Container not healthy")
            
            yield container, port
            
        finally:
            if container:
                try:
                    container.stop(timeout=10)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
    
    def test_reset_returns_observation(self, running_container):
        """Test /reset returns valid observation."""
        cont, port = running_container
        
        response = requests.post(
            f"http://localhost:{port}/reset",
            json={"seed": 42, "options": {"task_id": 0}},
            timeout=120
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert "observation" in data
        assert "image" in data["observation"]
        assert "image_shape" in data["observation"]
        assert "image_dtype" in data["observation"]
    
    def test_reset_with_different_tasks(self, running_container):
        """Test reset with different task_ids."""
        cont, port = running_container
        
        for task_id in [0, 1, 2]:
            response = requests.post(
                f"http://localhost:{port}/reset",
                json={"seed": task_id, "options": {"task_id": task_id}},
                timeout=120
            )
            
            assert response.status_code == 200, f"Reset failed for task_id={task_id}"


@skip_without_docker
@skip_without_kvm
class TestContainerStep:
    """Test container /step endpoint with real emulator."""
    
    @pytest.fixture(scope="class")
    def running_container(self, docker_client, docker_image, container_timeout):
        """Start and wait for a healthy container."""
        container = None
        port = 5002
        
        try:
            container = docker_client.containers.run(
                docker_image,
                environment={
                    "SERVER_PORT": str(port),
                    "EMULATOR_PORT": "5578",
                    "GRPC_PORT": "8578",
                    "ENV_ID": "2",
                    "ENV_SAMPLE_MODE": "sequential",
                    "ENV_SNAPSHOT": "clean",
                },
                devices=["/dev/kvm"],
                network_mode="host",
                detach=True,
                auto_remove=False,
                name="test_container_step",
            )
            
            # Wait for healthy
            start_time = time.time()
            while time.time() - start_time < container_timeout:
                try:
                    response = requests.get(f"http://localhost:{port}/health", timeout=10)
                    if response.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(10)
            else:
                raise TimeoutError("Container not healthy")
            
            # Reset to get into known state
            requests.post(
                f"http://localhost:{port}/reset",
                json={"seed": 42, "options": {"task_id": 0}},
                timeout=120
            )
            
            yield container, port
            
        finally:
            if container:
                try:
                    container.stop(timeout=10)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
    
    def test_step_click_action(self, running_container):
        """Test /step with click action."""
        cont, port = running_container
        
        response = requests.post(
            f"http://localhost:{port}/step",
            json={
                "action": {
                    "action_type": "click",
                    "touch_point": [0.5, 0.5]
                },
                "thought": "Testing click"
            },
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "success"
        assert "observation" in data
        assert "reward" in data
        assert "terminated" in data
        assert "truncated" in data
    
    def test_step_wait_action(self, running_container):
        """Test /step with wait action."""
        cont, port = running_container
        
        response = requests.post(
            f"http://localhost:{port}/step",
            json={
                "action": {"action_type": "wait"},
                "thought": "Waiting"
            },
            timeout=60
        )
        
        assert response.status_code == 200
    
    def test_step_status_complete(self, running_container):
        """Test /step with status=complete terminates episode."""
        cont, port = running_container
        
        response = requests.post(
            f"http://localhost:{port}/step",
            json={
                "action": {
                    "action_type": "status",
                    "goal_status": "complete"
                },
                "thought": "Marking complete"
            },
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["terminated"] == True


# ==================== Phase 4: RuntimeClient Integration ====================


@skip_without_docker
@skip_without_kvm
class TestRuntimeClientIntegration:
    """Test RuntimeClient with real container."""
    
    @pytest_asyncio.fixture(scope="class")
    async def container_manager(self, docker_image, container_timeout):
        """Create ContainerManager and start a container."""
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        
        manager = ContainerManager(
            docker_image=docker_image,
            temp_path="/tmp/android_integration_test",
        )
        
        try:
            # Create single container
            containers = await manager.create_pool_parallel(
                pool_size=1,
                base_env_id=10,
                max_concurrent=1,
                initial_wait=30.0,
                sample_mode="sequential",
                snapshot="clean",
            )
            
            yield manager, containers[0]
            
        finally:
            await manager.cleanup()
    
    @pytest.mark.asyncio
    async def test_runtime_client_reset(self, container_manager):
        """Test RuntimeClient.reset() with real container."""
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        manager, container = container_manager
        client = RuntimeClient(container)
        
        try:
            obs, info = await client.reset({
                "seed": 42,
                "options": {"task_id": 0}
            })
            
            assert obs is not None
            assert "image" in obs
            # Image should be numpy array after deserialization
            import numpy as np
            assert isinstance(obs["image"], np.ndarray)
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_runtime_client_step(self, container_manager):
        """Test RuntimeClient.step() with real container."""
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        manager, container = container_manager
        client = RuntimeClient(container)
        
        try:
            # Reset first
            await client.reset({
                "seed": 42,
                "options": {"task_id": 0}
            })
            
            # Step
            obs, reward, terminated, truncated, info = await client.step({
                "action": {"action_type": "wait"},
                "thought": "Testing step"
            })
            
            assert obs is not None
            assert isinstance(reward, (int, float))
            assert isinstance(terminated, bool)
            assert isinstance(truncated, bool)
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_runtime_client_health_check(self, container_manager):
        """Test RuntimeClient.is_healthy()."""
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        manager, container = container_manager
        client = RuntimeClient(container)
        
        try:
            is_healthy = await client.is_healthy()
            assert is_healthy == True
            
        finally:
            await client.close()


@skip_without_docker
@skip_without_kvm
class TestContainerManagerPool:
    """Test ContainerManager with multiple containers."""
    
    @pytest.mark.asyncio
    async def test_pool_creation(self, docker_image):
        """Test creating a pool of containers."""
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        
        manager = ContainerManager(
            docker_image=docker_image,
            temp_path="/tmp/android_pool_test",
        )
        
        try:
            containers = await manager.create_pool_parallel(
                pool_size=2,
                base_env_id=20,
                max_concurrent=2,
                initial_wait=30.0,
            )
            
            assert len(containers) == 2
            assert manager.available_queue.qsize() == 2
            
            # Each container should have unique ports
            ports = [c.server_port for c in containers]
            assert len(set(ports)) == 2
            
        finally:
            await manager.cleanup()
    
    @pytest.mark.asyncio
    async def test_container_allocation(self, docker_image):
        """Test allocating and releasing containers."""
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        
        manager = ContainerManager(
            docker_image=docker_image,
            temp_path="/tmp/android_alloc_test",
        )
        
        try:
            await manager.create_pool_parallel(pool_size=2, base_env_id=30, max_concurrent=2, initial_wait=30.0)
            
            # Allocate one
            container1 = await manager.allocate_container()
            assert container1.state == "in_use"
            assert manager.available_queue.qsize() == 1
            
            # Release it
            await manager.release_container(container1)
            assert container1.state == "ready"
            assert manager.available_queue.qsize() == 2
            
        finally:
            await manager.cleanup()
    
    @pytest.mark.asyncio
    async def test_pool_status(self, docker_image):
        """Test getting pool status."""
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        
        manager = ContainerManager(
            docker_image=docker_image,
            temp_path="/tmp/android_status_test",
        )
        
        try:
            await manager.create_pool_parallel(pool_size=2, base_env_id=40, max_concurrent=2, initial_wait=30.0)
            
            status = manager.get_pool_status()
            
            assert status["total"] == 2
            assert status["healthy"] == 2
            assert status["idle"] == 2
            assert status["in_use"] == 0
            
        finally:
            await manager.cleanup()


# ==================== End-to-End Workflow Test ====================


@skip_without_docker
@skip_without_kvm
class TestEndToEndWorkflow:
    """Test complete workflow from container start to task completion."""
    
    @pytest.mark.asyncio
    async def test_complete_trajectory(self, docker_image):
        """Test running a complete trajectory."""
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        manager = ContainerManager(
            docker_image=docker_image,
            temp_path="/tmp/android_e2e_test",
        )
        
        try:
            # Create container
            containers = await manager.create_pool_parallel(
                pool_size=1,
                base_env_id=50,
                max_concurrent=1,
                initial_wait=30.0,
            )
            
            # Allocate for trajectory
            container = await manager.allocate_container(
                batch_idx=0,
                trajectory_id=0
            )
            
            client = RuntimeClient(container)
            
            try:
                # Reset environment
                obs, info = await client.reset({
                    "seed": 42,
                    "options": {
                        "task_id": 0,
                        "go_home_on_reset": True,
                        "epoch": 0,
                        "mode": "test",
                        "traj": 0,
                        "total_traj": 1
                    }
                })
                
                assert obs is not None
                
                # Take a few steps
                for i in range(3):
                    obs, reward, terminated, truncated, info = await client.step({
                        "action": {"action_type": "wait"},
                        "thought": f"Step {i}"
                    })
                    
                    if terminated:
                        break
                
                # Complete task
                obs, reward, terminated, truncated, info = await client.step({
                    "action": {
                        "action_type": "status",
                        "goal_status": "complete"
                    },
                    "thought": "Marking complete"
                })
                
                assert terminated == True
                
            finally:
                await client.close()
            
            # Release container
            await manager.release_container(container, success=True)
            
            # Check status
            status = manager.get_pool_status()
            assert status["idle"] == 1
            assert status["in_use"] == 0
            
        finally:
            await manager.cleanup()
