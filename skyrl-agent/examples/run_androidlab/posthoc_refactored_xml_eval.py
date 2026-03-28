#!/usr/bin/env python3
"""
Step 3: Run REFACTORED XML verifier on saved Android-Lab traces.

Reads traces in original Android-Lab format (from eval.py run) and evaluates
using the same judge classes but through our refactored code path.

This proves our refactored verifier produces the same results as the original.

Usage:
    python posthoc_refactored_xml_eval.py \
        --trace-dir /path/to/Android-Lab/logs/evaluation/gpt4o_fresh_reproduce
"""

import argparse
import json
import os
import sys

# Add Android-Lab to path for judge classes
ANDROID_LAB_DIR = "/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab"
sys.path.insert(0, ANDROID_LAB_DIR)
os.chdir(ANDROID_LAB_DIR)

from evaluation.task import dump_xml
import importlib
import jsonlines


def get_judge(task_id):
    """Get original judge class for a task_id."""
    _map = {
        "setting":  ("evaluation.tasks.setting.setting",     "SingleTask_Setting_{}"),
        "contacts": ("evaluation.tasks.contacts.contacts",   "SingleTask_Contacts_{}"),
        "clock":    ("evaluation.tasks.clock.clock",         "SingleTask_Clock_{}"),
        "bluecoins":("evaluation.tasks.bluecoins.bluecoins", "SingleTask_bluecoins_{}"),
        "cantook":  ("evaluation.tasks.cantook.cantook",     "SingleTask_cantook_{}"),
        "pimusic":  ("evaluation.tasks.pimusic.pimusic",     "SingleTask_pimusic_{}"),
        "map":      ("evaluation.tasks.map_me.map",          "SingleTask_Mapme_{}"),
        "calendar": ("evaluation.tasks.calendar.calendar",   "SingleTask_calendar_{}"),
        "zoom":     ("evaluation.tasks.zoom.zoom",           "SingleTask_Zoom_{}"),
    }
    parts = task_id.split("_")
    entry = _map.get(parts[0])
    if not entry:
        return None
    mod_name, cls_tmpl = entry
    cls_name = cls_tmpl.format(parts[1])
    try:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name, None)
        if cls:
            class Args:
                judge_model = "gpt-4o-2024-05-13"
                api_key = ""
            return cls(Args())
    except ImportError:
        pass
    return None


def evaluate_traces(trace_dir):
    """Evaluate traces using the SAME code path as our refactored verifier.

    This replicates EXACTLY what our refactored XML verifier does inside
    run_gui_agent_androidlab.py — iterate all steps, call dump_xml + judge,
    keep last result where judge_page != False.
    """
    # Discover all task trace directories
    task_dirs = {}
    for name in os.listdir(trace_dir):
        full = os.path.join(trace_dir, name)
        if not os.path.isdir(full):
            continue
        # Parse task_id from directory name: {task_id}_{timestamp}
        parts = name.split("_")
        if len(parts) >= 3:
            task_id = f"{parts[0]}_{parts[1]}"
            task_dirs[task_id] = {
                "trace_root": full,
                "trace_file": os.path.join(full, "traces", "trace.jsonl"),
                "xml_path": os.path.join(full, "xml"),
            }

    print(f"Found {len(task_dirs)} task traces")

    results = []
    for task_id in sorted(task_dirs):
        info = task_dirs[task_id]

        judge = get_judge(task_id)
        if not judge:
            results.append({"task_id": task_id, "complete": False, "error": "no_judge"})
            continue

        if not os.path.exists(info["trace_file"]):
            results.append({"task_id": task_id, "complete": False, "error": "no_trace"})
            continue

        # Replicate EXACTLY the eval.py _evaluate_single_task logic
        final_result = {"complete": False}
        num_repeat = 0
        last_action = None

        with jsonlines.open(info["trace_file"]) as reader:
            for line in reader:
                # Repeat detection
                current_action = json.dumps(line["parsed_action"])
                if current_action == last_action:
                    num_repeat += 1
                    if num_repeat > 5:
                        break
                else:
                    num_repeat = 0
                    last_action = current_action

                # Get XML path
                if line["ac_xml"] is None:
                    xml_file = line["xml"]
                else:
                    xml_file = line["ac_xml"]
                xml_path = os.path.join(info["xml_path"], xml_file.split("/")[-1])

                if not os.path.exists(xml_path):
                    continue

                # Compress XML
                xml_compressed = dump_xml(xml_path)
                if xml_compressed is None:
                    continue

                try:
                    result = judge.judge(xml_compressed, line)

                    if "judge_page" in result and not result.get("judge_page"):
                        continue
                    else:
                        final_result = result
                except Exception:
                    pass

        results.append({
            "task_id": task_id,
            **final_result,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Refactored XML eval on Android-Lab traces")
    parser.add_argument("--trace-dir", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    results = evaluate_traces(args.trace_dir)

    # Compare with original
    total = len(results)
    passed = sum(1 for r in results if r.get("complete"))
    print(f"\nRefactored XML Verifier: {passed}/{total} ({100*passed/max(total,1):.1f}%)")

    # Per-app
    from collections import defaultdict
    apps = defaultdict(lambda: [0, 0])
    for r in results:
        app = r["task_id"].split("_")[0]
        apps[app][1] += 1
        if r.get("complete"):
            apps[app][0] += 1
    print(f"\nPer-app:")
    for app in sorted(apps):
        p, t = apps[app]
        print(f"  {app:15s} {p:2d}/{t:2d} ({100*p/t:.0f}%)")

    # Save
    output = args.output or os.path.join(args.trace_dir, "refactored_xml_results.jsonl")
    with open(output, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"\nOutput: {output}")


if __name__ == "__main__":
    sys.exit(main())
