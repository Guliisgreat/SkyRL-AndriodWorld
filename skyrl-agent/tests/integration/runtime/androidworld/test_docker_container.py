"""
Integration tests with real Docker containers (optional).
"""

import pytest
import os

# Check if Docker is available
DOCKER_AVAILABLE = os.path.exists("/var/run/docker.sock") or os.environ.get("DOCKER_HOST")
RUN_DOCKER_TESTS = os.environ.get("RUN_DOCKER_TESTS", "").lower() == "true"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not (DOCKER_AVAILABLE and RUN_DOCKER_TESTS), reason="Docker tests disabled")
async def test_real_container_communication():
    """Test RuntimeClient with real container server."""
    from skyrl_agent.runtime.android.container_manager import ContainerManager
    from skyrl_agent.runtime.android.runtime_client import RuntimeClient
    
    # This test requires a real Docker container running
    # Skip if not available
    docker_image = os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:v8")
    
    manager = ContainerManager(
        docker_image=docker_image,
        temp_path="/tmp/android_test",
    )
    
    try:
        # Create a single container
        containers = await manager.create_pool_parallel(
            pool_size=1,
            base_env_id=0,
            max_concurrent=1,
            initial_wait=30.0,
            sample_mode="sequential",
            snapshot="clean",
        )
        
        assert len(containers) == 1
        container = containers[0]
        
        # Create RuntimeClient
        client = RuntimeClient(container)
        
        # Test reset
        obs, info = await client.reset({
            "seed": 42,
            "options": {"task_id": 0}
        })
        
        assert obs is not None
        assert "image" in obs
        
        # Test step
        obs, reward, terminated, truncated, info = await client.step({
            "action": {"action_type": "status"},
            "thought": "test"
        })
        
        assert obs is not None
        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        
        # Cleanup
        await client.close()
        
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not (DOCKER_AVAILABLE and RUN_DOCKER_TESTS), reason="Docker tests disabled")
async def test_container_pool_with_real_containers():
    """Test ContainerManager with real Docker containers."""
    from skyrl_agent.runtime.android.container_manager import ContainerManager
    
    docker_image = os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:v8")
    
    manager = ContainerManager(
        docker_image=docker_image,
        temp_path="/tmp/android_test",
    )
    
    try:
        # Create pool - use different base_env_id to avoid conflict with first test
        containers = await manager.create_pool_parallel(
            pool_size=2,
            base_env_id=100,
            max_concurrent=2,
            initial_wait=30.0,
        )
        
        assert len(containers) == 2
        
        # Test allocation
        container1 = await manager.allocate_container()
        assert container1.state == "in_use"
        assert manager.available_queue.qsize() == 1
        
        # Test release
        await manager.release_container(container1)
        assert container1.state == "ready"
        assert manager.available_queue.qsize() == 2
        
        # Test reuse
        container2 = await manager.allocate_container()
        # Could be container1 or another one
        
    finally:
        await manager.cleanup()

