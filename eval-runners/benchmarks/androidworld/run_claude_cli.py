#!/usr/bin/env python3
"""
Mode 1: Self-verification — agent runs once, eval scores post-hoc.

The agent uses its own self-verification (checking its work before calling
finish). The rule-based evaluator runs when the agent calls finish, but its
result is NOT fed back to the agent. This is the standard evaluation mode.

Usage:
    # Sequential (single container)
    python run_mode1.py --data val_data_seed7_no_gui.jsonl --container-url http://localhost:5800

    # Parallel (broker)
    python run_mode1.py --data val_data_seed7_no_gui.jsonl --broker-url http://localhost:9200 --pool-size 16

    # With specific prompt and effort
    python run_mode1.py --data val_data_seed7_no_gui.jsonl --broker-url http://localhost:9200 \\
        --prompt hybrid --effort high
"""

import sys
from functools import partial

from claude_cli_common import (
    build_common_parser,
    check_health,
    get_allowed_tools,
    load_system_prompt,
    load_tasks,
    finalize_results,
    preflight_checks,
    resolve_output_path,
    run_one_task,
    run_parallel,
    run_sequential,
)


def main():
    parser = build_common_parser(
        description="Mode 1: Claude self-verification (standard eval)",
    )
    args = parser.parse_args()

    # Load prompt config
    system_prompt = load_system_prompt(args.prompt, stable=args.stable_endpoint)
    allowed_tools = get_allowed_tools(args.prompt, stable=args.stable_endpoint)
    disable_tree = "Read" not in allowed_tools

    if not preflight_checks(args, system_prompt, allowed_tools, disable_tree):
        return 1

    tasks = load_tasks(args.data, args.tasks)
    if not tasks:
        print("No tasks to run.")
        return 0

    output_path = resolve_output_path(args)

    # Bind run_one_task with all config → task_runner(task_def, container_url)
    task_runner = partial(
        run_one_task,
        model=args.model,
        max_turns=args.max_turns,
        system_prompt=system_prompt,
        effort=args.effort,
        allowed_tools=allowed_tools,
        disallowed_tools=None if args.deny_list else "",
        disable_tree=disable_tree,
        stable_endpoint=args.stable_endpoint,
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (self-verification)")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_turns={args.max_turns}")
    print(f"Output: {output_path}")

    if args.broker_url:
        if not check_health(args.broker_url):
            print(f"ERROR: Broker at {args.broker_url} is not healthy")
            return 1
        print(f"Broker {args.broker_url} is healthy. Pool size: {args.pool_size}")
        results = run_parallel(
            tasks, args.broker_url, args.pool_size, output_path, task_runner,
        )
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container at {args.container_url} is not healthy")
            return 1
        print(f"Container {args.container_url} is healthy.")
        results = run_sequential(
            tasks, args.container_url, output_path, task_runner,
        )

    finalize_results(results, output_path, args.model, system_prompt, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
