#!/usr/bin/env python3
"""
Mode 1: Self-verification — mini-swe-agent runs once per task.

Usage:
    # Sequential
    python run_agent.py --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \\
        --container-url http://localhost:5800 --model claude-sonnet-4-6

    # Parallel with broker
    python run_agent.py --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \\
        --broker-url http://localhost:9200 --pool-size 16 --model claude-sonnet-4-6
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

from mini_swe_common import (
    load_config,
    result_to_atif as mini_swe_result_to_atif,
    run_mini_swe_task,
)


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Mode 1: mini-swe-agent (self-verification)",
    )
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", required=True,
                        help="LiteLLM model string")
    parser.add_argument("--config", default=None,
                        help="Path to YAML config (default: androidworld.yaml)")
    parser.add_argument("--output", default=None,
                        help="Output JSONL file")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url",
                       help="Single container URL (sequential mode)")
    group.add_argument("--broker-url",
                       help="Broker URL for parallel mode")

    parser.add_argument("--pool-size", type=int, default=8,
                        help="Number of parallel workers")
    parser.add_argument("--task-timeout", type=int, default=900,
                        help="Per-task timeout in seconds")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="Override agent.step_limit from the YAML config "
                             "(default: use the value in androidworld.yaml, 30)")

    # Plumbed into config['model']['model_kwargs']['api_base']. Mirrors the
    # --api-base flag on run_terminus2.py — useful for local vLLM and for
    # OpenRouter when you want to be explicit (litellm handles `openrouter/*`
    # natively, so this is optional for OpenRouter).
    parser.add_argument("--api-base", default=None,
                        help="Override LiteLLM api_base (e.g. https://openrouter.ai/api/v1 "
                             "or http://localhost:8000/v1 for local vLLM)")
    parser.add_argument("--reasoning-effort", default=None,
                        help="LLM reasoning effort (for models that support it)")

    # For output path generation compatibility
    parser.add_argument("--prompt", default="mini_swe_agent",
                        help="Prompt label for output metadata")
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

    # Load config
    config_path = args.config or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "androidworld.yaml"
    )
    if not os.path.exists(config_path):
        print(f"ERROR: Config not found at {config_path}")
        return 1
    config = load_config(config_path)
    if args.max_turns is not None:
        config.setdefault("agent", {})["step_limit"] = args.max_turns
    # Reflect resolved step_limit back onto args so finalize_results' summary
    # (summary.json:"max_turns") matches what the agent actually used.
    args.max_turns = config.get("agent", {}).get("step_limit", 30)

    # --api-base goes inside model_kwargs (litellm.completion accepts api_base
    # there). Top-level `api_base` would fail Pydantic validation on
    # LitellmTextbasedModelConfig.
    if args.api_base:
        model_cfg = config.setdefault("model", {})
        model_cfg.setdefault("model_kwargs", {})["api_base"] = args.api_base

    if args.reasoning_effort:
        model_cfg = config.setdefault("model", {})
        model_cfg.setdefault("model_kwargs", {})["reasoning_effort"] = args.reasoning_effort

    output_path = resolve_output_path(args, agent_name="MiniSweAgent")
    traj_dir = os.path.join(os.path.dirname(output_path), "trajectories")

    task_runner = partial(
        run_mini_swe_task,
        model=args.model,
        config=config,
        task_timeout=args.task_timeout,
        traj_dir=traj_dir,
    )

    system_prompt = (
        f"[mini-swe-agent, model={args.model}, "
        f"step_limit={config.get('agent', {}).get('step_limit', 30)}]"
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (mini-swe-agent, self-verification)")
    print(f"Tasks: {len(tasks)}, model={args.model}")
    print(f"Config: {config_path}")
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

    finalize_results(results, output_path, args.model, system_prompt, args,
                     agent_name="MiniSweAgent",
                     result_to_atif_fn=mini_swe_result_to_atif)
    return 0


if __name__ == "__main__":
    sys.exit(main())
