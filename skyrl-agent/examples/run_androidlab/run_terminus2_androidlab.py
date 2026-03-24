#!/usr/bin/env python3
"""
Run Terminus-2 agent on Android-Lab benchmark tasks.

Usage:
    # Sequential
    python run_terminus2_androidlab.py \\
        --container-url http://localhost:5800 \\
        --model anthropic/claude-sonnet-4-20250514

    # Parallel
    python run_terminus2_androidlab.py \\
        --broker-url http://localhost:9200 --pool-size 8 \\
        --model anthropic/claude-sonnet-4-20250514
"""

import argparse
import os
import sys
from functools import partial

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_THIS_DIR)

# Add terminus2 runner to path
_TERMINUS2_DIR = os.path.join(_EXAMPLES_DIR, "run_terminus2")
if _TERMINUS2_DIR not in sys.path:
    sys.path.insert(0, _TERMINUS2_DIR)

from androidlab_common import (
    check_health,
    load_androidlab_tasks,
    print_summary,
    save_results,
)
from run_claude_cli_androidlab import run_parallel, run_sequential, _error_result

from terminus2_common import run_terminus2_task_sync


def _wrap_terminus2_for_androidlab(task_def, container_url, **kwargs):
    """Wrap Terminus-2 task runner for Android-Lab tasks.

    Handles Android-Lab-specific reset and result format.
    """
    from androidlab_common import androidlab_reset, format_androidlab_instruction
    import time

    task_id = task_def["task_id"]
    app = task_def["app"]
    package = task_def["package"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} ({app}): {task_def['task'][:80]}")
    print(f"{'='*70}")

    # Reset for Android-Lab
    try:
        androidlab_reset(container_url, package=package)
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        return _error_result(task_def, f"reset: {e}")

    # Reformat task for Terminus-2 (it expects AndroidWorld-style task_def)
    adapted_task = {
        "task_id": task_id,
        "seed": 0,
        "task": format_androidlab_instruction(task_def),
    }

    start_time = time.time()
    result = run_terminus2_task_sync(
        adapted_task, container_url,
        skip_reset=True,  # we already reset
        **kwargs,
    )
    elapsed = time.time() - start_time

    # Enrich result with Android-Lab metadata
    result["app"] = app
    result["package"] = package
    result["metric_type"] = task_def["metric_type"]
    result["task_id"] = task_id
    if "elapsed_seconds" not in result:
        result["elapsed_seconds"] = elapsed

    status = "OK" if result.get("reward", 0) > 0 else "FAIL"
    print(f"  >>> {status} (reward={result.get('reward', 0)}, "
          f"steps={result.get('step_count', 0)})")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run Terminus-2 on Android-Lab benchmark"
    )
    parser.add_argument("--data", default=None)
    parser.add_argument("--tasks", type=str, default=None)
    parser.add_argument("--apps", nargs="+", default=None)
    parser.add_argument("--metric-type", default=None,
                        choices=["operation", "query_detect"])
    parser.add_argument("--model", required=True,
                        help="LiteLLM model string")
    parser.add_argument("--max-turns", type=int, default=25)
    parser.add_argument("--output", default=None)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url")
    group.add_argument("--broker-url")
    parser.add_argument("--pool-size", type=int, default=8)

    # Terminus-2 specific
    parser.add_argument("--parser", default="json",
                        choices=["json", "xml", "android-json"])
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--task-timeout", type=int, default=900)
    parser.add_argument("--template", default=None)
    parser.add_argument("--max-tokens", type=int, default=None)

    args = parser.parse_args()

    tasks = load_androidlab_tasks(
        data_path=args.data, task_ids=args.tasks,
        apps=args.apps, metric_type=args.metric_type,
    )
    if not tasks:
        print("No tasks.")
        return 1

    # Output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        import time as _time
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        ts = _time.strftime("%y%m%d_%H%M")
        exp_name = f"AndroidLab_Terminus2_{model_short}_{ts}"
        output_dir = os.path.join(_EXAMPLES_DIR, os.pardir, "results", exp_name)
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    template_override = None
    if args.template:
        template_override = os.path.abspath(args.template)

    task_runner = partial(
        _wrap_terminus2_for_androidlab,
        model=args.model,
        max_turns=args.max_turns,
        parser=args.parser,
        temperature=args.temperature,
        api_base=args.api_base,
        task_timeout=args.task_timeout,
        template_override=template_override,
        max_tokens=args.max_tokens,
    )

    print(f"Android-Lab + Terminus-2: {len(tasks)} tasks, model={args.model}")

    if args.broker_url:
        if not check_health(args.broker_url):
            print(f"ERROR: Broker not healthy")
            return 1
        results = run_parallel(
            tasks, args.broker_url, args.pool_size, output_path, task_runner
        )
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container not healthy")
            return 1
        results = run_sequential(
            tasks, args.container_url, output_path, task_runner
        )

    print_summary(results)
    save_results(results, output_path, extra_meta={
        "model": args.model, "agent": "Terminus2",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
