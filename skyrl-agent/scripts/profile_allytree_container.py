#!/usr/bin/env python3
"""
Profile allytree-only containers (ENV_SKIP_SCREENSHOT=true) vs screenshot+allytree.

Measures timing for /reset, /step_adb, and /health endpoints across multiple
iterations and prints a comparison table.

Usage:
  cd skyrl-agent
  python scripts/profile_allytree_container.py --host-network
  python scripts/profile_allytree_container.py --host-network --compare   # run both modes side-by-side
  python scripts/profile_allytree_container.py --host-network --steps 10 --resets 3

Prerequisites: Docker, KVM, image androidworld:full_adb_agent.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


ADB_COMMANDS = [
    "adb shell input tap 540 1200",
    "adb shell input keyevent KEYCODE_HOME",
    "adb shell getprop ro.build.display.id",
    "adb shell wm size",
    "adb shell settings get system screen_brightness",
    "adb shell dumpsys battery",
    "adb shell date",
    "adb shell pm list packages -3",
]


def _fmt_stats(values: list[float]) -> str:
    if not values:
        return "N/A"
    mn = min(values)
    mx = max(values)
    avg = statistics.mean(values)
    med = statistics.median(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"avg={avg:.2f}s  med={med:.2f}s  min={mn:.2f}s  max={mx:.2f}s  std={sd:.2f}s"


def _print_table(label: str, timings: dict[str, list[float]]):
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    for name, values in timings.items():
        total = sum(values)
        print(f"  {name:25s}  n={len(values):3d}  total={total:7.2f}s  {_fmt_stats(values)}")
    print()


async def run_profile(
    image: str,
    host_network: bool,
    initial_wait: float,
    skip_screenshot: bool,
    num_resets: int,
    steps_per_reset: int,
    base_env_id: int,
) -> dict[str, list[float]]:
    """Run profiling on one container. Returns timing dict."""
    import requests
    from skyrl_agent.runtime.android.container_manager import ContainerManager

    mode_label = "allytree-only" if skip_screenshot else "screenshot+allytree"
    print(f"\n--- Profiling mode: {mode_label} (env_id base={base_env_id}) ---")

    manager = ContainerManager(
        docker_image=image,
        temp_path=f"/tmp/profile_allytree_{base_env_id}",
    )

    timings: dict[str, list[float]] = {
        "health": [],
        "reset": [],
        "step_adb": [],
        "response_size_kb": [],
    }

    try:
        print(f"  Creating container (skip_screenshot={skip_screenshot}) ...")
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
            skip_screenshot=skip_screenshot,
        )
        boot_time = time.time() - t0
        print(f"  Container ready in {boot_time:.1f}s")

        if not containers:
            print("  ERROR: No containers created.")
            return timings

        c = containers[0]
        base_url = f"http://localhost:{c.server_port}"

        # Health check timing
        for _ in range(3):
            t0 = time.time()
            r = requests.get(f"{base_url}/health", timeout=15)
            timings["health"].append(time.time() - t0)

        # Reset + step loops
        for reset_idx in range(num_resets):
            print(f"  Reset {reset_idx + 1}/{num_resets} ...", end="", flush=True)

            t0 = time.time()
            r = requests.post(
                f"{base_url}/reset",
                json={"seed": 42 + reset_idx, "options": {"task_id": reset_idx}},
                timeout=300,
            )
            reset_time = time.time() - t0
            timings["reset"].append(reset_time)

            if r.status_code != 200:
                print(f" FAILED (status={r.status_code})")
                continue

            resp_size = len(r.content) / 1024
            timings["response_size_kb"].append(resp_size)

            obs = r.json().get("observation", {})
            has_image = "image" in obs and obs["image"] is not None
            n_ui = len(obs.get("ui_elements", []))
            print(f" {reset_time:.2f}s  (resp={resp_size:.0f}KB, has_image={has_image}, ui_elements={n_ui})")

            # Step ADB loop
            for step_idx in range(steps_per_reset):
                cmd = ADB_COMMANDS[step_idx % len(ADB_COMMANDS)]

                t0 = time.time()
                r = requests.post(
                    f"{base_url}/step_adb",
                    json={"command": cmd, "thought": f"profile step {step_idx}"},
                    timeout=120,
                )
                step_time = time.time() - t0
                timings["step_adb"].append(step_time)

                resp_size = len(r.content) / 1024
                timings["response_size_kb"].append(resp_size)

                if r.status_code == 200:
                    data = r.json()
                    terminated = data.get("terminated", False)
                    if terminated:
                        print(f"    step {step_idx + 1}: terminated (task done), {step_time:.2f}s")
                        break
                    print(f"    step {step_idx + 1}/{steps_per_reset}: {step_time:.2f}s  (resp={resp_size:.0f}KB)  cmd={cmd[:50]}")
                else:
                    print(f"    step {step_idx + 1}/{steps_per_reset}: FAILED status={r.status_code}, {step_time:.2f}s")

        _print_table(f"Results: {mode_label}", timings)
        return timings

    finally:
        await manager.cleanup()
        print(f"  Containers cleaned up ({mode_label}).")


def main():
    parser = argparse.ArgumentParser(
        description="Profile allytree-only vs screenshot+allytree containers."
    )
    parser.add_argument(
        "--image",
        default=os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:full_adb_agent"),
        help="Docker image (default: androidworld:full_adb_agent)",
    )
    parser.add_argument("--host-network", action="store_true", help="Use host networking")
    parser.add_argument("--initial-wait", type=float, default=30.0, help="Emulator boot wait (seconds)")
    parser.add_argument("--resets", type=int, default=2, help="Number of reset cycles")
    parser.add_argument("--steps", type=int, default=5, help="ADB steps per reset")
    parser.add_argument(
        "--compare", action="store_true",
        help="Run both modes (screenshot+allytree, then allytree-only) for comparison",
    )
    parser.add_argument(
        "--base-env-id", type=int, default=300,
        help="Starting env_id (avoid collision with running containers)",
    )
    args = parser.parse_args()

    async def run():
        results = {}

        if args.compare:
            # Screenshot + allytree (baseline)
            results["screenshot+allytree"] = await run_profile(
                image=args.image,
                host_network=args.host_network,
                initial_wait=args.initial_wait,
                skip_screenshot=False,
                num_resets=args.resets,
                steps_per_reset=args.steps,
                base_env_id=args.base_env_id,
            )
            # Allytree-only (optimized)
            results["allytree-only"] = await run_profile(
                image=args.image,
                host_network=args.host_network,
                initial_wait=args.initial_wait,
                skip_screenshot=True,
                num_resets=args.resets,
                steps_per_reset=args.steps,
                base_env_id=args.base_env_id + 1,
            )

            # Print comparison
            print("\n" + "=" * 70)
            print("  COMPARISON SUMMARY")
            print("=" * 70)
            for metric in ["reset", "step_adb", "response_size_kb"]:
                base_vals = results["screenshot+allytree"].get(metric, [])
                opt_vals = results["allytree-only"].get(metric, [])
                if not base_vals or not opt_vals:
                    continue
                base_avg = statistics.mean(base_vals)
                opt_avg = statistics.mean(opt_vals)
                if metric == "response_size_kb":
                    unit = "KB"
                    speedup = f"{base_avg / opt_avg:.1f}x smaller" if opt_avg > 0 else "N/A"
                else:
                    unit = "s"
                    speedup = f"{base_avg / opt_avg:.1f}x faster" if opt_avg > 0 else "N/A"
                saving = base_avg - opt_avg
                print(
                    f"  {metric:20s}  "
                    f"baseline={base_avg:.2f}{unit}  "
                    f"optimized={opt_avg:.2f}{unit}  "
                    f"saving={saving:.2f}{unit}  "
                    f"({speedup})"
                )
            print()

        else:
            # Allytree-only mode
            results["allytree-only"] = await run_profile(
                image=args.image,
                host_network=args.host_network,
                initial_wait=args.initial_wait,
                skip_screenshot=True,
                num_resets=args.resets,
                steps_per_reset=args.steps,
                base_env_id=args.base_env_id,
            )

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
