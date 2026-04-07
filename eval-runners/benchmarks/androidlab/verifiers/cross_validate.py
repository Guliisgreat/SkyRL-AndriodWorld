#!/usr/bin/env python3
"""Cross-validate ADB verifiers against the container's initial state.

Runs all verifiers on a fresh (unreset) container and checks that tasks
which haven't been performed return complete=False.

Usage:
    python -m verifiers.cross_validate --container-url http://localhost:5230
"""

import argparse
import json
import sys

from .verifier_map import VERIFIER_MAP, UNVERIFIABLE_TASKS
from .query_detect_judge import GROUND_TRUTH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container-url", required=True)
    args = parser.parse_args()

    print(f"Cross-validating {len(VERIFIER_MAP)} operation verifiers")
    print(f"Container: {args.container_url}")
    print(f"Unverifiable tasks (no verifier): {len(UNVERIFIABLE_TASKS)}")
    print(f"Query-detect tasks (LLM judge): {len(GROUND_TRUTH)}")
    print()

    # Test operation verifiers on initial state
    # Expected: most should return complete=False (tasks not performed yet)
    results = {}
    for task_id, verifier_cls in sorted(VERIFIER_MAP.items()):
        verifier = verifier_cls(args.container_url)
        try:
            result = verifier.is_successful()
            status = "PASS" if result.get("complete") else "FAIL"
            results[task_id] = result
            # On initial state, we expect FAIL (task not done)
            expected = "FAIL"
            match = "OK" if status == expected else "UNEXPECTED"
            print(f"  {task_id:25s} → {status:4s} {result}  [{match}]")
        except Exception as e:
            results[task_id] = {"error": str(e)}
            print(f"  {task_id:25s} → ERROR: {e}")

    # Summary
    total = len(results)
    failures = sum(1 for r in results.values() if not r.get("complete", False))
    errors = sum(1 for r in results.values() if "error" in r)
    unexpected_passes = sum(1 for r in results.values()
                           if r.get("complete", False) and "error" not in r)

    print(f"\n{'='*60}")
    print(f"SUMMARY (initial state — expect all FAIL)")
    print(f"  Total verifiers: {total}")
    print(f"  Expected FAIL: {failures}")
    print(f"  Unexpected PASS: {unexpected_passes}")
    print(f"  Errors: {errors}")

    if unexpected_passes > 0:
        print(f"\nWARNING: {unexpected_passes} tasks show complete=True on initial state!")
        print("These verifiers may have false positive issues:")
        for tid, r in sorted(results.items()):
            if r.get("complete", False):
                print(f"  {tid}: {r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
