# Container Runtime Async Optimizations

Performance analysis and optimization plan for the host-side container management layer
(`skyrl_agent/runtime/android/`). This document focuses on the **async event loop,
health monitoring, and container lifecycle** — the orchestration code that manages the
Docker container pool and coordinates trajectory workers.

This is a companion to `[ToDo] Android Runtime ACCELERATION.md`, which covers emulator-
and data-transfer-level optimizations inside the containers.

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Context](#system-context)
3. [Problem: Event Loop Starvation](#problem-event-loop-starvation)
4. [Optimization 1: Async-ify Blocking Calls](#optimization-1-async-ify-blocking-calls)
5. [Optimization 2: Parallel Health Monitoring](#optimization-2-parallel-health-monitoring)
6. [Optimization 3: Eliminate Redundant Health Checks](#optimization-3-eliminate-redundant-health-checks)
7. [Optimization 4: Adaptive Container Boot Polling](#optimization-4-adaptive-container-boot-polling)
8. [Optimization 5: Parallel Container Cleanup](#optimization-5-parallel-container-cleanup)
9. [Optimization 6: Async Port Allocation](#optimization-6-async-port-allocation)
10. [Optimization 7: Worker Overprovisioning](#optimization-7-worker-overprovisioning)
11. [Optimization 8: Shared Health-Check Session](#optimization-8-shared-health-check-session)
12. [Implementation Plan](#implementation-plan)
13. [Verification](#verification)

---

## Executive Summary

The container management layer (`ContainerManager`, `HealthMonitor`, `RuntimeClient`)
runs in a single Python asyncio event loop alongside 16 trajectory workers. The core
problem is that **synchronous blocking calls in the health monitoring and container
lifecycle paths freeze the entire event loop**, stalling all 16 trajectory workers for
seconds to minutes at a time.

The eight optimizations in this document are all **low-effort, isolated changes** that
require no architectural redesign. Combined, they are expected to:

- Eliminate 100+ seconds of event loop stalls per health-monitor cycle
- Reduce container boot detection time by 5-20 seconds per container
- Cut cleanup time from minutes to seconds
- Improve steady-state trajectory throughput by 20-40%

---

## System Context

### Event Loop Architecture

A single asyncio event loop runs everything:

```
┌─────────────────── asyncio event loop ───────────────────┐
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │ Trajectory Workers (16 concurrent)            │        │
│  │                                               │        │
│  │  worker 0:  allocate → init → run → eval → release   │
│  │  worker 1:  allocate → init → run → eval → release   │
│  │  ...                                          │        │
│  │  worker 15: allocate → init → run → eval → release   │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │ HealthMonitor (background task)               │        │
│  │  every 30s: check all 16 containers           │        │
│  │  on unhealthy: failover or replace            │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  ┌──────────────────────────────────────────────┐        │
│  │ RuntimeClient instances (per-worker)          │        │
│  │  aiohttp POST /reset, /step, /step_adb        │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Critical property**: In a single-threaded event loop, any synchronous blocking call
blocks ALL coroutines. When `HealthMonitor` calls `requests.get()` (synchronous), all
16 trajectory workers freeze until that HTTP request completes.

### Typical Configuration (from YAML)

```yaml
env:
  pool_size: 16           # Main container pool
  buffer_size: 2          # Hot standby containers
  docker_image: androidworld-adb:v8
dispatcher:
  max_parallel_agents: 16 # Concurrent trajectory workers
```

### Key File Locations

| Component | File | Role |
|---|---|---|
| ContainerManager | `runtime/android/container_manager.py` | Pool management facade |
| HealthMonitor | `runtime/android/container_manager.py:412` | Background health checks |
| RuntimeClient | `runtime/android/runtime_client.py` | Async HTTP client to containers |
| Dispatcher | `dispatcher/dispatchers.py:938` | Worker pool orchestration |

---

## Problem: Event Loop Starvation

### Root Cause

The `HealthMonitor` and `ContainerManager` call synchronous blocking functions from
within the asyncio event loop:

| Blocking Call | Location (container_manager.py) | Max Block Time |
|---|---|---|
| `container.container.reload()` | lines 507, 1315 | 1-5s |
| `requests.get(..., timeout=(3,5))` | lines 543-546 | 8s per retry |
| `requests.get(..., timeout=(3,10))` | lines 1345-1348 | 13s |
| `time.sleep(2.0)` | line 575 | 2s (x2 retries = 4s) |
| `time.sleep(0.5)` | line 370 | 0.5s (x30 polls = 15s) |
| `time.sleep(1)` | line 233 | 1s |
| `container.container.stop()` | line 1576 | 1-10s |

### Impact Quantification

**HealthMonitor._monitor_loop** (lines 582-597) iterates over containers sequentially:

```python
for container in self.containers:               # 16 containers, one by one
    is_healthy = self.check_health(container)    # calls reload() + requests.get()
    if not is_healthy:
        await self._handle_unhealthy_container(container)
```

Per container, `check_health()` calls:
1. `container.container.reload()` → 1-5s blocking
2. `requests.get()` with up to 2 retries, 2s sleep between → 4-18s blocking

**Worst-case single monitor cycle (16 containers)**:
- 16 × (5s reload + 18s HTTP with retries) = **368 seconds**
- During this time: **all 16 trajectory workers frozen**

**Typical case (healthy containers)**:
- 16 × (1s reload + 0.5s HTTP) = **24 seconds** of event loop blocking
- This happens **every 30 seconds** (the monitor interval)

Even in the typical case, the event loop is blocked for 24 out of every 54 seconds
(30s interval + 24s check time), meaning trajectory workers are stalled **44% of the
time** just from health monitoring.

### Visualization

```
Timeline (1 monitor cycle, 4 containers shown, typical case):

Event Loop:
  |-- check c0 (2s BLOCKED) --|-- check c1 (2s BLOCKED) --|-- check c2 --|-- check c3 --|

Worker 0:  .... step() .......|FROZEN...................|FROZEN.........|.. step() ....
Worker 1:  .. reset() ........|FROZEN...................|FROZEN.........|... step() ...
Worker 2:  ....... step() ....|FROZEN...................|FROZEN.........|. eval() .....
Worker 3:  . allocate() ......|FROZEN...................|FROZEN.........|.. init() ....

                               ↑ All workers stall here ↑
```

---

## Optimization 1: Async-ify Blocking Calls

**Priority**: CRITICAL | **Effort**: Low | **Impact**: +20-40% throughput

### Problem

Every synchronous call in the table above blocks the asyncio event loop. The two
highest-impact offenders are:

1. **`requests.get()`** — Synchronous HTTP library used for health checks.
   The project already uses `aiohttp` for `RuntimeClient`, but `HealthMonitor` and
   `ContainerManager._check_container_health` use the synchronous `requests` library.

2. **`container.container.reload()` / `.stop()`** — Docker SDK calls that make
   synchronous HTTP requests to the Docker daemon socket.

3. **`time.sleep()`** — Blocks the event loop instead of yielding control. Used for
   retry delays in `_check_http_health` (line 575) and container removal polling
   (line 370).

### Solution

**Strategy A (preferred for HTTP calls)**: Replace `requests.get()` with `aiohttp` to
make health checks fully non-blocking. This requires the `HealthMonitor` to become
async-aware for its HTTP calls.

```python
# Before (container_manager.py, lines 522-580)
# --- Blocks event loop for 8-18s per container ---
def _check_http_health(self, container, max_retries=2, timeout=(3, 5)):
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                f"http://localhost:{container.server_port}/health",
                timeout=timeout,
            )
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        if attempt < max_retries:
            time.sleep(2.0)    # Blocks event loop!
    container.is_healthy = False
    return False


# After
# --- Fully non-blocking, event loop stays free ---
async def _check_http_health(self, container, max_retries=2, timeout=8.0):
    for attempt in range(max_retries + 1):
        try:
            async with self._health_session.get(
                f"http://localhost:{container.server_port}/health",
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 200:
                    return True
                elif response.status == 503:
                    pass  # busy, retry
                else:
                    container.is_healthy = False
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        if attempt < max_retries:
            await asyncio.sleep(2.0)   # Yields control to event loop
    container.is_healthy = False
    return False
```

**Strategy B (for Docker SDK calls)**: Wrap in `asyncio.to_thread()` to run in the
default thread pool executor. The Docker SDK is not async-native, so this is the
simplest fix.

```python
# Before (container_manager.py, lines 505-520)
# --- Blocks event loop for 1-5s ---
def _check_docker_status(self, container):
    try:
        container.container.reload()    # Synchronous Docker API call
        if container.container.status != "running":
            container.is_healthy = False
            return False
    except docker.errors.NotFound:
        container.is_healthy = False
        return False
    return True


# After
# --- Runs in thread pool, event loop stays free ---
async def _check_docker_status(self, container):
    try:
        await asyncio.to_thread(container.container.reload)
        if container.container.status != "running":
            container.is_healthy = False
            return False
    except docker.errors.NotFound:
        container.is_healthy = False
        return False
    return True
```

**Strategy C (for time.sleep)**: Replace with `await asyncio.sleep()`.

```python
# Before (line 575)
time.sleep(2.0)

# After
await asyncio.sleep(2.0)
```

```python
# Before (line 370, container removal polling)
time.sleep(0.5)

# After
await asyncio.sleep(0.5)
```

### Cascade Changes

Making `_check_docker_status` and `_check_http_health` async means `check_health` must
become async, which means callers must be updated:

```python
# check_health becomes async
async def check_health(self, container):
    container.last_health_check = time.time()
    if not await self._check_docker_status(container):
        return False
    if not await self._check_http_health(container):
        return False
    container.is_healthy = True
    return True
```

Callers that must be updated:
- `HealthMonitor._monitor_loop` (line 589) — already async
- `ContainerManager.allocate_container` (line 1114) — already async
- `ContainerManager.release_container` (line 1180) — already async
- `ContainerManager.quick_ping` (line 1426) — already async

All callers are already async, so the cascade is straightforward.

### Expected Impact

| Scenario | Before (blocking) | After (async) |
|---|---|---|
| Single health check | 2-18s event loop blocked | 0s blocked (runs in background) |
| Full monitor cycle (16 containers) | 24-368s blocked | 0s blocked |
| Event loop availability | ~56% (healthy) to ~0% (degraded) | ~100% |
| Trajectory throughput | Stalls during monitoring | Continuous |

---

## Optimization 2: Parallel Health Monitoring

**Priority**: HIGH | **Effort**: Low | **Impact**: Monitor cycle 10x faster

### Problem

`HealthMonitor._monitor_loop` (lines 582-597) checks containers sequentially:

```python
async def _monitor_loop(self, interval):
    while self._running:
        await asyncio.sleep(interval)
        for container in self.containers:       # One by one
            if not self._running:
                break
            is_healthy = self.check_health(container)
            if not is_healthy:
                await self._handle_unhealthy_container(container)
```

Even after Optimization 1 makes individual checks non-blocking, the loop still
serializes them: check container 0, wait for result, check container 1, wait, etc.
Total wall time = sum of all individual check times.

### Solution

Check all containers concurrently using `asyncio.gather`:

```python
async def _monitor_loop(self, interval):
    while self._running:
        try:
            await asyncio.sleep(interval)

            # Snapshot the container list to avoid mutation during iteration.
            # self.containers is modified in-place (under _containers_lock) by
            # replacement flows, so iterating the live list risks RuntimeError.
            containers_snapshot = list(self.containers)

            # Check all containers in parallel
            results = await asyncio.gather(*[
                self._check_one(container)
                for container in containers_snapshot
            ], return_exceptions=True)

            # Handle unhealthy containers (sequentially is fine here —
            # failover involves pool mutation and should not race)
            for container, result in zip(containers_snapshot, results):
                if not self._running:
                    break
                if isinstance(result, Exception):
                    logger.error(
                        f"[HealthMonitor] Check failed for env{container.env_id}: {result}"
                    )
                    continue
                if not result:  # result is False → unhealthy
                    await self._handle_unhealthy_container(container)

            if self._on_status_log:
                self._on_status_log()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[HealthMonitor] Error in monitor loop: {e}")

async def _check_one(self, container):
    """Check a single container's health. Returns True if healthy."""
    return await self.check_health(container)
```

### Why Sequential Failover Handling Is Fine

`_handle_unhealthy_container` modifies the container pool (removes from main, activates
backup, creates replacement). Running these in parallel could cause race conditions on
`self.containers` and `self.backup_containers`. Since unhealthy events are rare (only
during failures), sequential handling has negligible cost.

### Expected Impact

| Metric | Before (sequential) | After (parallel) |
|---|---|---|
| Monitor cycle wall time (16 containers, healthy) | 24s | 1.5s |
| Monitor cycle wall time (16 containers, worst-case) | 368s | 18s |
| Detection latency for container death | Up to cycle_time + position_in_list | cycle_time + single_check_time |

The monitor cycle now takes as long as the **slowest single container check** instead
of the **sum of all checks**.

---

## Optimization 3: Eliminate Redundant Health Checks

**Priority**: HIGH | **Effort**: Low | **Impact**: -30-60s blocking per minute

### Problem

The same container is health-checked up to 3 times in quick succession:

1. **Background monitor** (`_monitor_loop`, line 589): Every 30 seconds
2. **On allocation** (`allocate_container`, line 1113-1116): When worker picks up work
3. **On release** (`release_container`, line 1180): When worker finishes trajectory

A typical trajectory takes 40-150 seconds. A container running a 60-second trajectory
gets checked:
- Once by the monitor during the trajectory (~30s interval)
- Once when allocated (start)
- Once when released (end)

That's **3 full health checks** (Docker reload + HTTP GET) within 60 seconds. Each
check costs 1.5-18s of blocking time (before Optimization 1) or 1.5-18s of wall time
(after Optimization 1).

### Solution

Introduce a TTL-based health cache. If a container was checked recently and found
healthy, skip the check:

```python
# Add to HealthMonitor or ContainerManager

HEALTH_CHECK_TTL = 15.0  # seconds — skip check if last check was within this window

def _is_recently_healthy(self, container: ContainerInstance) -> bool:
    """
    Return True if the container was checked healthy within the TTL window.

    This avoids redundant Docker API + HTTP calls when the background monitor
    has already verified the container recently. The TTL must be shorter than
    the monitor interval (30s) to ensure no container goes unchecked.
    """
    age = time.time() - container.last_health_check
    return age < self.HEALTH_CHECK_TTL and container.is_healthy
```

Apply to allocation:

```python
# allocate_container (line 1100-1140)
async def allocate_container(self, batch_idx=None, trajectory_id=None):
    ...
    while attempts < max_attempts:
        container = await asyncio.wait_for(self.available_queue.get(), ...)

        # Skip full check if recently verified by background monitor
        if self._is_recently_healthy(container):
            is_healthy = True
        elif self._health_monitor:
            is_healthy = await self._health_monitor.check_health(container)
        else:
            is_healthy = await self._check_container_health(container)
        ...
```

Remove the health check on release entirely. Rationale:
- The container just completed a trajectory, so it was responsive moments ago.
- The background monitor will check it within 30 seconds.
- If it becomes unhealthy, the next `allocate_container` will catch it.

```python
# release_container (line 1146-1194)
async def release_container(self, container, success=True, error=None):
    ...
    # REMOVED: Health check on release.
    # Rationale: background monitor checks every 30s, and the next
    # allocate_container will verify health before handing it out.
    # This eliminates one full Docker + HTTP check per trajectory.
    container.state = "ready"
    container.current_trajectory = None
    await self.available_queue.put(container)
```

### Risk Analysis

| Scenario | Without this optimization | With this optimization |
|---|---|---|
| Container dies between release and next allocate | Caught on release check | Caught on next allocate check (delayed by at most queue wait) |
| Container dies during trajectory | Caught by RuntimeClient retry → ContainerDeadError | Same (unchanged) |
| Container dies while idle in queue | Caught by background monitor | Same (unchanged) |

The only new risk is a container dying between release and the next allocation, which
would previously be caught on release. With this change, it's caught on the next
allocation instead — a delay of at most a few seconds (queue wait time). This is
acceptable because:
- The container was just responsive (it completed a trajectory)
- A sudden death in the seconds between release and allocation is very rare
- Even if it happens, the allocator's health check catches it before any trajectory is affected

### Expected Impact

| Metric | Before | After |
|---|---|---|
| Health checks per trajectory | 3 (allocate + release + monitor) | 1-2 (monitor + maybe allocate) |
| Blocking time per trajectory | 4.5-54s | 0-18s |
| Redundant Docker API calls per minute (16 containers, 60s trajectories) | ~32 | ~0 |

---

## Optimization 4: Adaptive Container Boot Polling

**Priority**: MEDIUM | **Effort**: Low | **Impact**: -5-20s per container creation

### Problem

`ContainerFactory.wait_for_ready` (lines 381-398) has two inefficiencies:

1. **Static 45-second initial wait** (line 383): Always sleeps 45 seconds before the
   first health check poll, even if the server is ready in 25 seconds.

2. **Fixed 10-second polling interval** (line 396, `RETRY_INTERVAL = 10`): After the
   initial wait, checks every 10 seconds. If the server becomes ready 1 second after
   a failed poll, we waste 9 seconds.

```python
# Current implementation
async def wait_for_ready(self, server_port, env_id, timeout=SERVER_TIMEOUT):
    logger.info(f"env{env_id}: Waiting 45s for emulator to boot...")
    await asyncio.sleep(45)                   # Always 45s, even if ready sooner

    start_time = time.time()
    while time.time() - start_time < timeout:
        if self._check_server_health(server_port):    # Sync blocking call
            return True
        await asyncio.sleep(RETRY_INTERVAL)   # Fixed 10s between checks

    raise TimeoutError(...)
```

Combined, a container that's actually ready at t=30s won't be detected until t=55s
(45s wait + 10s poll), wasting 25 seconds.

### Solution

Replace the two-phase approach with a single adaptive polling loop:

```python
async def wait_for_ready(self, server_port, env_id, timeout=SERVER_TIMEOUT):
    """
    Wait for the container's health endpoint to respond.

    Uses adaptive polling: starts checking early (emulators occasionally boot
    fast), with increasing intervals to avoid hammering a slow-booting server.

    Polling schedule:
      - First check at 15s (some emulators boot in 20-25s with warm snapshots)
      - Interval grows from 3s to 10s (1.5x increase per poll)
      - Total timeout unchanged (SERVER_TIMEOUT = 600s)
    """
    start_time = time.time()

    # Wait a minimum before first check — emulator can't possibly be ready before this
    INITIAL_DELAY = 15.0
    await asyncio.sleep(INITIAL_DELAY)

    delay = 3.0       # Start with 3-second intervals
    MAX_DELAY = 10.0   # Cap at 10 seconds
    GROWTH = 1.5       # Multiply delay by 1.5 each iteration
    attempt = 0

    while time.time() - start_time < timeout:
        attempt += 1

        # Run the health check in a thread to avoid blocking the event loop
        # (_check_server_health uses synchronous requests.get)
        is_ready = await asyncio.to_thread(self._check_server_health, server_port)

        if is_ready:
            elapsed = time.time() - start_time
            logger.info(
                f"[ContainerFactory] env{env_id}: Health check passed after "
                f"{elapsed:.1f}s ({attempt} polls)"
            )
            return True

        if attempt % 5 == 0:
            elapsed = time.time() - start_time
            logger.debug(
                f"[ContainerFactory] env{env_id}: Not ready after {elapsed:.1f}s "
                f"({attempt} polls, next check in {delay:.1f}s)"
            )

        await asyncio.sleep(delay)
        delay = min(delay * GROWTH, MAX_DELAY)

    raise TimeoutError(
        f"Container env{env_id} (port {server_port}) failed to become ready "
        f"within {timeout}s"
    )
```

### Polling Schedule Comparison

```
Current:
  0s ──────────────── 45s ──── 55s ──── 65s ──── 75s ──── ...
  │     (sleeping)     │ poll  │ poll  │ poll  │ poll
                                ↑ Server ready at 30s, detected at 55s (25s waste)

Proposed:
  0s ──── 15s ── 18s ── 22.5s ── 29s ── 37s ── 47s ── 57s ── ...
  │        │ poll │ poll  │ poll  │poll │poll  │ poll │ poll
                           ↑ Server ready at 30s, detected at 29-37s (0-7s waste)
```

### Also Fix: Blocking _check_server_health

Note the `await asyncio.to_thread()` wrapper above. The underlying
`_check_server_health` (line 400-405) uses synchronous `requests.get`:

```python
def _check_server_health(self, server_port):
    try:
        response = requests.get(f"http://localhost:{server_port}/health", timeout=(10, 10))
        return response.status_code == 200
    except Exception:
        return False
```

Wrapping in `asyncio.to_thread` ensures this doesn't block the event loop during the
polling phase of parallel container creation (`create_pool_parallel` creates up to 8
containers concurrently, each running `wait_for_ready`).

### Expected Impact

| Metric | Before | After |
|---|---|---|
| Detection latency (server ready at 25s) | 55s | 25.5s |
| Detection latency (server ready at 30s) | 55s | 29-37s |
| Detection latency (server ready at 50s) | 55s | 50-57s |
| Wasted time per container (typical) | 15-25s | 0-7s |
| Pool creation (18 containers, max_concurrent=8) | ~3 batches × 80s = 240s | ~3 batches × 60s = 180s |

---

## Optimization 5: Parallel Container Cleanup

**Priority**: MEDIUM | **Effort**: Low | **Impact**: Cleanup 10-18x faster

### Problem

`ContainerManager.cleanup` (lines 1721-1753) stops all containers sequentially:

```python
async def cleanup(self):
    all_containers = self.containers + self.backup_containers  # 18 containers
    for container_instance in all_containers:
        try:
            container_instance.container.stop()  # 1-10s each, SYNCHRONOUS
        except Exception as e:
            ...
    self.containers.clear()
    self.backup_containers.clear()
```

With 18 containers, each taking 1-10s to stop, cleanup takes **18-180 seconds**.
During this time the event loop is completely blocked.

### Solution

Stop all containers in parallel using `asyncio.to_thread`:

```python
async def cleanup(self):
    """Stop all containers in both pool and buffer."""
    all_containers = self.containers + self.backup_containers

    if not all_containers:
        logger.info("[ContainerManager] No containers to cleanup")
        return

    logger.info(
        f"[ContainerManager] Cleaning up {len(self.containers)} pool + "
        f"{len(self.backup_containers)} buffer containers..."
    )

    # Stop all containers in parallel (each runs in thread pool)
    results = await asyncio.gather(*[
        asyncio.to_thread(self._stop_container_safe, c)
        for c in all_containers
    ], return_exceptions=True)

    # Log any failures
    for container, result in zip(all_containers, results):
        if isinstance(result, Exception):
            logger.warning(
                f"[ContainerManager] Error stopping env{container.env_id}: {result}"
            )

    self.containers.clear()
    self.backup_containers.clear()
    if self.available_queue is not None:
        while True:
            try:
                self.available_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.available_queue = None

    logger.info("[ContainerManager] Cleanup complete")
```

### Expected Impact

| Metric | Before | After |
|---|---|---|
| Cleanup time (18 containers) | 18-180s | 1-10s (bounded by slowest single stop) |
| Event loop blocked | Entire cleanup duration | 0s (all in thread pool) |

---

## Optimization 6: Async Port Allocation

**Priority**: MEDIUM | **Effort**: Low | **Impact**: Unblocks event loop during replacement

### Problem

`PortAllocator.preallocate_ports` (lines 239-271) is called during container
replacement and acquires a `FileLock` while querying system ports. Both the lock and
the queries are synchronous:

```python
def preallocate_ports(self, pool_size, base_env_id=0):
    lock = FileLock(str(self.lock_file))       # File-based lock
    with lock:                                  # Blocks until acquired
        used_ports = self.get_used_ports()      # psutil + Docker API (sync)
        for i in range(pool_size):
            # ... port allocation logic
```

This is called from `_create_container_internal` (line 1563), which runs during:
- Container replacement (HealthMonitor failover path)
- Backfill after pool creation failures
- Sync replacement when no backup available

All of these are async functions that currently block the event loop during port
allocation.

### Solution

Wrap the entire `preallocate_ports` call in `asyncio.to_thread` at the call site:

```python
# In _create_container_internal (line 1563)
# Before:
ports = self._port_allocator.preallocate_ports(pool_size=1, base_env_id=env_id)[0]

# After:
ports = (await asyncio.to_thread(
    self._port_allocator.preallocate_ports, pool_size=1, base_env_id=env_id
))[0]
```

The same change should be applied to the initial pool creation in
`create_pool_parallel` (line 952):

```python
# Before:
port_tuples = self._port_allocator.preallocate_ports(
    pool_size=total_containers, base_env_id=base_env_id,
)

# After:
port_tuples = await asyncio.to_thread(
    self._port_allocator.preallocate_ports,
    pool_size=total_containers,
    base_env_id=base_env_id,
)
```

### Expected Impact

Modest but important: prevents a 0.1-1s event loop stall during each container
replacement. More importantly, it prevents the `FileLock` from freezing all workers
if another process holds the lock (which could block indefinitely).

---

## Optimization 7: Worker Overprovisioning

**Priority**: LOW | **Effort**: Trivial | **Impact**: Better tail latency

### Problem

The dispatcher (dispatchers.py:975) creates exactly as many workers as containers:

```python
num_workers = cfg.get("num_workers", len(container_manager.containers))
```

If one container is slow (degraded emulator, slow screenshot), its worker is stuck
while the container sits idle after being released back to the queue. Since
`num_workers == pool_size`, no other worker is available to pick up work from the queue
using that now-idle container.

Example timeline:

```
Workers = Containers = 3, Trajectories = 6

Worker 0: |--- traj 0 (60s) ---|--- traj 3 (60s) ---|
Worker 1: |--- traj 1 (60s) ---|--- traj 4 (60s) ---|
Worker 2: |------ traj 2 (120s, slow container) ------|--- traj 5 (60s) ---|
                                                       ↑
                                    Workers 0,1 idle for 60s, no work to pick up

Total: 180s
```

With one extra worker:

```
Workers = 4, Containers = 3, Trajectories = 6

Worker 0: |--- traj 0 (60s) ---|--- traj 4 (60s) ---|
Worker 1: |--- traj 1 (60s) ---|--- traj 5 (60s) ---|
Worker 2: |------ traj 2 (120s, slow container) ------|
Worker 3: |  (wait for container) |--- traj 3 (60s) ---|

Total: 120s
```

Worker 3 picks up traj 3 as soon as Worker 0 or 1 releases their container.

### Solution

Add a small worker surplus (2 extra workers):

```python
# dispatchers.py, line 975
# Before:
num_workers = cfg.get("num_workers", len(container_manager.containers))

# After:
num_workers = cfg.get(
    "num_workers",
    len(container_manager.containers) + 2
)
```

The extra workers simply block on `allocate_container()` until a container becomes
available. They add negligible overhead (just coroutines waiting on a queue) but
ensure that freed containers are immediately picked up even if some workers are stuck
on slow trajectories.

### Risk

None. Extra workers just wait on `asyncio.Queue.get()` until a container is available.
If all containers are busy, the extra workers are idle with zero CPU cost. The `Queue`
guarantees FIFO ordering, so fairness is maintained.

---

## Optimization 8: Shared Health-Check Session

**Priority**: LOW | **Effort**: Low | **Impact**: Less TCP overhead, faster checks

### Problem

`_check_http_health` and `_check_container_health` create a new TCP connection for
every health check via `requests.get()`. With 16 containers checked every 30 seconds,
that's **32 TCP handshakes per minute** (SYN/SYN-ACK/ACK), plus TLS if ever enabled.

Meanwhile, `RuntimeClient` already uses a persistent `aiohttp.ClientSession` with
connection pooling for step/reset calls.

### Solution

After Optimization 1 converts health checks to `aiohttp`, share a single
`aiohttp.ClientSession` across all health checks:

```python
class HealthMonitor:
    def __init__(self, containers, ...):
        ...
        # Shared session for health checks — connection pooling with keep-alive
        self._health_session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self):
        if self._health_session is None:
            # Limit total connections to avoid overwhelming Docker host
            connector = aiohttp.TCPConnector(limit=20, keepalive_timeout=60)
            self._health_session = aiohttp.ClientSession(connector=connector)

    async def stop(self):
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            ...
        if self._health_session:
            await self._health_session.close()
            self._health_session = None
```

### Expected Impact

- Eliminates TCP handshake overhead for health checks (~1-3ms per check, minor)
- Enables HTTP keep-alive, reducing kernel socket churn
- Consistent with the existing `RuntimeClient` pattern

---

## Implementation Plan

### Phase 1: Event Loop Unblocking (Highest Impact)

These three changes are independent and can be implemented in parallel.
They address the critical event-loop starvation problem.

| # | Optimization | Files Changed | Estimated Effort |
|---|---|---|---|
| 1 | Async-ify blocking calls | `container_manager.py` | 2-3 hours |
| 2 | Parallel health monitoring | `container_manager.py` | 1 hour |
| 3 | Eliminate redundant checks | `container_manager.py` | 1 hour |

**Testing**: Run existing unit tests (if any), then validate with a small pool
(4 containers) by observing event loop responsiveness during health check cycles.
Key metric: trajectory step latency should not spike during health monitoring.

### Phase 2: Boot and Lifecycle

| # | Optimization | Files Changed | Estimated Effort |
|---|---|---|---|
| 4 | Adaptive boot polling | `container_manager.py` | 1 hour |
| 5 | Parallel cleanup | `container_manager.py` | 30 minutes |
| 6 | Async port allocation | `container_manager.py` | 30 minutes |

**Testing**: Measure pool creation time before/after. Measure cleanup time.

### Phase 3: Fine-Tuning

| # | Optimization | Files Changed | Estimated Effort |
|---|---|---|---|
| 7 | Worker overprovisioning | `dispatchers.py` | 15 minutes |
| 8 | Shared health session | `container_manager.py` | 30 minutes |

**Testing**: Run a full training batch and compare throughput/completion time.

### Total Estimated Effort: ~1 day

---

## Verification

### Key Metrics to Track Before/After

| Metric | How to Measure | Expected Improvement |
|---|---|---|
| Event loop block time | Add `asyncio` loop monitoring (`loop.slow_callback_duration`) | Near-zero (from 24-368s per cycle) |
| Health monitor cycle time | Log timestamps at start/end of `_monitor_loop` iteration | 1.5-18s (from 24-368s) |
| Container boot detection time | Log timestamp in `wait_for_ready` | -5-20s per container |
| Cleanup time | Log timestamps in `cleanup()` | 1-10s (from 18-180s) |
| Trajectory throughput | Count completed trajectories per minute | +20-40% |
| Tail latency (p99 trajectory time) | Track per-trajectory wall time | Reduced (less queuing behind blocked loop) |

### Quick Smoke Test

After implementing Phase 1, run this diagnostic:

```python
import asyncio
import time

# Patch the event loop to detect blocking
class MonitoredLoop(asyncio.SelectorEventLoop):
    def _run_once(self):
        start = time.monotonic()
        super()._run_once()
        elapsed = time.monotonic() - start
        if elapsed > 0.5:  # Flag anything blocking > 500ms
            print(f"WARNING: Event loop blocked for {elapsed:.2f}s")

# Use during testing
loop = MonitoredLoop()
asyncio.set_event_loop(loop)
```

If no warnings appear during a health check cycle, the async-ification is working.
Before the fix, you would see dozens of warnings per cycle.

---

## Changelog

| Date | Author | Changes |
|------|--------|---------|
| 2025-02-11 | Claude | Initial document — 8 optimizations for container runtime async performance |
