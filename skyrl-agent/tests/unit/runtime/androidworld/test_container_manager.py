"""
Unit tests for ContainerManager.
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from pathlib import Path
import psutil
import docker

from skyrl_agent.runtime.android.container_manager import (
    ContainerManager,
    ContainerInstance,
    PortAllocationError,
)

# Configure logging for test progress
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TestContainerManagerInit:
    """Test ContainerManager initialization."""
    
    def test_container_manager_init_default(self, tmp_path, mock_docker_client):
        """Test ContainerManager initialization with default parameters."""
        print("\n[TEST] Running: test_container_manager_init_default")
        logger.info("Testing ContainerManager initialization with default parameters...")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
        )
        
        assert manager.docker_image == "androidworld:v8"
        assert manager.temp_path == str(tmp_path)
        assert manager.containers == []
        assert manager.available_queue is None
        print("[TEST] ✓ test_container_manager_init_default passed")
    
    def test_container_manager_init_custom_lock_file(self, tmp_path, mock_docker_client):
        """Test initialization with custom lock file path."""
        print("\n[TEST] Running: test_container_manager_init_custom_lock_file")
        logger.info("Testing ContainerManager initialization with custom lock file...")
        
        custom_lock = tmp_path / "custom_lock.lck"
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
            lock_file=custom_lock,
        )
        
        assert manager.lock_file == custom_lock
        print("[TEST] ✓ test_container_manager_init_custom_lock_file passed")


class TestPortAllocation:
    """Test port allocation functionality."""
    
    def test_get_available_port(self, mock_docker_client):
        """Test port allocation finds available port."""
        print("\n[TEST] Running: test_get_available_port")
        logger.info("Testing port allocation finds available port...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]):
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path="/tmp",
            )
            manager.client = mock_docker_client
            
            port = manager._get_available_port(5000)
            assert port == 5000
        print("[TEST] ✓ test_get_available_port passed")
    
    def test_get_available_port_conflict(self, mock_docker_client):
        """Test port allocation handles conflicts."""
        print("\n[TEST] Running: test_get_available_port_conflict")
        logger.info("Testing port allocation handles conflicts...")
        
        # Mock port 5000 is taken
        mock_conn = Mock()
        mock_conn.laddr.port = 5000
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[mock_conn]):
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path="/tmp",
            )
            manager.client = mock_docker_client
            
            port = manager._get_available_port(5000)
            assert port == 5001  # Next available port
        print("[TEST] ✓ test_get_available_port_conflict passed")
    
    def test_get_used_ports(self, mock_docker_client):
        """Test getting used ports from system and Docker."""
        print("\n[TEST] Running: test_get_used_ports")
        logger.info("Testing getting used ports from system and Docker...")
        
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
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path="/tmp",
            )
            manager.client = mock_docker_client
            
            used_ports = manager._get_used_ports()
            assert 5000 in used_ports
            assert 5555 in used_ports
        print("[TEST] ✓ test_get_used_ports passed")
    
    def test_port_allocation_error(self, mock_docker_client):
        """Test PortAllocationError raised when no ports available."""
        print("\n[TEST] Running: test_port_allocation_error")
        logger.info("Testing PortAllocationError raised when no ports available...")
        
        # Mock all ports from 65354 onwards are taken
        mock_conns = [Mock() for _ in range(10)]
        for i, conn in enumerate(mock_conns):
            conn.laddr.port = 65354 + i
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=mock_conns):
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path="/tmp",
            )
            manager.client = mock_docker_client
            
            with pytest.raises(PortAllocationError):
                manager._get_available_port(65354)
        print("[TEST] ✓ test_port_allocation_error passed")


class TestContainerCreation:
    """Test container creation."""
    
    @pytest.mark.asyncio
    async def test_create_container(self, mock_docker_client, tmp_path):
        """Test creating a single container."""
        print("\n[TEST] Running: test_create_container")
        logger.info("Testing creating a single container...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            # Mock health check response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Creating container with env_id=0...")
            container = await manager._create_container(
                env_id=0,
                sample_mode="random",
                snapshot="clean",
                train_task_family="android_world",
                val_task_family="android_world",
            )
            
            assert isinstance(container, ContainerInstance)
            assert container.env_id == 0
            assert container.server_port == 5000
            assert container.emulator_port == 5574
            assert container.state == "ready"
        print("[TEST] ✓ test_create_container passed")
    
    @pytest.mark.asyncio
    async def test_create_pool(self, mock_docker_client, tmp_path):
        """Test creating pool of containers."""
        print("\n[TEST] Running: test_create_pool")
        logger.info("Testing creating pool of containers...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            # Mock health check responses
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Creating pool of 3 containers...")
            containers = await manager.create_pool(
                pool_size=3,
                base_env_id=0,
            )
            
            assert len(containers) == 3
            assert manager.available_queue is not None
            
            # Verify ports are sequential
            print("[TEST]   Verifying port allocation...")
            assert containers[0].server_port == 5000
            assert containers[1].server_port == 5002
            assert containers[2].server_port == 5004
            
            # Verify queue is populated
            assert manager.available_queue.qsize() == 3
        print("[TEST] ✓ test_create_pool passed")
    
    @pytest.mark.asyncio
    async def test_create_pool_port_allocation(self, mock_docker_client, tmp_path):
        """Test pool creation with correct port allocation."""
        print("\n[TEST] Running: test_create_pool_port_allocation")
        logger.info("Testing pool creation with correct port allocation...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Creating pool of 2 containers...")
            containers = await manager.create_pool(
                pool_size=2,
                base_env_id=0,
            )
            
            # Verify port allocation formula: 5000 + 2*env_id
            print("[TEST]   Verifying port allocation formula...")
            assert containers[0].server_port == 5000 + 2 * 0
            assert containers[0].emulator_port == 5574 + 2 * 0
            assert containers[1].server_port == 5000 + 2 * 1
            assert containers[1].emulator_port == 5574 + 2 * 1
        print("[TEST] ✓ test_create_pool_port_allocation passed")


class TestContainerPoolManagement:
    """Test container pool management."""
    
    @pytest.mark.asyncio
    async def test_allocate_container(self, mock_docker_client, tmp_path):
        """Test allocating container from pool."""
        print("\n[TEST] Running: test_allocate_container")
        logger.info("Testing allocating container from pool...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            # Create pool
            print("[TEST]   Creating pool...")
            await manager.create_pool(pool_size=2, base_env_id=0)
            
            # Allocate container
            print("[TEST]   Allocating container...")
            container = await manager.allocate_container()
            
            assert container.state == "in_use"
            assert manager.available_queue.qsize() == 1
        print("[TEST] ✓ test_allocate_container passed")
    
    @pytest.mark.asyncio
    async def test_allocate_container_empty_pool(self, mock_docker_client, tmp_path):
        """Test allocating from empty pool raises error."""
        print("\n[TEST] Running: test_allocate_container_empty_pool")
        logger.info("Testing allocating from empty pool raises error...")
        
        manager = ContainerManager(
            docker_image="androidworld:v8",
            temp_path=str(tmp_path),
        )
        manager.client = mock_docker_client
        
        # Don't create pool
        with pytest.raises(RuntimeError, match="Container pool not initialized"):
            await manager.allocate_container()
        print("[TEST] ✓ test_allocate_container_empty_pool passed")
    
    @pytest.mark.asyncio
    async def test_release_container(self, mock_docker_client, tmp_path):
        """Test releasing container back to pool."""
        print("\n[TEST] Running: test_release_container")
        logger.info("Testing releasing container back to pool...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            # Create pool and allocate
            print("[TEST]   Creating pool and allocating...")
            await manager.create_pool(pool_size=2, base_env_id=0)
            container = await manager.allocate_container()
            
            # Release container
            print("[TEST]   Releasing container...")
            await manager.release_container(container)
            
            assert container.state == "ready"
            assert manager.available_queue.qsize() == 2
        print("[TEST] ✓ test_release_container passed")
    
    @pytest.mark.asyncio
    async def test_container_pool_reuse(self, mock_docker_client, tmp_path):
        """Test containers can be reused."""
        print("\n[TEST] Running: test_container_pool_reuse")
        logger.info("Testing containers can be reused...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            # Create pool
            print("[TEST]   Creating pool...")
            await manager.create_pool(pool_size=2, base_env_id=0)
            
            # Allocate container 1
            print("[TEST]   Allocating container 1...")
            container1 = await manager.allocate_container()
            container1_id = container1.container_id
            
            # Release container 1
            print("[TEST]   Releasing container 1...")
            await manager.release_container(container1)
            
            # Allocate again - should get same container
            print("[TEST]   Allocating again (should reuse)...")
            container2 = await manager.allocate_container()
            assert container2.container_id == container1_id
        print("[TEST] ✓ test_container_pool_reuse passed")


class TestHealthCheck:
    """Test health check functionality."""
    
    @pytest.mark.asyncio
    async def test_wait_for_container_ready(self, mock_docker_client, tmp_path):
        """Test waiting for container to be ready."""
        print("\n[TEST] Running: test_wait_for_container_ready")
        logger.info("Testing waiting for container to be ready...")
        
        with patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
            )
            
            # Should not raise exception
            print("[TEST]   Waiting for container ready...")
            await manager._wait_for_container_ready(5555, 0)
            
            # Verify health endpoint called
            mock_get.assert_called()
        print("[TEST] ✓ test_wait_for_container_ready passed")
    
    @pytest.mark.asyncio
    async def test_wait_for_container_ready_timeout(self, mock_docker_client, tmp_path):
        """Test timeout when container never becomes ready."""
        print("\n[TEST] Running: test_wait_for_container_ready_timeout")
        logger.info("Testing timeout when container never becomes ready...")
        
        import skyrl_agent.runtime.android.container_manager as cm_module
        
        with patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch.object(cm_module, 'SERVER_TIMEOUT', 1), \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            mock_get.side_effect = Exception("Connection error")
            
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
            )
            
            print("[TEST]   Expecting TimeoutError...")
            with pytest.raises(TimeoutError):
                await manager._wait_for_container_ready(5555, 0)
        print("[TEST] ✓ test_wait_for_container_ready_timeout passed")


class TestCleanup:
    """Test cleanup functionality."""
    
    @pytest.mark.asyncio
    async def test_cleanup(self, mock_docker_client, tmp_path):
        """Test cleanup stops all containers."""
        print("\n[TEST] Running: test_cleanup")
        logger.info("Testing cleanup stops all containers...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            # Create pool
            print("[TEST]   Creating pool...")
            containers = await manager.create_pool(pool_size=2, base_env_id=0)
            
            # Cleanup
            print("[TEST]   Running cleanup...")
            await manager.cleanup()
            
            # Verify all containers stopped
            print("[TEST]   Verifying containers stopped...")
            for container in containers:
                container.container.stop.assert_called()
        print("[TEST] ✓ test_cleanup passed")


class TestPortPreallocation:
    """Test port pre-allocation functionality."""
    
    def test_preallocate_ports(self, mock_docker_client, tmp_path):
        """Test port pre-allocation for multiple containers."""
        print("\n[TEST] Running: test_preallocate_ports")
        logger.info("Testing port pre-allocation for multiple containers...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]):
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Pre-allocating ports for 3 containers...")
            port_tuples = manager._preallocate_ports(pool_size=3, base_env_id=0)
            
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
        logger.info("Testing pre-allocated ports are unique...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]):
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Pre-allocating ports for 4 containers...")
            port_tuples = manager._preallocate_ports(pool_size=4, base_env_id=0)
            
            # Collect all ports
            all_ports = []
            for server, emulator, grpc in port_tuples:
                all_ports.extend([server, emulator, grpc])
            
            # Verify all ports are unique
            print(f"[TEST]   Verifying {len(all_ports)} ports are unique...")
            assert len(all_ports) == len(set(all_ports))
        print("[TEST] ✓ test_preallocate_ports_unique passed")


class TestParallelPoolCreation:
    """Test parallel pool creation functionality."""
    
    @pytest.mark.asyncio
    async def test_create_container_with_ports(self, mock_docker_client, tmp_path):
        """Test creating container with pre-allocated ports."""
        print("\n[TEST] Running: test_create_container_with_ports")
        logger.info("Testing creating container with pre-allocated ports...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            # Pre-defined ports
            ports = (5000, 5574, 8574)
            
            print("[TEST]   Creating container with pre-allocated ports...")
            container = await manager._create_container_with_ports(
                env_id=0,
                ports=ports,
                sample_mode="random",
                snapshot="clean",
                train_task_family="android_world",
                val_task_family="android_world",
                initial_wait=1.0,  # Short wait for test
            )
            
            assert isinstance(container, ContainerInstance)
            assert container.server_port == 5000
            assert container.emulator_port == 5574
            assert container.grpc_port == 8574
            assert container.state == "ready"
        print("[TEST] ✓ test_create_container_with_ports passed")
    
    @pytest.mark.asyncio
    async def test_create_pool_parallel(self, mock_docker_client, tmp_path):
        """Test parallel pool creation."""
        print("\n[TEST] Running: test_create_pool_parallel")
        logger.info("Testing parallel pool creation...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock):
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Creating parallel pool of 3 containers (max_concurrent=2)...")
            containers = await manager.create_pool_parallel(
                pool_size=3,
                base_env_id=0,
                max_concurrent=2,
                initial_wait=1.0,  # Short wait for test
            )
            
            assert len(containers) == 3
            assert manager.available_queue is not None
            assert manager.available_queue.qsize() == 3
            
            # Verify pool config is stored
            assert manager._pool_config is not None
            assert manager._pool_config["initial_wait"] == 1.0
        print("[TEST] ✓ test_create_pool_parallel passed")
    
    @pytest.mark.asyncio
    async def test_create_pool_with_initial_wait(self, mock_docker_client, tmp_path):
        """Test pool creation with custom initial_wait."""
        print("\n[TEST] Running: test_create_pool_with_initial_wait")
        logger.info("Testing pool creation with custom initial_wait...")
        
        with patch('skyrl_agent.runtime.android.container_manager.psutil.net_connections', return_value=[]), \
             patch('skyrl_agent.runtime.android.container_manager.requests.get') as mock_get, \
             patch('skyrl_agent.runtime.android.container_manager.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            lock_file = tmp_path / "docker_port_allocation.lck"
            manager = ContainerManager(
                docker_image="androidworld:v8",
                temp_path=str(tmp_path),
                lock_file=lock_file,
            )
            manager.client = mock_docker_client
            
            print("[TEST]   Creating pool with initial_wait=30...")
            await manager.create_pool(
                pool_size=1,
                base_env_id=0,
                initial_wait=30.0,
            )
            
            # Verify initial_wait is stored in config
            assert manager._pool_config["initial_wait"] == 30.0
            
            # Verify asyncio.sleep was called with the correct value
            # The first call should be the initial wait
            sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
            assert 30.0 in sleep_calls
        print("[TEST] ✓ test_create_pool_with_initial_wait passed")
        print("\n" + "="*50)
        print("[TEST] All ContainerManager tests completed!")
        print("="*50)

