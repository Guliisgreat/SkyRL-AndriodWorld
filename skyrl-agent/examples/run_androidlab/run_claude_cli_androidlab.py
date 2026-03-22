#!/usr/bin/env python3
"""
Run Claude Code CLI on Android-Lab benchmark tasks.

Usage:
    # Sequential (single container)
    python run_claude_cli_androidlab.py \\
        --container-url http://localhost:5800 \\
        --model claude-opus-4-6

    # Parallel (broker)
    python run_claude_cli_androidlab.py \\
        --broker-url http://localhost:9200 --pool-size 8 \\
        --model claude-opus-4-6

    # Filter by app or metric type
    python run_claude_cli_androidlab.py \\
        --container-url http://localhost:5800 \\
        --apps settings clock \\
        --metric-type query_detect
"""

import argparse
import concurrent.futures
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time

from androidlab_common import (
    androidlab_reset,
    broker_acquire,
    broker_release,
    check_health,
    format_androidlab_instruction,
    http_post,
    load_androidlab_tasks,
    post_agent_xml_dump,
    print_summary,
    save_results,
    ANDROIDLAB_DATE,
)

# ─── Paths ───────────────────────────────────────────────────────────────────

_EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANDROID_ENV_SCRIPT = os.path.join(
    _EXAMPLES_DIR, "skyrl_agent", "agents", "android",
    "claude_sdk", "android_env.py",
)
ANDROID_ENV_SCRIPT = os.path.abspath(ANDROID_ENV_SCRIPT)

# Also try the standard location
if not os.path.exists(ANDROID_ENV_SCRIPT):
    ANDROID_ENV_SCRIPT = os.path.join(
        _EXAMPLES_DIR, os.pardir,
        "skyrl_agent", "agents", "android",
        "claude_sdk", "android_env.py",
    )
    ANDROID_ENV_SCRIPT = os.path.abspath(ANDROID_ENV_SCRIPT)


# ─── System prompt ───────────────────────────────────────────────────────────

ANDROIDLAB_SYSTEM_PROMPT = """You are an Android device automation agent. You interact with an Android emulator through ADB commands via a helper script.

## Tool

You have one tool: `python {android_env_script} adb "<adb_command>"`

Examples:
- `python {android_env_script} adb "adb shell input tap 540 960"`
- `python {android_env_script} adb "adb shell settings get system screen_brightness"`
- `python {android_env_script} adb "adb shell content query --uri content://com.android.calendar/events"`
- `python {android_env_script} adb "adb shell am start -n com.android.settings/.Settings"`

When done, call: `python {android_env_script} finish --status complete --description "<your answer or summary>"`
If the task asks a question, put the answer in the --description field.

## Important Context

- The current date on the device is **May 10, 2024** (2024-05-10).
- You are interacting with an Android emulator that has specific apps pre-installed with pre-loaded data.
- Use ADB shell commands to interact with the device. You can:
  - Tap, swipe, type text via `input` commands
  - Query app databases via `content query`
  - Modify settings via `settings put`
  - Launch apps via `am start` or `monkey`
  - Query system state via `getprop`, `dumpsys`, etc.
- After each ADB command, you'll see the accessibility tree showing current UI state.
- For information retrieval tasks, explore the app to find the answer, then call finish with the answer.
- For operation tasks, perform the required action, then call finish.

## Strategy

1. First understand what the task requires (query vs operation)
2. Launch the target app if needed
3. For queries: navigate to find the information, then finish with the answer
4. For operations: perform the action step by step, then finish
5. Use the accessibility tree to understand current UI state and find interactive elements
"""


def build_system_prompt():
    return ANDROIDLAB_SYSTEM_PROMPT.format(android_env_script=ANDROID_ENV_SCRIPT)


# ─── Core: run one task ─────────────────────────────────────────────────────

def run_one_task(task_def, container_url, model, max_turns, system_prompt,
                 task_timeout=900):
    """Run one Claude CLI attempt on an Android-Lab task."""
    task_id = task_def["task_id"]
    app = task_def["app"]
    package = task_def["package"]
    metric_type = task_def["metric_type"]

    instruction = format_androidlab_instruction(task_def)

    print(f"\n{'='*70}")
    print(f"TASK {task_id} ({app}, {metric_type}): {task_def['task'][:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    # Create state file
    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"androidlab_{task_id}_",
    )
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({
            "step_count": 0, "terminated": False, "reward": 0.0,
            "finish_status": "", "finish_description": "",
            "step_records": [], "_last_a11y_cache": "",
        }, f)

    # Reset container for Android-Lab
    try:
        androidlab_reset(container_url, package=package)
        print(f"  Reset OK (app={app}).")
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        os.unlink(state_file)
        return _error_result(task_def, f"reset: {e}")

    # Build prompt
    prompt = f"{system_prompt}\n\n## Task\n\n{instruction}\n\nComplete this task on the Android device."

    # Set env vars for android_env.py
    env = os.environ.copy()
    env["ANDROID_SERVER_URL"] = container_url
    env["ANDROID_STATE_FILE"] = state_file
    env.pop("ANDROID_DISABLE_TREE", None)  # keep tree enabled for Android-Lab
    env.pop("CLAUDECODE", None)

    # Run claude CLI
    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--max-turns", str(max_turns),
        "--output-format", "json",
        "--allowedTools", "Bash(command:*)",
    ]

    print(f"  Running claude CLI (model={model}, max_turns={max_turns})...")
    sys.stdout.flush()

    start_time = time.time()
    elapsed = 0
    claude_json = {}
    try:
        result = subprocess.run(
            cmd, env=env,
            capture_output=True, text=True,
            timeout=task_timeout,
        )
        elapsed = time.time() - start_time
        print(f"  Claude finished in {elapsed:.0f}s (exit={result.returncode})")

        if result.stdout:
            try:
                claude_json = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"  TIMEOUT after {elapsed:.0f}s")
        result = None

    # Extract token usage
    usage = claude_json.get("usage", {})
    input_tokens = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    output_tokens = usage.get("output_tokens", 0)
    cost_usd = claude_json.get("total_cost_usd", 0.0)
    num_turns = claude_json.get("num_turns", 0)

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

    step_count = state.get("step_count", 0)
    finished = state.get("terminated", False)
    finish_description = state.get("finish_description", "")

    # Evaluate using ADB verifiers
    reward = 0.0
    eval_result = {}
    if metric_type == "query_detect":
        from verifiers.query_detect_judge import judge_query_detect
        eval_result = judge_query_detect(
            task_id, task_def["task"], finish_description,
            adb_func=lambda cmd: _adb_for_verify(container_url, cmd),
        )
        reward = 1.0 if eval_result.get("complete") else 0.0
    else:
        from verifiers.verifier_map import get_verifier
        verifier_cls = get_verifier(task_id)
        if verifier_cls:
            verifier = verifier_cls(container_url)
            try:
                eval_result = verifier.is_successful()
                reward = 1.0 if eval_result.get("complete") else 0.0
            except Exception as e:
                print(f"  Verifier error: {e}")
                eval_result = {"error": str(e)}
        else:
            print(f"  No verifier for {task_id}")

    status = "OK" if reward > 0 else "FAIL"
    print(f"  >>> REWARD: {reward} ({status}), steps={step_count}, "
          f"eval={eval_result}")
    print(f"      tokens: in={input_tokens}, out={output_tokens}, "
          f"cost=${cost_usd:.4f}")
    sys.stdout.flush()

    return {
        "task_id": task_id,
        "app": app,
        "package": package,
        "metric_type": metric_type,
        "seed": 0,
        "task": task_def["task"],
        "reward": reward,
        "step_count": step_count,
        "finished": finished,
        "finish_description": finish_description,
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "num_turns": num_turns,
    }


def _adb_for_verify(container_url, cmd):
    """ADB executor for verifier use."""
    try:
        resp = http_post(f"{container_url}/step_adb", {
            "command": cmd, "thought": "verify",
        }, timeout=30)
        return resp.get("command_output", "")
    except Exception:
        return ""


def _error_result(task_def, error_msg):
    return {
        "task_id": task_def["task_id"],
        "app": task_def["app"],
        "package": task_def["package"],
        "metric_type": task_def["metric_type"],
        "seed": 0,
        "task": task_def["task"],
        "reward": 0.0,
        "error": error_msg,
    }


# ─── Orchestration ───────────────────────────────────────────────────────────

def run_sequential(tasks, container_url, output_path, task_runner):
    """Run tasks sequentially on a single container."""
    results = []
    with open(output_path, "w") as out:
        for i, task_def in enumerate(tasks):
            if not check_health(container_url):
                print(f"  Container unhealthy, waiting 30s...")
                time.sleep(30)
                if not check_health(container_url):
                    results.append(_error_result(task_def, "container_unhealthy"))
                    continue

            result = task_runner(task_def, container_url)
            results.append(result)
            out.write(json.dumps(result) + "\n")
            out.flush()

            successes = sum(1 for r in results if r.get("reward", 0) > 0)
            print(f"\n  Progress: {i+1}/{len(tasks)}, "
                  f"Success: {successes}/{len(results)} "
                  f"({100*successes/max(len(results),1):.0f}%)")
    return results


def run_parallel(tasks, broker_url, pool_size, output_path, task_runner):
    """Run tasks in parallel using the broker."""
    task_queue = queue.Queue()
    for t in tasks:
        task_queue.put(t)

    results = []
    results_lock = threading.Lock()
    completed = [0]

    out_file = open(output_path, "w")
    out_lock = threading.Lock()

    def worker(worker_id):
        while True:
            try:
                task_def = task_queue.get_nowait()
            except queue.Empty:
                return

            task_id = task_def["task_id"]
            container_info = None
            env_id = None

            try:
                container_info = broker_acquire(broker_url)
                env_id = container_info["env_id"]
                server_port = container_info["server_port"]
                container_url = f"http://localhost:{server_port}"
                print(f"  [w{worker_id}] Acquired env{env_id} for {task_id}")

                result = task_runner(task_def, container_url)
                healthy = True

            except Exception as e:
                print(f"  [w{worker_id}] ERROR on {task_id}: {e}")
                result = _error_result(task_def, str(e))
                healthy = False

            finally:
                if env_id is not None:
                    broker_release(broker_url, env_id, healthy=healthy)

            with results_lock:
                results.append(result)
                completed[0] += 1
                successes = sum(1 for r in results if r.get("reward", 0) > 0)
                print(f"\n  Progress: {completed[0]}/{len(tasks)}, "
                      f"SR: {successes}/{len(results)} "
                      f"({100*successes/max(len(results),1):.0f}%)")

            with out_lock:
                out_file.write(json.dumps(result) + "\n")
                out_file.flush()

            task_queue.task_done()

    num_workers = min(pool_size, len(tasks))
    print(f"Starting {num_workers} parallel workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as ex:
        futures = [ex.submit(worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)
        for f in futures:
            if f.exception():
                print(f"  Worker exception: {f.exception()}")

    out_file.close()
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run Claude Code CLI on Android-Lab benchmark"
    )
    parser.add_argument("--data", default=None,
                        help="JSONL task file (default: bundled androidlab_tasks.jsonl)")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (e.g., bluecoins_1,clock_5)")
    parser.add_argument("--apps", nargs="+", default=None,
                        help="Filter by app name(s)")
    parser.add_argument("--metric-type", default=None,
                        choices=["operation", "query_detect"],
                        help="Filter by metric type")
    parser.add_argument("--model", default="claude-opus-4-6",
                        help="Claude model (default: claude-opus-4-6)")
    parser.add_argument("--max-turns", type=int, default=25,
                        help="Max turns (default: 25, matching Android-Lab)")
    parser.add_argument("--task-timeout", type=int, default=900,
                        help="Per-task timeout in seconds")
    parser.add_argument("--output", default=None,
                        help="Output JSONL path (auto-generated if not set)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url",
                       help="Single container URL (sequential)")
    group.add_argument("--broker-url",
                       help="Broker URL (parallel)")

    parser.add_argument("--pool-size", type=int, default=8,
                        help="Parallel workers (broker mode)")

    args = parser.parse_args()

    # Load tasks
    tasks = load_androidlab_tasks(
        data_path=args.data,
        task_ids=args.tasks,
        apps=args.apps,
        metric_type=args.metric_type,
    )
    if not tasks:
        print("No tasks to run.")
        return 1

    # Resolve output
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        ts = time.strftime("%y%m%d_%H%M")
        exp_name = f"AndroidLab_ClaudeCLI_{model_short}_{ts}"
        output_dir = os.path.join(_EXAMPLES_DIR, os.pardir, "results", exp_name)
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Verify android_env.py exists
    if not os.path.exists(ANDROID_ENV_SCRIPT):
        print(f"ERROR: android_env.py not found at {ANDROID_ENV_SCRIPT}")
        return 1

    system_prompt = build_system_prompt()

    from functools import partial
    task_runner = partial(
        run_one_task,
        model=args.model,
        max_turns=args.max_turns,
        system_prompt=system_prompt,
        task_timeout=args.task_timeout,
    )

    mode = "parallel" if args.broker_url else "sequential"
    print(f"Android-Lab benchmark: {len(tasks)} tasks, mode={mode}")
    print(f"Model: {args.model}, max_turns={args.max_turns}")
    print(f"Output: {output_path}")

    if args.broker_url:
        if not check_health(args.broker_url):
            print(f"ERROR: Broker at {args.broker_url} not healthy")
            return 1
        results = run_parallel(
            tasks, args.broker_url, args.pool_size, output_path, task_runner
        )
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container at {args.container_url} not healthy")
            return 1
        results = run_sequential(
            tasks, args.container_url, output_path, task_runner
        )

    print_summary(results)
    save_results(results, output_path, extra_meta={
        "model": args.model,
        "max_turns": args.max_turns,
        "agent": "ClaudeCodeCLI",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
