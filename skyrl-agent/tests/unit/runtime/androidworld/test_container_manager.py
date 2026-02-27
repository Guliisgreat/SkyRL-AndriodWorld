"""
Unit tests for ContainerManager and related components.

Tests are organized by component:
- TestPortAllocator: Tests for PortAllocator class
- TestContainerFactory: Tests for ContainerFactory class  
- TestHealthMonitor: Tests for HealthMonitor class
- TestContainerManager: Tests for ContainerManager (integration)
"""

import pytest
import asyncio
import logging
import time
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from pathlib import Path

from skyrl_agent.runtime.android.container_manager import (
    ContainerManager,
    ContainerInstance,
    PortAllocationError,
    PortAllocator,
    ContainerFactory,
    ContainerConfig,
    HealthMonitor,
)

# Configure logging for test progress
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_docker_client():
    """Mock Docker client."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test-id"
    mock_container.stop = Mock()
    mock_container.status = "running"
    mock_container.attrs = {
        'NetworkSettings': {
            'Ports': {}
        }
    }
    
    mock_client.containers.list.return_value = []
    mock_client.containers.run.return_value = mock_container
    mock_client.containers.get.side_effect = Exception("Not found")
    
    return mock_client


@pytest.fixture
def mock_port_allocator(tmp_path):
    """Create mock PortAllocator."""
    allocator = Mock(spec=PortAllocator)
    allocator.lock_file = tmp_path / "test.lck"
    allocator.get_used_ports.return_value = set()
    allocator.allocate_port.side_effect = lambda start: start
    allocator.preallocate_ports.side_effect = lambda pool_size, base_env_id, **kwargs: [
        (5000 + 2 * (base_env_id + i), 5574 + 2 * (base_env_id + i), 8574 + 2 * (base_env_id + i))
        for i in range(pool_size)
    ]
    allocator._reserved_ports = set()
    return allocator


@pytest.fixture
def mock_container_factory():
    """Create mock ContainerFactory."""
    factory = Mock(spec=ContainerFactory)
    
    async def mock_create(env_id, ports, config, use_host_network=False):
        mock_container = MagicMock()
        mock_container.id = f"container-{env_id}"
        mock_container.stop = Mock()
        mock_container.status = "running"
        mock_container.reload = Mock()  # For health checks
        
        # Return a mock CreatedContainer-like object
        created = Mock()
        created.container_id = f"container-{env_id}"
        created.container = mock_container
        created.server_port = ports[0]
        created.emulator_port = ports[1]
        created.grpc_port = ports[2]
        created.env_id = env_id
        created.state = "ready"
        created.last_health_check = time.time()
        created.is_healthy = True
        return created
    
    factory.create = AsyncMock(side_effect=mock_create)
    return factory


@pytest.fixture
def mock_health_check():
    """Mock requests.get for health checks during allocation."""
    mock_response = Mock()
    mock_response.status_code = 200
    with patch('skyrl_agent.runtime.android.container_manager.requests.get', return_value=mock_response):
        yield mock_response


# =============================================================================
# PortAllocator Tests
# =============================================================================

class TestPortAllocator:
    """Test PortAllocator functionality."""
    
    def test_allocate_port(self, mock_docker_client, tmp_path):
        """Test port allocation finds available port."""
        print("\n[TEST] Running: test_allocate_port")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]):
            allocator = PortAllocator(
                lock_file=tmp_path / "test.lck",
                docker_client=mock_docker_client,
            )
            
            port = allocator.allocate_port(5000)
            assert port == 5000
        print("[TEST] ✓ test_allocate_port passed")
    
    def test_allocate_port_conflict(self, mock_docker_client, tmp_path):
        """Test port allocation handles conflicts."""
        print("\n[TEST] Running: test_allocate_port_conflict")
        
        # Mock port 5000 is taken
        mock_conn = Mock()
        mock_conn.laddr.port = 5000
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[mock_conn]):
            allocator = PortAllocator(
                lock_file=tmp_path / "test.lck",
                docker_client=mock_docker_client,
            )
            
            port = allocator.allocate_port(5000)
            assert port == 5001  # Next available port
        print("[TEST] ✓ test_allocate_port_conflict passed")
    
    def test_get_used_ports(self, mock_docker_client, tmp_path):
        """Test getting used ports from system and Docker."""
        print("\n[TEST] Running: test_get_used_ports")
        
        # Mock system ports
        mock_conn = Mock()
        mock_conn.laddr.port = 5000
        
        # Mock Docker ports
        mock_container = MagicMock()
        mock_container.attrs = {
            'NetworkSettings': {
                'Ports': {
                    '5555/tcp': [{'HostPort': '5555'}]
                }
            }
        }
        mock_docker_client.containers.list.return_value = [mock_container]
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[mock_conn]):
            allocator = PortAllocator(
                lock_file=tmp_path / "test.lck",
                docker_client=mock_docker_client,
            )
            
            used_ports = allocator.get_used_ports()
            assert 5000 in used_ports
            assert 5555 in used_ports
        print("[TEST] ✓ test_get_used_ports passed")
    
    def test_port_allocation_error(self, mock_docker_client, tmp_path):
        """Test PortAllocationError raised when no ports available."""
        print("\n[TEST] Running: test_port_allocation_error")
        
        # Mock all ports from 65354 onwards are taken
        mock_conns = [Mock() for _ in range(10)]
        for i, conn in enumerate(mock_conns):
            conn.laddr.port = 65354 + i
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=mock_conns):
            allocator = PortAllocator(
                lock_file=tmp_path / "test.lck",
                docker_client=mock_docker_client,
            )
            
            with pytest.raises(PortAllocationError):
                allocator.allocate_port(65354)
        print("[TEST] ✓ test_port_allocation_error passed")
    
    def test_preallocate_ports(self, mock_docker_client, tmp_path):
        """Test port pre-allocation for multiple containers."""
        print("\n[TEST] Running: test_preallocate_ports")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]):
            allocator = PortAllocator(
                lock_file=tmp_path / "test.lck",
                docker_client=mock_docker_client,
            )
            
            port_tuples = allocator.preallocate_ports(pool_size=3, base_env_id=0)
            
            assert len(port_tuples) == 3
            # Verify each tuple has (server, emulator, grpc) ports
            for i, (server, emulator, grpc) in enumerate(port_tuples):
                print(f"[TEST]   Container {i}: server={server}, emulator={emulator}, grpc={grpc}")
                assert server > 0
                assert emulator > 0
                assert grpc > 0
        print("[TEST] ✓ test_preallocate_ports passed")
    
    def test_preallocate_ports_unique(self, mock_docker_client, tmp_path):
        """Test pre-allocated ports are unique."""
        print("\n[TEST] Running: test_preallocate_ports_unique")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]):
            allocator = PortAllocator(
                lock_file=tmp_path / "test.lck",
                docker_client=mock_docker_client,
            )
            
            port_tuples = allocator.preallocate_ports(pool_size=4, base_env_id=0)
            
            # Collect all ports
            all_ports = []
            for server, emulator, grpc in port_tuples:
                all_ports.extend([server, emulator, grpc])
            
            # Verify all ports are unique
            assert len(all_ports) == len(set(all_ports))
        print("[TEST] ✓ test_preallocate_ports_unique passed")


# =============================================================================
# ContainerFactory Tests
# =============================================================================

class TestContainerFactory:
    """Test ContainerFactory functionality."""
    
    @pytest.mark.asyncio
    async def test_wait_for_ready(self, mock_docker_client, tmp_path):
        """Test waiting for container to be ready."""
        print("\n[TEST] Running: test_wait_for_ready")
        
        with patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            factory = ContainerFactory(
                docker_image="test:v1",
                temp_path=str(tmp_path),
                docker_client=mock_docker_client,
            )
            
            # Should not raise exception
            await factory.wait_for_ready(5555, 0)
            
            # Verify health endpoint called
            mock_get.assert_called()
        print("[TEST] ✓ test_wait_for_ready passed")
    
    @pytest.mark.asyncio
    async def test_create_container(self, mock_docker_client, tmp_path):
        """Test creating a container."""
        print("\n[TEST] Running: test_create_container")
        
        with patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            factory = ContainerFactory(
                docker_image="test:v1",
                temp_path=str(tmp_path),
                docker_client=mock_docker_client,
            )
            
            config = ContainerConfig(
                sample_mode="random",
                snapshot="clean",
                train_task_family="android_world",
                val_task_family="android_world",
                initial_wait=1.0,
            )
            
            created = await factory.create(
                env_id=0,
                ports=(5000, 5574, 8574),
                config=config,
                use_host_network=False,
            )
            
            assert created.env_id == 0
            assert created.server_port == 5000
            assert created.emulator_port == 5574
            assert created.grpc_port == 8574
            assert created.state == "ready"
        print("[TEST] ✓ test_create_container passed")


# =============================================================================
# HealthMonitor Tests
# =============================================================================

class TestHealthMonitor:
    """Test HealthMonitor functionality."""
    
    def test_check_health_healthy(self):
        """Test health check on healthy container."""
        print("\n[TEST] Running: test_check_health_healthy")
        
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_container.reload = Mock()
        
        container = ContainerInstance(
            container_id="test-id",
            container=mock_container,
            server_port=5000,
            emulator_port=5574,
            grpc_port=8574,
            env_id=0,
            state="ready",
        )
        
        with patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            monitor = HealthMonitor(containers=[container])
            is_healthy = monitor.check_health(container)
            
            assert is_healthy is True
            assert container.is_healthy is True
        print("[TEST] ✓ test_check_health_healthy passed")
    
    def test_check_health_docker_not_running(self):
        """Test health check when Docker container not running."""
        print("\n[TEST] Running: test_check_health_docker_not_running")
        
        mock_container = MagicMock()
        mock_container.status = "stopped"
        mock_container.reload = Mock()
        
        container = ContainerInstance(
            container_id="test-id",
            container=mock_container,
            server_port=5000,
            emulator_port=5574,
            grpc_port=8574,
            env_id=0,
            state="ready",
        )
        
        monitor = HealthMonitor(containers=[container])
        is_healthy = monitor.check_health(container)
        
        assert is_healthy is False
        assert container.is_healthy is False
        print("[TEST] ✓ test_check_health_docker_not_running passed")
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping health monitor."""
        print("\n[TEST] Running: test_start_stop")
        
        monitor = HealthMonitor(containers=[])
        
        assert monitor.is_running is False
        
        await monitor.start(interval=1.0)
        assert monitor.is_running is True
        
        await monitor.stop()
        assert monitor.is_running is False
        print("[TEST] ✓ test_start_stop passed")


# =============================================================================
# ContainerManager Integration Tests
# =============================================================================

class TestContainerManagerInit:
    """Test ContainerManager initialization."""
    
    def test_init_default(self, tmp_path, mock_docker_client):
        """Test ContainerManager initialization with default parameters."""
        print("\n[TEST] Running: test_init_default")
        
        with patch('skyrl_agent.runtime.android.container_manager.docker.from_env', return_value=mock_docker_client):
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                _docker_client=mock_docker_client,
            )
            
            assert manager.docker_image == "androidworld:v8"
            assert manager.temp_path == str(tmp_path)
            assert manager.containers == []
            assert manager.available_queue is None
        print("[TEST] ✓ test_init_default passed")
    
    def test_init_custom_lock_file(self, tmp_path, mock_docker_client):
        """Test initialization with custom lock file path."""
        print("\n[TEST] Running: test_init_custom_lock_file")
        
        with patch('skyrl_agent.runtime.android.container_manager.docker.from_env', return_value=mock_docker_client):
            custom_lock = tmp_path / "custom_lock.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=custom_lock,
                _docker_client=mock_docker_client,
            )
            
            assert manager.lock_file == custom_lock
        print("[TEST] ✓ test_init_custom_lock_file passed")
    
    def test_init_with_injected_components(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory):
        """Test initialization with injected components for testing."""
        print("\n[TEST] Running: test_init_with_injected_components")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        assert manager._port_allocator is mock_port_allocator
        assert manager._factory is mock_container_factory
        print("[TEST] ✓ test_init_with_injected_components passed")


class TestContainerPoolManagement:
    """Test container pool management with DI."""
    
    @pytest.mark.asyncio
    async def test_create_pool(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory):
        """Test creating pool of containers."""
        print("\n[TEST] Running: test_create_pool")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        containers = await manager.create_pool_parallel(
            pool_size=3,
            base_env_id=0,
            max_concurrent=2,
            initial_wait=0.1,
        )
        
        assert len(containers) == 3
        assert manager.available_queue is not None
        assert manager.available_queue.qsize() == 3
        
        # Verify factory was called 3 times
        assert mock_container_factory.create.call_count == 3
        print("[TEST] ✓ test_create_pool passed")
    
    @pytest.mark.asyncio
    async def test_create_pool_parallel(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory):
        """Test parallel pool creation."""
        print("\n[TEST] Running: test_create_pool_parallel")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        containers = await manager.create_pool_parallel(
            pool_size=3,
            base_env_id=0,
            max_concurrent=2,
            initial_wait=1.0,
        )
        
        assert len(containers) == 3
        assert manager.available_queue is not None
        assert manager.available_queue.qsize() == 3
        
        # Verify pool config is stored
        assert manager._pool_config is not None
        assert manager._pool_config["initial_wait"] == 1.0
        print("[TEST] ✓ test_create_pool_parallel passed")
    
    @pytest.mark.asyncio
    async def test_allocate_container(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory, mock_health_check):
        """Test allocating container from pool."""
        print("\n[TEST] Running: test_allocate_container")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        # Create pool
        await manager.create_pool_parallel(pool_size=2, base_env_id=0, max_concurrent=2, initial_wait=0.1)
        
        # Allocate container
        container = await manager.allocate_container()
        
        assert container.state == "in_use"
        assert manager.available_queue.qsize() == 1
        print("[TEST] ✓ test_allocate_container passed")
    
    @pytest.mark.asyncio
    async def test_allocate_container_empty_pool(self, tmp_path, mock_docker_client):
        """Test allocating from empty pool raises error."""
        print("\n[TEST] Running: test_allocate_container_empty_pool")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _docker_client=mock_docker_client,
        )
        
        # Don't create pool
        with pytest.raises(RuntimeError, match="Container pool not initialized"):
            await manager.allocate_container()
        print("[TEST] ✓ test_allocate_container_empty_pool passed")
    
    @pytest.mark.asyncio
    async def test_release_container(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory, mock_health_check):
        """Test releasing container back to pool."""
        print("\n[TEST] Running: test_release_container")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        # Create pool and allocate
        await manager.create_pool_parallel(pool_size=2, base_env_id=0, max_concurrent=2, initial_wait=0.1)
        container = await manager.allocate_container()
        
        # Release container
        await manager.release_container(container)
        
        assert container.state == "ready"
        assert manager.available_queue.qsize() == 2
        print("[TEST] ✓ test_release_container passed")
    
    @pytest.mark.asyncio
    async def test_container_pool_reuse(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory, mock_health_check):
        """Test containers can be reused after release."""
        print("\n[TEST] Running: test_container_pool_reuse")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        # Create pool with 1 container to ensure reuse
        await manager.create_pool_parallel(pool_size=1, base_env_id=0, max_concurrent=1, initial_wait=0.1)
        
        # Allocate the only container
        container1 = await manager.allocate_container()
        container1_id = container1.container_id
        assert container1.state == "in_use"
        
        # Release container
        await manager.release_container(container1)
        assert container1.state == "ready"
        
        # Allocate again - must get same container (only one in pool)
        container2 = await manager.allocate_container()
        assert container2.container_id == container1_id
        assert container2 is container1  # Same object
        print("[TEST] ✓ test_container_pool_reuse passed")


class TestCleanup:
    """Test cleanup functionality."""
    
    @pytest.mark.asyncio
    async def test_cleanup(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory):
        """Test cleanup stops all containers."""
        print("\n[TEST] Running: test_cleanup")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        # Create pool
        containers = await manager.create_pool_parallel(pool_size=2, base_env_id=0, max_concurrent=2, initial_wait=0.1)
        
        # Cleanup
        await manager.cleanup()
        
        # Verify all containers stopped
        for container in containers:
            container.container.stop.assert_called()
        print("[TEST] ✓ test_cleanup passed")


class TestPoolStatus:
    """Test pool status functionality."""
    
    @pytest.mark.asyncio
    async def test_get_pool_status(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory):
        """Test getting pool status."""
        print("\n[TEST] Running: test_get_pool_status")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        # Create pool
        await manager.create_pool_parallel(pool_size=2, base_env_id=0, max_concurrent=2, initial_wait=0.1)
        
        # Get status
        status = manager.get_pool_status()
        
        assert status["total"] == 2
        assert status["healthy"] == 2
        assert status["idle"] == 2
        assert status["in_use"] == 0
        print("[TEST] ✓ test_get_pool_status passed")
    
    @pytest.mark.asyncio
    async def test_failed_trajectories(self, tmp_path, mock_docker_client, mock_port_allocator, mock_container_factory, mock_health_check):
        """Test failed trajectory tracking."""
        print("\n[TEST] Running: test_failed_trajectories")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            _port_allocator=mock_port_allocator,
            _container_factory=mock_container_factory,
            _docker_client=mock_docker_client,
        )
        
        # Create pool
        await manager.create_pool_parallel(pool_size=1, base_env_id=0, max_concurrent=1, initial_wait=0.1)
        
        # Allocate and release with failure
        container = await manager.allocate_container(batch_idx=0, trajectory_id=1)
        await manager.release_container(container, success=False, error="Test error")
        
        # Check failed trajectories
        failed = manager.get_failed_trajectories()
        assert len(failed) == 1
        assert failed[0] == (0, 1, "Test error")
        
        # Clear and verify
        manager.clear_failed_trajectories()
        assert len(manager.get_failed_trajectories()) == 0
        print("[TEST] ✓ test_failed_trajectories passed")


print("\n" + "=" * 50)
print("[TEST SUITE] ContainerManager refactored tests")
print("=" * 50)
