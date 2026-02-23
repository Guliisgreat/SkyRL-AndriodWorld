#!/usr/bin/env python3
"""
Verify container pool (trainer/inference style) without running the agent.

Creates a pool with the same options as AndroidTask.initialize_runtime, checks
/health on each container, optionally runs allocate/release, then cleans up.
Use this to validate Docker image and host-network/bridge setup before
running full inference or training.

Usage:
  cd skyrl-agent && RUN_DOCKER_TESTS=true python scripts/verify_container_pool.py
  RUN_DOCKER_TESTS=true python scripts/verify_container_pool.py --pool-size 8 --buffer-size 2 --host-network
  python scripts/verify_container_pool.py --pool-size 2 --image androidworld:v9

Options:
  --pool-size N       Main pool size (default: 8)
  --buffer-size N     Hot standby containers (default: 2)
  --image IMAGE       Docker image (default: androidworld:v9, or ANDROID_DOCKER_IMAGE)
  --host-network      Use host networking (per-container ADB port)
  --temp-dir DIR      Temp path for manager (default: /tmp/verify_container_pool)
  --initial-wait S   Emulator boot wait in seconds (default: 30)
  --max-concurrent N  Max concurrent creations (default: min(pool_size+buffer_size, 8))
  --skip-allocate     Skip allocate/release verification
  --skip-cleanup      Do not remove stale env* containers before run

Why [3/3] can raise "No healthy containers available":
  allocate_container() takes a container from the pool and checks health via
  _check_container_health() (Docker reload + HTTP GET /health). If that check
  fails (e.g. container exited, connection refused, or another process removed
  the container), the container is destroyed and a replacement is started. After
  len(pool) such attempts with no healthy container, RuntimeError is raised.
  Use --skip-allocate to pass verification when [1/3] and [2/3] succeed.
"""

import argparse
import asyncio
import os
import sys
import time

try:
    import requests
except ImportError:
    requests = None

# Project root for imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def cleanup_stale_containers(pattern: str = "env*") -> int:
    """Remove stale Docker containers matching pattern. Returns count removed."""
    import docker
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": pattern})
        for c in containers:
            try:
                c.remove(force=True)
            except Exception:
                pass
        return len(containers)
    except Exception:
        return 0


async def run_verification(args):
    from skyrl_agent.runtime.android.container_manager import ContainerManager

    pool_size = args.pool_size
    buffer_size = args.buffer_size
    total = pool_size + buffer_size
    max_concurrent = min(total, args.max_concurrent)

    print(f"Image: {args.image}")
    print(f"Pool: {pool_size} main + {buffer_size} buffer, host_network={args.host_network}")
    print(f"max_concurrent={max_concurrent}, initial_wait={args.initial_wait}s")

    if not args.skip_cleanup:
        n = cleanup_stale_containers()
        if n:
            print(f"Removed {n} stale env* container(s).")
        await asyncio.sleep(1)

    manager = ContainerManager(
        docker_image=args.image,
        temp_path=args.temp_dir,
    )

    try:
        print("\n[1/3] Creating container pool...")
        start = time.time()
        containers = await manager.create_pool_parallel(
            pool_size=pool_size,
            base_env_id=0,
            max_concurrent=max_concurrent,
            initial_wait=args.initial_wait,
            max_retries=2,
            sample_mode="sequential",
            snapshot="clean",
            train_task_family="android_world",
            val_task_family="android_world",
            buffer_size=buffer_size,
            use_host_network=args.host_network,
        )
        elapsed = time.time() - start
        n_backup = len(manager.backup_containers)
        n_total = len(containers) + n_backup
        print(f"      Created {n_total} containers ({len(containers)} main + {n_backup} backup) in {elapsed:.1f}s")

        if len(containers) < pool_size:
            print(f"ERROR: Expected {pool_size} main containers, got {len(containers)}")
            return 1
        if n_backup < buffer_size:
            print(f"WARNING: Expected {buffer_size} backup containers, got {n_backup}")

        # [2/3] Health check each container (main + backup)
        print("\n[2/3] Verifying /health on each container...")
        all_containers = list(containers) + list(manager.backup_containers)
        failed = []
        for c in all_containers:
            url = f"http://localhost:{c.server_port}/health"
            try:
                r = requests.get(url, timeout=10) if requests else None
                if not r or r.status_code != 200:
                    failed.append((c.env_id, c.server_port, getattr(r, "status_code", None)))
            except Exception as e:
                failed.append((c.env_id, c.server_port, str(e)))
        if failed:
            for env_id, port, err in failed:
                print(f"      env{env_id} (port={port}): FAIL - {err}")
            print(f"ERROR: {len(failed)} container(s) failed health check")
            return 1
        print("      All containers healthy.")

        # [3/3] Optional allocate/release
        if not args.skip_allocate:
            print("\n[3/3] Allocate/release verification...")
            try:
                container = await manager.allocate_container(batch_idx=0, trajectory_id=0)
                await manager.release_container(container, success=True)
                print("      Allocate/release OK.")
            except RuntimeError as e:
                if "No healthy containers available" in str(e):
                    print(
                        "      Allocate failed: manager health check rejected all containers.\n"
                        "      (Containers may have exited, been removed by another run, or HTTP/Docker check failed.)\n"
                        "      Use --skip-allocate to pass when [1/3] and [2/3] succeed."
                    )
                    return 1
                raise

        print("\nVerification passed.")
        return 0
    finally:
        await manager.cleanup()
        print("Containers cleaned up.")


def main():
    parser = argparse.ArgumentParser(description="Verify container pool (no agent).")
    parser.add_argument("--pool-size", type=int, default=8)
    parser.add_argument("--buffer-size", type=int, default=2)
    parser.add_argument("--image", default=os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:v9"))
    parser.add_argument("--host-network", action="store_true", help="Use host networking")
    parser.add_argument("--temp-dir", default="/tmp/verify_container_pool")
    parser.add_argument("--initial-wait", type=float, default=30.0)
    parser.add_argument("--max-concurrent", type=int, default=10)
    parser.add_argument("--skip-allocate", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")
    args = parser.parse_args()

    if os.environ.get("RUN_DOCKER_TESTS", "").lower() != "true":
        print("Set RUN_DOCKER_TESTS=true to run (e.g. RUN_DOCKER_TESTS=true python scripts/verify_container_pool.py)")
        return 1
    if requests is None:
        print("Install requests for /health checks: pip install requests")
        return 1

    return asyncio.run(run_verification(args))


if __name__ == "__main__":
    sys.exit(main())
