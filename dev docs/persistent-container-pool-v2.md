# Implementation Spec: Persistent Container Pool (Model 2 — Task-Level Pool)

**Date:** 2026-02-26
**Updated:** 2026-02-27
**Status:** Implementation Ready
**Target:** Cursor Agent / Claude Coding

---

## Overview

This spec defines two operational modes for Android emulator container management. A single YAML config key (`broker_url`) selects the mode. **All existing code paths remain untouched.**

| | Mode A: Local | Mode B: Broker |
|---|---|---|
| **Config** | No `broker_url` set | `broker_url: "http://..."` |
| **Container lifecycle** | Created per-experiment, destroyed on exit | Pre-created once, reused across experiments |
| **Startup time** | 5-10 min (boot emulators) | Instant (containers already running) |
| **Container ownership** | One experiment owns its containers | Shared pool, any task from any experiment |
| **Health management** | ContainerManager + HealthMonitor | Broker process manages everything |
| **Concurrency** | Requires manual `base_env_id` coordination | Broker handles all allocation |
| **Code changes** | **None** | 2 new files + 1 branch point in `android_task.py` |

### Key Design Principles

1. **Zero changes to local mode** — when `broker_url` is absent, the entire existing code path executes identically. No modified classes, no new fields, no behavior changes.
2. **Adapter pattern** — `BrokerContainerManager` implements the same interface as `ContainerManager`, so the dispatcher, runner, and RuntimeClient work unchanged in both modes.
3. **Task-level granularity** — each trajectory independently acquires/returns a container. No batch reservation, no experiment concept at broker level.
4. **No broker-side reset** — `AndroidTrajectory.initialize_trajectory()` already calls `env.reset()` on every use. The broker just tracks availability.
5. **Minimal API** — `POST /acquire`, `POST /return`, `GET /status`. No leases, no heartbeats, no experiment IDs.

---

## 1. Architecture: Mode A (Local) — No Changes

This is the existing architecture. **Nothing changes.**

```
┌─────────────────────────────────────────────────────────┐
│  Experiment Process                                      │
│                                                         │
│  AndroidAgentRunner.run()                                │
│    → AndroidTask.initialize_runtime(env_config)          │
│        → ContainerManager.create_pool_parallel()         │  ← 5-10 min
│        → ContainerManager.start_health_monitor()         │
│    → async_fix_pool_android dispatcher:                  │
│        → container_manager.allocate_container()           │  ← local queue
│        → init_fn → RuntimeClient(container).reset()      │
│        → run_fn  → RuntimeClient(container).step()       │
│        → eval_fn                                         │
│        → container_manager.release_container()            │  ← local queue
│    → AndroidTask.cleanup_runtime()                       │
│        → ContainerManager.cleanup()                      │  ← destroy all
│                                                         │
│  Docker Containers (created at startup, destroyed at end)│
│  ┌──────┐ ┌──────┐ ┌──────┐         ┌──────┐           │
│  │env0  │ │env1  │ │env2  │  ...    │envN  │           │
│  │:5000 │ │:5002 │ │:5004 │         │:500X │           │
│  └──────┘ └──────┘ └──────┘         └──────┘           │
└─────────────────────────────────────────────────────────┘
```

**Files involved (READ ONLY — no modifications):**
- `container_manager.py` — ContainerManager, ContainerFactory, PortAllocator, HealthMonitor
- `runtime_client.py` — RuntimeClient with `base_url = f"http://localhost:{port}"`
- `android_task.py` — AndroidTask.initialize_runtime creates ContainerManager
- `android_runner.py` — AndroidAgentRunner passes container_manager to dispatcher
- `dispatchers.py` — async_fix_pool_android uses allocate_container/release_container

---

## 2. Architecture: Mode B (Broker) — New

```
┌─────────────────────────────────────────────────────────────┐
│  Container Pool Broker (standalone process, port 9100)       │
│  Started once: python -m skyrl_agent.runtime.android.pool_broker │
│                                                             │
│  ┌────────────────┐  ┌───────────────────────────────────┐  │
│  │ Available Queue │  │ Health Monitor (30s)               │  │
│  │  [env3, env7,  │  │  - HTTP /health per container     │  │
│  │   env12, ...]  │  │  - Docker status                  │  │
│  └────────────────┘  │  - Auto-replace dead → new env_id │  │
│                      └───────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Container Registry                                    │   │
│  │  env0: {port:5000, state:LEASED, pid:12345}          │   │
│  │  env3: {port:5006, state:IDLE}                       │   │
│  │  env7: {port:5014, state:IDLE}                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Dead Process GC (60s)                               │     │
│  │  - psutil.pid_exists(pid) for each LEASED container │     │
│  │  - Reclaim if process died                          │     │
│  └────────────────────────────────────────────────────┘     │
│                                                             │
│  Docker Containers (host network, /dev/kvm)                 │
│  ┌──────┐ ┌──────┐ ┌──────┐         ┌──────┐              │
│  │env0  │ │env3  │ │env7  │  ...    │envN  │              │
│  │:5000 │ │:5006 │ │:5014 │         │:500X │              │
│  └──────┘ └──────┘ └──────┘         └──────┘              │
└─────────────────────────────────────────────────────────────┘
       ▲               ▲
       │ POST /acquire │ POST /acquire
       │ POST /return  │ POST /return
┌──────┴──────┐  ┌─────┴───────┐
│ Experiment A│  │ Experiment B│  ← both use same pool
│ (skyrl-agent│  │ (skyrl-agent│
│  process)   │  │  process)   │
└─────────────┘  └─────────────┘
```

**Data flow in Mode B — adapter pattern:**

The key insight is that `BrokerContainerManager` implements the same interface as `ContainerManager`. The dispatcher, runner, and callback functions see no difference.

```
AndroidAgentRunner.run()
  → AndroidTask.initialize_runtime(env_config)
      → sees broker_url in config
      → PoolClient(broker_url) + BrokerContainerManager(pool_client)
      → stores BrokerContainerManager as cls._container_manager   ← same attribute!
  → async_fix_pool_android dispatcher:                            ← UNCHANGED
      → container_manager.allocate_container()      ← adapter → broker POST /acquire
      → init_fn → RuntimeClient(container).reset()  ← RemoteContainerInfo duck-types
      → run_fn  → RuntimeClient(container).step()
      → eval_fn
      → container_manager.release_container()        ← adapter → broker POST /return
  → AndroidTask.cleanup_runtime()                                 ← UNCHANGED
      → ContainerManager.cleanup()                   ← adapter closes HTTP session
```

**Why the adapter pattern works:** The dispatcher (`async_fix_pool_android_dispatcher`) calls `container_manager.allocate_container()` and `container_manager.release_container()`. The runner's `init_fn` creates `RuntimeClient(container)` from whatever is returned. By having `BrokerContainerManager` return `RemoteContainerInfo` objects (duck-typed with `ContainerInstance`), and adding `getattr(container, 'host', 'localhost')` to `RuntimeClient.base_url`, the entire existing call chain works without modification.

**Files involved:**
- `pool_broker.py` (NEW) — standalone broker process
- `pool_client.py` (NEW) — PoolClient + BrokerContainerManager adapter
- `android_task.py` (MODIFY) — single branch point in `initialize_runtime()`
- `runtime_client.py` (MODIFY) — one-line `base_url` change (getattr fallback)

**Files NOT modified** (unlike previous design):
- `android_runner.py` — unchanged, always uses `container_manager`
- `dispatchers.py` — unchanged, always uses `container_manager`
- `__init__.py` — unchanged, no eager imports of broker code

---

## 3. Broker API Specification

The broker is a FastAPI application running as a standalone process.

### 3.1 `POST /acquire`

Acquire a single available container for a task.

**Request:**
```json
{"pid": 12345, "timeout": 300}
```
- `pid` (int, required): Caller's process ID. Used for dead-process detection.
- `timeout` (float, optional): Max seconds to wait. Default 300.

**Response (200):**
```json
{
  "env_id": 7,
  "server_port": 5014,
  "emulator_port": 5588,
  "grpc_port": 8588,
  "host": "localhost",
  "container_id": "abc123def"
}
```

**Response (503):** No containers available within timeout.

**Behavior:**
1. Pop from available queue (with timeout)
2. Quick health check — if unhealthy, skip + trigger background replacement, try next
3. Mark `LEASED`, record caller PID + process create time
4. Return container info

### 3.2 `POST /return`

Return a container back to the pool.

**Request:**
```json
{"env_id": 7, "healthy": true}
```
- `env_id` (int, required): Which container to return.
- `healthy` (bool, optional, default true): If false, broker triggers replacement.

**Response (200):**
```json
{"status": "returned"}
```

**Behavior:**
1. `healthy=false` → trigger replacement (destroy old, create new env_id)
2. `healthy=true` → quick health check → put back in queue, or replace if unhealthy
3. Clear PID association

### 3.3 `GET /status`

**Response (200):**
```json
{
  "total": 24, "idle": 18, "leased": 5, "replacing": 1,
  "containers": [
    {"env_id": 0, "state": "LEASED", "pid": 12345, "server_port": 5000, "healthy": true},
    {"env_id": 3, "state": "IDLE", "pid": null, "server_port": 5006, "healthy": true}
  ]
}
```

### 3.4 `GET /health`

Broker liveness check.

**Response (200):**
```json
{"status": "ok", "uptime": 3600, "pool_size": 24}
```

### 3.5 `POST /scale` (future)

Dynamically adjust pool size. Not implemented in v1.

---

## 4. Container State Machine (Broker)

```
                    ┌──────────────────────────┐
                    │                          │
                    ▼                          │
    ┌────────┐  acquire   ┌────────┐  return  │
    │  IDLE  │ ────────►  │ LEASED │ ─────────┘
    └────────┘            └────────┘
        │                      │
        │ health_fail          │ return(healthy=false)
        │                      │  OR health_fail on return
        ▼                      ▼
    ┌───────────┐         ┌───────────┐
    │ REPLACING │         │ REPLACING │
    └───────────┘         └───────────┘
        │                      │
        │ new container        │ new container
        ▼                      ▼
    ┌────────┐            ┌────────┐
    │  IDLE  │            │  IDLE  │   ← always NEW env_id
    │ (new)  │            │ (new)  │
    └────────┘            └────────┘
```

Replacement always creates a **NEW container with NEW env_id**. Old container is destroyed. Matches existing ContainerManager design (never restart in-place).

---

## 5. Dead Process Detection

No heartbeats needed. Broker uses **PID-based garbage collection** (runs every 60s).

To guard against PID reuse by the OS, we store both the PID and its creation time. This ensures that even if the OS assigns the same PID to a new unrelated process, the GC correctly detects the original process is gone.

```python
for entry in registry.values():
    if entry.state == "LEASED" and entry.pid is not None:
        try:
            proc = psutil.Process(entry.pid)
            if proc.create_time() != entry.pid_create_time:
                # PID was reused by a different process
                logger.warning(f"PID {entry.pid} reused, reclaiming env{entry.env_id}")
                reclaim(entry)
        except psutil.NoSuchProcess:
            logger.warning(f"Process {entry.pid} died, reclaiming env{entry.env_id}")
            reclaim(entry)
```

---

## 6. Mode Selection Logic

Mode selection happens in **one place**: `AndroidTask.initialize_runtime()`. Thanks to the adapter pattern, no other file needs to know which mode is active.

```python
# In AndroidTask.initialize_runtime():
broker_url = env_config.get("broker_url")  # None → Mode A, URL → Mode B

if broker_url:
    # Mode B: create BrokerContainerManager (same interface as ContainerManager)
    pool_client = PoolClient(broker_url)
    cls._container_manager = BrokerContainerManager(pool_client)
else:
    # Mode A: create real ContainerManager (existing code, unchanged)
    cls._container_manager = ContainerManager(...)
```

**Rule:** When `broker_url` is NOT in config, the code never imports `PoolClient`, never touches broker-related code. The existing path runs exactly as before.

**Why only one branch point:** `BrokerContainerManager` implements the same interface as `ContainerManager` (`allocate_container`, `release_container`, `start_health_monitor`, `cleanup`, `containers`, etc.). The dispatcher and runner always talk to `_container_manager` — they don't know or care which implementation is behind it.

---

## 7. Files to Create (Mode B only)

### 7.1 `skyrl-agent/skyrl_agent/runtime/android/pool_broker.py` (NEW)

Standalone broker process. Reuses existing `ContainerFactory`, `PortAllocator`, `ContainerConfig` from `container_manager.py`.

```python
"""
Container Pool Broker — standalone FastAPI server managing a shared container pool.

Usage:
    python -m skyrl_agent.runtime.android.pool_broker \
        --pool-size 24 \
        --docker-image androidworld:v8 \
        --port 9100

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

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger

from skyrl_agent.runtime.android.container_manager import (
    ContainerFactory,
    ContainerConfig,
    ContainerInstance,
    PortAllocator,
)


# ─── Models ───────────────────────────────────────────────────────────────────

class BrokerContainerState(str, Enum):
    IDLE = "IDLE"
    LEASED = "LEASED"
    REPLACING = "REPLACING"


@dataclass
class PoolEntry:
    """Registry entry for a managed container."""
    container: ContainerInstance
    state: BrokerContainerState = BrokerContainerState.IDLE
    pid: Optional[int] = None
    pid_create_time: Optional[float] = None  # psutil.Process.create_time()
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
    ):
        self.pool_size = pool_size
        self.use_host_network = use_host_network
        self.health_check_interval = health_check_interval
        self.gc_interval = gc_interval

        self.config = ContainerConfig(
            sample_mode=sample_mode,
            snapshot=snapshot,
            train_task_family=train_task_family,
            val_task_family=val_task_family,
            skip_screenshot=skip_screenshot,
        )

        # Reuse existing components from container_manager.py
        self.port_allocator = PortAllocator()
        self.factory = ContainerFactory(docker_image=docker_image, temp_path=temp_path)

        # State
        self.registry: Dict[int, PoolEntry] = {}   # env_id → PoolEntry
        self.available_queue: asyncio.Queue = asyncio.Queue()
        self._next_env_id: int = 0
        self._env_id_lock: asyncio.Lock = asyncio.Lock()
        self._registry_lock: asyncio.Lock = asyncio.Lock()

        # Background tasks
        self._health_task: Optional[asyncio.Task] = None
        self._gc_task: Optional[asyncio.Task] = None
        self._start_time: float = time.time()

    # ── Pool Initialization ──────────────────────────────────────────────

    async def initialize_pool(self):
        """Create all containers at startup (parallel, bounded concurrency)."""
        logger.info(f"Creating {self.pool_size} containers...")

        port_tuples = self.port_allocator.preallocate_ports(
            pool_size=self.pool_size, base_env_id=0
        )

        sem = asyncio.Semaphore(4)

        async def create_one(env_id: int, ports):
            async with sem:
                return await self.factory.create(
                    env_id=env_id, ports=ports,
                    config=self.config, use_host_network=self.use_host_network,
                )

        tasks = [create_one(i, port_tuples[i]) for i in range(self.pool_size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Failed to create container: {result}")
                continue
            self.registry[result.env_id] = PoolEntry(container=result)
            await self.available_queue.put(result.env_id)

        self._next_env_id = self.pool_size
        logger.info(
            f"Pool ready: {len(self.registry)}/{self.pool_size} containers, "
            f"{self.available_queue.qsize()} available"
        )

    async def start_background_tasks(self):
        self._health_task = asyncio.create_task(self._health_loop())
        self._gc_task = asyncio.create_task(self._gc_loop())

    async def stop_background_tasks(self):
        for task in [self._health_task, self._gc_task]:
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

            healthy = await asyncio.to_thread(self._check_health_sync, entry.container)

            async with self._registry_lock:
                # Re-check: entry may have been modified while we were health-checking
                if env_id not in self.registry or entry.state != BrokerContainerState.IDLE:
                    continue

                if not healthy:
                    logger.warning(f"Unhealthy env{env_id} during acquire, replacing")
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
        """Return a container to the pool."""
        async with self._registry_lock:
            entry = self.registry.get(env_id)
            if entry is None:
                logger.warning(f"return: env{env_id} not in registry")
                return

            entry.pid = None
            entry.pid_create_time = None
            entry.leased_at = None

            if not healthy:
                logger.warning(f"env{env_id} unhealthy on return (caller reported), replacing")
                entry.state = BrokerContainerState.REPLACING
                asyncio.create_task(self._replace_container(env_id))
                return

        # Health check outside lock for healthy returns
        is_healthy = await asyncio.to_thread(self._check_health_sync, entry.container)

        async with self._registry_lock:
            if env_id not in self.registry:
                return
            if not is_healthy:
                logger.warning(f"env{env_id} unhealthy on return (health check failed), replacing")
                entry.state = BrokerContainerState.REPLACING
                asyncio.create_task(self._replace_container(env_id))
                return
            entry.state = BrokerContainerState.IDLE

        await self.available_queue.put(env_id)

    def get_status(self) -> Dict[str, Any]:
        counts = {"IDLE": 0, "LEASED": 0, "REPLACING": 0}
        containers_info = []
        for env_id, entry in sorted(self.registry.items()):
            counts[entry.state.value] += 1
            containers_info.append({
                "env_id": env_id,
                "state": entry.state.value,
                "pid": entry.pid,
                "server_port": entry.container.server_port,
                "healthy": entry.container.is_healthy,
            })
        return {
            "total": len(self.registry),
            "idle": counts["IDLE"],
            "leased": counts["LEASED"],
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

            ports = self.port_allocator.preallocate_ports(pool_size=1, base_env_id=new_env_id)[0]
            new_container = await self.factory.create(
                env_id=new_env_id, ports=ports,
                config=self.config, use_host_network=self.use_host_network,
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
                idle = [(eid, e) for eid, e in self.registry.items()
                        if e.state == BrokerContainerState.IDLE]
            for env_id, entry in idle:
                healthy = await asyncio.to_thread(self._check_health_sync, entry.container)
                if not healthy:
                    # Re-check state under lock: container may have been acquired
                    # between our idle snapshot and now
                    async with self._registry_lock:
                        if entry.state != BrokerContainerState.IDLE:
                            continue  # was acquired in the meantime, skip
                        logger.warning(f"Health loop: env{env_id} unhealthy, replacing")
                        entry.state = BrokerContainerState.REPLACING
                    asyncio.create_task(self._replace_container(env_id))

    async def _gc_loop(self):
        """Reclaim containers from dead processes (PID reuse safe)."""
        while True:
            await asyncio.sleep(self.gc_interval)
            async with self._registry_lock:
                leased = [(eid, e) for eid, e in self.registry.items()
                          if e.state == BrokerContainerState.LEASED and e.pid]
            for env_id, entry in leased:
                should_reclaim = False
                try:
                    proc = psutil.Process(entry.pid)
                    if entry.pid_create_time is not None and \
                       proc.create_time() != entry.pid_create_time:
                        # PID was reused by a different process
                        should_reclaim = True
                except psutil.NoSuchProcess:
                    should_reclaim = True

                if should_reclaim:
                    logger.warning(f"GC: pid {entry.pid} gone, reclaiming env{env_id}")
                    async with self._registry_lock:
                        entry.state = BrokerContainerState.IDLE
                        entry.pid = None
                        entry.pid_create_time = None
                        entry.leased_at = None
                    await self.available_queue.put(env_id)

    async def shutdown(self):
        await self.stop_background_tasks()
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
    """Modern FastAPI lifespan handler (replaces deprecated on_event)."""
    await broker.initialize_pool()
    await broker.start_background_tasks()
    yield
    if broker:
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
    return {"status": "ok", "uptime": time.time() - broker._start_time, "pool_size": len(broker.registry)}


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
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--temp-path", type=str, default="/tmp")
    parser.add_argument("--health-interval", type=float, default=30.0)
    parser.add_argument("--gc-interval", type=float, default=60.0)
    parser.add_argument("--skip-screenshot", action="store_true")
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
        skip_screenshot=args.skip_screenshot,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

---

### 7.2 `skyrl-agent/skyrl_agent/runtime/android/pool_client.py` (NEW)

This file contains two classes:
1. **`PoolClient`** — thin HTTP client for the broker
2. **`BrokerContainerManager`** — adapter that implements the `ContainerManager` interface, backed by `PoolClient`

The adapter pattern means the dispatcher, runner, and RuntimeClient work unchanged — they always talk to a `ContainerManager`-like object.

```python
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
from dataclasses import dataclass, field
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
    host: str                          # "localhost" for single-server
    container_id: str
    # Fields that RuntimeClient or dispatcher may access:
    state: str = "in_use"
    is_healthy: bool = True
    container: Any = None              # Not available remotely
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
                        raise RuntimeError(f"Broker: {data.get('detail', 'timeout')}")
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

        raise RuntimeError(f"Broker unavailable at {self.broker_url} after "
                           f"{self.ACQUIRE_RETRIES} attempts: {last_error}")

    async def release(self, env_id: int, healthy: bool = True):
        """Return a container to the broker."""
        await self._ensure_session()
        try:
            async with self._session.post(
                f"{self.broker_url}/return",
                json={"env_id": env_id, "healthy": healthy},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to return env{env_id} to broker: {e}")
        logger.debug(f"Returned env{env_id} to broker (healthy={healthy})")

    async def get_status(self) -> Dict[str, Any]:
        await self._ensure_session()
        async with self._session.get(
            f"{self.broker_url}/status", timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def check_broker_health(self) -> bool:
        try:
            await self._ensure_session()
            async with self._session.get(
                f"{self.broker_url}/health", timeout=aiohttp.ClientTimeout(total=5),
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

    def __init__(self, pool_client: PoolClient):
        self._client = pool_client
        self.containers: List[RemoteContainerInfo] = []
        self.backup_containers: List = []
        self.failed_trajectories: List[Tuple[int, int, str]] = []
        self._recovery_callback: Optional[Callable] = None

    async def initialize(self):
        """Fetch pool size from broker and pre-populate containers list."""
        status = await self._client.get_status()
        pool_size = status.get("total", 0)
        # Create placeholder entries so len(self.containers) reflects pool size.
        # These are replaced with real RemoteContainerInfo on allocate().
        self.containers = [None] * pool_size
        logger.info(f"BrokerContainerManager: connected, pool_size={pool_size}")

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
            batch_idx = container.current_trajectory[0] if container.current_trajectory else 0
            traj_id = container.current_trajectory[1] if container.current_trajectory else 0
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
        """Proxy to broker /status endpoint (sync wrapper)."""
        return {
            "pool_size": len(self.containers),
            "buffer_size": 0,
            "healthy": len(self.containers),
            "failed_trajectories": len(self.failed_trajectories),
        }

    def get_failed_trajectories(self) -> List[Tuple[int, int, str]]:
        return list(self.failed_trajectories)

    def clear_failed_trajectories(self):
        self.failed_trajectories.clear()

    def print_batch_summary(self, total_trajectories: int):
        failed = len(self.failed_trajectories)
        succeeded = total_trajectories - failed
        logger.info(f"Batch: {succeeded}/{total_trajectories} succeeded, {failed} failed")

    async def mark_container_unhealthy_async(self, env_id: int):
        """Release container as unhealthy to broker."""
        await self._client.release(env_id, healthy=False)
```

---

## 8. Files to Modify (Mode B branch points only)

Thanks to the adapter pattern, only **2 existing files** need modification. Both changes are minimal and guarded behind `broker_url` checks.

### 8.1 `AndroidTask` — add broker branch in `initialize_runtime`

**File:** `skyrl-agent/skyrl_agent/tasks/android/android_task.py`

**Modify** `initialize_runtime` — add early-return branch at top of method (before existing code):
```python
    @classmethod
    async def initialize_runtime(cls, env_config: Dict[str, Any]) -> List:
        # ── Mode B: Broker ────────────────────────────────────────────
        broker_url = env_config.get("broker_url")
        if broker_url:
            from skyrl_agent.runtime.android.pool_client import PoolClient, BrokerContainerManager
            pool_client = PoolClient(broker_url)
            if not await pool_client.check_broker_health():
                raise RuntimeError(f"Broker not reachable at {broker_url}")
            broker_manager = BrokerContainerManager(pool_client)
            await broker_manager.initialize()
            cls._container_manager = broker_manager  # ← same attribute as Mode A
            logger.info(f"Connected to container pool broker at {broker_url}")
            return []  # No pre-created RuntimeClients; containers acquired per-task

        # ── Mode A: Local (existing code, completely unchanged) ───────
        from skyrl_agent.runtime.android import ContainerManager, RuntimeClient
        # ... entire existing body unchanged ...
```

**Modify** `cleanup_runtime` — no changes needed! The existing code already does:
```python
    @classmethod
    async def cleanup_runtime(cls):
        if cls._container_manager is not None:
            await cls._container_manager.stop_health_monitor()  # no-op on BrokerContainerManager
            await cls._container_manager.cleanup()              # closes HTTP session
            cls._container_manager = None
```

Since `BrokerContainerManager.stop_health_monitor()` and `.cleanup()` are implemented, the existing cleanup code works for both modes without any changes.

### 8.2 `RuntimeClient.base_url` — support `host` attribute via getattr

**File:** `skyrl-agent/skyrl_agent/runtime/android/runtime_client.py`

This is the **only change** to an existing class. It's backward-compatible: `getattr` falls back to `'localhost'` when `host` attribute doesn't exist (Mode A).

```python
    @property
    def base_url(self) -> str:
        """Get base URL. Supports both ContainerInstance (local) and RemoteContainerInfo (broker)."""
        host = getattr(self.container, 'host', 'localhost')
        return f"http://{host}:{self.container.server_port}"
```

**Why this is safe for Mode A:** `ContainerInstance` has no `host` field → `getattr` returns `'localhost'` → identical to the current hardcoded `f"http://localhost:{port}"`.

### Files NOT modified (compared to previous design)

| File | Why no change needed |
|------|---------------------|
| `android_runner.py` | Always uses `_container_manager` — adapter handles Mode B transparently |
| `dispatchers.py` | Always calls `allocate_container()`/`release_container()` — adapter handles Mode B |
| `__init__.py` | No eager imports needed — `android_task.py` imports conditionally |

---

## 9. Configuration

### 9.1 Mode A — YAML (unchanged)

```yaml
env:
  pool_size: 16
  base_env_id: 0
  docker_image: "androidworld:v8"
  snapshot: "clean"
  buffer_size: 2
```

### 9.2 Mode B — YAML

```yaml
env:
  broker_url: "http://localhost:9100"    # ← this single key activates Mode B
  # Everything below is ignored — broker manages containers:
  # pool_size, base_env_id, docker_image, buffer_size — all ignored
```

Note: `num_workers` is **not needed** in Mode B config. `BrokerContainerManager.initialize()` fetches the pool size from the broker's `/status` endpoint and populates `self.containers` accordingly. The runner's existing `len(container_manager.containers)` just works.

### 9.3 Mode B — Broker startup

```bash
# Start once. Containers persist across experiments.
python -m skyrl_agent.runtime.android.pool_broker \
    --pool-size 24 \
    --docker-image androidworld:v8 \
    --port 9100 \
    --snapshot clean

# Or with systemd for production:
# [Unit]
# Description=Container Pool Broker
# After=docker.service
#
# [Service]
# ExecStart=python -m skyrl_agent.runtime.android.pool_broker --pool-size 24 --port 9100
# Restart=on-failure
```

---

## 10. Why No Broker-Side Reset Is Needed

`AndroidTrajectory.initialize_trajectory()` (line 50-65 of `android_trajectory.py`) does:

```python
async def initialize_trajectory(self):
    self.template_messages = self.task.get_instruction(self.data["instance"])
    payload = self._build_reset_payload()
    observation, info = await self.env_handle.reset(payload)  # ← resets container
    self.initial_observation = observation
```

Every task calls `env.reset()` which navigates to home screen and initializes a fresh task. The broker doesn't need to know about task semantics — it just tracks which containers are available.

### Container State Contamination Trade-off

Broker mode trades container cleanliness for startup speed. If experiment A crashes mid-trajectory (app installed, files written, settings changed), experiment B may get that container. The `env.reset()` navigates to home screen and reinitializes the task, but may not undo all side effects from the previous experiment.

This is an acceptable trade-off for most use cases. If a container gets into a bad state, it can be explicitly reported unhealthy via `POST /return {"env_id": X, "healthy": false}`, and the broker will destroy and replace it.

---

## 11. Testing Plan

### Unit Tests — `tests/test_pool_broker.py` (NEW)

```python
"""Tests for broker, pool_client, and BrokerContainerManager adapter."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from skyrl_agent.runtime.android.pool_broker import ContainerPoolBroker, PoolEntry, BrokerContainerState
from skyrl_agent.runtime.android.pool_client import PoolClient, RemoteContainerInfo, BrokerContainerManager


class TestBrokerAcquireReturn:
    @pytest.mark.asyncio
    async def test_acquire_returns_idle_and_marks_leased(self): ...
    @pytest.mark.asyncio
    async def test_acquire_skips_unhealthy_triggers_replace(self): ...
    @pytest.mark.asyncio
    async def test_acquire_timeout_raises(self): ...
    @pytest.mark.asyncio
    async def test_return_healthy_puts_back_in_queue(self): ...
    @pytest.mark.asyncio
    async def test_return_unhealthy_triggers_replace(self): ...

class TestBrokerHealthLoop:
    @pytest.mark.asyncio
    async def test_health_loop_rechecks_state_under_lock(self): ...
    @pytest.mark.asyncio
    async def test_health_loop_skips_recently_acquired_container(self): ...

class TestBrokerGC:
    @pytest.mark.asyncio
    async def test_gc_reclaims_dead_pid(self): ...
    @pytest.mark.asyncio
    async def test_gc_reclaims_reused_pid(self): ...
    @pytest.mark.asyncio
    async def test_gc_ignores_alive_pid(self): ...

class TestBrokerReplace:
    @pytest.mark.asyncio
    async def test_replace_uses_new_env_id(self): ...
    @pytest.mark.asyncio
    async def test_replace_stops_old_container(self): ...

class TestPoolClientRetry:
    @pytest.mark.asyncio
    async def test_acquire_retries_on_transient_error(self): ...
    @pytest.mark.asyncio
    async def test_acquire_fails_after_max_retries(self): ...

class TestBrokerContainerManagerAdapter:
    @pytest.mark.asyncio
    async def test_allocate_delegates_to_pool_client(self): ...
    @pytest.mark.asyncio
    async def test_release_delegates_to_pool_client(self): ...
    @pytest.mark.asyncio
    async def test_release_unhealthy_on_container_dead_error(self): ...
    @pytest.mark.asyncio
    async def test_start_health_monitor_is_noop(self): ...
    @pytest.mark.asyncio
    async def test_cleanup_closes_session(self): ...
    @pytest.mark.asyncio
    async def test_initialize_fetches_pool_size(self): ...

class TestRemoteContainerInfoCompat:
    def test_duck_typing_with_runtime_client(self):
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        info = RemoteContainerInfo(
            env_id=5, server_port=5010, emulator_port=5584,
            grpc_port=8584, host="192.168.1.100", container_id="abc",
        )
        client = RuntimeClient(info)
        assert client.base_url == "http://192.168.1.100:5010"

class TestModeAUnchanged:
    """Verify Mode A code path is not affected."""
    def test_no_broker_url_uses_container_manager(self): ...
    def test_cleanup_works_with_both_modes(self): ...
```

### Integration Test

```bash
# 1. Start broker
python -m skyrl_agent.runtime.android.pool_broker --pool-size 4 --port 9100

# 2. Verify broker
curl http://localhost:9100/health   # → {"status":"ok",...}
curl http://localhost:9100/status   # → {total:4, idle:4, ...}

# 3. Run experiment in Mode A (unchanged, no broker)
python train.py --config config/exp_local.yaml

# 4. Run experiment in Mode B (uses broker)
python train.py --config config/exp_broker.yaml   # has broker_url: http://localhost:9100

# 5. Run TWO experiments concurrently against same broker
python train.py --config config/exp_broker.yaml &
python train.py --config config/exp_broker.yaml &
```

---

## 12. Rollback Strategy

Mode B is **purely additive**. To revert to Mode A:

1. Remove `broker_url` from YAML config → Mode A runs, broker code never executes
2. Stop the broker process → no running process to maintain
3. Optionally remove `pool_broker.py` and `pool_client.py` → zero effect on Mode A

No existing file has its Mode A behavior altered.

---

## 13. Implementation Order

| Step | File(s) | Dependencies | Mode A affected? |
|------|---------|-------------|-----------------|
| 1 | `pool_broker.py` (new) | None | No |
| 2 | `pool_client.py` (new) | None | No |
| 3 | `runtime_client.py` L208 | None | No (getattr fallback) |
| 4 | `android_task.py` | Steps 1-2 | No (branch point) |
| 5 | `test_pool_broker.py` (new) | Steps 1-4 | No |

Steps 1-3 can all be done in parallel. Step 4 depends on 1-2. Step 3 is independent.

**Compared to previous design:** Steps reduced from 8 to 5 by eliminating modifications to `android_runner.py`, `dispatchers.py`, and `__init__.py`.

---

## 14. Summary of All Changes

| File | Type | What Changes | Mode A Impact |
|------|------|-------------|---------------|
| `runtime/android/pool_broker.py` | **NEW** | Standalone broker (FastAPI + CLI) | None |
| `runtime/android/pool_client.py` | **NEW** | PoolClient + BrokerContainerManager adapter | None |
| `runtime/android/runtime_client.py` | MODIFY | `base_url`: `getattr(container, 'host', 'localhost')` | None (getattr fallback = same behavior) |
| `tasks/android/android_task.py` | MODIFY | Add broker branch in `initialize_runtime()` only | None (branch not taken) |
| `tests/test_pool_broker.py` | **NEW** | Unit + integration tests | None |

**Total: 3 new files, 2 modified files. Zero behavioral changes in Mode A.**

### Key improvements over previous design (v1 → v2)

| Area | v1 (Previous) | v2 (Current) |
|------|---------------|--------------|
| **Modified files** | 5 existing files | 2 existing files |
| **Pattern** | `if pool_client` / `else container_manager` branches in dispatcher, runner, task | Adapter pattern: `BrokerContainerManager` implements same interface |
| **Dispatcher changes** | Dual-mode worker() with parallel code paths | None — dispatcher untouched |
| **Runner changes** | Pass pool_client to config, conditional num_workers | None — runner untouched |
| **Broker health checks** | Synchronous `requests.get()` blocking event loop | `asyncio.to_thread()` for all sync I/O |
| **Health loop race** | Check IDLE, skip to replace without re-checking | Re-check state under lock before replacement |
| **PID GC** | Bare `psutil.pid_exists(pid)` — PID reuse possible | `(pid, create_time)` tuple — PID reuse safe |
| **PoolClient resilience** | No retry on transient broker errors | 3 retries with backoff |
| **FastAPI lifecycle** | Deprecated `@app.on_event` | Modern `lifespan` context manager |
| **`num_workers` config** | Manual, must sync with broker pool_size | Auto-fetched from broker `/status` |
| **`__init__.py` imports** | Eager import of pool_client (always loaded) | No change — conditional import only |
