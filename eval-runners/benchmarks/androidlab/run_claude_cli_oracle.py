#!/usr/bin/env python3
"""
Oracle mode: Claude CLI agent with verifier-in-the-loop retries.

After each attempt, the ADB verifier checks if the task succeeded.
If failed, the container resets and the agent retries with feedback
about what went wrong. Up to --max-attempts per task.

Usage:
    python run_claude_cli_oracle.py \\
        --data androidlab_tasks_evaluable.jsonl \\
        --broker-url http://localhost:9200 --pool-size 8 \\
        --model claude-sonnet-4-6 --max-attempts 3
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from functools import partial

from androidlab_common import (
    androidlab_reset,
    broker_acquire,
    broker_release,
    check_health,
    format_androidlab_instruction,
    http_post,
    load_androidlab_tasks,
    print_summary,
    save_results,
    ANDROIDLAB_DATE,
)
from run_claude_cli_androidlab import (
    ANDROID_ENV_SCRIPT,
    build_system_prompt,
    run_parallel,
    run_sequential,
    _adb_for_verify,
    _error_result,
)


def _evaluate_task(task_def, container_url, finish_description=""):
    """Run ADB verifier or LLM judge on current container state."""
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]

    if metric_type == "query_detect":
        from verifiers.query_detect_verifier import FUNCTION_MAP as QD_MAP
        qd_cls = QD_MAP.get(task_id)
        if qd_cls:
            qd = qd_cls(container_url)
            return qd.is_successful(agent_answer=finish_description)
        return {"complete": False, "no_verifier": True}
    else:
        from verifiers.verifier_map import get_verifier
        verifier_cls = get_verifier(task_id)
        if verifier_cls:
            verifier = verifier_cls(container_url)
            try:
                return verifier.is_successful()
            except Exception as e:
                return {"complete": False, "error": str(e)}
        return {"complete": False, "no_verifier": True}


def _build_feedback(attempt_num, prev_result, eval_result):
    """Build feedback prompt from failed attempt."""
    lines = [
        f"## Previous Attempt Feedback (attempt {attempt_num - 1})",
        "",
        "Your previous attempt **failed** the automated verification.",
        f"- Steps taken: {prev_result.get('step_count', 0)}",
        f"- Verification result: {eval_result}",
    ]
    desc = prev_result.get("finish_description", "")
    if desc:
        lines.append(f"- Your finish description: \"{desc}\"")

    lines.extend([
        "",
        "The container has been **reset to its initial state**.",
        "Try a **different approach**:",
        "- If you used GUI taps, try direct ADB/SQL commands instead",
        "- If a database query failed, check the schema first",
        "- For settings tasks, use `settings put` or `cmd` commands",
        "- For contacts, use `content insert/delete` with correct URIs",
        "- For clock alarms, use SET_ALARM intent or sqlite3 on alarms.db",
        "- For bluecoins, use sqlite3 on bluecoins.fydb (amounts in micro-units × 1,000,000)",
        "- Double-check column names, data types, and required fields",
    ])
    return "\n".join(lines)


def run_one_task_oracle(task_def, container_url, model, max_turns,
                        system_prompt, max_attempts=3, task_timeout=900):
    """Run one task with verifier-in-the-loop retries."""
    task_id = task_def["task_id"]
    app = task_def["app"]
    package = task_def["package"]
    metric_type = task_def["metric_type"]
    instruction = format_androidlab_instruction(task_def)

    print(f"\n{'='*70}")
    print(f"TASK {task_id} ({app}, {metric_type}): {task_def['task'][:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    all_attempts = []
    best_result = None

    for attempt in range(1, max_attempts + 1):
        print(f"  [Attempt {attempt}/{max_attempts}]")

        # Reset container
        try:
            androidlab_reset(container_url, package=package)
        except Exception as e:
            print(f"  Reset FAILED: {e}")
            all_attempts.append(_error_result(task_def, f"reset: {e}"))
            continue

        # Create state file
        state_fd, state_file = tempfile.mkstemp(
            suffix=".json", prefix=f"oracle_{task_id}_",
        )
        os.close(state_fd)
        with open(state_file, "w") as f:
            json.dump({
                "step_count": 0, "terminated": False, "reward": 0.0,
                "finish_status": "", "finish_description": "",
                "step_records": [], "_last_a11y_cache": "",
            }, f)

        # Build prompt with feedback
        prompt = (f"{system_prompt}\n\n## Task\n\n{instruction}\n\n"
                  f"Complete this task on the Android device.")
        if attempt > 1 and all_attempts:
            prev = all_attempts[-1]
            prev_eval = prev.get("eval_result", {})
            feedback = _build_feedback(attempt, prev, prev_eval)
            prompt += f"\n\n{feedback}"

        # Set env vars
        env = os.environ.copy()
        env["ANDROID_SERVER_URL"] = container_url
        env["ANDROID_STATE_FILE"] = state_file
        env.pop("ANDROID_DISABLE_TREE", None)
        env.pop("CLAUDECODE", None)

        # Run claude CLI
        cmd = [
            "claude", "-p", prompt,
            "--model", model,
            "--max-turns", str(max_turns),
            "--output-format", "json",
            "--allowedTools", f"Bash(python {ANDROID_ENV_SCRIPT} *)",
        ]

        start_time = time.time()
        claude_json = {}
        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True,
                timeout=task_timeout,
            )
            elapsed = time.time() - start_time
            if result.stdout:
                try:
                    claude_json = json.loads(result.stdout)
                except json.JSONDecodeError:
                    pass
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            print(f"    TIMEOUT after {elapsed:.0f}s")

        # Read state
        state = {}
        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception:
            pass
        finally:
            try:
                os.unlink(state_file)
            except OSError:
                pass

        usage = claude_json.get("usage", {})
        input_tokens = (usage.get("input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0))
        output_tokens = usage.get("output_tokens", 0)

        finish_description = state.get("finish_description", "")
        step_count = state.get("step_count", 0)

        # Evaluate with ADB verifier
        eval_result = _evaluate_task(task_def, container_url, finish_description)
        reward = 1.0 if eval_result.get("complete") else 0.0

        attempt_result = {
            "task_id": task_id, "app": app, "package": package,
            "metric_type": metric_type, "seed": 0,
            "task": task_def["task"],
            "reward": reward, "step_count": step_count,
            "finished": state.get("terminated", False),
            "finish_description": finish_description,
            "elapsed_seconds": elapsed,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": claude_json.get("total_cost_usd", 0.0),
            "num_turns": claude_json.get("num_turns", 0),
            "attempt": attempt,
            "eval_result": eval_result,
        }
        all_attempts.append(attempt_result)

        status = "OK" if reward > 0 else "FAIL"
        print(f"    >>> {status} (attempt {attempt}), steps={step_count}, "
              f"eval={eval_result}")

        if reward > 0:
            best_result = attempt_result
            break

        if attempt < max_attempts:
            print(f"    Retrying ({max_attempts - attempt} left)...")

    if best_result is None:
        best_result = all_attempts[-1] if all_attempts else _error_result(task_def, "no attempts")

    # Aggregate across attempts
    best_result["total_attempts"] = len(all_attempts)
    best_result["total_input_tokens"] = sum(a.get("input_tokens", 0) for a in all_attempts)
    best_result["total_output_tokens"] = sum(a.get("output_tokens", 0) for a in all_attempts)
    best_result["total_cost_usd"] = sum(a.get("cost_usd", 0.0) for a in all_attempts)

    return best_result


def main():
    parser = argparse.ArgumentParser(
        description="Oracle mode: Claude CLI with verifier-in-the-loop retries"
    )
    parser.add_argument("--data", default=None)
    parser.add_argument("--tasks", type=str, default=None)
    parser.add_argument("--apps", nargs="+", default=None)
    parser.add_argument("--metric-type", default=None,
                        choices=["operation", "query_detect"])
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-turns", type=int, default=25)
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Max retry attempts per task (default: 3)")
    parser.add_argument("--task-timeout", type=int, default=900)
    parser.add_argument("--output", default=None)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url")
    group.add_argument("--broker-url")
    parser.add_argument("--pool-size", type=int, default=8)

    args = parser.parse_args()

    tasks = load_androidlab_tasks(
        data_path=args.data, task_ids=args.tasks,
        apps=args.apps, metric_type=args.metric_type,
    )
    if not tasks:
        print("No tasks.")
        return 1

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        ts = time.strftime("%y%m%d_%H%M")
        exp_name = f"AndroidLab_Oracle_{model_short}_{ts}"
        _EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(_EXAMPLES_DIR, os.pardir, "results", exp_name)
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    system_prompt = build_system_prompt()

    task_runner = partial(
        run_one_task_oracle,
        model=args.model,
        max_turns=args.max_turns,
        system_prompt=system_prompt,
        max_attempts=args.max_attempts,
        task_timeout=args.task_timeout,
    )

    print(f"Android-Lab ORACLE MODE")
    print(f"Model: {args.model}, max_turns={args.max_turns}, "
          f"max_attempts={args.max_attempts}")
    print(f"Tasks: {len(tasks)}")
    print(f"Output: {output_path}")

    if args.broker_url:
        if not check_health(args.broker_url):
            print("ERROR: Broker not healthy")
            return 1
        results = run_parallel(
            tasks, args.broker_url, args.pool_size, output_path, task_runner
        )
    else:
        if not check_health(args.container_url):
            print("ERROR: Container not healthy")
            return 1
        results = run_sequential(
            tasks, args.container_url, output_path, task_runner
        )

    print_summary(results)
    save_results(results, output_path, extra_meta={
        "model": args.model,
        "agent": "ClaudeCodeCLI_Oracle",
        "max_attempts": args.max_attempts,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
