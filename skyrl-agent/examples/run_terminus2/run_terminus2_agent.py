#!/usr/bin/env python3
"""
Mode 1: Self-verification — Terminus_2 agent runs once per task.

Uses Harbor's Terminus_2 agent (LiteLLM multi-model, JSON/XML parsing)
with direct subprocess execution (no tmux).

Usage:
    # Sequential (single container)
    python run_terminus2_agent.py --data val_data_seed7_no_gui.jsonl \\
        --container-url http://localhost:5800 --model anthropic/claude-sonnet-4-20250514

    # Parallel (broker)
    python run_terminus2_agent.py --data val_data_seed7_no_gui.jsonl \\
        --broker-url http://localhost:9200 --pool-size 16 \\
        --model anthropic/claude-sonnet-4-20250514

    # With XML parser and custom temperature
    python run_terminus2_agent.py --data val_data_seed7_no_gui.jsonl \\
        --container-url http://localhost:5800 --model openai/gpt-4o \\
        --parser xml --temperature 0.5
"""

import os
import sys
from functools import partial

# Add run_claude_sdk to path for claude_cli_common
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
    ANDROID_ENV_SCRIPT,
)

from terminus2_common import run_terminus2_task_sync


def build_parser():
    """Build argument parser with Terminus_2-specific args."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Mode 1: Terminus_2 agent (self-verification, standard eval)",
    )
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", required=True,
                        help="LiteLLM model string (e.g., anthropic/claude-sonnet-4-20250514)")
    parser.add_argument("--max-turns", type=int, default=30,
                        help="Max agent turns (default: 30)")
    parser.add_argument("--output", default=None,
                        help="Output JSONL file (auto-generated if not set)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url",
                       help="Single container URL (sequential mode)")
    group.add_argument("--broker-url",
                       help="Broker URL for parallel mode")

    parser.add_argument("--pool-size", type=int, default=8,
                        help="Number of parallel workers (broker mode)")

    # Terminus_2-specific
    parser.add_argument("--parser", default="json", choices=["json", "xml", "android-json"],
                        help="Response parser format (default: json)")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="LLM temperature (default: 0.7)")
    parser.add_argument("--api-base", default=None,
                        help="LiteLLM api_base override (e.g., for local vLLM)")
    parser.add_argument("--command-timeout", type=int, default=60,
                        help="Per-command timeout in seconds (default: 60)")
    parser.add_argument("--task-timeout", type=int, default=900,
                        help="Per-task timeout in seconds (default: 900)")
    parser.add_argument("--reasoning-effort", default=None,
                        help="LLM reasoning effort (for models that support it)")
    parser.add_argument("--template", default=None,
                        help="Path to custom template file (overrides default for parser)")

    # Reuse --prompt and --effort for output path generation compatibility
    parser.add_argument("--prompt", default="terminus2_json",
                        help="Prompt label for output metadata (default: terminus2_json)")
    parser.add_argument("--effort", default=None,
                        help="(unused, kept for CLI compatibility)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    tasks = load_tasks(args.data, args.tasks)
    if not tasks:
        print("No tasks to run.")
        return 0

    if not os.path.exists(ANDROID_ENV_SCRIPT):
        print(f"ERROR: android_env.py not found at {ANDROID_ENV_SCRIPT}")
        return 1

    output_path = resolve_output_path(args)

    # Resolve template override to absolute path
    template_override = None
    if args.template:
        template_override = os.path.abspath(args.template)
        if not os.path.exists(template_override):
            print(f"ERROR: Template file not found: {template_override}")
            return 1

    # Bind task runner with all config
    task_runner = partial(
        run_terminus2_task_sync,
        model=args.model,
        max_turns=args.max_turns,
        parser=args.parser,
        temperature=args.temperature,
        api_base=args.api_base,
        command_timeout=args.command_timeout,
        task_timeout=args.task_timeout,
        reasoning_effort=args.reasoning_effort,
        template_override=template_override,
    )

    # Build a system prompt string for ATIF / finalize (not used by agent itself)
    system_prompt = (
        f"[Terminus_2 agent, model={args.model}, parser={args.parser}, "
        f"temp={args.temperature}]"
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (Terminus_2, self-verification)")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_turns={args.max_turns}")
    print(f"Parser: {args.parser}, temperature: {args.temperature}")
    if args.api_base:
        print(f"API base: {args.api_base}")
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
