#!/usr/bin/env python3
"""
Run Claude Code CLI agent on MobileWorld tasks.

Supports sequential (single container), parallel (multiple containers),
and broker-managed modes.

Usage:
    # Sequential
    python run_claude_cli.py --data tasks.jsonl --container-url http://localhost:6804 \
        --prompt mw_terminal_expert

    # Broker
    python run_claude_cli.py --data tasks.jsonl --broker-url http://localhost:9400 \
        --pool-size 4 --prompt mw_terminal_expert
"""

import sys
from functools import partial

from mw_cli_common import (
    build_common_parser,
    check_health,
    finalize_results,
    get_allowed_tools,
    load_system_prompt,
    load_tasks,
    parse_containers,
    preflight_checks,
    resolve_output_path,
    run_broker,
    run_one_task,
    run_parallel,
    run_sequential,
)


def main():
    parser = build_common_parser(
        description="Claude Code CLI agent on MobileWorld",
    )
    args = parser.parse_args()

    system_prompt = load_system_prompt(args.prompt)
    allowed_tools = get_allowed_tools(args.prompt)
    disable_tree = "Read" not in allowed_tools

    if not preflight_checks(args, system_prompt, allowed_tools, disable_tree):
        return 1

    tasks = load_tasks(args.data, args.tasks)
    if not tasks:
        print("No tasks to run.")
        return 0

    output_path = resolve_output_path(args)

    task_runner = partial(
        run_one_task,
        model=args.model,
        max_turns=args.max_turns,
        system_prompt=system_prompt,
        effort=args.effort,
        allowed_tools=allowed_tools,
        disable_tree=disable_tree,
    )

    if args.broker_url:
        mode = "broker"
        if not check_health(args.broker_url):
            print(f"ERROR: Broker at {args.broker_url} is not healthy")
            return 1
        print(f"Broker {args.broker_url} is healthy. Pool size: {args.pool_size}")
    elif args.containers:
        mode = "parallel"
    else:
        mode = "sequential"

    print(f"Mode: {mode}")
    print(f"Prompt: {args.prompt}")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_turns={args.max_turns}")
    print(f"Allowed tools: {allowed_tools}")
    print(f"Output: {output_path}")

    if mode == "broker":
        results = run_broker(
            tasks, args.broker_url, args.pool_size, output_path, task_runner,
        )
    elif mode == "parallel":
        containers = parse_containers(args.containers)
        results = run_parallel(tasks, containers, output_path, task_runner)
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container at {args.container_url} is not healthy")
            return 1
        print(f"Container {args.container_url} is healthy.")
        results = run_sequential(tasks, args.container_url, output_path, task_runner)

    finalize_results(results, output_path, args.model, system_prompt, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
