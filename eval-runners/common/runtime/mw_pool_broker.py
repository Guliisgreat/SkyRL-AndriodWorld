"""
MobileWorld Static Pool Broker — manages pre-existing MobileWorld containers.

Unlike pool_broker.py (which creates AndroidWorld containers on the fly),
this broker adopts already-running MobileWorld Docker containers and exposes
the same /acquire, /return, /status, /health API so experiment scripts can
use the broker protocol unchanged.

Usage:
    python -m skyrl_agent.runtime.android.mw_pool_broker \
        --containers 'http://localhost:6804=emulator-5554,http://localhost:6805=emulator-5554,...' \
        --port 9400

    # Auto-discover by scanning a port range
    python -m skyrl_agent.runtime.android.mw_pool_broker \
        --scan-range 6800-6820 --port 9400
"""

import argparse
import asyncio
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger


class ContainerState(str, Enum):
    IDLE = "IDLE"
    LEASED = "LEASED"


@dataclass
class MWContainer:
    env_id: int
    server_url: str
    server_port: int
    device_id: str
    state: ContainerState = ContainerState.IDLE
    pid: Optional[int] = None
    pid_create_time: Optional[float] = None
    leased_at: Optional[float] = None
    is_healthy: bool = True


class AcquireRequest(BaseModel):
    pid: int
    timeout: float = 300.0


class ReturnRequest(BaseModel):
    env_id: int
    healthy: bool = True


class MWPoolBroker:
    """Manages a static pool of pre-existing MobileWorld containers."""

    def __init__(
        self,
        containers: List[Tuple[str, str]],
        health_check_interval: float = 60.0,
        gc_interval: float = 120.0,
        max_lease_duration: float = 900.0,
    ):
        self.health_check_interval = health_check_interval
        self.gc_interval = gc_interval
        self.max_lease_duration = max_lease_duration
        self._start_time = time.time()

        self.registry: Dict[int, MWContainer] = {}
        self.available_queue: asyncio.Queue = asyncio.Queue()
        self._registry_lock = asyncio.Lock()

        for env_id, (server_url, device_id) in enumerate(containers):
            port = int(server_url.rstrip("/").rsplit(":", 1)[1])
            entry = MWContainer(
                env_id=env_id,
                server_url=server_url.rstrip("/"),
                server_port=port,
                device_id=device_id,
            )
            self.registry[env_id] = entry

        self._health_task: Optional[asyncio.Task] = None
        self._gc_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Health-check all containers and add healthy ones to the available queue."""
        healthy = 0
        for env_id, entry in sorted(self.registry.items()):
            ok = await asyncio.to_thread(self._check_health_sync, entry)
            entry.is_healthy = ok
            if ok:
                await self.available_queue.put(env_id)
                healthy += 1
                logger.info(f"env{env_id}: {entry.server_url} (device={entry.device_id}) -> healthy")
            else:
                logger.warning(f"env{env_id}: {entry.server_url} -> UNHEALTHY, excluded")
        logger.info(f"Pool ready: {healthy}/{len(self.registry)} containers available")

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

    def _check_health_sync(self, entry: MWContainer) -> bool:
        try:
            req = urllib.request.Request(f"{entry.server_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return (data.get("ok", False)
                        or data.get("status") in ("ok", "healthy")
                        or data.get("ready", False))
        except Exception:
            return False

    async def acquire(self, pid: int, timeout: float = 300.0) -> Dict[str, Any]:
        deadline = time.time() + timeout

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"No container available within {timeout}s")

            try:
                env_id = await asyncio.wait_for(
                    self.available_queue.get(), timeout=min(remaining, 10.0),
                )
            except asyncio.TimeoutError:
                continue

            entry = self.registry.get(env_id)
            if entry is None:
                continue

            healthy = await asyncio.to_thread(self._check_health_sync, entry)

            async with self._registry_lock:
                if env_id not in self.registry or entry.state != ContainerState.IDLE:
                    continue

                if not healthy:
                    logger.warning(f"env{env_id} unhealthy during acquire, skipping")
                    entry.is_healthy = False
                    continue

                entry.state = ContainerState.LEASED
                entry.pid = pid
                try:
                    entry.pid_create_time = psutil.Process(pid).create_time()
                except psutil.NoSuchProcess:
                    entry.pid_create_time = None
                entry.leased_at = time.time()

            emulator_port_num = 5554
            try:
                emulator_port_num = int(entry.device_id.split("-")[1])
            except (IndexError, ValueError):
                pass

            return {
                "env_id": env_id,
                "server_port": entry.server_port,
                "emulator_port": emulator_port_num,
                "device_id": entry.device_id,
                "host": "localhost",
                "server_url": entry.server_url,
            }

    async def return_container(self, env_id: int, healthy: bool = True):
        async with self._registry_lock:
            entry = self.registry.get(env_id)
            if entry is None:
                logger.warning(f"return: env{env_id} not in registry")
                return

            entry.pid = None
            entry.pid_create_time = None
            entry.leased_at = None
            entry.state = ContainerState.IDLE

        if healthy:
            # Reset container state before making it available again
            reset_ok = await asyncio.to_thread(self._reset_container_sync, entry)
            if not reset_ok:
                logger.warning(f"env{env_id}: reset failed, marking unhealthy")
                healthy = False

        entry.is_healthy = healthy
        if healthy:
            await self.available_queue.put(env_id)
            logger.debug(f"env{env_id} returned to pool (reset ok)")
        else:
            logger.warning(f"env{env_id} returned as unhealthy, will re-check later")

    def _reset_container_sync(self, entry: MWContainer) -> bool:
        """Call /reset on a container to fully reset state between tasks."""
        try:
            data = json.dumps({
                "task_name": "_reset",
                "req_device": entry.device_id,
            }).encode()
            req = urllib.request.Request(
                f"{entry.server_url}/reset",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                ok = result.get("ok", False)
                ms = result.get("reset_time_ms", 0)
                logger.info(f"env{entry.env_id}: reset {'ok' if ok else 'FAILED'} in {ms}ms")
                return ok
        except Exception as e:
            logger.error(f"env{entry.env_id}: reset failed: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        idle = sum(1 for e in self.registry.values() if e.state == ContainerState.IDLE)
        leased = sum(1 for e in self.registry.values() if e.state == ContainerState.LEASED)
        containers_info = []
        for env_id, entry in sorted(self.registry.items()):
            containers_info.append({
                "env_id": env_id,
                "state": entry.state.value,
                "pid": entry.pid,
                "server_port": entry.server_port,
                "device_id": entry.device_id,
                "healthy": entry.is_healthy,
            })
        return {
            "total": len(self.registry),
            "idle": idle,
            "leased": leased,
            "containers": containers_info,
        }

    async def _health_loop(self):
        while True:
            await asyncio.sleep(self.health_check_interval)
            async with self._registry_lock:
                to_check = [
                    (eid, e) for eid, e in self.registry.items()
                    if e.state == ContainerState.IDLE and not e.is_healthy
                ]
            for env_id, entry in to_check:
                ok = await asyncio.to_thread(self._check_health_sync, entry)
                if ok:
                    async with self._registry_lock:
                        if entry.state == ContainerState.IDLE and not entry.is_healthy:
                            entry.is_healthy = True
                            await self.available_queue.put(env_id)
                            logger.info(f"env{env_id} recovered, added back to pool")

    async def _gc_loop(self):
        while True:
            await asyncio.sleep(self.gc_interval)
            now = time.time()
            async with self._registry_lock:
                leased = [
                    (eid, e) for eid, e in self.registry.items()
                    if e.state == ContainerState.LEASED
                ]
            for env_id, entry in leased:
                should_reclaim = False
                reason = ""

                if entry.pid:
                    try:
                        proc = psutil.Process(entry.pid)
                        if (entry.pid_create_time is not None
                                and proc.create_time() != entry.pid_create_time):
                            should_reclaim = True
                            reason = f"pid {entry.pid} reused"
                    except psutil.NoSuchProcess:
                        should_reclaim = True
                        reason = f"pid {entry.pid} gone"

                if (not should_reclaim and entry.leased_at
                        and (now - entry.leased_at) > self.max_lease_duration):
                    should_reclaim = True
                    elapsed = now - entry.leased_at
                    reason = f"lease expired ({elapsed:.0f}s > {self.max_lease_duration:.0f}s)"

                if should_reclaim:
                    logger.warning(f"GC: reclaiming env{env_id} — {reason}")
                    async with self._registry_lock:
                        entry.state = ContainerState.IDLE
                        entry.pid = None
                        entry.pid_create_time = None
                        entry.leased_at = None
                        entry.is_healthy = True
                    await self.available_queue.put(env_id)


# ─── FastAPI App ──────────────────────────────────────────────────────────────

broker: Optional[MWPoolBroker] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.initialize()
    await broker.start_background_tasks()
    yield
    await broker.stop_background_tasks()


app = FastAPI(title="MobileWorld Pool Broker", lifespan=lifespan)


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
        "ok": True,
        "uptime": time.time() - broker._start_time,
        "pool_total": len(broker.registry),
    }


def scan_port_range(start: int, end: int) -> List[Tuple[str, str]]:
    """Auto-discover healthy MobileWorld containers in a port range."""
    found = []
    for port in range(start, end + 1):
        try:
            req = urllib.request.Request(f"http://localhost:{port}/health", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok", False) or data.get("status") == "ok":
                    devices = data.get("devices", ["emulator-5554"])
                    device_id = devices[0] if devices else "emulator-5554"
                    found.append((f"http://localhost:{port}", device_id))
        except Exception:
            pass
    return found


def parse_containers_arg(s: str) -> List[Tuple[str, str]]:
    """Parse 'url=device_id,url=device_id,...' into list of tuples."""
    result = []
    for spec in s.split(","):
        spec = spec.strip()
        if not spec:
            continue
        if "=" in spec:
            url, device_id = spec.split("=", 1)
            result.append((url.strip(), device_id.strip()))
        else:
            result.append((spec, "emulator-5554"))
    return result


def main():
    parser = argparse.ArgumentParser(description="MobileWorld Static Pool Broker")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--containers", type=str,
                       help="Container specs: 'url=device_id,...'")
    group.add_argument("--scan-range", type=str,
                       help="Auto-discover by scanning port range, e.g. '6800-6820'")

    parser.add_argument("--port", type=int, default=9400)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--health-interval", type=float, default=60.0)
    parser.add_argument("--gc-interval", type=float, default=120.0)
    parser.add_argument("--max-lease", type=float, default=900.0,
                        help="Max seconds a container can be leased before GC reclaims it")
    args = parser.parse_args()

    if args.scan_range:
        start, end = args.scan_range.split("-")
        containers = scan_port_range(int(start), int(end))
        if not containers:
            logger.error(f"No healthy containers found in port range {args.scan_range}")
            return
        logger.info(f"Discovered {len(containers)} containers via port scan")
    else:
        containers = parse_containers_arg(args.containers)

    global broker
    broker = MWPoolBroker(
        containers=containers,
        health_check_interval=args.health_interval,
        gc_interval=args.gc_interval,
        max_lease_duration=args.max_lease,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
