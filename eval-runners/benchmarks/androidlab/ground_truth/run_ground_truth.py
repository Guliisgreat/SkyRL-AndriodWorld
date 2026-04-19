#!/usr/bin/env python3
"""
Ground truth validation: execute ADB commands and verify with rule-based verifiers.

Usage:
    # Run all 67 operation tasks:
    python run_ground_truth.py --broker-url http://localhost:9200 --pool-size 16

    # Run specific tasks:
    python run_ground_truth.py --broker-url http://localhost:9200 --tasks setting_1,setting_3

    # Run specific app:
    python run_ground_truth.py --broker-url http://localhost:9200 --apps bluecoins

    # Run only query tasks:
    python run_ground_truth.py --broker-url http://localhost:9200 --metric-type query_detect

    # Dry run (print commands without executing):
    python run_ground_truth.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from androidlab_common import (
    broker_acquire,
    broker_release,
    broker_androidlab_reset,
    check_health,
    http_post,
    load_androidlab_tasks,
    print_summary,
    save_results,
    ANDROIDLAB_DATE,
)
from ground_truth_commands import (
    OPERATION_COMMANDS,
    QUERY_COMMANDS,
    get_commands,
    get_expected_answer,
)
from verifiers.verifier_map import get_verifier, EXCLUDED_TASKS
from verifiers.query_detect_verifier import FUNCTION_MAP as QD_MAP


def adb_exec(container_url, command, timeout=30):
    """Execute an ADB shell command on a container.

    For sqlite3 commands, uses base64 encoding to bypass shell quoting issues
    (same approach as android_env.py's cmd_sql).
    """
    import base64 as _b64

    # Handle sqlite3 commands via base64 encoding
    if "sqlite3" in command and not command.startswith("adb"):
        # Parse: sqlite3 <db_path> 'SQL' or sqlite3 <db_path> "SQL"
        parts = command.split(None, 2)  # ['sqlite3', db_path, 'SQL...']
        if len(parts) >= 3:
            db_path = parts[1]
            sql = parts[2]
            # Strip only the outermost matching quote pair
            if (sql.startswith("'") and sql.endswith("'")) or \
               (sql.startswith('"') and sql.endswith('"')):
                sql = sql[1:-1]
            encoded = _b64.b64encode(sql.encode("utf-8")).decode("ascii")
            command = f'adb shell "echo {encoded} | base64 -d | sqlite3 {db_path}"'
        else:
            # Just a sqlite3 command like .tables
            if not command.startswith("adb"):
                command = f"adb shell {command}"
    elif not command.startswith("adb"):
        command = f"adb shell {command}"
    try:
        data = json.dumps({
            "command": command,
            "thought": "ground_truth",
        }).encode()
        import urllib.request
        req = urllib.request.Request(
            f"{container_url}/step_adb",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
            return result.get("command_output", "")
    except Exception as e:
        # Fallback to /step endpoint
        try:
            result = http_post(f"{container_url}/step", {
                "action": {"action_type": "adb", "command": command},
                "thought": "ground_truth",
            }, timeout=timeout)
            return result.get("observation", result.get("command_output", f"ERROR: {e}"))
        except Exception as e2:
            return f"ERROR: {e2}"


def run_one_task(task_def, container_url, verbose=False):
    """Run ground truth commands for one task and verify."""
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]
    package = task_def["package"]

    start = time.time()
    commands = get_commands(task_id)
    outputs = []

    if not commands and metric_type != "query_detect":
        return {
            "task_id": task_id,
            "app": task_def["app"],
            "metric_type": metric_type,
            "reward": 0.0,
            "status": "no_commands",
            "commands": [],
            "outputs": [],
            "eval_result": {"complete": False, "reason": "no ground truth commands"},
            "elapsed": 0,
        }

    # Check if commands use shell variables ($()) — need script mode
    needs_script = any("$(" in c or "$NEW_ID" in c or "$AAA_ID" in c
                       or "$ABC_ID" in c or "$GRP_ID" in c or "$ABC_PHONE" in c
                       for c in commands)

    if needs_script:
        # Write commands as a shell script on device for variable expansion
        import base64
        script_lines = ["#!/system/bin/sh"]
        for cmd in commands:
            script_lines.append(cmd)
        script_content = "\n".join(script_lines) + "\n"
        # Base64 encode to avoid quoting issues
        b64 = base64.b64encode(script_content.encode()).decode()
        adb_exec(container_url, f"echo {b64} | base64 -d > /data/local/tmp/gt.sh")
        adb_exec(container_url, "chmod 755 /data/local/tmp/gt.sh")
        output = adb_exec(container_url, "sh /data/local/tmp/gt.sh", timeout=60)
        outputs.append(output)
        if verbose:
            print(f"    SCRIPT ({len(commands)} cmds)")
            print(f"    OUT: {output[:300]}")
    else:
        for cmd in commands:
            if cmd.startswith("sleep"):
                secs = int(cmd.split()[1]) if len(cmd.split()) > 1 else 2
                time.sleep(secs)
                outputs.append(f"(slept {secs}s)")
                continue

            # Special: BASE64_SH — encode command as base64 and pipe to sh
            # Preserves all quoting/spaces through the HTTP API shell layers
            if cmd.startswith("BASE64_SH:"):
                import base64 as _b64_sh
                shell_cmd = cmd[len("BASE64_SH:"):]
                enc = _b64_sh.b64encode(shell_cmd.encode()).decode()
                output = adb_exec(container_url, f'adb shell "echo {enc} | base64 -d | sh"')
                outputs.append(output)
                if verbose:
                    print(f"    BASE64_SH: {shell_cmd[:80]}")
                    print(f"    OUT: {output[:200]}")
                continue

            # Special: CLOCK_PREFS — edit Clock SharedPreferences XML
            if cmd.startswith("CLOCK_PREFS:"):
                import re as _re
                parts = cmd.split(":", 2)
                action = parts[1] if len(parts) > 1 else ""
                arg = parts[2] if len(parts) > 2 else ""

                prefs_path = "/data/user_de/0/com.google.android.deskclock/shared_prefs/com.google.android.deskclock_preferences.xml"
                prefs_xml = adb_exec(container_url, f"adb shell cat {prefs_path}")

                if action == "add_cities":
                    # arg = "London,Europe/London,London UK,placeId|Barcelona,..."
                    cities = arg.split("|")
                    # Find current number_of_places
                    m = _re.search(r'name="number_of_places" value="(\d+)"', prefs_xml)
                    n = int(m.group(1)) if m else 0
                    new_entries = []
                    for city_str in cities:
                        cparts = city_str.split(",", 3)
                        if len(cparts) >= 4:
                            display, tz, full, pid = cparts
                            new_entries.append(
                                f'    <string name="place_display_name_{n}">{display}</string>\n'
                                f'    <string name="place_timezone_id_{n}">{tz}</string>\n'
                                f'    <string name="place_full_name_{n}">{full}</string>\n'
                                f'    <string name="place_id{n}">{pid}</string>'
                            )
                            n += 1
                    # Update number_of_places
                    if m:
                        prefs_xml = _re.sub(r'name="number_of_places" value="\d+"',
                                           f'name="number_of_places" value="{n}"', prefs_xml)
                    else:
                        prefs_xml = prefs_xml.replace("</map>",
                            f'    <int name="number_of_places" value="{n}" />\n</map>')
                    # Insert new entries before </map>
                    insert_text = "\n".join(new_entries)
                    prefs_xml = prefs_xml.replace("</map>", f"{insert_text}\n</map>")

                elif action == "remove_city":
                    # Remove city by display name
                    city_name = arg
                    # Find which index this city is at
                    m = _re.search(rf'name="place_display_name_(\d+)">{city_name}', prefs_xml)
                    if m:
                        idx = m.group(1)
                        # Remove all entries for this index
                        for key in ["place_display_name", "place_timezone_id", "place_full_name", "place_id"]:
                            prefs_xml = _re.sub(rf'\s*<string name="{key}_{idx}">[^<]*</string>', '', prefs_xml)
                            prefs_xml = _re.sub(rf'\s*<string name="{key}{idx}">[^<]*</string>', '', prefs_xml)
                        # Decrement number_of_places
                        nm = _re.search(r'name="number_of_places" value="(\d+)"', prefs_xml)
                        if nm:
                            new_n = max(0, int(nm.group(1)) - 1)
                            prefs_xml = _re.sub(r'name="number_of_places" value="\d+"',
                                               f'name="number_of_places" value="{new_n}"', prefs_xml)

                elif action == "set_key":
                    # Set or add a key-value pair
                    kv = arg.split(":", 1)
                    key, val = kv[0], kv[1] if len(kv) > 1 else ""
                    if f'name="{key}"' in prefs_xml:
                        # Update existing — handle both string and other types
                        prefs_xml = _re.sub(rf'name="{key}">[^<]*<', f'name="{key}">{val}<', prefs_xml)
                        prefs_xml = _re.sub(rf'name="{key}" value="[^"]*"', f'name="{key}" value="{val}"', prefs_xml)
                    else:
                        prefs_xml = prefs_xml.replace("</map>",
                            f'    <string name="{key}">{val}</string>\n</map>')

                # Write back via base64
                import base64 as _b64_2
                enc = _b64_2.b64encode(prefs_xml.encode()).decode()
                adb_exec(container_url, f'adb shell "echo {enc} | base64 -d > {prefs_path}"')
                outputs.append(f"CLOCK_PREFS:{action}:{arg[:50]}")
                if verbose:
                    print(f"    CLOCK_PREFS: {action} {arg[:80]}")
                continue

            # Special: SETTINGS_XML — edit Android settings XML directly
            if cmd.startswith("SETTINGS_XML:"):
                import re as _re
                parts = cmd.split(":", 3)
                namespace = parts[1]  # secure, system, global
                key = parts[2]
                val = parts[3] if len(parts) > 3 else ""
                xml_path = f"/data/system/users/0/settings_{namespace}.xml"
                xml_content = adb_exec(container_url, f"adb shell cat {xml_path}")
                if f'name="{key}"' in xml_content:
                    xml_content = _re.sub(
                        rf'name="{key}" value="[^"]*"',
                        f'name="{key}" value="{val}"',
                        xml_content
                    )
                else:
                    xml_content = xml_content.replace("</settings>",
                        f'  <setting id="999" name="{key}" value="{val}" package="android" />\n</settings>')
                import base64 as _b64_3
                enc = _b64_3.b64encode(xml_content.encode()).decode()
                adb_exec(container_url, f'adb shell "echo {enc} | base64 -d > {xml_path}"')
                # Force settings provider to re-read
                adb_exec(container_url, "adb shell am force-stop com.android.providers.settings")
                time.sleep(1)
                outputs.append(f"SETTINGS_XML:{namespace}:{key}={val}")
                if verbose:
                    print(f"    SETTINGS_XML: {namespace}/{key} = {val}")
                continue

            # Special command: TAP_TEXT:xyz — dump UI, find text, tap center
            if cmd.startswith("TAP_TEXT:"):
                target_text = cmd.split(":", 1)[1]
                adb_exec(container_url, "adb shell uiautomator dump /sdcard/ui.xml")
                ui_xml = adb_exec(container_url, "adb shell cat /sdcard/ui.xml")
                import re as _re
                nodes = _re.findall(
                    r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                    ui_xml
                )
                tapped = False
                for text, x1, y1, x2, y2 in nodes:
                    if target_text in text:
                        cx = (int(x1) + int(x2)) // 2
                        cy = (int(y1) + int(y2)) // 2
                        adb_exec(container_url, f"adb shell input tap {cx} {cy}")
                        outputs.append(f"TAP_TEXT:{target_text} -> tap({cx},{cy})")
                        tapped = True
                        if verbose:
                            print(f"    TAP_TEXT: '{target_text}' at ({cx},{cy})")
                        break
                if not tapped:
                    outputs.append(f"TAP_TEXT:{target_text} -> NOT FOUND")
                    if verbose:
                        print(f"    TAP_TEXT: '{target_text}' NOT FOUND on screen")
                continue

            output = adb_exec(container_url, cmd)
            outputs.append(output)
            if verbose:
                print(f"    CMD: {cmd[:100]}")
                print(f"    OUT: {output[:200]}")

    # Small wait for state to settle
    time.sleep(1)

    # For WAL-mode DB tasks, force-stop before verification so verifier can read DB
    # But NOT for app-launch tasks (cantook_10/11, pimusic_7/11) that need the app running
    wal_tasks = {"cantook_6", "cantook_7", "cantook_8", "cantook_9", "cantook_12", "pimusic_9"}
    if task_id in wal_tasks:
        adb_exec(container_url, f"adb shell am force-stop {package}")
        time.sleep(1)

    # Verify
    eval_result = {"complete": False}
    try:
        if metric_type == "operation":
            verifier_cls = get_verifier(task_id)
            if verifier_cls:
                verifier = verifier_cls(container_url)
                eval_result = verifier.is_successful()
            else:
                eval_result = {"complete": False, "reason": "no_verifier"}
        elif metric_type == "query_detect":
            expected = get_expected_answer(task_id)
            qd_cls = QD_MAP.get(task_id)
            if qd_cls:
                qd = qd_cls(container_url)
                eval_result = qd.is_successful(agent_answer=expected)
            else:
                eval_result = {"complete": False, "reason": "no_query_verifier"}
    except Exception as e:
        eval_result = {"complete": False, "error": str(e)}

    elapsed = time.time() - start
    reward = 1.0 if eval_result.get("complete") else 0.0

    return {
        "task_id": task_id,
        "app": task_def["app"],
        "package": package,
        "metric_type": metric_type,
        "task": task_def["task"],
        "reward": reward,
        "eval_result": eval_result,
        "commands": commands,
        "outputs": outputs,
        "elapsed": round(elapsed, 1),
    }


def run_task_with_broker(task_def, broker_url, verbose=False):
    """Acquire container, reset, run task, release."""
    task_id = task_def["task_id"]
    package = task_def["package"]
    container_info = None

    try:
        # Acquire
        container_info = broker_acquire(broker_url, timeout=120)
        env_id = container_info["env_id"]
        host = container_info.get("host", "localhost")
        port = container_info.get("server_port", 6000 + env_id)
        container_url = container_info.get("url", f"http://{host}:{port}")

        if verbose:
            print(f"\n  [{task_id}] acquired env{env_id} ({container_url})")

        # Reset container for this task
        broker_androidlab_reset(broker_url, env_id, package=package)
        if verbose:
            print(f"  [{task_id}] reset done")

        # Ensure root
        adb_exec(container_url, "adb root")
        time.sleep(1)

        # Set fixed date
        adb_exec(container_url, f"date '{ANDROIDLAB_DATE}'")

        # Run ground truth
        result = run_one_task(task_def, container_url, verbose=verbose)

        # Release
        broker_release(broker_url, env_id, healthy=True)
        return result

    except Exception as e:
        if container_info:
            try:
                broker_release(broker_url, container_info["env_id"], healthy=True)
            except Exception:
                pass
        return {
            "task_id": task_id,
            "app": task_def["app"],
            "metric_type": task_def["metric_type"],
            "reward": 0.0,
            "status": "error",
            "error": str(e),
            "eval_result": {"complete": False, "error": str(e)},
            "elapsed": 0,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Run ground truth commands and verify"
    )
    parser.add_argument("--broker-url", default="http://localhost:9200")
    parser.add_argument("--pool-size", type=int, default=16)
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs")
    parser.add_argument("--apps", nargs="+", default=None)
    parser.add_argument("--metric-type", default=None,
                        choices=["operation", "query_detect"])
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without executing")
    parser.add_argument("--output", default=None)

    args = parser.parse_args()

    # Load tasks
    tasks = load_androidlab_tasks(
        task_ids=args.tasks, apps=args.apps, metric_type=args.metric_type,
    )

    # Filter to only evaluable tasks (exclude GUI-only)
    tasks = [t for t in tasks if t["task_id"] not in EXCLUDED_TASKS]

    # Filter to tasks that have ground truth commands
    all_gt_ids = set(OPERATION_COMMANDS.keys()) | set(QUERY_COMMANDS.keys())
    tasks = [t for t in tasks if t["task_id"] in all_gt_ids]

    if not tasks:
        print("No tasks to run.")
        return 1

    print(f"Ground Truth Validation")
    print(f"Tasks: {len(tasks)}")
    print(f"Broker: {args.broker_url}")
    print(f"Pool size: {args.pool_size}")

    if args.dry_run:
        print(f"\n{'='*70}")
        print("DRY RUN — commands only")
        print(f"{'='*70}")
        for t in sorted(tasks, key=lambda x: x["task_id"]):
            tid = t["task_id"]
            cmds = get_commands(tid)
            print(f"\n[{tid}] ({t['metric_type']}) {t['task'][:60]}")
            for c in cmds:
                print(f"  $ {c}")
            if tid in QUERY_COMMANDS:
                print(f"  EXPECTED: {get_expected_answer(tid)}")
        return 0

    # Check broker health
    if not check_health(args.broker_url):
        print("ERROR: Broker not healthy")
        return 1

    # Output path
    if args.output:
        output_path = args.output
    else:
        ts = time.strftime("%y%m%d_%H%M")
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            os.pardir, "results", f"GroundTruth_{ts}"
        )
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Run tasks in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.pool_size) as executor:
        futures = {
            executor.submit(
                run_task_with_broker, t, args.broker_url, args.verbose
            ): t
            for t in tasks
        }

        for future in as_completed(futures):
            task_def = futures[future]
            try:
                result = future.result(timeout=300)
            except Exception as e:
                result = {
                    "task_id": task_def["task_id"],
                    "app": task_def["app"],
                    "metric_type": task_def["metric_type"],
                    "reward": 0.0,
                    "error": str(e),
                    "eval_result": {"complete": False},
                }

            results.append(result)
            status = "PASS" if result.get("reward", 0) > 0 else "FAIL"
            eval_r = result.get("eval_result", {})
            print(f"  {status} {result['task_id']:20s} "
                  f"({result.get('elapsed', 0):.0f}s) {eval_r}")

            # Save incrementally
            with open(output_path, "a") as f:
                f.write(json.dumps(result) + "\n")

    # Print summary
    print_summary(results)

    # Save final
    save_results(results, output_path, extra_meta={
        "agent": "GroundTruth",
        "total_tasks": len(tasks),
    })

    # Print failures for analysis
    failures = [r for r in results if r.get("reward", 0) == 0]
    if failures:
        print(f"\n{'='*70}")
        print(f"FAILURES ({len(failures)}):")
        print(f"{'='*70}")
        for f in sorted(failures, key=lambda x: x["task_id"]):
            print(f"\n  {f['task_id']} ({f['app']}, {f['metric_type']}):")
            print(f"    Task: {f.get('task', '')[:80]}")
            print(f"    Eval: {f.get('eval_result', {})}")
            if f.get("commands"):
                for i, (cmd, out) in enumerate(
                    zip(f.get("commands", []), f.get("outputs", []))
                ):
                    print(f"    [{i}] $ {cmd[:100]}")
                    print(f"        -> {str(out)[:150]}")
            if f.get("error"):
                print(f"    Error: {f['error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
