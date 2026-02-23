#!/usr/bin/env python3
"""
Debug script: spin up one AndroidWorld container and verify all server endpoints.

Tests (in order):
  1. GET  /health    - container is ready
  2. POST /reset     - environment resets, observation contains ui_elements
  3. POST /step      - GUI action executes
  4. POST /step_adb  - ADB command executes and returns command_output

Usage:
  cd skyrl-agent && python scripts/debug_adb_container.py --host-network
  python scripts/debug_adb_container.py --image androidworld:full_adb_agent --host-network
  python scripts/debug_adb_container.py --show-docker-run

Prerequisites: Docker, KVM, image androidworld:full_adb_agent (or ANDROID_DOCKER_IMAGE).
"""

import argparse
import asyncio
import json
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _log(msg: str):
    print(msg, flush=True)


def _print_result(name: str, passed: bool, detail: str = ""):
    tag = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    _log(f"  [{tag}] {name}{suffix}")


def main():
    parser = argparse.ArgumentParser(
        description="Debug AndroidWorld container: start one, test /health /reset /step /step_adb."
    )
    parser.add_argument(
        "--image",
        default=os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:full_adb_agent"),
        help="Docker image (default: androidworld:full_adb_agent)",
    )
    parser.add_argument("--pool-size", type=int, default=1)
    parser.add_argument("--host-network", action="store_true", help="Use host networking (required for per-container ADB port)")
    parser.add_argument("--initial-wait", type=float, default=30.0, help="Emulator boot wait (seconds)")
    parser.add_argument("--no-step-adb", action="store_true", help="Skip POST /step_adb check")
    parser.add_argument("--no-step", action="store_true", help="Skip POST /step check")
    parser.add_argument("--no-reset", action="store_true", help="Skip POST /reset check")
    parser.add_argument(
        "--show-docker-run", action="store_true",
        help="Print docker run command for manual debugging",
    )
    args = parser.parse_args()

    if args.show_docker_run:
        env_id = 0
        server_port = 5000
        emulator_port = 5574
        grpc_port = 8574
        adb_port = 5037
        net_flag = "--network host" if args.host_network else (
            f"-p {server_port}:{server_port} -p {emulator_port}:{emulator_port} -p {grpc_port}:{grpc_port}"
        )
        cmd = (
            f"docker run --rm {net_flag} "
            f"-e SERVER_PORT={server_port} -e EMULATOR_PORT={emulator_port} "
            f"-e GRPC_PORT={grpc_port} -e ADB_SERVER_PORT={adb_port} -e ENV_ID={env_id} "
            f"-e ENV_SAMPLE_MODE=sequential -e ENV_SAVE_IMAGES=False "
            f"-e ENV_SNAPSHOT=clean -e ENV_TASK_FAMILY=android_world "
            f"--device /dev/kvm {args.image}"
        )
        print("Run one container and stream logs (Ctrl+C to stop).")
        print(f"Then in another terminal: curl http://localhost:{server_port}/health")
        print(cmd)
        return 0

    async def run():
        import requests
        from skyrl_agent.runtime.android.container_manager import ContainerManager

        _log(f"Image : {args.image}")
        _log(f"Host network : {args.host_network}")
        _log(f"Initial wait : {args.initial_wait}s")
        _log(f"Pool size : {args.pool_size}")
        _log("")

        manager = ContainerManager(
            docker_image=args.image,
            temp_path="/tmp/debug_adb_container",
        )

        results = {}

        try:
            _log("[0/4] Creating container pool ...")
            t0 = time.time()
            containers = await manager.create_pool_parallel(
                pool_size=args.pool_size,
                buffer_size=0,
                base_env_id=200,
                max_concurrent=1,
                initial_wait=args.initial_wait,
                max_retries=2,
                sample_mode="sequential",
                snapshot="clean",
                train_task_family="android_world",
                val_task_family="android_world",
                use_host_network=args.host_network,
            )
            elapsed = time.time() - t0
            _log(f"       Pool created: {len(containers)} container(s) in {elapsed:.1f}s")

            if not containers:
                _log("ERROR: No containers created.")
                return 1

            c = containers[0]
            base = f"http://localhost:{c.server_port}"
            _log(f"       env{c.env_id}: server_port={c.server_port}, healthy={c.is_healthy}\n")

            # --- 1. /health ---
            _log("[1/4] GET /health")
            try:
                r = requests.get(f"{base}/health", timeout=15)
                ok = r.status_code == 200 and r.json().get("status") == "healthy"
                _print_result("/health", ok, f"status={r.status_code} body={r.text[:200]}")
                results["health"] = ok
            except Exception as e:
                _print_result("/health", False, str(e))
                results["health"] = False

            # --- 2. /reset ---
            if not args.no_reset:
                _log("[2/4] POST /reset")
                try:
                    r = requests.post(
                        f"{base}/reset",
                        json={"seed": 42, "options": None},
                        timeout=180,
                    )
                    data = r.json()
                    if r.status_code != 200:
                        _print_result("/reset", False, f"status={r.status_code}, body={json.dumps(data)[:500]}")
                        results["reset"] = False
                    else:
                        obs = data.get("observation", {})
                        ui_els = obs.get("ui_elements", None)
                        has_image = "image" in obs and len(obs["image"]) > 0
                        has_ui = isinstance(ui_els, list)
                        ok = has_image and has_ui
                        detail = (
                            f"status={r.status_code}, has_image={has_image}, "
                            f"ui_elements={'list(len=' + str(len(ui_els)) + ')' if has_ui else ui_els}"
                        )
                        _print_result("/reset", ok, detail)
                        if has_ui and ui_els:
                            _log(f"         sample ui_element: {json.dumps(ui_els[0], indent=2)[:300]}")
                        results["reset"] = ok
                except Exception as e:
                    _print_result("/reset", False, str(e))
                    results["reset"] = False
            else:
                _log("[2/4] POST /reset — SKIPPED")
                results["reset"] = None

            # --- 3. /step (GUI action) ---
            if not args.no_step:
                _log("[3/4] POST /step")
                try:
                    action = {"action_type": "status", "coordinate": [0, 0]}
                    r = requests.post(
                        f"{base}/step",
                        json={"action": action, "thought": "debug: no-op status check"},
                        timeout=60,
                    )
                    data = r.json()
                    if r.status_code != 200:
                        _print_result("/step", False, f"status={r.status_code}, body={json.dumps(data)[:500]}")
                        results["step"] = False
                    else:
                        obs = data.get("observation", {})
                        has_image = "image" in obs and len(obs["image"]) > 0
                        ui_els = obs.get("ui_elements", None)
                        has_ui = isinstance(ui_els, list)
                        ok = data.get("status") == "success"
                        detail = (
                            f"status={r.status_code}, reward={data.get('reward')}, "
                            f"terminated={data.get('terminated')}, has_image={has_image}, "
                            f"ui_elements_count={len(ui_els) if has_ui else 'N/A'}"
                        )
                        _print_result("/step", ok, detail)
                        results["step"] = ok
                except Exception as e:
                    _print_result("/step", False, str(e))
                    results["step"] = False
            else:
                _log("[3/4] POST /step — SKIPPED")
                results["step"] = None

            # --- 4. /step_adb ---
            if not args.no_step_adb:
                _log("[4/4] POST /step_adb")
                try:
                    r = requests.post(
                        f"{base}/step_adb",
                        json={"command": "adb shell getprop ro.build.display.id", "thought": "debug getprop"},
                        timeout=60,
                    )
                    data = r.json()
                    if r.status_code != 200:
                        _print_result("/step_adb", False, f"status={r.status_code}, body={json.dumps(data)[:500]}")
                        results["step_adb"] = False
                    else:
                        cmd_out = data.get("command_output", "")
                        obs = data.get("observation", {})
                        has_image = "image" in obs and len(obs["image"]) > 0
                        ok = len(cmd_out.strip()) > 0
                        detail = (
                            f"status={r.status_code}, command_output={cmd_out.strip()!r}, "
                            f"has_image={has_image}"
                        )
                        _print_result("/step_adb", ok, detail)
                        results["step_adb"] = ok
                except Exception as e:
                    _print_result("/step_adb", False, str(e))
                    results["step_adb"] = False
            else:
                _log("[4/4] POST /step_adb — SKIPPED")
                results["step_adb"] = None

            # --- Summary ---
            _log("\n" + "=" * 50)
            tested = {k: v for k, v in results.items() if v is not None}
            passed = sum(1 for v in tested.values() if v)
            total = len(tested)
            _log(f"Results: {passed}/{total} passed")
            if passed == total:
                _log("All checks passed.")
                return 0
            else:
                failed = [k for k, v in tested.items() if not v]
                _log(f"Failed: {', '.join(failed)}")
                return 1

        finally:
            await manager.cleanup()
            _log("Containers cleaned up.")

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
