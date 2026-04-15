#!/usr/bin/env python3
"""
Cross-validate ADB rule-based verifiers against original Android-Lab XML verifiers.

For each task:
1. Reset container
2. Execute ground truth commands (so the task IS done correctly)
3. Run ADB verifier → get result
4. Dump XML tree, run original XML verifier → get result
5. Compare: do they agree?

This validates that our ADB verifiers match the original benchmark's XML verifiers
when the task is correctly completed.

Usage:
    python cross_validate_verifiers.py --broker-url http://localhost:9200 --pool-size 8
    python cross_validate_verifiers.py --broker-url http://localhost:9200 --tasks setting_1,clock_1
"""

import argparse
import json
import os
import sys
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Add Android-Lab to path for XML verifiers
ANDROID_LAB_DIR = "/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab"
sys.path.insert(0, ANDROID_LAB_DIR)

from androidlab_common import (
    broker_acquire, broker_release, broker_androidlab_reset,
    check_health, http_post, load_androidlab_tasks, ANDROIDLAB_DATE,
)
from ground_truth_commands import get_commands, get_expected_answer, OPERATION_COMMANDS, QUERY_COMMANDS
from verifiers.verifier_map import get_verifier, EXCLUDED_TASKS
from verifiers.query_detect_verifier import FUNCTION_MAP as QD_MAP
from run_ground_truth import adb_exec


def run_xml_verifier(task_id, container_url, metric_type, finish_description=""):
    """Run the original Android-Lab XML verifier on current container state."""
    try:
        # Import the original Android-Lab evaluation
        from evaluation.task import SingleTask
        from utils_mobile.utils import get_compressed_xml

        # Dump UI XML from device
        adb_exec(container_url, "adb shell uiautomator dump /sdcard/window_dump.xml")
        time.sleep(1)
        xml_raw = adb_exec(container_url, "adb shell cat /sdcard/window_dump.xml")

        if not xml_raw or len(xml_raw) < 50:
            return {"complete": False, "error": "no_xml_dump"}

        # Compress XML like Android-Lab does
        xml_compressed = get_compressed_xml(xml_raw)
        if xml_compressed is None:
            return {"complete": False, "error": "xml_compress_failed"}
        xml_tree = json.loads(xml_compressed)

        # Get the task's judge class
        app_module_map = {
            "setting": "evaluation.tasks.setting",
            "contacts": "evaluation.tasks.contacts",
            "clock": "evaluation.tasks.clock",
            "bluecoins": "evaluation.tasks.bluecoins",
            "cantook": "evaluation.tasks.cantook",
            "pimusic": "evaluation.tasks.pimusic",
            "map": "evaluation.tasks.map_me",
            "calendar": "evaluation.tasks.calendar",
            "zoom": "evaluation.tasks.zoom",
        }

        # Find the judge class
        app = task_id.split("_")[0]
        if app == "map":
            app = "map"
        module_name = app_module_map.get(app)
        if not module_name:
            return {"complete": False, "error": f"no_module_for_{app}"}

        import importlib
        mod = importlib.import_module(module_name)

        # Class name: SingleTask_{TaskId} with capitalized parts
        # e.g., setting_1 -> SingleTask_Setting_1
        parts = task_id.split("_")
        class_name = f"SingleTask_{parts[0].capitalize()}_{parts[1]}"
        judge_cls = getattr(mod, class_name, None)

        if judge_cls is None:
            return {"complete": False, "error": f"no_class_{class_name}"}

        # Create judge instance and run
        judge = judge_cls()

        # Build the 'line' dict that the judge expects
        line = {"parsed_action": {"action": ""}}

        # For query_detect tasks, add command outputs and finish action
        if metric_type == "query_detect":
            line["parsed_action"]["action"] = "finish"
            line["parsed_action"]["description"] = finish_description

            # Add command outputs for tasks that check them
            adb_queries = {
                "setting_0": {"adb shell settings get global airplane_mode_on": adb_exec(container_url, "adb shell settings get global airplane_mode_on").strip()},
                "setting_3": {"adb shell settings get global bluetooth_on": adb_exec(container_url, "adb shell settings get global bluetooth_on").strip()},
                "setting_9": {"adb shell settings list system | grep volume_ring_speaker": adb_exec(container_url, "adb shell settings list system | grep volume_ring_speaker").strip()},
                "setting_10": {"adb shell settings list system | grep volume_alarm_speaker": adb_exec(container_url, "adb shell settings list system | grep volume_alarm_speaker").strip()},
                "setting_14": {"adb shell 'getprop persist.sys.timezone'": adb_exec(container_url, "adb shell getprop persist.sys.timezone").strip()},
                "setting_17": {"adb shell getprop ro.build.version.release": adb_exec(container_url, "adb shell getprop ro.build.version.release").strip()},
                "setting_20": {"adb shell pm list packages | grep 'com.booking'": adb_exec(container_url, "adb shell pm list packages | grep com.booking").strip()},
                "setting_22": {"adb shell settings get global airplane_mode_on": adb_exec(container_url, "adb shell settings get global airplane_mode_on").strip()},
            }
            if task_id in adb_queries:
                line["command"] = adb_queries[task_id]

        result = judge.judge(xml_tree, line)
        return result

    except Exception as e:
        return {"complete": False, "error": str(e)[:200]}


def cross_validate_one_task(task_def, broker_url, verbose=False):
    """Cross-validate one task: run ground truth, then both verifiers."""
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]
    package = task_def["package"]

    container_info = None
    try:
        container_info = broker_acquire(broker_url, timeout=120)
        env_id = container_info["env_id"]
        host = container_info.get("host", "localhost")
        port = container_info.get("server_port", 6000 + env_id)
        container_url = f"http://{host}:{port}"

        # Reset
        broker_androidlab_reset(broker_url, env_id, package=package)
        adb_exec(container_url, "adb root")
        time.sleep(2)
        adb_exec(container_url, f"adb shell date '{ANDROIDLAB_DATE}'")

        # Execute ground truth commands
        commands = get_commands(task_id)
        for cmd in commands:
            if cmd.startswith("sleep"):
                secs = int(cmd.split()[1]) if len(cmd.split()) > 1 else 2
                time.sleep(secs)
            elif cmd.startswith("TAP_TEXT:") or cmd.startswith("CLOCK_PREFS:") or \
                 cmd.startswith("SETTINGS_XML:") or cmd.startswith("BASE64_SH:"):
                # Skip special commands for now — these need the runner's handlers
                pass
            else:
                adb_exec(container_url, cmd)

        time.sleep(2)

        # For WAL apps, force-stop before verification
        wal_tasks = {"cantook_6", "cantook_7", "cantook_8", "cantook_9", "cantook_12", "pimusic_9"}
        if task_id in wal_tasks:
            adb_exec(container_url, f"adb shell am force-stop {package}")
            time.sleep(1)

        # Run ADB verifier
        adb_result = {"complete": False, "error": "no_verifier"}
        expected_answer = get_expected_answer(task_id)
        if metric_type == "operation":
            verifier_cls = get_verifier(task_id)
            if verifier_cls:
                adb_result = verifier_cls(container_url).is_successful()
        elif metric_type == "query_detect":
            qd_cls = QD_MAP.get(task_id)
            if qd_cls:
                adb_result = qd_cls(container_url).is_successful(agent_answer=expected_answer)

        # Launch the app for XML verifier (needs correct page)
        adb_exec(container_url, f"adb shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
        time.sleep(5)

        # Run XML verifier
        xml_result = run_xml_verifier(task_id, container_url, metric_type,
                                       finish_description=expected_answer)

        # Compare
        adb_pass = adb_result.get("complete", False)
        xml_pass = xml_result.get("complete", False)

        agreement = (adb_pass == xml_pass)

        result = {
            "task_id": task_id,
            "app": task_def["app"],
            "metric_type": metric_type,
            "adb_result": adb_result,
            "xml_result": xml_result,
            "adb_pass": adb_pass,
            "xml_pass": xml_pass,
            "agreement": agreement,
        }

        if verbose:
            status = "AGREE" if agreement else "DISAGREE"
            print(f"  {status} {task_id:20s} ADB={adb_pass} XML={xml_pass}")

        broker_release(broker_url, env_id, healthy=True)
        return result

    except Exception as e:
        if container_info:
            try:
                broker_release(broker_url, container_info["env_id"], healthy=True)
            except:
                pass
        return {
            "task_id": task_id,
            "error": str(e),
            "agreement": None,
        }


def main():
    parser = argparse.ArgumentParser(description="Cross-validate ADB vs XML verifiers")
    parser.add_argument("--broker-url", default="http://localhost:9200")
    parser.add_argument("--pool-size", type=int, default=8)
    parser.add_argument("--tasks", type=str, default=None)
    parser.add_argument("--apps", nargs="+", default=None)
    parser.add_argument("--metric-type", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    tasks = load_androidlab_tasks(task_ids=args.tasks, apps=args.apps, metric_type=args.metric_type)

    # Only cross-validate tasks that have ground truth commands
    gt_ids = set(OPERATION_COMMANDS.keys()) | set(QUERY_COMMANDS.keys())
    tasks = [t for t in tasks if t["task_id"] in gt_ids]
    # Skip tasks with special commands (TAP_TEXT, CLOCK_PREFS, etc.)
    skip_special = {"pimusic_7", "pimusic_11", "clock_15", "clock_17", "clock_20", "clock_22", "clock_24", "setting_4"}
    tasks = [t for t in tasks if t["task_id"] not in skip_special]

    print(f"Cross-Validation: {len(tasks)} tasks")
    print(f"Broker: {args.broker_url}")

    if not check_health(args.broker_url):
        print("ERROR: Broker not healthy")
        return 1

    output_path = args.output or f"cross_validate_{time.strftime('%y%m%d_%H%M')}.jsonl"

    results = []
    with ThreadPoolExecutor(max_workers=args.pool_size) as executor:
        futures = {
            executor.submit(cross_validate_one_task, t, args.broker_url, args.verbose): t
            for t in tasks
        }
        for future in as_completed(futures):
            result = future.result(timeout=300)
            results.append(result)
            with open(output_path, "a") as f:
                f.write(json.dumps(result) + "\n")

    # Summary
    agree = sum(1 for r in results if r.get("agreement") is True)
    disagree = [r for r in results if r.get("agreement") is False]
    errors = [r for r in results if r.get("agreement") is None]

    print(f"\n{'='*60}")
    print(f"CROSS-VALIDATION RESULTS")
    print(f"{'='*60}")
    print(f"  Agree:    {agree}/{len(results)}")
    print(f"  Disagree: {len(disagree)}/{len(results)}")
    print(f"  Errors:   {len(errors)}/{len(results)}")

    if disagree:
        print(f"\nDISAGREEMENTS:")
        for r in sorted(disagree, key=lambda x: x["task_id"]):
            print(f"  {r['task_id']:20s} ADB={r['adb_pass']} XML={r['xml_pass']}")

    if errors:
        print(f"\nERRORS:")
        for r in sorted(errors, key=lambda x: x.get("task_id", "")):
            print(f"  {r.get('task_id', '?'):20s} {r.get('error', '')[:80]}")

    print(f"\nResults: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
