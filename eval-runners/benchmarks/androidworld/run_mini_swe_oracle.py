#!/usr/bin/env python3
"""
Mode 2: Oracle feedback — mini-swe-agent retries on eval failure.

Usage:
    python run_oracle.py --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \\
        --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4 \\
        --model claude-sonnet-4-6
"""

from __future__ import annotations

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
    force_eval,
    load_tasks,
    finalize_results,
    resolve_output_path,
    run_parallel,
    run_sequential,
    ANDROID_ENV_SCRIPT,
)

from mini_swe_common import run_mini_swe_task, load_config


def _build_feedback_suffix(attempt_num: int, prev_result: dict) -> str:
    """Build prompt suffix with feedback from the previous failed attempt."""
    step_count = prev_result.get("step_count", 0)
    finish_desc = prev_result.get("finish_description", "")
    error = prev_result.get("error", "")

    lines = [
        f"## Previous Attempt Feedback (attempt {attempt_num - 1} of multiple)",
        "",
        "Your previous attempt **failed** the automated evaluation (reward=0).",
        f"- Steps taken: {step_count}",
    ]
    if finish_desc:
        lines.append(f'- Your finish description: "{finish_desc}"')
    if error:
        lines.append(f"- Error: {error}")

    lines.extend([
        "",
        "The container has been **reset to its initial state** — all your previous",
        "changes are gone. Try a **different approach** this time.",
        "",
        "Common reasons for failure:",
        "- Data was written to the wrong location or in the wrong format",
        "- A required field was missing or had the wrong value",
        "- Information-retrieval answer was incorrect or imprecise",
        "",
        "Carefully re-read the task, explore the device state, and try again.",
    ])
    return "\n".join(lines)


def run_one_task_with_retries(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    config: dict,
    task_timeout: int,
    max_attempts: int,
    traj_dir: str | None = None,
) -> dict:
    """Run a task with up to *max_attempts*, feeding eval reward as signal."""
    task_id = task_def["task_id"]
    all_attempts: list[dict] = []
    best_result: dict | None = None

    for attempt in range(1, max_attempts + 1):
        print(f"\n  [Task {task_id}] Attempt {attempt}/{max_attempts}")

        result = run_mini_swe_task(
            task_def, container_url,
            model=model,
            config=config,
            task_timeout=task_timeout,
            traj_dir=traj_dir,
            traj_suffix=f"_attempt_{attempt}",
        )

        # Force-evaluate if agent didn't finish
        # if not result.get("finished", False) and result.get("reward", 0.0) == 0.0:
        #     print(f"  [Task {task_id}] Agent didn't finish — forcing evaluation...")
        #     forced_reward = force_eval(container_url)
        #     if forced_reward > 0:
        #         result["reward"] = forced_reward
        #         print(f"  [Task {task_id}] Forced eval reward: {forced_reward}")

        result["attempt"] = attempt
        all_attempts.append(result)

        # Success — stop retrying
        if result.get("reward", 0.0) > 0:
            print(f"  [Task {task_id}] SUCCESS on attempt {attempt}")
            best_result = result
            break

        # Failed — will retry if attempts remaining
        if attempt < max_attempts:
            print(f"  [Task {task_id}] Failed, will retry "
                  f"({max_attempts - attempt} attempts remaining)...")
            feedback = _build_feedback_suffix(attempt + 1, result)
            task_def = {**task_def, "task": task_def["task"] + "\n\n" + feedback}

    if best_result is None:
        best_result = all_attempts[-1]

    # Augment result with retry metadata
    best_result["total_attempts"] = len(all_attempts)
    best_result["all_attempts"] = [
        {
            "attempt": a.get("attempt", i + 1),
            "reward": a.get("reward", 0.0),
            "step_count": a.get("step_count", 0),
            "elapsed_seconds": a.get("elapsed_seconds", 0),
            "cost_usd": a.get("cost_usd", 0.0),
            "finish_description": a.get("finish_description", ""),
        }
        for i, a in enumerate(all_attempts)
    ]
    best_result["total_cost_usd"] = sum(
        a.get("cost_usd", 0.0) for a in all_attempts
    )
    best_result["total_elapsed_seconds"] = sum(
        a.get("elapsed_seconds", 0) for a in all_attempts
    )

    return best_result


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Mode 2: mini-swe-agent oracle feedback loop",
    )
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", required=True,
                        help="LiteLLM model string")
    parser.add_argument("--config", default=None,
                        help="Path to YAML config (default: androidworld.yaml)")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Max attempts per task (default: 3)")
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
                        help="Override agent.step_limit per attempt (default: "
                             "use the value in androidworld.yaml, 30)")

    # For output path generation compatibility
    parser.add_argument("--prompt", default="mini_swe_oracle",
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
    args.max_turns = config.get("agent", {}).get("step_limit", 30)

    output_path = resolve_output_path(args, agent_name="MiniSweAgentOracle")
    traj_dir = os.path.join(os.path.dirname(output_path), "trajectories")

    task_runner = partial(
        run_one_task_with_retries,
        model=args.model,
        config=config,
        task_timeout=args.task_timeout,
        max_attempts=args.max_attempts,
        traj_dir=traj_dir,
    )

    system_prompt = (
        f"[mini-swe-agent oracle, model={args.model}, "
        f"max_attempts={args.max_attempts}]"
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (mini-swe-agent, oracle feedback, "
          f"max_attempts={args.max_attempts})")
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

    # Extra summary stats
    total_attempts = sum(r.get("total_attempts", 1) for r in results)
    extra_summary = {
        "max_attempts": args.max_attempts,
        "total_attempts": total_attempts,
        "avg_attempts": round(total_attempts / max(len(results), 1), 2),
        "total_cost_all_attempts": round(
            sum(r.get("total_cost_usd", r.get("cost_usd", 0)) for r in results), 4,
        ),
    }

    finalize_results(
        results, output_path, args.model, system_prompt, args,
        extra_summary=extra_summary,
        agent_name="MiniSweAgentOracle",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
