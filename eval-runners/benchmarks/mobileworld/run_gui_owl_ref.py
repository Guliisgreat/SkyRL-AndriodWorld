#!/usr/bin/env python3
"""Reference-faithful GUI-Owl-1.5 runner for AndroidWorld evaluation.

Uses the paper's original system prompt, 2-message conversation format,
and history extraction logic.  See gui_owl_ref_common.py for details.

Usage:
    # Parallel (broker)
    python run_gui_owl_ref.py --data ../../data/mobileworld/gui_only_tasks.jsonl \
        --broker-url http://localhost:9400 --pool-size 16 \
        --model GUI-Owl-1.5-32B-Instruct \
        --api-url http://localhost:8401/v1

    # Sequential (single container)
    python run_gui_owl_ref.py --data ../../data/mobileworld/gui_only_tasks.jsonl \
        --container-url http://localhost:6896 \
        --model GUI-Owl-1.5-32B-Instruct \
        --api-url http://localhost:8401/v1
"""

import os
import sys
from functools import partial

_BENCHMARKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AW_DIR = os.path.join(_BENCHMARKS_DIR, "androidworld")
_GUI_DIR = os.path.join(os.path.dirname(_BENCHMARKS_DIR), "agents", "gui")
for _d in (_AW_DIR, _GUI_DIR):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from claude_cli_common import (
    check_health,
    load_tasks,
    finalize_results,
    resolve_output_path,
    run_parallel,
    run_sequential,
)

from gui_owl_ref_common import run_gui_owl_ref_task_sync


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Reference-faithful GUI-Owl-1.5 agent for AndroidWorld evaluation",
    )
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", required=True,
                        help="OpenAI-compatible model name")
    parser.add_argument("--api-url", required=True,
                        help="API base URL (e.g. http://localhost:8401/v1)")
    parser.add_argument("--api-key", default=None,
                        help="API key (default: from env)")
    parser.add_argument("--max-steps", type=int, default=50,
                        help="Max agent steps per task (default: 50)")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="LLM temperature (default: 0.0)")
    parser.add_argument("--max-tokens", type=int, default=2048,
                        help="Max output tokens per LLM call (default: 2048)")
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
    parser.add_argument("--prompt", default="gui_owl_1_5_ref",
                        help="Prompt label for output metadata")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="(alias for --max-steps, for CLI compat)")
    parser.add_argument("--effort", default=None,
                        help="(unused, kept for CLI compatibility)")
    parser.add_argument("--history-n", type=int, default=1,
                        help="(unused, kept for CLI compat)")
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

    api_key = args.api_key or os.environ.get(
        "OPENROUTER_API_KEY",
        os.environ.get("OPENAI_API_KEY", "empty"),
    )

    output_path = resolve_output_path(args)

    task_runner = partial(
        run_gui_owl_ref_task_sync,
        model=args.model,
        api_url=args.api_url,
        api_key=api_key,
        max_steps=args.max_steps,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        task_timeout=args.task_timeout,
    )

    system_prompt = (
        f"[GUI-Owl-1.5-REF agent, model={args.model}, "
        f"temp={args.temperature}, max_steps={args.max_steps}]"
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (GUI-Owl-1.5-REF -> AndroidWorld)")
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
