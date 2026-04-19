#!/usr/bin/env python3
"""
Post-hoc evaluation using the ORIGINAL Android-Lab XML verifier code.

Reads saved per-step XML dumps from a GUI agent run and evaluates them
using the original Android-Lab judge classes — zero modifications to
the original codebase.

This allows direct comparison: original XML verifier vs refactored XML verifier
on the exact same agent traces.

Usage:
    python posthoc_original_xml_eval.py \
        --results /path/to/results.jsonl \
        --output /path/to/original_xml_results.jsonl
"""

import argparse
import json
import os
import sys

# Add original Android-Lab to path
ANDROID_LAB_DIR = "/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab"
sys.path.insert(0, ANDROID_LAB_DIR)
os.chdir(ANDROID_LAB_DIR)  # Some imports expect CWD to be Android-Lab

# Import original evaluation code — NO MODIFICATIONS
from evaluation.task import dump_xml


def get_judge_class(task_id):
    """Get the original judge class for a task_id.

    Uses the exact same class lookup as Android-Lab's Evaluation_Task.
    """
    import importlib

    # Mapping: task_id prefix → (module, class template)
    # Derived from Android-Lab/evaluation/tasks/*/
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
    app_key = parts[0]
    task_num = parts[1]

    entry = _map.get(app_key)
    if not entry:
        return None

    mod_name, cls_tmpl = entry
    cls_name = cls_tmpl.format(task_num)

    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, cls_name, None)
    except ImportError:
        return None


def evaluate_task_original(task_result):
    """Evaluate one task using the ORIGINAL Android-Lab XML verifier.

    Replicates _evaluate_single_task() from evaluation/task.py exactly:
    1. Iterate all per-step XML files
    2. Compress each via dump_xml()
    3. Call judge.judge(xml_compressed, line)
    4. If judge_page=False → skip
    5. Otherwise → keep as final_result (overwrite)
    6. Repeat detection: same action >5 times → stop
    """
    task_id = task_result["task_id"]
    traces = task_result.get("traces", [])

    # Get the judge class
    judge_cls = get_judge_class(task_id)
    if not judge_cls:
        return {"complete": False, "error": f"no_judge_class_for_{task_id}"}

    # Create judge instance with args matching original
    class Args:
        judge_model = "gpt-4o-2024-05-13"
        api_key = ""
    judge = judge_cls(Args())

    final_result = {"complete": False}
    num_repeat = 0
    last_action = None

    for trace in traces:
        # Repeat detection — same as original eval.py lines 136-143
        current_action = json.dumps(trace.get("parsed_action", {}))
        if current_action == last_action:
            num_repeat += 1
            if num_repeat > 5:
                break
        else:
            num_repeat = 0
            last_action = current_action

        # Get XML file
        xml_file = trace.get("xml_file")
        if not xml_file or not os.path.exists(xml_file):
            continue

        # Compress XML — use original dump_xml() from evaluation/task.py
        xml_compressed = dump_xml(xml_file)
        if xml_compressed is None:
            continue

        # Build line dict — same fields as original trace.jsonl
        line = {
            "parsed_action": trace.get("parsed_action", {"action": ""}),
            "target": trace.get("target", ""),
        }
        if trace.get("command"):
            line["command"] = trace["command"]

        try:
            result = judge.judge(xml_compressed, line)

            # Same logic as eval.py lines 167-170
            if "judge_page" in result and not result.get("judge_page"):
                continue
            else:
                final_result = result
        except Exception:
            pass

    return final_result


def main():
    parser = argparse.ArgumentParser(
        description="Post-hoc evaluation with original Android-Lab XML verifier"
    )
    parser.add_argument("--results", required=True,
                        help="Path to GUI agent results.jsonl (with traces and xml_file paths)")
    parser.add_argument("--output", default=None,
                        help="Output path for original XML eval results")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # Load results
    results = []
    with open(args.results) as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))

    print(f"Post-hoc Original XML Evaluation")
    print(f"Tasks: {len(results)}")
    print(f"Using: {ANDROID_LAB_DIR}/evaluation/")

    output_path = args.output or args.results.replace(".jsonl", "_original_xml.jsonl")

    eval_results = []
    for r in results:
        task_id = r["task_id"]

        if "traces" not in r or not r["traces"]:
            orig_xml = {"complete": False, "error": "no_traces"}
        else:
            orig_xml = evaluate_task_original(r)

        orig_reward = 1.0 if orig_xml.get("complete") else 0.0

        entry = {
            "task_id": task_id,
            "app": r.get("app", ""),
            "metric_type": r.get("metric_type", ""),
            "refactored_xml_reward": r.get("xml_reward", 0),
            "refactored_xml_eval": r.get("xml_eval", {}),
            "original_xml_reward": orig_reward,
            "original_xml_eval": orig_xml,
            "adb_reward": r.get("reward", 0),
            "adb_eval": r.get("adb_eval", {}),
            "agree_refactored_vs_original": (r.get("xml_reward", 0) > 0) == (orig_reward > 0),
        }
        eval_results.append(entry)

        if args.verbose:
            ref = "PASS" if r.get("xml_reward", 0) > 0 else "FAIL"
            orig = "PASS" if orig_reward > 0 else "FAIL"
            match = "OK" if ref == orig else "MISMATCH"
            print(f"  {task_id:20s} refactored={ref} original={orig} {match}")

    # Save
    with open(output_path, "w") as f:
        for e in eval_results:
            f.write(json.dumps(e) + "\n")

    # Summary
    n = len(eval_results)
    ref_pass = sum(1 for e in eval_results if e["refactored_xml_reward"] > 0)
    orig_pass = sum(1 for e in eval_results if e["original_xml_reward"] > 0)
    adb_pass = sum(1 for e in eval_results if e["adb_reward"] > 0)
    agree = sum(1 for e in eval_results if e["agree_refactored_vs_original"])

    print(f"\n{'='*60}")
    print(f"COMPARISON: Refactored vs Original XML Verifier")
    print(f"{'='*60}")
    print(f"  Refactored XML:  {ref_pass}/{n} ({100*ref_pass/n:.1f}%)")
    print(f"  Original XML:    {orig_pass}/{n} ({100*orig_pass/n:.1f}%)")
    print(f"  ADB verifier:    {adb_pass}/{n} ({100*adb_pass/n:.1f}%)")
    print(f"  Original paper:  37/138 (26.8%)")
    print(f"")
    print(f"  Refactored vs Original agreement: {agree}/{n} ({100*agree/n:.1f}%)")

    # Show mismatches
    mismatches = [e for e in eval_results if not e["agree_refactored_vs_original"]]
    if mismatches:
        print(f"\n  Mismatches ({len(mismatches)}):")
        for e in sorted(mismatches, key=lambda x: x["task_id"]):
            ref = "PASS" if e["refactored_xml_reward"] > 0 else "FAIL"
            orig = "PASS" if e["original_xml_reward"] > 0 else "FAIL"
            print(f"    {e['task_id']:20s} refactored={ref} original={orig}")
            print(f"      ref:  {str(e['refactored_xml_eval'])[:100]}")
            print(f"      orig: {str(e['original_xml_eval'])[:100]}")
    else:
        print(f"\n  PERFECT MATCH: Refactored XML verifier is identical to original.")

    print(f"\nOutput: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
