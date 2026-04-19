#!/usr/bin/env python3
"""
Run mini-swe-agent on Android-Lab benchmark tasks.

Usage:
    # Sequential
    python run_mini_swe_androidlab.py \\
        --container-url http://localhost:5800 \\
        --model anthropic/claude-sonnet-4-20250514

    # Parallel
    python run_mini_swe_androidlab.py \\
        --broker-url http://localhost:9200 --pool-size 8 \\
        --model anthropic/claude-sonnet-4-20250514
"""

import argparse
import os
import sys
from functools import partial

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_THIS_DIR)

# Add mini_swe runner to path
_MINI_SWE_DIR = os.path.join(_EXAMPLES_DIR, "run_mini_swe")
if _MINI_SWE_DIR not in sys.path:
    sys.path.insert(0, _MINI_SWE_DIR)

from androidlab_common import (
    check_health,
    load_androidlab_tasks,
    print_summary,
    save_results,
)
from run_claude_cli_androidlab import run_parallel, run_sequential, _error_result


def _wrap_mini_swe_for_androidlab(task_def, container_url, **kwargs):
    """Wrap mini-swe task runner for Android-Lab tasks."""
    from androidlab_common import androidlab_reset, format_androidlab_instruction
    from mini_swe_common import run_mini_swe_task
    import time

    task_id = task_def["task_id"]
    app = task_def["app"]
    package = task_def["package"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} ({app}): {task_def['task'][:80]}")
    print(f"{'='*70}")

    try:
        androidlab_reset(container_url, package=package)
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        return _error_result(task_def, f"reset: {e}")

    adapted_task = {
        "task_id": task_id,
        "seed": 0,
        "task": format_androidlab_instruction(task_def),
    }

    start_time = time.time()
    result = run_mini_swe_task(
        adapted_task, container_url,
        skip_reset=True,
        **kwargs,
    )
    elapsed = time.time() - start_time

    result["app"] = app
    result["package"] = package
    result["metric_type"] = task_def["metric_type"]
    result["task_id"] = task_id
    if "elapsed_seconds" not in result:
        result["elapsed_seconds"] = elapsed

    status = "OK" if result.get("reward", 0) > 0 else "FAIL"
    print(f"  >>> {status} (reward={result.get('reward', 0)})")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run mini-swe-agent on Android-Lab benchmark"
    )
    parser.add_argument("--data", default=None)
    parser.add_argument("--tasks", type=str, default=None)
    parser.add_argument("--apps", nargs="+", default=None)
    parser.add_argument("--metric-type", default=None,
                        choices=["operation", "query_detect"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-turns", type=int, default=25)
    parser.add_argument("--output", default=None)
    parser.add_argument("--config", default=None,
                        help="Mini-SWE YAML config path")
    parser.add_argument("--task-timeout", type=int, default=900)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url")
    group.add_argument("--broker-url")
    parser.add_argument("--pool-size", type=int, default=8)

    args = parser.parse_args()

    tasks = load_androidlab_tasks(
        data_path=args.data, task_ids=args.tasks,
        apps=args.apps, metric_type=args.metric_type,
    )
    if not tasks:
        print("No tasks.")
        return 1

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        import time as _time
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        ts = _time.strftime("%y%m%d_%H%M")
        exp_name = f"AndroidLab_MiniSWE_{model_short}_{ts}"
        output_dir = os.path.join(_EXAMPLES_DIR, os.pardir, "results", exp_name)
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    task_runner = partial(
        _wrap_mini_swe_for_androidlab,
        model=args.model,
        config=args.config,
        task_timeout=args.task_timeout,
    )

    print(f"Android-Lab + mini-swe: {len(tasks)} tasks, model={args.model}")

    if args.broker_url:
        if not check_health(args.broker_url):
            print("ERROR: Broker not healthy")
            return 1
        results = run_parallel(
            tasks, args.broker_url, args.pool_size, output_path, task_runner
        )
    else:
        if not check_health(args.container_url):
            print("ERROR: Container not healthy")
            return 1
        results = run_sequential(
            tasks, args.container_url, output_path, task_runner
        )

    print_summary(results)
    save_results(results, output_path, extra_meta={
        "model": args.model, "agent": "MiniSWE",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
