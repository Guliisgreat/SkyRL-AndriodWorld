#!/usr/bin/env python3
"""
Per-step observation overhead micro-benchmark.

Measures wall-clock cost of screenshot capture, accessibility tree dump,
and direct ADB commands against an Android emulator running in a Docker
container (or a manually specified device).

Usage:
    # Auto-create a container
    python experiments/exp1_observation_overhead/run_benchmark.py --host-network

    # Use existing emulator (skip container creation)
    python experiments/exp1_observation_overhead/run_benchmark.py --adb-serial emulator-5574
"""

import argparse
import asyncio
import csv
import os
import subprocess
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# Project path setup
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_SCRIPT_DIR, "..", "..")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_SKYRL_AGENT_ROOT = os.path.join(_PROJECT_ROOT, "skyrl-agent")
if _SKYRL_AGENT_ROOT not in sys.path:
    sys.path.insert(0, _SKYRL_AGENT_ROOT)

from experiments.exp1_observation_overhead.config import (
    APP_SCREENS,
    COOLDOWN_BETWEEN_CONDITIONS,
    COOLDOWN_BETWEEN_REPS,
    CONDITIONS,
    ADB_TIMEOUT,
    NUM_REPETITIONS,
    NUM_WARMUP,
    OUTPUT_DIR,
)


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

def _inject_adb_prefix(cmd: str, adb_prefix: str) -> str:
    """Replace bare 'adb ' with the full prefix (e.g. 'adb -P 5437 ')."""
    return cmd.replace("adb ", f"{adb_prefix} ", )


def _run_adb(cmd: str, timeout: int = ADB_TIMEOUT) -> tuple[bool, float, str]:
    """
    Run a shell command, return (success, wall_clock_seconds, output_or_error).
    """
    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        if result.returncode != 0:
            return False, elapsed, result.stderr.strip()
        return True, elapsed, result.stdout.strip()
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        return False, elapsed, "TIMEOUT"
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return False, elapsed, str(e)


def _wait_for_device(adb_prefix: str, max_wait: float = 120.0):
    """Poll until the emulator is booted and responsive."""
    print("  Waiting for emulator to be ready ...", end="", flush=True)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        ok, _, out = _run_adb(f"{adb_prefix} shell getprop sys.boot_completed", timeout=10)
        if ok and out.strip() == "1":
            print(" ready.")
            return
        print(".", end="", flush=True)
        time.sleep(3)
    raise RuntimeError(f"Emulator did not become ready within {max_wait}s")


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------

async def _create_container(image: str, host_network: bool, base_env_id: int, initial_wait: float):
    """Spin up one container via ContainerManager. Returns (container_instance, manager)."""
    from skyrl_agent.runtime.android.container_manager import ContainerManager

    manager = ContainerManager(
        docker_image=image,
        temp_path=f"/tmp/obs_overhead_bench_{base_env_id}",
    )

    print(f"  Creating container (env_id={base_env_id}, image={image}) ...")
    t0 = time.time()
    containers = await manager.create_pool_parallel(
        pool_size=1,
        buffer_size=0,
        base_env_id=base_env_id,
        max_concurrent=1,
        initial_wait=initial_wait,
        max_retries=2,
        sample_mode="sequential",
        snapshot="clean",
        train_task_family="android_world",
        val_task_family="android_world",
        use_host_network=host_network,
        skip_screenshot=True,  # don't need the HTTP screenshot endpoint
    )
    boot_time = time.time() - t0

    if not containers:
        await manager.cleanup()
        raise RuntimeError("Container creation failed — no containers returned.")

    c = containers[0]
    print(f"  Container ready in {boot_time:.1f}s  "
          f"(emulator_port={c.emulator_port}, adb_server_port={5037 + base_env_id})")
    return c, manager


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(adb_prefix: str, num_reps: int, num_warmup: int) -> list[dict]:
    """Run all conditions on all screens. Returns list of measurement dicts."""
    rows: list[dict] = []
    total_conditions = len(CONDITIONS)

    for ci, condition in enumerate(CONDITIONS, 1):
        cond_name = condition["name"]
        category = condition["category"]
        raw_cmd = condition["cmd"]
        cmd = _inject_adb_prefix(raw_cmd, adb_prefix)

        for screen in APP_SCREENS:
            screen_name = screen["name"]
            setup_cmd = _inject_adb_prefix(screen["setup_cmd"], adb_prefix)

            print(f"\n[{ci}/{total_conditions}] {cond_name} @ {screen_name}")
            print(f"  cmd: {cmd[:90]}{'...' if len(cmd) > 90 else ''}")

            # Navigate to the target screen
            ok, _, err = _run_adb(setup_cmd)
            if not ok:
                print(f"  WARNING: screen setup failed: {err}")
            time.sleep(1.0)  # let the screen settle

            # Warmup
            for w in range(num_warmup):
                _run_adb(cmd)

            # Measurement
            for rep in range(num_reps):
                success, elapsed, _ = _run_adb(cmd)
                rows.append({
                    "condition": cond_name,
                    "category": category,
                    "screen": screen_name,
                    "rep": rep,
                    "wall_clock_s": round(elapsed, 6),
                    "success": success,
                })
                if rep % 25 == 0:
                    print(f"    rep {rep:3d}/{num_reps}  last={elapsed:.4f}s  ok={success}")
                time.sleep(COOLDOWN_BETWEEN_REPS)

        time.sleep(COOLDOWN_BETWEEN_CONDITIONS)

    return rows


def write_csv(rows: list[dict], path: str):
    if not rows:
        print("  No data to write.")
        return
    fieldnames = ["condition", "category", "screen", "rep", "wall_clock_s", "success"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows to {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Micro-benchmark: per-step observation overhead on Android emulator.",
    )
    parser.add_argument(
        "--adb-serial",
        default=None,
        help="Use an existing emulator (e.g. 'emulator-5684'). Skips container creation.",
    )
    parser.add_argument(
        "--adb-port",
        type=int,
        default=None,
        help="ADB server port (e.g. 5092). Use with --adb-serial for host-network containers.",
    )
    parser.add_argument(
        "--host-network",
        action="store_true",
        help="Use host networking when creating a container.",
    )
    parser.add_argument(
        "--image",
        default=os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:full_adb_agent"),
        help="Docker image for the emulator container.",
    )
    parser.add_argument(
        "--base-env-id",
        type=int,
        default=400,
        help="Starting env_id (avoid collision with running containers).",
    )
    parser.add_argument(
        "--initial-wait",
        type=float,
        default=30.0,
        help="Seconds to wait for emulator boot.",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=NUM_REPETITIONS,
        help=f"Number of measurement repetitions (default: {NUM_REPETITIONS}).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=NUM_WARMUP,
        help=f"Number of warmup repetitions (default: {NUM_WARMUP}).",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    manager = None
    if args.adb_serial:
        # Manual mode: use the provided serial directly
        port_flag = f"-P {args.adb_port} " if args.adb_port else ""
        adb_prefix = f"adb {port_flag}-s {args.adb_serial}"
        print(f"Using existing device: {args.adb_serial}"
              + (f" (ADB server port {args.adb_port})" if args.adb_port else ""))
    else:
        # Container mode: spin up a container
        adb_server_port = 5037 + args.base_env_id

        async def setup():
            return await _create_container(
                image=args.image,
                host_network=args.host_network,
                base_env_id=args.base_env_id,
                initial_wait=args.initial_wait,
            )

        container, manager = asyncio.run(setup())
        adb_prefix = f"adb -P {adb_server_port}"
        print(f"ADB prefix: {adb_prefix}")

    try:
        _wait_for_device(adb_prefix)

        print(f"\nStarting benchmark: {len(CONDITIONS)} conditions × "
              f"{len(APP_SCREENS)} screens × {args.reps} reps "
              f"(+ {args.warmup} warmup each)")
        print("=" * 70)

        rows = run_benchmark(adb_prefix, num_reps=args.reps, num_warmup=args.warmup)

        csv_path = os.path.join(OUTPUT_DIR, "raw_timings.csv")
        write_csv(rows, csv_path)

        # Quick summary
        if rows:
            from collections import defaultdict
            by_cond: dict[str, list[float]] = defaultdict(list)
            for r in rows:
                if r["success"]:
                    by_cond[r["condition"]].append(r["wall_clock_s"])
            print("\n" + "=" * 70)
            print("  Quick summary (mean ± std, seconds)")
            print("-" * 70)
            for cond, vals in by_cond.items():
                import statistics
                avg = statistics.mean(vals)
                std = statistics.stdev(vals) if len(vals) > 1 else 0.0
                print(f"  {cond:<30s}  {avg:.4f} ± {std:.4f}  (n={len(vals)})")
            print("=" * 70)

    finally:
        if manager is not None:
            print("\nCleaning up container ...")
            asyncio.run(manager.cleanup())
            print("  Done.")


if __name__ == "__main__":
    main()
