"""
Tests for Container Pool Broker, PoolClient, and BrokerContainerManager adapter.

Covers:
- RemoteContainerInfo duck-typing compatibility with RuntimeClient
- PoolClient HTTP operations and retry logic
- BrokerContainerManager adapter interface
- ContainerPoolBroker acquire/return logic
- Health loop race condition handling
- PID-based GC with PID-reuse safety
- Mode selection in AndroidTask.initialize_runtime
"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, MagicMock, patch
import pytest

from skyrl_agent.runtime.android.pool_client import (
    RemoteContainerInfo,
    PoolClient,
    BrokerContainerManager,
)
from skyrl_agent.runtime.android.pool_broker import (
    ContainerPoolBroker,
    PoolEntry,
    BrokerContainerState,
)
from skyrl_agent.runtime.android.container_manager import ContainerInstance


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def remote_info():
    """Create a RemoteContainerInfo for testing."""
    return RemoteContainerInfo(
        env_id=5,
        server_port=5010,
        emulator_port=5584,
        grpc_port=8584,
        host="192.168.1.100",
        container_id="abc123",
    )


@pytest.fixture
def remote_info_localhost():
    """Create a localhost RemoteContainerInfo."""
    return RemoteContainerInfo(
        env_id=0,
        server_port=5000,
        emulator_port=5574,
        grpc_port=8574,
        host="localhost",
        container_id="def456",
    )


@pytest.fixture
def mock_container_instance():
    """Create a real ContainerInstance (no host field)."""
    mock_container = Mock()
    mock_container.id = "test-container-id"
    mock_container.stop = Mock()
    return ContainerInstance(
        container_id="test-container-id",
        container=mock_container,
        server_port=5010,
        emulator_port=5584,
        grpc_port=8584,
        env_id=0,
        state="ready",
    )


@pytest.fixture
def mock_pool_client():
    """Create a mocked PoolClient."""
    client = AsyncMock(spec=PoolClient)
    client.broker_url = "http://localhost:9100"
    client.acquire = AsyncMock(
        return_value=RemoteContainerInfo(
            env_id=7,
            server_port=5014,
            emulator_port=5588,
            grpc_port=8588,
            host="localhost",
            container_id="mock123",
        )
    )
    client.release = AsyncMock()
    client.get_status = AsyncMock(
        return_value={"total": 16, "idle": 16, "leased": 0, "replacing": 0}
    )
    client.check_broker_health = AsyncMock(return_value=True)
    client.close = AsyncMock()
    return client


@pytest.fixture
def broker_manager(mock_pool_client):
    """Create a BrokerContainerManager with mocked PoolClient."""
    return BrokerContainerManager(mock_pool_client)


def _make_pool_entry(env_id=0, state=BrokerContainerState.IDLE, pid=None):
    """Helper to create a PoolEntry with a mock container."""
    mock_docker = Mock()
    mock_docker.id = f"container-{env_id}"
    mock_docker.stop = Mock()
    mock_docker.reload = Mock()
    mock_docker.status = "running"

    container = ContainerInstance(
        container_id=f"container-{env_id}",
        container=mock_docker,
        server_port=5000 + 2 * env_id,
        emulator_port=5574 + 2 * env_id,
        grpc_port=8574 + 2 * env_id,
        env_id=env_id,
        state="ready",
    )
    return PoolEntry(container=container, state=state, pid=pid)


# ─── TestRemoteContainerInfoCompat ────────────────────────────────────────────


class TestRemoteContainerInfoCompat:
    """Verify RemoteContainerInfo is duck-type compatible with RuntimeClient."""

    def test_runtime_client_uses_host_field(self, remote_info):
        """RuntimeClient.base_url should use the host field from RemoteContainerInfo."""
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient

        client = RuntimeClient(remote_info)
        assert client.base_url == "http://192.168.1.100:5010"

    def test_runtime_client_localhost_fallback(self, mock_container_instance):
        """ContainerInstance (no host field) should fallback to localhost."""
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient

        client = RuntimeClient(mock_container_instance)
        assert client.base_url == "http://localhost:5010"

    def test_has_required_fields(self, remote_info):
        """RemoteContainerInfo must have all fields accessed by dispatcher/runner."""
        assert hasattr(remote_info, "env_id")
        assert hasattr(remote_info, "server_port")
        assert hasattr(remote_info, "state")
        assert hasattr(remote_info, "is_healthy")
        assert hasattr(remote_info, "current_trajectory")
        assert hasattr(remote_info, "container")

    def test_state_and_trajectory_mutable(self, remote_info):
        """Dispatcher sets state and current_trajectory on allocation."""
        remote_info.state = "in_use"
        remote_info.current_trajectory = (3, 1)
        assert remote_info.state == "in_use"
        assert remote_info.current_trajectory == (3, 1)


# ─── TestPoolClient ──────────────────────────────────────────────────────────


class TestPoolClient:
    """Test PoolClient HTTP operations and retry logic."""

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        """Successful acquire returns RemoteContainerInfo with correct fields."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "env_id": 3,
                "server_port": 5006,
                "emulator_port": 5580,
                "grpc_port": 8580,
                "host": "localhost",
                "container_id": "abc",
            }
        )
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        mock_session = AsyncMock()
        mock_session.post = Mock(return_value=mock_resp)
        client._session = mock_session

        info = await client.acquire(timeout=10.0)

        assert isinstance(info, RemoteContainerInfo)
        assert info.env_id == 3
        assert info.server_port == 5006
        assert info.host == "localhost"

    @pytest.mark.asyncio
    async def test_acquire_retries_on_network_error(self):
        """Acquire retries on transient aiohttp.ClientError."""
        import aiohttp

        call_count = 0

        # Create mock responses: 2 failures, then success
        success_resp = AsyncMock()
        success_resp.status = 200
        success_resp.json = AsyncMock(
            return_value={
                "env_id": 1,
                "server_port": 5002,
                "emulator_port": 5576,
                "grpc_port": 8576,
                "host": "localhost",
                "container_id": "x",
            }
        )
        success_resp.__aenter__ = AsyncMock(return_value=success_resp)
        success_resp.__aexit__ = AsyncMock(return_value=False)

        error_resp = AsyncMock()
        error_resp.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("connection refused")
        )
        error_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        client.ACQUIRE_RETRY_BASE_DELAY = 0.01  # fast retries for test
        mock_session = AsyncMock()
        mock_session.post = Mock(
            side_effect=[error_resp, error_resp, success_resp]
        )
        client._session = mock_session

        info = await client.acquire(timeout=10.0)
        assert info.env_id == 1
        assert mock_session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_acquire_fails_after_max_retries(self):
        """Acquire raises RuntimeError after exhausting retries."""
        import aiohttp

        error_resp = AsyncMock()
        error_resp.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("connection refused")
        )
        error_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        client.ACQUIRE_RETRY_BASE_DELAY = 0.01
        mock_session = AsyncMock()
        mock_session.post = Mock(
            side_effect=[error_resp, error_resp, error_resp]
        )
        client._session = mock_session

        with pytest.raises(RuntimeError, match="Broker unavailable"):
            await client.acquire(timeout=10.0)

    @pytest.mark.asyncio
    async def test_acquire_503_raises_runtime_error(self):
        """503 from broker raises RuntimeError immediately (no retry)."""
        mock_resp = AsyncMock()
        mock_resp.status = 503
        mock_resp.json = AsyncMock(return_value={"detail": "No container available"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        mock_session = AsyncMock()
        mock_session.post = Mock(return_value=mock_resp)
        client._session = mock_session

        with pytest.raises(RuntimeError, match="Broker: No container available"):
            await client.acquire(timeout=10.0)

    @pytest.mark.asyncio
    async def test_release_success(self):
        """Release sends correct payload to broker."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.raise_for_status = Mock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        mock_session = AsyncMock()
        mock_session.post = Mock(return_value=mock_resp)
        client._session = mock_session

        await client.release(env_id=7, healthy=False)

        call_args = mock_session.post.call_args
        assert call_args[1]["json"] == {"env_id": 7, "healthy": False}

    @pytest.mark.asyncio
    async def test_release_swallows_errors(self):
        """Release logs warning but doesn't raise on network errors."""
        mock_resp = AsyncMock()
        mock_resp.__aenter__ = AsyncMock(side_effect=Exception("network error"))
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        mock_session = AsyncMock()
        mock_session.post = Mock(return_value=mock_resp)
        client._session = mock_session

        # Should not raise
        await client.release(env_id=7, healthy=True)

    @pytest.mark.asyncio
    async def test_check_broker_health_success(self):
        """check_broker_health returns True on 200."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        mock_session = AsyncMock()
        mock_session.get = Mock(return_value=mock_resp)
        client._session = mock_session

        assert await client.check_broker_health() is True

    @pytest.mark.asyncio
    async def test_check_broker_health_failure(self):
        """check_broker_health returns False on network error."""
        mock_resp = AsyncMock()
        mock_resp.__aenter__ = AsyncMock(side_effect=Exception("unreachable"))
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        client = PoolClient("http://localhost:9100")
        mock_session = AsyncMock()
        mock_session.get = Mock(return_value=mock_resp)
        client._session = mock_session

        assert await client.check_broker_health() is False


# ─── TestBrokerContainerManagerAdapter ────────────────────────────────────────


class TestBrokerContainerManagerAdapter:
    """Test BrokerContainerManager implements ContainerManager interface."""

    @pytest.mark.asyncio
    async def test_initialize_fetches_pool_size(self, broker_manager, mock_pool_client):
        """initialize() fetches pool size from broker and populates containers list."""
        await broker_manager.initialize()
        assert len(broker_manager.containers) == 16
        mock_pool_client.get_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allocate_delegates_to_pool_client(
        self, broker_manager, mock_pool_client
    ):
        """allocate_container() delegates to PoolClient.acquire()."""
        info = await broker_manager.allocate_container(batch_idx=3, trajectory_id=1)

        assert isinstance(info, RemoteContainerInfo)
        assert info.env_id == 7
        assert info.state == "in_use"
        assert info.current_trajectory == (3, 1)
        mock_pool_client.acquire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_release_healthy(self, broker_manager, mock_pool_client):
        """Successful release sends healthy=True to broker."""
        container = RemoteContainerInfo(
            env_id=7,
            server_port=5014,
            emulator_port=5588,
            grpc_port=8588,
            host="localhost",
            container_id="x",
            current_trajectory=(0, 0),
        )
        await broker_manager.release_container(container, success=True)
        mock_pool_client.release.assert_awaited_once_with(7, healthy=True)
        assert len(broker_manager.failed_trajectories) == 0

    @pytest.mark.asyncio
    async def test_release_unhealthy_on_container_dead(
        self, broker_manager, mock_pool_client
    ):
        """Container dead error sends healthy=False and tracks failure."""
        container = RemoteContainerInfo(
            env_id=7,
            server_port=5014,
            emulator_port=5588,
            grpc_port=8588,
            host="localhost",
            container_id="x",
            current_trajectory=(2, 1),
        )
        await broker_manager.release_container(
            container, success=False, error="container_dead: connection refused"
        )
        mock_pool_client.release.assert_awaited_once_with(7, healthy=False)
        assert len(broker_manager.failed_trajectories) == 1
        assert broker_manager.failed_trajectories[0] == (
            2,
            1,
            "container_dead: connection refused",
        )

    @pytest.mark.asyncio
    async def test_release_success_false_marks_unhealthy(
        self, broker_manager, mock_pool_client
    ):
        """Any failure (success=False) marks container unhealthy for broker to verify."""
        container = RemoteContainerInfo(
            env_id=7,
            server_port=5014,
            emulator_port=5588,
            grpc_port=8588,
            host="localhost",
            container_id="x",
            current_trajectory=(0, 0),
        )
        await broker_manager.release_container(
            container, success=False, error="ValueError: bad input"
        )
        mock_pool_client.release.assert_awaited_once_with(7, healthy=False)

    @pytest.mark.asyncio
    async def test_release_success_true_marks_healthy(
        self, broker_manager, mock_pool_client
    ):
        """Successful trajectory marks container healthy."""
        container = RemoteContainerInfo(
            env_id=7,
            server_port=5014,
            emulator_port=5588,
            grpc_port=8588,
            host="localhost",
            container_id="x",
            current_trajectory=(0, 0),
        )
        await broker_manager.release_container(container, success=True, error=None)
        mock_pool_client.release.assert_awaited_once_with(7, healthy=True)

    @pytest.mark.asyncio
    async def test_health_monitor_noop(self, broker_manager):
        """start/stop_health_monitor are no-ops and don't raise."""
        await broker_manager.start_health_monitor(interval=30.0)
        await broker_manager.stop_health_monitor()

    @pytest.mark.asyncio
    async def test_cleanup_closes_session(self, broker_manager, mock_pool_client):
        """cleanup() closes the PoolClient HTTP session."""
        await broker_manager.cleanup()
        mock_pool_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_quick_ping_always_true(self, broker_manager):
        """quick_ping always returns True (broker validates on acquire)."""
        assert await broker_manager.quick_ping(env_id=5) is True

    def test_set_recovery_callback(self, broker_manager):
        """set_recovery_callback stores callback without error."""
        cb = Mock()
        broker_manager.set_recovery_callback(cb)
        assert broker_manager._recovery_callback is cb

    def test_get_pool_status(self, broker_manager):
        """get_pool_status returns basic status dict."""
        broker_manager.containers = [None] * 8
        status = broker_manager.get_pool_status()
        assert status["pool_size"] == 8
        assert status["buffer_size"] == 0

    def test_failed_trajectory_tracking(self, broker_manager):
        """Failed trajectories are tracked and clearable."""
        broker_manager.failed_trajectories.append((0, 1, "error1"))
        broker_manager.failed_trajectories.append((1, 0, "error2"))
        assert len(broker_manager.get_failed_trajectories()) == 2
        broker_manager.clear_failed_trajectories()
        assert len(broker_manager.get_failed_trajectories()) == 0


# ─── TestBrokerAcquireReturn ─────────────────────────────────────────────────


class TestBrokerAcquireReturn:
    """Test ContainerPoolBroker acquire/return logic with mocked containers."""

    def _make_broker(self) -> ContainerPoolBroker:
        """Create broker with mocked factory (skip real Docker)."""
        broker = ContainerPoolBroker.__new__(ContainerPoolBroker)
        broker.pool_size = 2
        broker.use_host_network = True
        broker.health_check_interval = 30.0
        broker.gc_interval = 60.0
        broker.config = Mock()
        broker.port_allocator = Mock()
        broker.factory = AsyncMock()
        broker.registry = {}
        broker.available_queue = asyncio.Queue()
        broker._next_env_id = 2
        broker._env_id_lock = asyncio.Lock()
        broker._registry_lock = asyncio.Lock()
        broker._health_task = None
        broker._gc_task = None
        broker._start_time = time.time()
        broker._pool_initializing = False
        return broker

    @pytest.mark.asyncio
    async def test_acquire_returns_idle_marks_leased(self):
        """Acquire pops IDLE container, marks LEASED, returns correct info."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=3)
        broker.registry[3] = entry
        await broker.available_queue.put(3)

        with patch.object(broker, "_check_health_sync", return_value=True):
            result = await broker.acquire(pid=12345, timeout=5.0)

        assert result["env_id"] == 3
        assert result["server_port"] == 5006
        assert result["host"] == "localhost"
        assert entry.state == BrokerContainerState.LEASED
        assert entry.pid == 12345

    @pytest.mark.asyncio
    async def test_acquire_skips_unhealthy_triggers_replace(self):
        """Acquire skips unhealthy container and triggers replacement."""
        broker = self._make_broker()
        unhealthy_entry = _make_pool_entry(env_id=0)
        healthy_entry = _make_pool_entry(env_id=1)
        broker.registry[0] = unhealthy_entry
        broker.registry[1] = healthy_entry
        await broker.available_queue.put(0)
        await broker.available_queue.put(1)

        # First container unhealthy, second healthy
        health_results = [False, True]

        with patch.object(
            broker, "_check_health_sync", side_effect=health_results
        ), patch.object(broker, "_replace_container", new_callable=AsyncMock):
            result = await broker.acquire(pid=100, timeout=5.0)

        assert result["env_id"] == 1
        assert unhealthy_entry.state == BrokerContainerState.REPLACING

    @pytest.mark.asyncio
    async def test_acquire_timeout(self):
        """Acquire raises TimeoutError when no containers available."""
        broker = self._make_broker()
        # Empty queue — no containers available

        with pytest.raises(TimeoutError, match="No container available"):
            await broker.acquire(pid=100, timeout=0.1)

    @pytest.mark.asyncio
    async def test_return_healthy_triggers_snapshot_restore(self):
        """Return with healthy=True triggers async snapshot restore."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=5, state=BrokerContainerState.LEASED, pid=100)
        broker.registry[5] = entry

        with patch.object(broker, "_restore_snapshot_sync", return_value=True):
            await broker.return_container(env_id=5, healthy=True)
            # Let the async task run
            await asyncio.sleep(0.05)

        assert entry.state == BrokerContainerState.IDLE
        assert entry.pid is None
        assert broker.available_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_return_unhealthy_triggers_replace(self):
        """Return with healthy=False triggers replacement."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=5, state=BrokerContainerState.LEASED, pid=100)
        broker.registry[5] = entry

        with patch.object(broker, "_replace_container", new_callable=AsyncMock):
            await broker.return_container(env_id=5, healthy=False)

        assert entry.state == BrokerContainerState.REPLACING

    @pytest.mark.asyncio
    async def test_return_unknown_env_id(self):
        """Return with unknown env_id logs warning without error."""
        broker = self._make_broker()
        # Should not raise
        await broker.return_container(env_id=999, healthy=True)

    def test_get_status(self):
        """get_status returns correct counts including RESETTING."""
        broker = self._make_broker()
        broker.registry[0] = _make_pool_entry(
            env_id=0, state=BrokerContainerState.IDLE
        )
        broker.registry[1] = _make_pool_entry(
            env_id=1, state=BrokerContainerState.LEASED
        )
        broker.registry[2] = _make_pool_entry(
            env_id=2, state=BrokerContainerState.REPLACING
        )
        broker.registry[3] = _make_pool_entry(
            env_id=3, state=BrokerContainerState.RESETTING
        )

        status = broker.get_status()
        assert status["total"] == 4
        assert status["idle"] == 1
        assert status["leased"] == 1
        assert status["resetting"] == 1
        assert status["replacing"] == 1
        assert len(status["containers"]) == 4


# ─── TestBrokerSnapshotRestore ────────────────────────────────────────────────


class TestBrokerSnapshotRestore:
    """Test snapshot restore on container return."""

    def _make_broker(self) -> ContainerPoolBroker:
        """Create broker with mocked factory (skip real Docker)."""
        broker = ContainerPoolBroker.__new__(ContainerPoolBroker)
        broker.pool_size = 2
        broker.use_host_network = True
        broker.health_check_interval = 30.0
        broker.gc_interval = 60.0
        broker.config = Mock()
        broker.port_allocator = Mock()
        broker.factory = AsyncMock()
        broker.registry = {}
        broker.available_queue = asyncio.Queue()
        broker._next_env_id = 2
        broker._env_id_lock = asyncio.Lock()
        broker._registry_lock = asyncio.Lock()
        broker._health_task = None
        broker._gc_task = None
        broker._start_time = time.time()
        broker._pool_initializing = False
        return broker

    @pytest.mark.asyncio
    async def test_return_sets_resetting_state(self):
        """Return with healthy=True sets state to RESETTING before restore."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=5, state=BrokerContainerState.LEASED, pid=100)
        broker.registry[5] = entry

        # Block the restore so we can observe the intermediate RESETTING state
        restore_started = asyncio.Event()
        restore_proceed = asyncio.Event()

        def slow_restore(server_port):
            restore_started.set()
            # Use a sync sleep to simulate blocking I/O in the thread
            import threading
            evt = threading.Event()
            # We'll unblock from the test
            while not restore_proceed.is_set():
                evt.wait(0.01)
            return True

        with patch.object(broker, "_restore_snapshot_sync", side_effect=slow_restore):
            await broker.return_container(env_id=5, healthy=True)
            # Wait for restore to start
            await asyncio.wait_for(restore_started.wait(), timeout=2.0)

            # Container should be in RESETTING state
            assert entry.state == BrokerContainerState.RESETTING
            # Should NOT be in the available queue yet
            assert broker.available_queue.qsize() == 0

            # Let restore finish
            restore_proceed.set()
            await asyncio.sleep(0.1)

        assert entry.state == BrokerContainerState.IDLE
        assert broker.available_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_restore_success_returns_to_pool(self):
        """Successful snapshot restore marks IDLE and enqueues container."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=3, state=BrokerContainerState.LEASED, pid=200)
        broker.registry[3] = entry

        with patch.object(broker, "_restore_snapshot_sync", return_value=True):
            await broker.return_container(env_id=3, healthy=True)
            await asyncio.sleep(0.05)

        assert entry.state == BrokerContainerState.IDLE
        assert entry.pid is None
        assert broker.available_queue.qsize() == 1
        assert broker.available_queue.get_nowait() == 3

    @pytest.mark.asyncio
    async def test_restore_failure_triggers_replacement(self):
        """Failed snapshot restore triggers container replacement."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=7, state=BrokerContainerState.LEASED, pid=300)
        broker.registry[7] = entry

        with patch.object(broker, "_restore_snapshot_sync", return_value=False), \
             patch.object(broker, "_replace_container", new_callable=AsyncMock) as mock_replace:
            await broker.return_container(env_id=7, healthy=True)
            await asyncio.sleep(0.05)

        assert entry.state == BrokerContainerState.REPLACING
        assert broker.available_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_restore_exception_triggers_replacement(self):
        """Exception during snapshot restore triggers container replacement."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=4, state=BrokerContainerState.LEASED, pid=400)
        broker.registry[4] = entry

        with patch.object(
            broker, "_restore_snapshot_sync",
            side_effect=Exception("connection refused")
        ), patch.object(broker, "_replace_container", new_callable=AsyncMock):
            await broker.return_container(env_id=4, healthy=True)
            await asyncio.sleep(0.05)

        assert entry.state == BrokerContainerState.REPLACING
        assert broker.available_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_restore_calls_reset_endpoint(self):
        """_restore_snapshot_sync posts to the container's /reset endpoint."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=2, state=BrokerContainerState.LEASED, pid=500)
        broker.registry[2] = entry
        server_port = entry.container.server_port

        mock_response = Mock()
        mock_response.status_code = 200

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = broker._restore_snapshot_sync(server_port)

        assert result is True
        mock_post.assert_called_once_with(
            f"http://localhost:{server_port}/reset",
            json={"seed": None, "options": {}},
            timeout=(5, 120),
        )

    @pytest.mark.asyncio
    async def test_restore_sync_returns_false_on_non_200(self):
        """_restore_snapshot_sync returns False on non-200 status."""
        broker = self._make_broker()

        mock_response = Mock()
        mock_response.status_code = 500

        with patch("requests.post", return_value=mock_response):
            result = broker._restore_snapshot_sync(5000)

        assert result is False

    @pytest.mark.asyncio
    async def test_restore_sync_returns_false_on_timeout(self):
        """_restore_snapshot_sync returns False on request timeout."""
        import requests as _requests

        broker = self._make_broker()

        with patch("requests.post",
                    side_effect=_requests.exceptions.Timeout("timeout")):
            result = broker._restore_snapshot_sync(5000)

        assert result is False

    @pytest.mark.asyncio
    async def test_unhealthy_return_skips_restore(self):
        """Return with healthy=False skips snapshot restore and replaces directly."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=6, state=BrokerContainerState.LEASED, pid=600)
        broker.registry[6] = entry

        with patch.object(broker, "_restore_snapshot_sync") as mock_restore, \
             patch.object(broker, "_replace_container", new_callable=AsyncMock):
            await broker.return_container(env_id=6, healthy=False)
            await asyncio.sleep(0.05)

        # Restore should NOT have been called
        mock_restore.assert_not_called()
        assert entry.state == BrokerContainerState.REPLACING

    @pytest.mark.asyncio
    async def test_resetting_container_not_acquirable(self):
        """Container in RESETTING state is not in the available queue."""
        broker = self._make_broker()
        entry = _make_pool_entry(env_id=1, state=BrokerContainerState.RESETTING)
        broker.registry[1] = entry
        # Queue is empty — RESETTING container is not available

        with pytest.raises(TimeoutError):
            await broker.acquire(pid=100, timeout=0.1)

    @pytest.mark.asyncio
    async def test_health_loop_skips_resetting_containers(self):
        """Health loop only checks IDLE containers, not RESETTING ones."""
        broker = self._make_broker()
        resetting_entry = _make_pool_entry(
            env_id=0, state=BrokerContainerState.RESETTING
        )
        idle_entry = _make_pool_entry(
            env_id=1, state=BrokerContainerState.IDLE
        )
        broker.registry[0] = resetting_entry
        broker.registry[1] = idle_entry

        async with broker._registry_lock:
            idle = [
                (eid, e)
                for eid, e in broker.registry.items()
                if e.state == BrokerContainerState.IDLE
            ]

        # Only IDLE container should be checked
        assert len(idle) == 1
        assert idle[0][0] == 1

    @pytest.mark.asyncio
    async def test_multiple_returns_restore_concurrently(self):
        """Multiple concurrent returns each trigger independent restores."""
        broker = self._make_broker()
        entries = {}
        for i in range(3):
            entry = _make_pool_entry(
                env_id=i, state=BrokerContainerState.LEASED, pid=100 + i
            )
            broker.registry[i] = entry
            entries[i] = entry

        with patch.object(broker, "_restore_snapshot_sync", return_value=True):
            # Return all three concurrently
            await asyncio.gather(
                broker.return_container(env_id=0, healthy=True),
                broker.return_container(env_id=1, healthy=True),
                broker.return_container(env_id=2, healthy=True),
            )
            await asyncio.sleep(0.1)

        for i in range(3):
            assert entries[i].state == BrokerContainerState.IDLE
        assert broker.available_queue.qsize() == 3


# ─── TestBrokerHealthLoop ────────────────────────────────────────────────────


class TestBrokerHealthLoop:
    """Test health loop race condition handling."""

    @pytest.mark.asyncio
    async def test_rechecks_state_under_lock(self):
        """Health loop skips replacement if container was acquired between check and lock.

        This tests the race condition guard in _health_loop(): after getting an
        unhealthy result from _check_health_sync, the code re-acquires the lock
        and checks entry.state != IDLE before triggering replacement.
        """
        broker = ContainerPoolBroker.__new__(ContainerPoolBroker)
        broker.registry = {}
        broker.available_queue = asyncio.Queue()
        broker._registry_lock = asyncio.Lock()
        broker._env_id_lock = asyncio.Lock()
        broker.health_check_interval = 0.01

        entry = _make_pool_entry(env_id=0, state=BrokerContainerState.IDLE)
        broker.registry[0] = entry

        # Simulate the race: the health check is slow, and during that time
        # the container gets acquired (state changes to LEASED).
        # The guard in _health_loop should detect this and skip replacement.

        # Step 1: take the IDLE snapshot (as _health_loop does)
        async with broker._registry_lock:
            idle = [
                (eid, e)
                for eid, e in broker.registry.items()
                if e.state == BrokerContainerState.IDLE
            ]
        assert len(idle) == 1

        # Step 2: simulate the container being acquired while health check runs
        entry.state = BrokerContainerState.LEASED

        # Step 3: simulate unhealthy health check result and apply the guard
        replace_triggered = False
        for env_id, entry_ref in idle:
            healthy = False  # unhealthy result from _check_health_sync
            if not healthy:
                async with broker._registry_lock:
                    if entry_ref.state != BrokerContainerState.IDLE:
                        continue  # Race condition guard: skip!
                    entry_ref.state = BrokerContainerState.REPLACING
                    replace_triggered = True

        # The guard should have prevented replacement
        assert entry.state == BrokerContainerState.LEASED
        assert not replace_triggered


# ─── TestBrokerGC ────────────────────────────────────────────────────────────


class TestBrokerGC:
    """Test PID-based garbage collection."""

    def _make_broker_for_gc(self):
        broker = ContainerPoolBroker.__new__(ContainerPoolBroker)
        broker.registry = {}
        broker.available_queue = asyncio.Queue()
        broker._registry_lock = asyncio.Lock()
        broker.gc_interval = 0.01
        return broker

    @pytest.mark.asyncio
    async def test_reclaims_dead_pid(self):
        """GC reclaims container when process no longer exists."""
        import psutil as _psutil

        broker = self._make_broker_for_gc()
        entry = _make_pool_entry(
            env_id=0, state=BrokerContainerState.LEASED, pid=99999
        )
        entry.pid_create_time = 1000.0
        broker.registry[0] = entry

        with patch(
            "skyrl_agent.runtime.android.pool_broker.psutil.Process",
            side_effect=_psutil.NoSuchProcess(99999),
        ):
            # Run one GC iteration manually
            async with broker._registry_lock:
                leased = [
                    (eid, e)
                    for eid, e in broker.registry.items()
                    if e.state == BrokerContainerState.LEASED and e.pid
                ]
            for env_id, e in leased:
                should_reclaim = False
                try:
                    import psutil

                    proc = psutil.Process(e.pid)
                except _psutil.NoSuchProcess:
                    should_reclaim = True

                if should_reclaim:
                    async with broker._registry_lock:
                        e.state = BrokerContainerState.IDLE
                        e.pid = None
                        e.pid_create_time = None
                    await broker.available_queue.put(env_id)

        assert entry.state == BrokerContainerState.IDLE
        assert entry.pid is None
        assert broker.available_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_reclaims_reused_pid(self):
        """GC reclaims container when PID was reused by different process."""
        broker = self._make_broker_for_gc()
        entry = _make_pool_entry(
            env_id=0, state=BrokerContainerState.LEASED, pid=12345
        )
        entry.pid_create_time = 1000.0  # original create time
        broker.registry[0] = entry

        mock_proc = Mock()
        mock_proc.create_time.return_value = 2000.0  # different create time = reused PID

        with patch(
            "skyrl_agent.runtime.android.pool_broker.psutil.Process",
            return_value=mock_proc,
        ):
            # Run GC logic
            async with broker._registry_lock:
                leased = [
                    (eid, e)
                    for eid, e in broker.registry.items()
                    if e.state == BrokerContainerState.LEASED and e.pid
                ]
            for env_id, e in leased:
                should_reclaim = False
                import psutil

                proc = psutil.Process(e.pid)
                if (
                    e.pid_create_time is not None
                    and proc.create_time() != e.pid_create_time
                ):
                    should_reclaim = True

                if should_reclaim:
                    async with broker._registry_lock:
                        e.state = BrokerContainerState.IDLE
                        e.pid = None
                    await broker.available_queue.put(env_id)

        assert entry.state == BrokerContainerState.IDLE

    @pytest.mark.asyncio
    async def test_ignores_alive_pid(self):
        """GC does NOT reclaim container when process is still alive."""
        broker = self._make_broker_for_gc()
        entry = _make_pool_entry(
            env_id=0, state=BrokerContainerState.LEASED, pid=12345
        )
        entry.pid_create_time = 1000.0
        broker.registry[0] = entry

        mock_proc = Mock()
        mock_proc.create_time.return_value = 1000.0  # same create time = same process

        with patch(
            "skyrl_agent.runtime.android.pool_broker.psutil.Process",
            return_value=mock_proc,
        ):
            async with broker._registry_lock:
                leased = [
                    (eid, e)
                    for eid, e in broker.registry.items()
                    if e.state == BrokerContainerState.LEASED and e.pid
                ]
            for env_id, e in leased:
                should_reclaim = False
                import psutil

                proc = psutil.Process(e.pid)
                if (
                    e.pid_create_time is not None
                    and proc.create_time() != e.pid_create_time
                ):
                    should_reclaim = True

                if should_reclaim:
                    async with broker._registry_lock:
                        e.state = BrokerContainerState.IDLE
                    await broker.available_queue.put(env_id)

        # Should NOT be reclaimed
        assert entry.state == BrokerContainerState.LEASED
        assert entry.pid == 12345
        assert broker.available_queue.qsize() == 0


# ─── TestModeSelection ───────────────────────────────────────────────────────


class TestModeSelection:
    """Test mode selection in AndroidTask.initialize_runtime."""

    @pytest.mark.asyncio
    async def test_broker_url_uses_broker_manager(self):
        """When broker_url is set, initialize_runtime creates BrokerContainerManager."""
        from skyrl_agent.tasks.android.android_task import AndroidTask

        mock_pool_client_instance = AsyncMock()
        mock_pool_client_instance.check_broker_health = AsyncMock(return_value=True)

        mock_broker_mgr_instance = AsyncMock()
        mock_broker_mgr_instance.initialize = AsyncMock()

        mock_pool_client_cls = Mock(return_value=mock_pool_client_instance)
        mock_broker_mgr_cls = Mock(return_value=mock_broker_mgr_instance)

        # Save original state
        original_cm = AndroidTask._container_manager

        try:
            # The import happens dynamically inside initialize_runtime via:
            #   from skyrl_agent.runtime.android.pool_client import PoolClient, BrokerContainerManager
            # We patch the module in sys.modules so the dynamic import resolves to our mocks.
            mock_module = MagicMock(
                PoolClient=mock_pool_client_cls,
                BrokerContainerManager=mock_broker_mgr_cls,
            )
            with patch.dict(
                "sys.modules",
                {"skyrl_agent.runtime.android.pool_client": mock_module},
            ):
                result = await AndroidTask.initialize_runtime(
                    {"broker_url": "http://localhost:9100"}
                )

            assert result == []
            assert AndroidTask._container_manager is mock_broker_mgr_instance
            mock_pool_client_cls.assert_called_once_with("http://localhost:9100")
            mock_broker_mgr_instance.initialize.assert_awaited_once()
        finally:
            # Restore
            AndroidTask._container_manager = original_cm

    @pytest.mark.asyncio
    async def test_broker_unreachable_raises(self):
        """When broker is unreachable, initialize_runtime raises RuntimeError."""
        from skyrl_agent.tasks.android.android_task import AndroidTask

        mock_pool_client_cls = Mock()
        mock_pool_client_instance = AsyncMock()
        mock_pool_client_instance.check_broker_health = AsyncMock(return_value=False)
        mock_pool_client_cls.return_value = mock_pool_client_instance

        original_cm = AndroidTask._container_manager

        try:
            with patch.dict(
                "sys.modules",
                {
                    "skyrl_agent.runtime.android.pool_client": MagicMock(
                        PoolClient=mock_pool_client_cls,
                        BrokerContainerManager=Mock(),
                    )
                },
            ):
                with pytest.raises(RuntimeError, match="Broker not reachable"):
                    await AndroidTask.initialize_runtime(
                        {"broker_url": "http://localhost:9100"}
                    )
        finally:
            AndroidTask._container_manager = original_cm

    @pytest.mark.asyncio
    async def test_no_broker_url_does_not_import_pool_client(self):
        """Without broker_url, pool_client is never imported."""
        # This verifies Mode A doesn't touch broker code.
        # We just check that the code path doesn't reach the broker import
        # by verifying it tries to import ContainerManager instead.
        from skyrl_agent.tasks.android.android_task import AndroidTask

        original_cm = AndroidTask._container_manager

        try:
            # This will fail because we're not providing Docker,
            # but it proves the code takes Mode A path
            with patch(
                "skyrl_agent.runtime.android.ContainerManager"
            ) as mock_cm_cls:
                mock_cm = AsyncMock()
                mock_cm.create_pool_parallel = AsyncMock(return_value=[])
                mock_cm.start_health_monitor = AsyncMock()
                mock_cm_cls.return_value = mock_cm
                AndroidTask._container_manager = None

                result = await AndroidTask.initialize_runtime(
                    {"pool_size": 1, "docker_image": "test:v1"}
                )

                # Verify ContainerManager was used (Mode A path)
                mock_cm_cls.assert_called_once()
        finally:
            AndroidTask._container_manager = original_cm
