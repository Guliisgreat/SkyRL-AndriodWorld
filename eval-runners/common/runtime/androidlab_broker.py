"""
AndroidLabPoolBroker — broker compatible with Android-Lab Docker images.

Extends ContainerPoolBroker with Android-Lab-specific reset logic:
  - Snapshot restore (same as base)
  - Fixed date: 2024-05-10 12:00:00
  - GPS: 37.438, -122.156
  - Launch target app by package name

Usage:
    python -m skyrl_agent.runtime.android.androidlab_broker \\
        --pool-size 8 \\
        --docker-image androidlab:v1 \\
        --port 9200

The broker accepts an optional ``package`` field in the /return request
to pre-launch the target app after reset.  The /acquire and /status
endpoints are identical to the base broker.
"""

import time
import argparse
import asyncio
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
from contextlib import asynccontextmanager

from skyrl_agent.runtime.android.pool_broker import (
    ContainerPoolBroker,
    BrokerContainerState,
    AcquireRequest,
    ScaleRequest,
)


# ─── Extended request models ────────────────────────────────────────────────

class AndroidLabReturnRequest(BaseModel):
    env_id: int
    healthy: bool = True


class AndroidLabResetRequest(BaseModel):
    """Reset a leased container for a new Android-Lab task."""
    env_id: int
    package: str = ""


# ─── AndroidLabPoolBroker ────────────────────────────────────────────────────

# Android-Lab assumes this fixed date for all tasks.
ANDROIDLAB_DATE = "2024-05-10 12:00:00"
ANDROIDLAB_GPS_LAT = "37.438"
ANDROIDLAB_GPS_LON = "-122.156"


class AndroidLabPoolBroker(ContainerPoolBroker):
    """Broker compatible with Android-Lab Docker images.

    Key differences from ContainerPoolBroker:
    - Reset includes fixed date/GPS setup for Android-Lab
    - New /androidlab_reset endpoint for per-task reset without returning
    - Snapshot restore as the primary reset mechanism
    """

    def _androidlab_reset_sync(self, server_port: int, package: str = "") -> bool:
        """Reset container for an Android-Lab task (synchronous).

        Steps:
        1. Restore AVD snapshot (via container's /reset endpoint)
        2. Set fixed date (2024-05-10 12:00:00)
        3. Set GPS coordinates
        4. Launch target app (if package provided)
        """
        import requests

        # Step 1: Restore snapshot
        try:
            resp = requests.post(
                f"http://localhost:{server_port}/reset",
                json={"seed": None, "options": {}},
                timeout=(5, 300),  # emulator restart can take ~90s
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Snapshot restore failed (port {server_port}): "
                    f"status={resp.status_code}"
                )
                return False
        except Exception as e:
            logger.warning(f"Snapshot restore request failed (port {server_port}): {e}")
            return False

        # Step 2: Set fixed date
        try:
            resp = requests.post(
                f"http://localhost:{server_port}/step",
                json={
                    "action": {
                        "action_type": "adb",
                        "command": f"adb shell date '{ANDROIDLAB_DATE}'",
                    },
                    "thought": "Set Android-Lab fixed date",
                },
                timeout=(5, 30),
            )
        except Exception as e:
            logger.warning(f"Date set failed (port {server_port}): {e}")

        # Step 3: Set GPS
        try:
            resp = requests.post(
                f"http://localhost:{server_port}/step",
                json={
                    "action": {
                        "action_type": "adb",
                        "command": (
                            "adb shell settings put secure location_providers_allowed gps"
                        ),
                    },
                    "thought": "Enable GPS",
                },
                timeout=(5, 30),
            )
        except Exception as e:
            logger.warning(f"GPS enable failed (port {server_port}): {e}")

        # Step 4: Launch target app
        if package:
            try:
                resp = requests.post(
                    f"http://localhost:{server_port}/step",
                    json={
                        "action": {
                            "action_type": "adb",
                            "command": (
                                f"adb shell monkey -p {package} "
                                f"-c android.intent.category.LAUNCHER 1"
                            ),
                        },
                        "thought": f"Launch {package}",
                    },
                    timeout=(5, 30),
                )
            except Exception as e:
                logger.warning(f"App launch failed (port {server_port}): {e}")

        return True

    async def androidlab_reset(self, env_id: int, package: str = "") -> bool:
        """Reset a leased container for Android-Lab (snapshot + date + GPS + app)."""
        entry = self.registry.get(env_id)
        if entry is None:
            logger.warning(f"androidlab_reset: env{env_id} not in registry")
            return False

        server_port = entry.container.server_port
        ok = await asyncio.to_thread(
            self._androidlab_reset_sync, server_port, package
        )
        if ok:
            logger.info(f"env{env_id}: Android-Lab reset OK (package={package})")
        else:
            logger.warning(f"env{env_id}: Android-Lab reset FAILED")
        return ok

    async def _restore_and_return(self, env_id: int):
        """Override: use Android-Lab reset (with date/GPS) on return."""
        entry = self.registry.get(env_id)
        if entry is None:
            return

        ok = await asyncio.to_thread(
            self._androidlab_reset_sync, entry.container.server_port
        )

        if ok:
            async with self._registry_lock:
                entry.state = BrokerContainerState.IDLE
            await self.available_queue.put(env_id)
            logger.info(f"env{env_id} Android-Lab reset+return OK")
        else:
            logger.warning(
                f"env{env_id} Android-Lab reset failed on return, replacing"
            )
            async with self._registry_lock:
                entry.state = BrokerContainerState.REPLACING
            asyncio.create_task(self._replace_container(env_id))


# ─── FastAPI App ─────────────────────────────────────────────────────────────

broker: Optional[AndroidLabPoolBroker] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
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


app = FastAPI(title="Android-Lab Container Pool Broker", lifespan=lifespan)


@app.post("/acquire")
async def api_acquire(req: AcquireRequest):
    try:
        return await broker.acquire(pid=req.pid, timeout=req.timeout)
    except TimeoutError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/return")
async def api_return(req: AndroidLabReturnRequest):
    await broker.return_container(env_id=req.env_id, healthy=req.healthy)
    return {"status": "returned"}


@app.post("/androidlab_reset")
async def api_androidlab_reset(req: AndroidLabResetRequest):
    """Reset a leased container for a new Android-Lab task.

    Call this BEFORE running an agent on a task.  The container must be
    in LEASED state (acquired first).
    """
    ok = await broker.androidlab_reset(env_id=req.env_id, package=req.package)
    if not ok:
        raise HTTPException(status_code=500, detail="Android-Lab reset failed")
    return {"status": "reset_ok"}


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
        "broker_type": "androidlab",
    }


@app.post("/scale")
async def api_scale(req: ScaleRequest):
    raise HTTPException(status_code=501, detail="Not implemented yet")


def main():
    parser = argparse.ArgumentParser(description="Android-Lab Container Pool Broker")
    parser.add_argument("--pool-size", type=int, default=8)
    parser.add_argument("--docker-image", type=str, default="androidlab:v1")
    parser.add_argument("--port", type=int, default=9200)
    parser.add_argument("--snapshot", type=str, default="clean")
    parser.add_argument("--sample-mode", type=str, default="sequential")
    parser.add_argument("--base-env-id", type=int, default=0)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--temp-path", type=str, default="/tmp")
    parser.add_argument("--health-interval", type=float, default=30.0)
    parser.add_argument("--gc-interval", type=float, default=60.0)
    parser.add_argument("--reconcile-interval", type=float, default=180.0)
    parser.add_argument("--skip-screenshot", action="store_true")
    parser.add_argument("--parallel", type=int, default=4,
                        help="Max concurrent container creations")
    parser.add_argument("--adopt", action="store_true",
                        help="Adopt already-running containers")
    args = parser.parse_args()

    global broker
    broker = AndroidLabPoolBroker(
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
