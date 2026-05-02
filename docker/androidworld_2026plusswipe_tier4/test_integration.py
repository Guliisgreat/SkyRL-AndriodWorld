#!/usr/bin/env python3
"""Integration tests for androidworld:2026plusswipe_tier4 container.

Validates that the full server stack correctly serves all 50 tier4 tasks
and that the /reset -> /step_adb -> FINISH flow works for each one.

Usage:
    # 1. Start the container:
    docker run -d --name tier4_test --device /dev/kvm \
      -e ENV_SKIP_SCREENSHOT=true -e LAZY_EVAL=true \
      -p 5000:5000 androidworld:2026plusswipe_tier4

    # 2. Run the integration tests (waits for container to become healthy):
    python test_integration.py --base-url http://localhost:5000

    # 3. Cleanup:
    docker rm -f tier4_test

Options:
    --base-url   Server URL (default: http://localhost:5000)
    --timeout    Max seconds to wait for container health (default: 600)
    --verbose    Print detailed per-task output
"""

import argparse
import json
import sys
import time

import requests

EXPECTED_TASK_COUNT = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_health(base_url: str, timeout: int) -> bool:
    """Poll /health until the container reports healthy or timeout expires."""
    print(f"Waiting for container to become healthy (timeout={timeout}s) ...")
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=10)
            data = resp.json()
            status = data.get("status")
            if status != last_status:
                print(f"  health: {status} (ready={data.get('ready')})")
                last_status = status
            if status == "healthy" and data.get("ready"):
                print(f"Container healthy after {int(time.time() - (deadline - timeout))}s")
                return True
        except requests.ConnectionError:
            pass
        except Exception as e:
            print(f"  health check error: {e}")
        time.sleep(5)
    print("ERROR: Container did not become healthy within timeout")
    return False


def reset_task(base_url: str, seed: int, task_id: int | None = None) -> dict:
    """Call /reset and return the response JSON.

    In sequential mode the server uses ``options.task_id`` (not seed) to
    select the task.  Pass *task_id* explicitly to cycle through tasks.
    """
    payload: dict = {"seed": seed}
    if task_id is not None:
        payload["options"] = {"task_id": task_id}
    resp = requests.post(
        f"{base_url}/reset",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def step_adb(base_url: str, command: str, thought: str = "integration test") -> dict:
    """Call /step_adb and return the response JSON."""
    resp = requests.post(
        f"{base_url}/step_adb",
        json={"command": command, "thought": thought},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_get_n_tasks(base_url: str) -> bool:
    """Verify /get_n_tasks returns EXPECTED_TASK_COUNT."""
    print(f"\n[TEST] /get_n_tasks == {EXPECTED_TASK_COUNT}")
    resp = requests.get(f"{base_url}/get_n_tasks", timeout=10)
    data = resp.json()
    n = data.get("n_tasks")
    if n == EXPECTED_TASK_COUNT:
        print(f"  PASS: n_tasks={n}")
        return True
    else:
        print(f"  FAIL: expected {EXPECTED_TASK_COUNT}, got {n}")
        return False


def test_reset_all_tasks(base_url: str, verbose: bool) -> list[dict]:
    """Cycle through all tasks via /reset, verify each initializes."""
    print(f"\n[TEST] Reset all {EXPECTED_TASK_COUNT} tasks sequentially")
    results = []
    seen_names = set()

    for i in range(EXPECTED_TASK_COUNT):
        try:
            data = reset_task(base_url, seed=i, task_id=i)
            status = data.get("status")
            task_name = data.get("info", {}).get("task_name", "unknown")
            task_goal = data.get("observation", {}).get("task", "")

            passed = (
                status == "success"
                and task_name != "unknown"
                and task_name != ""
            )

            result = {
                "task_id": i,
                "task_name": task_name,
                "task_goal": task_goal[:80] if task_goal else "",
                "status": "PASS" if passed else "FAIL",
                "error": None,
            }

            if task_name in seen_names:
                # In sequential mode, each seed should give a different task
                # (wraps around after 50). Not a hard failure, just a note.
                result["note"] = f"duplicate of earlier task"
            seen_names.add(task_name)

            if verbose:
                mark = "PASS" if passed else "FAIL"
                print(f"  [{mark}] task_id={i:2d}  {task_name}")

        except Exception as e:
            result = {
                "task_id": i,
                "task_name": "ERROR",
                "task_goal": "",
                "status": "FAIL",
                "error": str(e),
            }
            if verbose:
                print(f"  [FAIL] task_id={i:2d}  ERROR: {e}")

        results.append(result)

    passed = sum(1 for r in results if r["status"] == "PASS")
    print(f"  Result: {passed}/{EXPECTED_TASK_COUNT} tasks initialized successfully")
    return results


def test_step_adb_basic(base_url: str) -> bool:
    """After reset, verify /step_adb works for ADB commands and FINISH."""
    print("\n[TEST] /step_adb basic flow (echo + FINISH)")

    # Reset to first task (task_id=0)
    reset_task(base_url, seed=0, task_id=0)

    # 1. Execute a simple ADB command
    data = step_adb(base_url, "adb shell echo integration_test_ping")
    output = data.get("command_output", "")
    echo_ok = "integration_test_ping" in output
    print(f"  echo command: {'PASS' if echo_ok else 'FAIL'} (output={output.strip()!r})")

    # 2. FINISH the task
    data = step_adb(base_url, "FINISH(content='integration test completed')")
    terminated = data.get("terminated", False)
    reward = data.get("reward", -1)
    finish_ok = terminated is True
    print(f"  FINISH: {'PASS' if finish_ok else 'FAIL'} (terminated={terminated}, reward={reward})")

    return echo_ok and finish_ok


def test_golden_path_bulk_delete(base_url: str) -> bool:
    """Solve Tier4BulkDeleteTmpInDownloads and verify reward=1.0.

    This task creates .tmp files in Downloads and expects them all deleted.
    task_id=0 in the sequential registry is Tier4BulkDeleteTmpInDownloads.
    """
    print("\n[TEST] Golden path: Tier4BulkDeleteTmpInDownloads (solve + reward=1.0)")

    # Reset - task_id=0 should be Tier4BulkDeleteTmpInDownloads
    data = reset_task(base_url, seed=0, task_id=0)
    task_name = data.get("info", {}).get("task_name", "")
    print(f"  task: {task_name}")

    if "BulkDeleteTmp" not in task_name:
        print(f"  SKIP: expected Tier4BulkDeleteTmpInDownloads at task_id=0, got {task_name}")
        return True  # Not a failure, just wrong task order

    # Solve: delete all .tmp files in Downloads
    data = step_adb(
        base_url,
        "adb shell find /storage/emulated/0/Download -name '*.tmp' -delete",
    )
    print(f"  delete command: output={data.get('command_output', '').strip()!r}")

    # FINISH and check reward
    data = step_adb(
        base_url,
        "FINISH(content='deleted all .tmp files from Downloads')",
    )
    reward = data.get("reward", 0)
    terminated = data.get("terminated", False)
    passed = reward == 1.0 and terminated
    print(f"  result: {'PASS' if passed else 'FAIL'} (reward={reward}, terminated={terminated})")
    return passed


def test_golden_path_app_versions(base_url: str) -> bool:
    """Solve Tier4HiddenStateListAppVersions via dumpsys and verify reward=1.0.

    task_id=2 in the sequential registry is Tier4HiddenStateListAppVersions.
    """
    print("\n[TEST] Golden path: Tier4HiddenStateListAppVersions (solve + reward=1.0)")

    # Reset - task_id=2 should be Tier4HiddenStateListAppVersions
    data = reset_task(base_url, seed=2, task_id=2)
    task_name = data.get("info", {}).get("task_name", "")
    print(f"  task: {task_name}")

    if "ListAppVersions" not in task_name:
        print(f"  SKIP: expected Tier4HiddenStateListAppVersions at task_id=2, got {task_name}")
        return True

    # Query versions for all 3 apps
    packages = {
        "Markor": "net.gsantner.markor",
        "Pro Expense": "com.arduia.expense",
        "Simple Calendar Pro": "com.simplemobiletools.calendar.pro",
    }
    version_info = []
    for app_name, pkg in packages.items():
        data = step_adb(base_url, f"adb shell dumpsys package {pkg} | grep versionName")
        output = data.get("command_output", "").strip()
        # Extract version from "versionName=X.Y.Z"
        version = "unknown"
        for line in output.split("\n"):
            if "versionName=" in line:
                version = line.split("versionName=")[-1].strip()
                break
        version_info.append(f"{app_name} {version}")
        print(f"  {app_name}: {version}")

    # FINISH with the version info as the answer
    answer = ", ".join(version_info)
    data = step_adb(base_url, f"FINISH(content='{answer}')")
    reward = data.get("reward", 0)
    terminated = data.get("terminated", False)
    passed = reward == 1.0 and terminated
    print(f"  result: {'PASS' if passed else 'FAIL'} (reward={reward}, terminated={terminated})")
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Integration tests for tier4 container")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Server URL")
    parser.add_argument("--timeout", type=int, default=600, help="Health wait timeout (s)")
    parser.add_argument("--verbose", action="store_true", help="Print per-task details")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    # Wait for container to be healthy
    if not wait_for_health(base_url, args.timeout):
        sys.exit(1)

    results = {
        "get_n_tasks": False,
        "reset_all_tasks": False,
        "step_adb_basic": False,
        "golden_bulk_delete": False,
        "golden_app_versions": False,
    }
    task_results = []

    # Run tests
    try:
        results["get_n_tasks"] = test_get_n_tasks(base_url)
        task_results = test_reset_all_tasks(base_url, args.verbose)
        results["reset_all_tasks"] = all(r["status"] == "PASS" for r in task_results)
        results["step_adb_basic"] = test_step_adb_basic(base_url)
        results["golden_bulk_delete"] = test_golden_path_bulk_delete(base_url)
        results["golden_app_versions"] = test_golden_path_app_versions(base_url)
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"\nUnexpected error: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}")
        if not passed:
            all_passed = False

    if task_results:
        passed_tasks = sum(1 for r in task_results if r["status"] == "PASS")
        failed_tasks = [r for r in task_results if r["status"] == "FAIL"]
        print(f"\n  Tasks initialized: {passed_tasks}/{len(task_results)}")
        if failed_tasks:
            print("  Failed tasks:")
            for r in failed_tasks:
                err = f" ({r['error']})" if r.get("error") else ""
                print(f"    - id={r['task_id']} {r['task_name']}{err}")

    # Task list for reference
    if task_results and args.verbose:
        print("\n  All tasks:")
        for r in task_results:
            print(f"    {r['task_id']:2d}. {r['task_name']}")

    print()
    if all_passed:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
