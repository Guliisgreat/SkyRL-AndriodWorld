"""
Container Pool Broker — standalone FastAPI server managing a shared container pool.

Usage:
    python -m skyrl_agent.runtime.android.pool_broker \\
        --pool-size 24 \\
        --docker-image androidworld:v8 \\
        --port 9100 \\
        --base-env-id 0

Containers are pre-created at startup and reused across experiments.
Each task acquires/returns individual containers via HTTP API.
"""

import os
import time
import asyncio
import argparse
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager

import docker as docker_lib

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger

try:
    from skyrl_agent.runtime.android.container_manager import (
        ContainerFactory,
        ContainerConfig,
        ContainerInstance,
        PortAllocator,
    )
except ModuleNotFoundError:
    from container_manager import (
        ContainerFactory,
        ContainerConfig,
        ContainerInstance,
        PortAllocator,
    )


# ─── Models ───────────────────────────────────────────────────────────────────


class BrokerContainerState(str, Enum):
    IDLE = "IDLE"
    LEASED = "LEASED"
    RESETTING = "RESETTING"
    REPLACING = "REPLACING"


@dataclass
class PoolEntry:
    """Registry entry for a managed container."""

    container: ContainerInstance
    state: BrokerContainerState = BrokerContainerState.IDLE
    pid: Optional[int] = None
    pid_create_time: Optional[float] = None
    leased_at: Optional[float] = None


class AcquireRequest(BaseModel):
    pid: int
    timeout: float = 300.0


class ReturnRequest(BaseModel):
    env_id: int
    healthy: bool = True


class ScaleRequest(BaseModel):
    target_size: int


# ─── Broker ───────────────────────────────────────────────────────────────────


class ContainerPoolBroker:
    """
    Manages a persistent pool of Android emulator containers.

    Containers are pre-created at startup. Tasks acquire/return them via
    simple queue operations. Health monitoring and dead-lease GC run in background.
    No concept of "experiment" — just individual container checkouts.
    """

    def __init__(
        self,
        docker_image: str = "androidworld:v8",
        temp_path: str = "/tmp",
        pool_size: int = 24,
        snapshot: str = "clean",
        sample_mode: str = "sequential",
        train_task_family: str = "android_world",
        val_task_family: str = "android_world",
        use_host_network: bool = True,
        skip_screenshot: bool = False,
        health_check_interval: float = 30.0,
        gc_interval: float = 60.0,
        reconcile_interval: float = 180.0,
        base_env_id: int = 0,
        parallel: int = 4,
        adopt: bool = False,
    ):
        self.pool_size = pool_size
        self.base_env_id = base_env_id
        self.parallel = parallel
        self.use_host_network = use_host_network
        self.health_check_interval = health_check_interval
        self.gc_interval = gc_interval
        self.reconcile_interval = reconcile_interval
        self.max_lease_duration = 600.0  # seconds; reclaim leaked leases
        self.adopt = adopt

        self.config = ContainerConfig(
            sample_mode=sample_mode,
            snapshot=snapshot,
            train_task_family=train_task_family,
            val_task_family=val_task_family,
            skip_screenshot=skip_screenshot,
        )

        # Reuse existing components from container_manager.py
        self.port_allocator = PortAllocator()
        self.factory = ContainerFactory(docker_image=docker_image, temp_path=temp_path,
                                        port_allocator=self.port_allocator)

        # State
        self.registry: Dict[int, PoolEntry] = {}
        self.available_queue: asyncio.Queue = asyncio.Queue()
        self._next_env_id: int = 0
        self._env_id_lock: asyncio.Lock = asyncio.Lock()
        self._registry_lock: asyncio.Lock = asyncio.Lock()

        # Background tasks
        self._health_task: Optional[asyncio.Task] = None
        self._gc_task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None
        self._init_task: Optional[asyncio.Task] = None
        self._pool_initializing: bool = False
        self._start_time: float = time.time()

    # ── Pool Initialization ──────────────────────────────────────────────

    async def initialize_pool(self):
        """Create or adopt containers at startup."""
        if self.adopt:
            await self.adopt_existing_pool()
        else:
            await self._create_pool()

    async def _create_pool(self):
        """Create containers incrementally (parallel, bounded concurrency).

        Each container is added to the pool as soon as it passes health checks,
        so the broker can serve requests before the full pool is ready.
        """
        self._pool_initializing = True
        logger.info(f"Creating {self.pool_size} containers (available incrementally)...")

        port_tuples = self.port_allocator.preallocate_ports(
            pool_size=self.pool_size, base_env_id=self.base_env_id,
            use_host_network=self.use_host_network,
        )

        sem = asyncio.Semaphore(self.parallel)

        async def create_one(env_id: int, ports):
            async with sem:
                container = await self.factory.create(
                    env_id=env_id,
                    ports=ports,
                    config=self.config,
                    use_host_network=self.use_host_network,
                )
                # Add to pool immediately so it can be acquired
                self.registry[env_id] = PoolEntry(container=container)
                await self.available_queue.put(env_id)
                logger.info(
                    f"env{env_id}: ready "
                    f"({len(self.registry)}/{self.pool_size} in pool)"
                )

        tasks = []
        for i in range(self.pool_size):
            env_id = self.base_env_id + i
            tasks.append(create_one(env_id, port_tuples[i]))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed = sum(1 for r in results if isinstance(r, Exception))
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Failed to create container: {r}")

        self._next_env_id = self.base_env_id + self.pool_size
        self._pool_initializing = False
        logger.info(
            f"Pool creation complete: {len(self.registry)}/{self.pool_size} containers, "
            f"{failed} failed, {self.available_queue.qsize()} available"
        )

    async def adopt_existing_pool(self):
        """Adopt already-running Docker containers into the broker pool.

        Discovers containers named env{base_env_id}..env{base_env_id+pool_size-1},
        reads their port configuration from environment variables, health-checks them,
        and registers healthy ones in the broker registry.
        """
        import requests

        client = docker_lib.from_env()
        adopted = 0
        failed = 0

        logger.info(
            f"Adopting {self.pool_size} existing containers "
            f"(env{self.base_env_id}..env{self.base_env_id + self.pool_size - 1})..."
        )

        for i in range(self.pool_size):
            env_id = self.base_env_id + i
            container_name = f"env{env_id}"

            try:
                container = client.containers.get(container_name)
            except docker_lib.errors.NotFound:
                logger.warning(f"Container {container_name} not found, skipping")
                failed += 1
                continue

            if container.status != "running":
                logger.warning(f"Container {container_name} status={container.status}, skipping")
                failed += 1
                continue

            # Read port config from container env vars
            env_vars = {}
            for var in container.attrs["Config"]["Env"]:
                key, _, val = var.partition("=")
                env_vars[key] = val

            server_port = int(env_vars.get("SERVER_PORT", 0))
            emulator_port = int(env_vars.get("EMULATOR_PORT", 0))
            grpc_port = int(env_vars.get("GRPC_PORT", 0))

            if not server_port:
                logger.warning(f"{container_name}: missing SERVER_PORT env var, skipping")
                failed += 1
                continue

            # Quick HTTP health check
            try:
                resp = requests.get(
                    f"http://localhost:{server_port}/health", timeout=(3, 10)
                )
                healthy = resp.status_code == 200
            except Exception:
                healthy = False

            if not healthy:
                logger.warning(f"{container_name}: health check failed (port {server_port}), skipping")
                failed += 1
                continue

            instance = ContainerInstance(
                container_id=container.id,
                container=container,
                server_port=server_port,
                emulator_port=emulator_port,
                grpc_port=grpc_port,
                env_id=env_id,
                state="ready",
                last_health_check=time.time(),
                is_healthy=True,
            )

            self.registry[env_id] = PoolEntry(container=instance)
            await self.available_queue.put(env_id)
            adopted += 1

        self._next_env_id = self.base_env_id + self.pool_size
        logger.info(
            f"Adopt complete: {adopted}/{self.pool_size} adopted, "
            f"{failed} failed, {self.available_queue.qsize()} available"
        )

    async def start_background_tasks(self):
        """Start health monitor, dead-process GC, and pool reconciliation loops."""
        self._health_task = asyncio.create_task(self._health_loop())
        self._gc_task = asyncio.create_task(self._gc_loop())
        self._reconcile_task = asyncio.create_task(self._reconcile_loop())

    async def stop_background_tasks(self):
        """Cancel background tasks."""
        for task in [self._health_task, self._gc_task, self._reconcile_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # ── Core Operations ──────────────────────────────────────────────────

    async def acquire(self, pid: int, timeout: float = 300.0) -> Dict[str, Any]:
        """Acquire a healthy container. Blocks until one is available or timeout."""
        deadline = time.time() + timeout

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"No container available within {timeout}s")

            try:
                env_id = await asyncio.wait_for(
                    self.available_queue.get(), timeout=min(remaining, 10.0)
                )
            except asyncio.TimeoutError:
                continue

            # Health check OUTSIDE registry lock to avoid blocking other operations
            entry = self.registry.get(env_id)
            if entry is None:
                continue

            healthy = await asyncio.to_thread(
                self._check_health_sync, entry.container
            )

            async with self._registry_lock:
                # Re-check: entry may have been modified while we were health-checking
                if (
                    env_id not in self.registry
                    or entry.state != BrokerContainerState.IDLE
                ):
                    continue

                if not healthy:
                    logger.warning(
                        f"Unhealthy env{env_id} during acquire, replacing"
                    )
                    entry.state = BrokerContainerState.REPLACING
                    asyncio.create_task(self._replace_container(env_id))
                    continue

                entry.state = BrokerContainerState.LEASED
                entry.pid = pid
                try:
                    entry.pid_create_time = psutil.Process(pid).create_time()
                except psutil.NoSuchProcess:
                    entry.pid_create_time = None
                entry.leased_at = time.time()

            return {
                "env_id": env_id,
                "server_port": entry.container.server_port,
                "emulator_port": entry.container.emulator_port,
                "grpc_port": entry.container.grpc_port,
                "host": "localhost",
                "container_id": entry.container.container_id,
            }

    async def return_container(self, env_id: int, healthy: bool = True):
        """Return a container to the pool.

        Restores the emulator snapshot to a clean state before making it
        available again.  This prevents state contamination between tasks.
        """
        async with self._registry_lock:
            entry = self.registry.get(env_id)
            if entry is None:
                logger.warning(f"return: env{env_id} not in registry")
                return

            entry.pid = None
            entry.pid_create_time = None
            entry.leased_at = None

            if not healthy:
                logger.warning(
                    f"env{env_id} unhealthy on return (caller reported), replacing"
                )
                entry.state = BrokerContainerState.REPLACING
                asyncio.create_task(self._replace_container(env_id))
                return

            # Mark as RESETTING while snapshot restore is in progress
            entry.state = BrokerContainerState.RESETTING

        asyncio.create_task(self._restore_and_return(env_id))

    async def _restore_and_return(self, env_id: int):
        """Restore snapshot on a returned container and put it back in the pool."""
        entry = self.registry.get(env_id)
        if entry is None:
            return

        server_port = entry.container.server_port
        try:
            ok = await asyncio.to_thread(
                self._restore_snapshot_sync, server_port
            )
        except Exception as e:
            logger.warning(f"env{env_id} snapshot restore raised: {e}")
            ok = False

        if ok:
            async with self._registry_lock:
                entry.state = BrokerContainerState.IDLE
            await self.available_queue.put(env_id)
            logger.info(f"env{env_id} snapshot restored, returned to pool")
        else:
            logger.warning(
                f"env{env_id} snapshot restore failed, replacing container"
            )
            async with self._registry_lock:
                entry.state = BrokerContainerState.REPLACING
            asyncio.create_task(self._replace_container(env_id))

    def _restore_snapshot_sync(self, server_port: int) -> bool:
        """Call the container's /reset endpoint to restore the clean snapshot."""
        import requests

        try:
            resp = requests.post(
                f"http://localhost:{server_port}/reset",
                json={"seed": None, "options": {}},
                timeout=(5, 120),
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Snapshot restore request failed (port {server_port}): {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get current pool status."""
        counts = {"IDLE": 0, "LEASED": 0, "RESETTING": 0, "REPLACING": 0}
        containers_info = []
        for env_id, entry in sorted(self.registry.items()):
            counts[entry.state.value] += 1
            containers_info.append(
                {
                    "env_id": env_id,
                    "state": entry.state.value,
                    "pid": entry.pid,
                    "server_port": entry.container.server_port,
                    "healthy": entry.container.is_healthy,
                }
            )
        return {
            "total": len(self.registry),
            "target": self.pool_size,
            "initializing": self._pool_initializing,
            "idle": counts["IDLE"],
            "leased": counts["LEASED"],
            "resetting": counts["RESETTING"],
            "replacing": counts["REPLACING"],
            "containers": containers_info,
        }

    # ── Health / GC / Replace ────────────────────────────────────────────

    def _check_health_sync(self, container: ContainerInstance) -> bool:
        """
        Docker status + HTTP /health check (synchronous).

        Always called via asyncio.to_thread() from async context to avoid
        blocking the event loop.
        """
        import docker as docker_lib
        import requests

        try:
            container.container.reload()
            if container.container.status != "running":
                container.is_healthy = False
                return False
        except docker_lib.errors.NotFound:
            container.is_healthy = False
            return False
        except Exception:
            return False

        try:
            resp = requests.get(
                f"http://localhost:{container.server_port}/health",
                timeout=(3, 10),
            )
            if resp.status_code == 200:
                container.is_healthy = True
                return True
        except Exception:
            pass

        container.is_healthy = False
        return False

    async def _replace_container(self, env_id: int):
        """Destroy old container, create replacement with new env_id."""
        async with self._registry_lock:
            entry = self.registry.pop(env_id, None)
        if entry is None:
            return

        try:
            await asyncio.to_thread(entry.container.container.stop)
        except Exception as e:
            logger.warning(f"Error stopping env{env_id}: {e}")

        try:
            async with self._env_id_lock:
                new_env_id = self._next_env_id
                self._next_env_id += 1

            ports = self.port_allocator.preallocate_ports(
                pool_size=1, base_env_id=new_env_id,
                use_host_network=self.use_host_network,
            )[0]
            new_container = await self.factory.create(
                env_id=new_env_id,
                ports=ports,
                config=self.config,
                use_host_network=self.use_host_network,
            )

            async with self._registry_lock:
                self.registry[new_env_id] = PoolEntry(container=new_container)
            await self.available_queue.put(new_env_id)
            logger.info(f"Replaced env{env_id} → env{new_env_id}")
        except Exception as e:
            logger.error(f"Failed to replace env{env_id}: {e}")

    async def _health_loop(self):
        """Periodic health checks on IDLE containers."""
        while True:
            await asyncio.sleep(self.health_check_interval)
            async with self._registry_lock:
                idle = [
                    (eid, e)
                    for eid, e in self.registry.items()
                    if e.state == BrokerContainerState.IDLE
                ]
            for env_id, entry in idle:
                healthy = await asyncio.to_thread(
                    self._check_health_sync, entry.container
                )
                if not healthy:
                    # Re-check state under lock: container may have been acquired
                    # between our idle snapshot and now
                    async with self._registry_lock:
                        if entry.state != BrokerContainerState.IDLE:
                            continue  # was acquired in the meantime, skip
                        logger.warning(
                            f"Health loop: env{env_id} unhealthy, replacing"
                        )
                        entry.state = BrokerContainerState.REPLACING
                    asyncio.create_task(self._replace_container(env_id))

    async def _gc_loop(self):
        """Reclaim containers from dead processes or expired leases.

        Two reclamation strategies:
        1. Dead PID: The leasing process no longer exists (PID reuse safe).
        2. Lease timeout: The container has been leased longer than
           max_lease_duration.  This catches the case where a worker finished
           its task but the return HTTP POST failed (container leaked).
        """
        while True:
            await asyncio.sleep(self.gc_interval)
            now = time.time()
            async with self._registry_lock:
                leased = [
                    (eid, e)
                    for eid, e in self.registry.items()
                    if e.state == BrokerContainerState.LEASED
                ]
            for env_id, entry in leased:
                should_reclaim = False
                reason = ""

                # Strategy 1: dead PID
                if entry.pid:
                    try:
                        proc = psutil.Process(entry.pid)
                        if (
                            entry.pid_create_time is not None
                            and proc.create_time() != entry.pid_create_time
                        ):
                            should_reclaim = True
                            reason = f"pid {entry.pid} reused"
                    except psutil.NoSuchProcess:
                        should_reclaim = True
                        reason = f"pid {entry.pid} gone"

                # Strategy 2: lease timeout (catches failed returns)
                if (
                    not should_reclaim
                    and entry.leased_at
                    and (now - entry.leased_at) > self.max_lease_duration
                ):
                    should_reclaim = True
                    elapsed = now - entry.leased_at
                    reason = (
                        f"lease expired ({elapsed:.0f}s > "
                        f"{self.max_lease_duration:.0f}s)"
                    )

                if should_reclaim:
                    logger.warning(
                        f"GC: reclaiming env{env_id} — {reason}"
                    )
                    async with self._registry_lock:
                        entry.state = BrokerContainerState.IDLE
                        entry.pid = None
                        entry.pid_create_time = None
                        entry.leased_at = None
                    await self.available_queue.put(env_id)

    async def _reconcile_loop(self):
        """Maintain pool at target size by replacing containers lost to failed replacements."""
        while True:
            await asyncio.sleep(self.reconcile_interval)
            current = len(self.registry)
            if current >= self.pool_size:
                continue

            deficit = self.pool_size - current
            logger.info(f"Reconcile: pool at {current}/{self.pool_size}, creating {deficit} containers")
            created = 0

            for _ in range(deficit):
                try:
                    async with self._env_id_lock:
                        new_env_id = self._next_env_id
                        self._next_env_id += 1

                    ports = self.port_allocator.preallocate_ports(
                        pool_size=1, base_env_id=new_env_id,
                        use_host_network=self.use_host_network,
                    )[0]
                    new_container = await self.factory.create(
                        env_id=new_env_id,
                        ports=ports,
                        config=self.config,
                        use_host_network=self.use_host_network,
                    )

                    async with self._registry_lock:
                        self.registry[new_env_id] = PoolEntry(container=new_container)
                    await self.available_queue.put(new_env_id)
                    created += 1
                except Exception as e:
                    logger.error(f"Reconcile: failed to create container: {e}")

            logger.info(
                f"Reconcile: {created}/{deficit} restored, "
                f"pool now {len(self.registry)}/{self.pool_size}"
            )

    async def shutdown(self):
        """Stop background tasks and optionally stop containers."""
        await self.stop_background_tasks()
        if self.adopt:
            logger.info(f"Broker shutdown (adopt mode: leaving {len(self.registry)} containers running)")
        else:
            logger.info(f"Stopping {len(self.registry)} containers...")
            for entry in self.registry.values():
                try:
                    entry.container.container.stop()
                except Exception:
                    pass
        logger.info("Broker shutdown complete")


# ─── FastAPI App ──────────────────────────────────────────────────────────────

broker: Optional[ContainerPoolBroker] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan handler (replaces deprecated on_event).

    Pool creation runs in the background so the API is available immediately.
    Containers are added to the pool incrementally as they become ready.
    """
    broker._init_task = asyncio.create_task(broker.initialize_pool())
    await broker.start_background_tasks()
    yield
    if broker:
        if broker._init_task and not broker._init_task.done():
            broker._init_task.cancel()
            try:
                await broker._init_task
            except asyncio.CancelledError:
                pass
        await broker.shutdown()


app = FastAPI(title="Container Pool Broker", lifespan=lifespan)


@app.post("/acquire")
async def api_acquire(req: AcquireRequest):
    try:
        return await broker.acquire(pid=req.pid, timeout=req.timeout)
    except TimeoutError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/return")
async def api_return(req: ReturnRequest):
    await broker.return_container(env_id=req.env_id, healthy=req.healthy)
    return {"status": "returned"}


@app.get("/status")
async def api_status():
    return broker.get_status()


@app.get("/health")
async def api_health():
    return {
        "status": "ok",
        "uptime": time.time() - broker._start_time,
        "pool_ready": len(broker.registry),
        "pool_target": broker.pool_size,
        "pool_initializing": broker._pool_initializing,
    }


@app.post("/scale")
async def api_scale(req: ScaleRequest):
    raise HTTPException(status_code=501, detail="Not implemented yet")


def main():
    parser = argparse.ArgumentParser(description="Container Pool Broker")
    parser.add_argument("--pool-size", type=int, default=24)
    parser.add_argument("--docker-image", type=str, default="androidworld:v8")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--snapshot", type=str, default="clean")
    parser.add_argument("--sample-mode", type=str, default="sequential")
    parser.add_argument("--base-env-id", type=int, default=0)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--temp-path", type=str, default="/tmp")
    parser.add_argument("--health-interval", type=float, default=30.0)
    parser.add_argument("--gc-interval", type=float, default=60.0)
    parser.add_argument("--reconcile-interval", type=float, default=180.0,
                        help="Seconds between pool size reconciliation checks")
    parser.add_argument("--skip-screenshot", action="store_true")
    parser.add_argument("--parallel", type=int, default=4, help="Max concurrent container creations")
    parser.add_argument("--adopt", action="store_true",
                        help="Adopt already-running containers instead of creating new ones")
    args = parser.parse_args()

    global broker
    broker = ContainerPoolBroker(
        docker_image=args.docker_image,
        temp_path=args.temp_path,
        pool_size=args.pool_size,
        snapshot=args.snapshot,
        sample_mode=args.sample_mode,
        health_check_interval=args.health_interval,
        gc_interval=args.gc_interval,
        reconcile_interval=args.reconcile_interval,
        skip_screenshot=args.skip_screenshot,
        base_env_id=args.base_env_id,
        parallel=args.parallel,
        adopt=args.adopt,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
