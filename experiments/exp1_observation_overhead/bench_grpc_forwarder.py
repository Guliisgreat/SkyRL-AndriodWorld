#!/usr/bin/env python3
"""
Benchmark the gRPC AccessibilityForwarder path via the container's HTTP server.

Measures observation retrieval latency through the actual agent pipeline:
  /step_adb (adb shell date) → ADB exec + get_state() → gRPC a11y tree + screenshot → JSON response

This captures the real per-step cost an agent pays, including:
  - gRPC tree fetch from the AccessibilityForwarder APK
  - Screenshot capture (if SKIP_SCREENSHOT=false)
  - Protobuf → dict conversion + JSON serialization
  - HTTP transfer

Results are appended to raw_timings.csv for unified analysis.

Usage:
    # Using an existing container (env55, screenshot+a11y)
    python experiments/exp1_observation_overhead/bench_grpc_forwarder.py \\
        --server-url http://localhost:5137

    # Specify number of reps
    python experiments/exp1_observation_overhead/bench_grpc_forwarder.py \\
        --server-url http://localhost:5137 --reps 100
"""

import argparse
import csv
import os
import sys
import time

import requests

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_SCRIPT_DIR, "..", "..")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from experiments.exp1_observation_overhead.config import (
    APP_SCREENS,
    COOLDOWN_BETWEEN_CONDITIONS,
    COOLDOWN_BETWEEN_REPS,
    NUM_REPETITIONS,
    NUM_WARMUP,
    OUTPUT_DIR,
)

# ---------------------------------------------------------------------------
# ADB helper (for screen navigation only — uses container's /step_adb)
# ---------------------------------------------------------------------------

def _navigate_screen(server_url: str, adb_cmd: str):
    """Send an ADB command through the container to navigate to a screen."""
    try:
        requests.post(
            f"{server_url}/step_adb",
            json={"command": adb_cmd, "thought": "screen navigation"},
            timeout=30,
        )
    except Exception as e:
        print(f"  WARNING: navigation failed: {e}")


def _fetch_observation(server_url: str, timeout: int = 60) -> tuple[bool, float, dict]:
    """
    Call /step_adb with a minimal command to trigger a full observation fetch.
    Returns (success, wall_clock_s, response_metadata).
    """
    t0 = time.perf_counter()
    try:
        r = requests.post(
            f"{server_url}/step_adb",
            json={"command": "adb shell date", "thought": "benchmark"},
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        if r.status_code != 200:
            return False, elapsed, {"error": f"status={r.status_code}"}
        data = r.json()
        obs = data.get("observation", {})
        meta = {
            "has_image": obs.get("image") is not None,
            "n_ui_elements": len(obs.get("ui_elements", [])),
            "resp_size_kb": len(r.content) / 1024,
        }
        return True, elapsed, meta
    except requests.Timeout:
        elapsed = time.perf_counter() - t0
        return False, elapsed, {"error": "TIMEOUT"}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return False, elapsed, {"error": str(e)}


def _deep_health(server_url: str, timeout: int = 60) -> tuple[bool, float, dict]:
    """
    Call /deep_health to get observation timing without ADB command overhead.
    """
    t0 = time.perf_counter()
    try:
        r = requests.get(f"{server_url}/deep_health", timeout=timeout)
        elapsed = time.perf_counter() - t0
        if r.status_code != 200:
            return False, elapsed, {}
        data = r.json()
        return data.get("status") == "healthy", elapsed, data
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return False, elapsed, {"error": str(e)}


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

HTTP_CONDITIONS = [
    {
        "name": "grpc_step_adb_obs",
        "category": "gRPC Forwarder",
        "description": "/step_adb(date) → gRPC a11y tree + screenshot + JSON response",
        "func": lambda url: _fetch_observation(url),
    },
    {
        "name": "grpc_deep_health",
        "category": "gRPC Forwarder",
        "description": "/deep_health → get_raw_observation() timing",
        "func": lambda url: _deep_health(url),
    },
]


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    server_url: str,
    adb_prefix: str,
    num_reps: int,
    num_warmup: int,
) -> list[dict]:
    rows: list[dict] = []

    for ci, condition in enumerate(HTTP_CONDITIONS, 1):
        cond_name = condition["name"]
        category = condition["category"]
        func = condition["func"]

        for screen in APP_SCREENS:
            screen_name = screen["name"]

            print(f"\n[{ci}/{len(HTTP_CONDITIONS)}] {cond_name} @ {screen_name}")

            # Navigate to screen via container's ADB
            _navigate_screen(server_url, screen["setup_cmd"])
            time.sleep(1.5)  # let screen settle

            # Warmup
            for w in range(num_warmup):
                func(server_url)

            # Measurement
            for rep in range(num_reps):
                success, elapsed, meta = func(server_url)
                rows.append({
                    "condition": cond_name,
                    "category": category,
                    "screen": screen_name,
                    "rep": rep,
                    "wall_clock_s": round(elapsed, 6),
                    "success": success,
                })
                if rep % 25 == 0:
                    extra = ""
                    if "n_ui_elements" in meta:
                        extra = f"  ui={meta['n_ui_elements']} resp={meta.get('resp_size_kb',0):.0f}KB"
                    print(f"    rep {rep:3d}/{num_reps}  last={elapsed:.4f}s  ok={success}{extra}")
                time.sleep(COOLDOWN_BETWEEN_REPS)

        time.sleep(COOLDOWN_BETWEEN_CONDITIONS)

    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark gRPC AccessibilityForwarder via container HTTP server.",
    )
    parser.add_argument(
        "--server-url",
        required=True,
        help="Container server URL (e.g. http://localhost:5137)",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=NUM_REPETITIONS,
        help=f"Number of measurement reps (default: {NUM_REPETITIONS})",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=NUM_WARMUP,
        help=f"Number of warmup reps (default: {NUM_WARMUP})",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        default=True,
        help="Append results to existing raw_timings.csv (default: True)",
    )
    parser.add_argument(
        "--no-append",
        action="store_true",
        help="Write results to a separate grpc_timings.csv instead of appending",
    )
    # Dummy flags for compatibility (screen navigation uses container's /step_adb, not host ADB)
    parser.add_argument("--adb-serial", default=None)
    parser.add_argument("--adb-port", type=int, default=None)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Verify server is reachable
    print(f"Checking server at {args.server_url} ...")
    try:
        r = requests.get(f"{args.server_url}/health", timeout=10)
        data = r.json()
        print(f"  Server healthy: {data}")
    except Exception as e:
        print(f"  ERROR: cannot reach server: {e}")
        return 1

    print(f"\nStarting gRPC forwarder benchmark: {len(HTTP_CONDITIONS)} conditions × "
          f"{len(APP_SCREENS)} screens × {args.reps} reps (+ {args.warmup} warmup)")
    print("=" * 70)

    # ADB prefix for screen navigation commands (not used for measurement)
    adb_prefix = "adb"
    rows = run_benchmark(args.server_url, adb_prefix, args.reps, args.warmup)

    # Write results
    if args.no_append:
        csv_path = os.path.join(OUTPUT_DIR, "grpc_timings.csv")
    else:
        csv_path = os.path.join(OUTPUT_DIR, "raw_timings.csv")

    fieldnames = ["condition", "category", "screen", "rep", "wall_clock_s", "success"]

    mode = "a" if (not args.no_append and os.path.exists(csv_path)) else "w"
    write_header = mode == "w" or not os.path.exists(csv_path)

    with open(csv_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"\n  {'Appended' if mode == 'a' else 'Wrote'} {len(rows)} rows to {csv_path}")

    # Quick summary
    if rows:
        from collections import defaultdict
        import statistics
        by_cond: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            if r["success"]:
                by_cond[r["condition"]].append(r["wall_clock_s"])
        print("\n" + "=" * 70)
        print("  Quick summary (mean ± std, seconds)")
        print("-" * 70)
        for cond, vals in by_cond.items():
            avg = statistics.mean(vals)
            std = statistics.stdev(vals) if len(vals) > 1 else 0.0
            print(f"  {cond:<30s}  {avg:.4f} ± {std:.4f}  (n={len(vals)})")
        print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
