#!/usr/bin/env python3
"""
Convert our GUI agent traces to Android-Lab's expected directory format
so we can run the original generate_result.py on them.

Our format:
  results.jsonl → per-task results with traces[] and xml_dump_dir
  xml_dumps/{task_id}/{round}.xml → per-step raw XML

Android-Lab expected format:
  logs/evaluation/{run_name}/{task_id}_{timestamp}/
    traces/trace.jsonl   → one JSON line per step
    xml/{round}.xml      → raw XML per step
    Screen/              → screenshots (empty for us)

Usage:
    python convert_traces_to_androidlab.py \
        --results /path/to/results.jsonl \
        --output-dir /path/to/Android-Lab/logs/evaluation/crossval_v4
"""

import argparse
import json
import os
import shutil
import sys


def convert(results_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    with open(results_path) as f:
        results = [json.loads(l) for l in f if l.strip()]

    for r in results:
        task_id = r["task_id"]
        traces = r.get("traces", [])
        xml_dump_dir = r.get("xml_dump_dir", "")

        if not traces:
            continue

        # Create Android-Lab directory structure
        # {task_id}_{timestamp}/
        task_dir = os.path.join(output_dir, f"{task_id}_crossval")
        trace_dir = os.path.join(task_dir, "traces")
        xml_dir = os.path.join(task_dir, "xml")
        screen_dir = os.path.join(task_dir, "Screen")
        os.makedirs(trace_dir, exist_ok=True)
        os.makedirs(xml_dir, exist_ok=True)
        os.makedirs(screen_dir, exist_ok=True)

        # Copy XML files
        for t in traces:
            src_xml = t.get("xml_file", "")
            if src_xml and os.path.exists(src_xml):
                round_num = t.get("round", 0)
                dst_xml = os.path.join(xml_dir, f"{round_num}.xml")
                shutil.copy2(src_xml, dst_xml)

        # Write trace.jsonl in original format
        with open(os.path.join(trace_dir, "trace.jsonl"), "w") as tf:
            for t in traces:
                round_num = t.get("round", 0)
                # Build line matching original trace format exactly
                line = {
                    "trace_id": f"{task_id}_crossval",
                    "index": round_num,
                    "prompt": t.get("target", r.get("task", "")),
                    "image": f"./Screen/screenshot-{round_num}.png",
                    "xml": f"./xml/{round_num}.xml",
                    "ac_xml": None,
                    "current_activity": "",
                    "window": [1440, 3120],
                    "target": t.get("target", r.get("task", "")),
                    "command": t.get("command") if t.get("command") else {},
                    "parsed_action": t.get("parsed_action", {}),
                    "current_response": t.get("response", ""),
                }
                tf.write(json.dumps(line) + "\n")

    print(f"Converted {len(results)} tasks to {output_dir}")
    print(f"Directory structure: {output_dir}/{{task_id}}_crossval/{{traces,xml,Screen}}/")


def main():
    parser = argparse.ArgumentParser(description="Convert traces to Android-Lab format")
    parser.add_argument("--results", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    convert(args.results, args.output_dir)


if __name__ == "__main__":
    sys.exit(main())
