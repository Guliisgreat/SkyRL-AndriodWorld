#!/usr/bin/env python3
"""Qwen3.5 GUI agent via DashScope API for AndroidWorld (Terminus2 paradigm).

Uses DashScope's native endpoint with vl_high_resolution_images for better
screenshot understanding than OpenRouter.

Usage:
    # Sequential (single container)
    python run_qwen35_dashscope_agent.py --data val_data_seed7.jsonl \
        --container-url http://localhost:5800 \
        --model qwen-vl-max-latest

    # Parallel (broker)
    python run_qwen35_dashscope_agent.py --data val_data_seed7.jsonl \
        --broker-url http://localhost:9300 --pool-size 16 \
        --model qwen-vl-max-latest
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

from qwen35_dashscope_common import run_qwen35_dashscope_task_sync

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Qwen3.5 GUI agent via DashScope for AndroidWorld evaluation",
    )
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", default="qwen-vl-max-latest",
                        help="DashScope model name (default: qwen-vl-max-latest)")
    parser.add_argument("--api-url", default=DASHSCOPE_BASE_URL,
                        help=f"API base URL (default: {DASHSCOPE_BASE_URL})")
    parser.add_argument("--api-key", default=None,
                        help="DashScope API key (default: from DASHSCOPE_API_KEY env)")
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

    parser.add_argument("--prompt", default="qwen35_dashscope_gui",
                        help="Prompt label for output metadata")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="(alias for --max-steps)")
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

    api_key = args.api_key or os.environ.get("DASHSCOPE_API_KEY", "empty")

    output_path = resolve_output_path(args)

    task_runner = partial(
        run_qwen35_dashscope_task_sync,
        model=args.model,
        api_url=args.api_url,
        api_key=api_key,
        max_steps=args.max_steps,
        temperature=args.temperature,
        task_timeout=args.task_timeout,
    )

    system_prompt = (
        f"[Qwen3.5 DashScope GUI agent, model={args.model}, "
        f"temp={args.temperature}, max_steps={args.max_steps}]"
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (Qwen3.5 DashScope)")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_steps={args.max_steps}")
    print(f"API: {args.api_url}")
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
