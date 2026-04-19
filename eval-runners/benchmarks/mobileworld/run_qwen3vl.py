#!/usr/bin/env python3
"""Qwen3-VL GUI agent runner for AndroidWorld (Terminus2 paradigm).

Uses claude_cli_common for broker orchestration and parallel execution.
Each task runs in an isolated thread with its own API client.

Usage:
    # Sequential (single container)
    python run_qwen3vl_agent.py --data val_data_seed7.jsonl \\
        --container-url http://localhost:5800 \\
        --model qwen/qwen3-vl-30b-a3b-instruct \\
        --api-url https://openrouter.ai/api/v1

    # Parallel (broker)
    python run_qwen3vl_agent.py --data val_data_seed7.jsonl \\
        --broker-url http://localhost:9300 --pool-size 12 \\
        --model qwen/qwen3-vl-30b-a3b-instruct \\
        --api-url https://openrouter.ai/api/v1
"""

import os
import sys
from functools import partial

_EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLAUDE_SDK_DIR = os.path.join(_EXAMPLES_DIR, "run_claude_sdk")
if _CLAUDE_SDK_DIR not in sys.path:
    sys.path.insert(0, _CLAUDE_SDK_DIR)

from claude_cli_common import (
    check_health,
    load_tasks,
    finalize_results,
    resolve_output_path,
    run_parallel,
    run_sequential,
)

from qwen3vl_common import run_qwen3vl_task_sync


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Qwen3-VL GUI agent for AndroidWorld evaluation",
    )
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", required=True,
                        help="OpenAI-compatible model name")
    parser.add_argument("--api-url", required=True,
                        help="API base URL (e.g. https://openrouter.ai/api/v1)")
    parser.add_argument("--api-key", default=None,
                        help="API key (default: from OPENROUTER_API_KEY or OPENAI_API_KEY env)")
    parser.add_argument("--max-steps", type=int, default=30,
                        help="Max agent steps per task (default: 30)")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="LLM temperature (default: 0.0)")
    parser.add_argument("--task-timeout", type=int, default=1800,
                        help="Per-task timeout in seconds (default: 1800)")
    parser.add_argument("--output", default=None,
                        help="Output JSONL file (auto-generated if not set)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url",
                       help="Single container URL (sequential mode)")
    group.add_argument("--broker-url",
                       help="Broker URL for parallel mode")

    parser.add_argument("--pool-size", type=int, default=8,
                        help="Number of parallel workers (broker mode)")

    # For output path generation compatibility with claude_cli_common
    parser.add_argument("--prompt", default="qwen3vl_gui",
                        help="Prompt label for output metadata")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="(alias for --max-steps, for CLI compat)")
    parser.add_argument("--effort", default=None,
                        help="(unused, kept for CLI compatibility)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.max_turns and not args.max_steps:
        args.max_steps = args.max_turns
    if args.max_turns is None:
        args.max_turns = args.max_steps

    tasks = load_tasks(args.data, args.tasks)
    if not tasks:
        print("No tasks to run.")
        return 0

    # Resolve API key
    api_key = args.api_key or os.environ.get(
        "OPENROUTER_API_KEY",
        os.environ.get("OPENAI_API_KEY", "empty"),
    )

    output_path = resolve_output_path(args)

    task_runner = partial(
        run_qwen3vl_task_sync,
        model=args.model,
        api_url=args.api_url,
        api_key=api_key,
        max_steps=args.max_steps,
        temperature=args.temperature,
        task_timeout=args.task_timeout,
    )

    system_prompt = (
        f"[Qwen3-VL GUI agent, model={args.model}, "
        f"temp={args.temperature}, max_steps={args.max_steps}]"
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (Qwen3-VL GUI)")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_steps={args.max_steps}")
    print(f"API: {args.api_url}, temperature: {args.temperature}")
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
