"""
Pool Client + Broker Adapter — remote container management via HTTP broker.

Used by experiment processes when broker_url is configured.
BrokerContainerManager implements the same interface as ContainerManager,
so the dispatcher and runner work unchanged in both modes.
"""

import os
import asyncio
import aiohttp
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass
from loguru import logger


@dataclass
class RemoteContainerInfo:
    """
    Container info returned by the broker.

    Duck-typed compatible with ContainerInstance — RuntimeClient reads
    .server_port and .host (via getattr fallback), so this works
    as a drop-in without modifying RuntimeClient or ContainerInstance.
    """

    env_id: int
    server_port: int
    emulator_port: int
    grpc_port: int
    host: str
    container_id: str
    # Fields that RuntimeClient or dispatcher may access:
    state: str = "in_use"
    is_healthy: bool = True
    container: Any = None  # Not available remotely
    last_health_check: float = 0.0
    restart_count: int = 0
    current_trajectory: Optional[tuple] = None


class PoolClient:
    """
    HTTP client for the Container Pool Broker.

    Provides acquire()/release() for BrokerContainerManager to delegate to.
    Includes retry logic for transient broker connection errors.
    """

    ACQUIRE_RETRIES = 3
    ACQUIRE_RETRY_BASE_DELAY = 1.0
    RELEASE_RETRIES = 3
    RELEASE_RETRY_BASE_DELAY = 1.0
    RELEASE_TIMEOUT = 30.0  # seconds; must exceed broker's health-check time

    def __init__(self, broker_url: str):
        self.broker_url = broker_url.rstrip("/")
        self.pid = os.getpid()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def acquire(self, timeout: float = 300.0) -> RemoteContainerInfo:
        """Acquire a container from the broker. Retries on transient network errors."""
        await self._ensure_session()

        last_error = None
        for attempt in range(self.ACQUIRE_RETRIES):
            try:
                async with self._session.post(
                    f"{self.broker_url}/acquire",
                    json={"pid": self.pid, "timeout": timeout},
                    timeout=aiohttp.ClientTimeout(total=timeout + 10),
                ) as resp:
                    if resp.status == 503:
                        data = await resp.json()
                        raise RuntimeError(
                            f"Broker: {data.get('detail', 'timeout')}"
                        )
                    resp.raise_for_status()
                    data = await resp.json()

                info = RemoteContainerInfo(
                    env_id=data["env_id"],
                    server_port=data["server_port"],
                    emulator_port=data["emulator_port"],
                    grpc_port=data["grpc_port"],
                    host=data.get("host", "localhost"),
                    container_id=data.get("container_id", ""),
                )
                logger.debug(f"Acquired env{info.env_id} from broker")
                return info

            except aiohttp.ClientError as e:
                last_error = e
                if attempt < self.ACQUIRE_RETRIES - 1:
                    delay = self.ACQUIRE_RETRY_BASE_DELAY * (attempt + 1)
                    logger.warning(
                        f"Broker connection error (attempt {attempt + 1}/"
                        f"{self.ACQUIRE_RETRIES}), retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"Broker unavailable at {self.broker_url} after "
            f"{self.ACQUIRE_RETRIES} attempts: {last_error}"
        )

    async def release(self, env_id: int, healthy: bool = True):
        """Return a container to the broker. Retries on transient errors."""
        await self._ensure_session()

        for attempt in range(self.RELEASE_RETRIES):
            try:
                async with self._session.post(
                    f"{self.broker_url}/return",
                    json={"env_id": env_id, "healthy": healthy},
                    timeout=aiohttp.ClientTimeout(total=self.RELEASE_TIMEOUT),
                ) as resp:
                    resp.raise_for_status()
                logger.debug(f"Returned env{env_id} to broker (healthy={healthy})")
                return
            except Exception as e:
                if attempt < self.RELEASE_RETRIES - 1:
                    delay = self.RELEASE_RETRY_BASE_DELAY * (attempt + 1)
                    logger.warning(
                        f"Failed to return env{env_id} to broker (attempt "
                        f"{attempt + 1}/{self.RELEASE_RETRIES}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Failed to return env{env_id} to broker after "
                        f"{self.RELEASE_RETRIES} attempts: {e}. "
                        f"Container may be leaked — broker GC will reclaim it."
                    )

    async def get_status(self) -> Dict[str, Any]:
        """Get broker pool status."""
        await self._ensure_session()
        async with self._session.get(
            f"{self.broker_url}/status",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def check_broker_health(self) -> bool:
        """Check if broker is reachable."""
        try:
            await self._ensure_session()
            async with self._session.get(
                f"{self.broker_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


class BrokerContainerManager:
    """
    Adapter: same interface as ContainerManager, delegates to broker via PoolClient.

    The dispatcher calls allocate_container()/release_container() on this object
    exactly as it would on a real ContainerManager. Internally, these become
    HTTP acquire/return calls to the broker.

    This eliminates the need to modify the dispatcher or runner code.
    """

    def __init__(self, pool_client: PoolClient, pool_size: Optional[int] = None):
        self._client = pool_client
        self._requested_pool_size = pool_size
        self.containers: List[RemoteContainerInfo] = []
        self.backup_containers: List = []
        self.failed_trajectories: List[Tuple[int, int, str]] = []
        self._recovery_callback: Optional[Callable] = None

    async def initialize(self):
        """Connect to broker and set local pool size.

        Uses the per-experiment pool_size passed at construction (from yaml env.pool_size)
        rather than the broker's total, so the dispatcher only spawns the correct number
        of workers for this experiment.
        """
        status = await self._client.get_status()
        broker_total = status.get("total", 0)
        pool_size = self._requested_pool_size or broker_total
        self.containers = [None] * pool_size
        logger.info(
            f"BrokerContainerManager: connected, broker_total={broker_total}, "
            f"local_pool_size={pool_size}"
        )

    async def allocate_container(
        self,
        batch_idx: Optional[int] = None,
        trajectory_id: Optional[int] = None,
    ) -> RemoteContainerInfo:
        """Acquire a container from the broker."""
        info = await self._client.acquire()
        info.state = "in_use"
        info.current_trajectory = (batch_idx, trajectory_id)
        return info

    async def release_container(
        self,
        container: RemoteContainerInfo,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """Return a container to the broker."""
        is_healthy = success and ("container_dead" not in (error or ""))
        await self._client.release(container.env_id, healthy=is_healthy)

        if not success and error:
            batch_idx = (
                container.current_trajectory[0]
                if container.current_trajectory
                else 0
            )
            traj_id = (
                container.current_trajectory[1]
                if container.current_trajectory
                else 0
            )
            self.failed_trajectories.append((batch_idx, traj_id, error))

    async def start_health_monitor(self, interval: float = 30.0):
        """No-op: broker handles health monitoring."""
        pass

    async def stop_health_monitor(self):
        """No-op: broker handles health monitoring."""
        pass

    async def cleanup(self):
        """Close HTTP session. Containers stay alive in broker."""
        await self._client.close()

    async def quick_ping(self, env_id: int, **kwargs) -> bool:
        """Broker validates health on acquire; always return True here."""
        return True

    def set_recovery_callback(self, callback: Optional[Callable] = None):
        """No-op: broker handles recovery."""
        self._recovery_callback = callback

    def get_pool_status(self) -> Dict[str, Any]:
        """Return basic pool status."""
        return {
            "pool_size": len(self.containers),
            "buffer_size": 0,
            "healthy": len(self.containers),
            "unhealthy": 0,
            "idle": 0,
            "in_use": len(self.containers),
            "failed_trajectories": len(self.failed_trajectories),
        }

    def get_failed_trajectories(self) -> List[Tuple[int, int, str]]:
        return list(self.failed_trajectories)

    def clear_failed_trajectories(self):
        self.failed_trajectories.clear()

    def print_batch_summary(self, total_trajectories: int):
        failed = len(self.failed_trajectories)
        succeeded = total_trajectories - failed
        logger.info(
            f"Batch: {succeeded}/{total_trajectories} succeeded, {failed} failed"
        )

    async def mark_container_unhealthy_async(self, env_id: int):
        """Release container as unhealthy to broker."""
        await self._client.release(env_id, healthy=False)
