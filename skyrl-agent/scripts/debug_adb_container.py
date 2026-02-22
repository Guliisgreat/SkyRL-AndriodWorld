#!/usr/bin/env python3
"""
Debug script: run one AndroidWorld container with the ADB image and verify /health (and optionally /step_adb).

Usage:
  cd skyrl-agent && python scripts/debug_adb_container.py
  ANDROID_DOCKER_IMAGE=androidworld-adb:v8 python scripts/debug_adb_container.py

Prerequisites: Docker, KVM (for emulator), image androidworld-adb:v8 (or ANDROID_DOCKER_IMAGE).
"""

import argparse
import asyncio
import os
import sys
import time

# Add project root so we can import skyrl_agent
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Debug ADB Docker container: start one, check /health and /step_adb.")
    parser.add_argument("--image", default=os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld-adb:v8"), help="Docker image")
    parser.add_argument("--pool-size", type=int, default=1, help="Number of containers to create (default 1)")
    parser.add_argument("--timeout", type=int, default=600, help="Max seconds to wait for health (default 600)")
    parser.add_argument("--no-step-adb", action="store_true", help="Skip POST /step_adb check")
    parser.add_argument("--show-docker-run", action="store_true", help="Print docker run command to run one container and see logs (for debugging health failures)")
    args = parser.parse_args()

    if args.show_docker_run:
        env_id = 0
        server_port = 5000
        emulator_port = 5574
        grpc_port = 8574
        cmd = (
            f"docker run --rm -p {server_port}:{server_port} -p {emulator_port}:{emulator_port} -p {grpc_port}:{grpc_port} "
            f"-e SERVER_PORT={server_port} -e EMULATOR_PORT={emulator_port} -e GRPC_PORT={grpc_port} -e ENV_ID={env_id} "
            f"-e ENV_SAMPLE_MODE=sequential -e ENV_SAVE_IMAGES=False -e ENV_SNAPSHOT=clean -e ENV_TASK_FAMILY=android_world "
            f"--device /dev/kvm {args.image}"
        )
        print("Run one container and stream logs (Ctrl+C to stop). In another terminal: curl http://localhost:5000/health")
        print(cmd)
        return 0

    async def run():
        from skyrl_agent.runtime.android.container_manager import ContainerManager

        print(f"Using image: {args.image}")
        print(f"Creating pool of {args.pool_size} container(s), timeout={args.timeout}s ...")
        manager = ContainerManager(
            docker_image=args.image,
            temp_path="/tmp/debug_adb_container",
        )
        try:
            containers = await manager.create_pool_parallel(
                pool_size=args.pool_size,
                buffer_size=0,
                base_env_id=0,
                max_concurrent=1,
                initial_wait=30.0,
                max_retries=1,
                sample_mode="sequential",
                snapshot="clean",
                train_task_family="android_world",
                val_task_family="android_world",
            )
            print(f"Pool created: {len(containers)} container(s).")
            if not containers:
                print("No containers in pool.")
                return 1
            c = containers[0]
            print(f"env{c.env_id}: server_port={c.server_port}, healthy={c.is_healthy}")

            if not args.no_step_adb:
                import requests
                url = f"http://localhost:{c.server_port}/step_adb"
                print(f"Testing POST {url} ...")
                try:
                    r = requests.post(url, json={"command": "adb shell echo 1", "thought": "debug"}, timeout=30)
                    print(f"  status={r.status_code}, body={r.text[:500]}")
                    if r.status_code != 200:
                        return 1
                except Exception as e:
                    print(f"  error: {e}")
                    return 1
            print("All checks passed.")
            return 0
        finally:
            await manager.cleanup()
            print("Containers cleaned up.")

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
