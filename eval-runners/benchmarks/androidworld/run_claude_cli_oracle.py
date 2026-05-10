#!/usr/bin/env python3
"""
Mode 2: Oracle feedback loop — agent gets eval reward as verification signal.

After each attempt, the rule-based evaluator's reward is checked. If the task
failed (reward=0), the container is reset and the agent retries with feedback
about what happened in the previous attempt. This continues up to --max-attempts.

This is essentially RL with the verifier in the loop: the agent gets a binary
signal (pass/fail) and can adjust its strategy across attempts.

Usage:
    # Sequential
    python run_mode2.py --data val_data_seed7_no_gui.jsonl --container-url http://localhost:5800

    # Parallel with broker, 3 attempts per task
    python run_mode2.py --data val_data_seed7_no_gui.jsonl --broker-url http://localhost:9200 \\
        --pool-size 16 --max-attempts 5

    # With specific prompt
    python run_mode2.py --data val_data_seed7_no_gui.jsonl --broker-url http://localhost:9200 \\
        --prompt hybrid --max-attempts 5
"""

import sys
import time
from functools import partial

from claude_cli_common import (
    build_common_parser,
    check_health,
    force_eval,
    get_allowed_tools,
    load_system_prompt,
    load_tasks,
    finalize_results,
    preflight_checks,
    reset_container,
    resolve_output_path,
    run_one_task,
    run_parallel,
    run_sequential,
)


def _build_feedback_suffix(attempt_num, prev_result):
    """Build a prompt suffix with feedback from the previous failed attempt."""
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
        lines.append(f"- Your finish description: \"{finish_desc}\"")
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
        "- The task required GUI interaction but only programmatic was used (or vice versa)",
        "- Information-retrieval answer was incorrect or imprecise",
        "",
        "Carefully re-read the task, explore the device state, and try again.",
    ])
    return "\n".join(lines)


def run_one_task_with_retries(task_def, container_url, model, max_turns,
                              system_prompt, effort=None,
                              allowed_tools=None, disallowed_tools=None,
                              disable_tree=True, max_attempts=3,
                              stable_endpoint=True):
    """Run a task with up to max_attempts, feeding eval reward back as signal.

    On each failed attempt:
    1. Force-eval if agent didn't call finish
    2. Reset the container (same task_id, seed)
    3. Run agent again with feedback from previous attempt
    """
    task_id = task_def["task_id"]
    seed = task_def["seed"]

    all_attempts = []
    best_result = None

    for attempt in range(1, max_attempts + 1):
        print(f"\n  [Task {task_id}] Attempt {attempt}/{max_attempts}")

        # Build feedback suffix for retries
        prompt_suffix = ""
        if attempt > 1 and all_attempts:
            prompt_suffix = _build_feedback_suffix(attempt, all_attempts[-1])

        result = run_one_task(
            task_def, container_url, model, max_turns,
            system_prompt=system_prompt,
            effort=effort,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            disable_tree=disable_tree,
            prompt_suffix=prompt_suffix,
            stable_endpoint=stable_endpoint,
        )

        # If agent didn't call finish (no reward set), force-evaluate
        # if not result.get("finished", False) and result.get("reward", 0.0) == 0.0:
        #     print(f"  [Task {task_id}] Agent didn't finish — forcing evaluation...")
        #     forced_reward = force_eval(container_url)
        #     if forced_reward > 0:
        #         result["reward"] = forced_reward
        #         print(f"  [Task {task_id}] Forced eval reward: {forced_reward}")

        # Track attempt
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

    # Use the best result (success if any, otherwise last attempt)
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
            "input_tokens": a.get("input_tokens", 0),
            "output_tokens": a.get("output_tokens", 0),
            "cost_usd": a.get("cost_usd", 0.0),
            "finish_description": a.get("finish_description", ""),
        }
        for i, a in enumerate(all_attempts)
    ]

    # Aggregate token costs across all attempts
    best_result["total_input_tokens"] = sum(a.get("input_tokens", 0) for a in all_attempts)
    best_result["total_output_tokens"] = sum(a.get("output_tokens", 0) for a in all_attempts)
    best_result["total_cost_usd"] = sum(a.get("cost_usd", 0.0) for a in all_attempts)
    best_result["total_elapsed_seconds"] = sum(a.get("elapsed_seconds", 0) for a in all_attempts)

    return best_result


def main():
    parser = build_common_parser(
        description="Mode 2: Oracle feedback loop (eval reward as verification signal)",
    )
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Max attempts per task (default: 3)")
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

    # Bind run_one_task_with_retries with all config
    task_runner = partial(
        run_one_task_with_retries,
        model=args.model,
        max_turns=args.max_turns,
        system_prompt=system_prompt,
        effort=args.effort,
        allowed_tools=allowed_tools,
        disallowed_tools=None if args.deny_list else "",
        disable_tree=disable_tree,
        max_attempts=args.max_attempts,
        stable_endpoint=args.stable_endpoint,
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Mode: {mode} (oracle feedback, max_attempts={args.max_attempts})")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_turns={args.max_turns}")
    print(f"Max budget per task: {args.max_attempts} × {args.max_turns} = "
          f"{args.max_attempts * args.max_turns} turns")
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

    # Extra summary stats for mode 2
    total_attempts = sum(r.get("total_attempts", 1) for r in results)
    tasks_retried = sum(1 for r in results if r.get("total_attempts", 1) > 1)
    extra_summary = {
        "max_attempts": args.max_attempts,
        "total_attempts": total_attempts,
        "avg_attempts": round(total_attempts / max(len(results), 1), 2),
        "tasks_retried": tasks_retried,
        "total_cost_all_attempts": round(
            sum(r.get("total_cost_usd", r.get("cost_usd", 0)) for r in results), 4
        ),
    }

    finalize_results(
        results, output_path, args.model, system_prompt, args,
        extra_summary=extra_summary,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
