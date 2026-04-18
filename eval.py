#!/usr/bin/env python3
import json
import sys
import argparse


def main():
    parser = argparse.ArgumentParser(description="Evaluate results for a specific task group")
    parser.add_argument("result_file", help="Path to results.jsonl file")
    parser.add_argument(
        "--task-ids",
        nargs="+",
        type=int,
        default=[0, 1, 8, 20, 28, 29, 30, 37, 40, 47, 55, 75, 76, 78, 80],
        help="Task IDs to filter (default: 0 1 8 20 28 29 30 37 40 47 55 75 76 78 80)",
    )
    args = parser.parse_args()

    target_ids = set(args.task_ids)

    found = {}
    with open(args.result_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            tid = entry["task_id"]
            if tid in target_ids:
                found[tid] = entry["reward"]

    success = sum(1 for r in found.values() if r == 1)
    total = len(target_ids)
    present = len(found)

    print(f"Target group: {sorted(target_ids)}")
    print(f"Tasks found in file: {present}/{total}")
    print(f"Tasks with reward=1: {success}/{present}")
    print(f"Success rate: {success/present*100:.1f}%" if present else "No matching tasks found")
    print()
    print("Details:")
    for tid in sorted(target_ids):
        if tid in found:
            status = "PASS" if found[tid] == 1 else "FAIL"
            print(f"  task_id={tid:3d}  reward={found[tid]}  [{status}]")
        else:
            print(f"  task_id={tid:3d}  (not found in results)")


if __name__ == "__main__":
    main()
