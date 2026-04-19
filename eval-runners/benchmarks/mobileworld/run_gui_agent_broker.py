#!/usr/bin/env python3
"""
Run MobileWorld SOTA GUI agents on MobileWorld containers via broker.

This script reproduces paper success-rate (SR) numbers by running native
MobileWorld GUI agents (GeneralE2E, Qwen3VL, GelabAgent, etc.) on
MobileWorld containers managed by the broker pool.

The flow for each task:
  broker_acquire → AndroidEnvClient → init_task → agent.predict() loop
  → eval_task → teardown → broker_release

Usage:
    # Broker mode (parallel)
    python run_gui_agent_broker.py \
        --data ../../data/mobileworld/gui_only_tasks.jsonl \
        --agent-type general_e2e \
        --model gpt-4o \
        --api-url https://api.openai.com/v1 \
        --broker-url http://localhost:9400 \
        --pool-size 8

    # Single container (sequential)
    python run_gui_agent_broker.py \
        --data ../../data/mobileworld/gui_only_tasks.jsonl \
        --agent-type qwen3vl \
        --model Qwen/Qwen2.5-VL-72B-Instruct \
        --api-url http://localhost:8000/v1 \
        --container-url http://localhost:6805

    # Custom agent from file
    python run_gui_agent_broker.py \
        --data ../../data/mobileworld/gui_only_tasks.jsonl \
        --agent-type /path/to/my_agent.py \
        --model gpt-4o \
        --api-url https://api.openai.com/v1 \
        --broker-url http://localhost:9400
"""

import argparse
import concurrent.futures
import json
import os
import queue
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Add MobileWorld to path so we can import its agent registry + client
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKYRL_AGENT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, os.pardir, os.pardir))

# Resolve repo root: works both in main checkout and git worktrees.
# In a worktree, _SKYRL_AGENT_ROOT/..(worktree dir)/MobileWorld won't exist,
# so we fall back to `git rev-parse --show-superproject-working-tree` or the
# commondir approach.
_REPO_ROOT = os.path.abspath(os.path.join(_SKYRL_AGENT_ROOT, os.pardir))
if not os.path.isdir(os.path.join(_REPO_ROOT, "MobileWorld")):
    # We're likely in a worktree — resolve the main repo root via .git
    _git_dir = os.path.join(_REPO_ROOT, ".git")
    if os.path.isfile(_git_dir):
        # .git is a file in worktrees, content: "gitdir: /path/to/.git/worktrees/..."
        with open(_git_dir) as f:
            _gitdir_path = f.read().strip().split("gitdir: ", 1)[-1]
        # Walk up from .git/worktrees/<name> to the repo root
        _REPO_ROOT = os.path.abspath(os.path.join(_gitdir_path, os.pardir, os.pardir, os.pardir))

_MW_SRC = os.path.join(_REPO_ROOT, "MobileWorld", "src")
if _MW_SRC not in sys.path:
    sys.path.insert(0, _MW_SRC)

from mobile_world.agents.registry import create_agent
from mobile_world.runtime.client import AndroidEnvClient
from mobile_world.runtime.utils.models import ANSWER, ENV_FAIL, FINISHED, UNKNOWN


# ---------------------------------------------------------------------------
# HTTP + Broker helpers (self-contained, no mw_cli_common dependency)
# ---------------------------------------------------------------------------

def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url, params=None, timeout=120):
    if params:
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body


def check_health(base_url):
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ok", False) or data.get("status") == "ok"
    except Exception:
        return False


def broker_acquire(broker_url, timeout=300, retries=3):
    """Acquire a container from the broker. Returns container info dict."""
    for attempt in range(retries):
        try:
            return http_post(
                f"{broker_url}/acquire",
                {"pid": os.getpid(), "timeout": timeout},
                timeout=timeout + 30,
            )
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError(f"Failed to acquire container after {retries} attempts: {e}")


def broker_release(broker_url, env_id, healthy=True, retries=3):
    """Return a container to the broker."""
    for attempt in range(retries):
        try:
            return http_post(
                f"{broker_url}/return",
                {"env_id": env_id, "healthy": healthy},
                timeout=120,
            )
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  WARNING: Failed to return container env_id={env_id}: {e}")


# ---------------------------------------------------------------------------
# Single-task runner (runs on one container)
# ---------------------------------------------------------------------------

def run_one_gui_task(
    task_def: dict,
    container_url: str,
    device_id: str,
    agent_type: str,
    model_name: str,
    api_url: str,
    api_key: str,
    max_steps: int,
    runtime_conf: dict,
    log_dir: str | None = None,
) -> dict:
    """Run a MobileWorld GUI agent on a single task.

    Uses AndroidEnvClient for the native MobileWorld step protocol:
      init_task → agent.predict() loop → eval → teardown
    """
    task_name = task_def["task_name"]
    trial = task_def.get("trial", 1)

    print(f"\n{'='*60}")
    print(f"TASK: {task_name} (trial={trial})")
    print(f"  container={container_url}  agent={agent_type}  model={model_name}")

    t0 = time.time()
    step_count = 0
    reward = 0.0
    eval_reason = ""
    error_msg = ""
    task_goal = ""
    token_usage = {}

    try:
        # 1. Create env client
        env = AndroidEnvClient(url=container_url, device=device_id)

        # 2. Init task + get goal
        obs = env.initialize_task(task_name=task_name)
        task_goal = env.get_task_goal(task_type=task_name)
        print(f"  goal: {str(task_goal)[:120]}")

        # 3. Create agent
        agent = create_agent(
            agent_type=agent_type,
            model_name=model_name,
            llm_base_url=api_url,
            api_key=api_key,
            env=env,       # needed for registry agents (passes tools)
            **runtime_conf,
        )
        agent.initialize(task_goal)

        # 4. Step loop
        for step in range(1, max_steps + 1):
            step_count = step

            prediction, action = agent.predict({
                "screenshot": obs.screenshot,
                "tool_call": getattr(obs, "tool_call", None),
                "ask_user_response": getattr(obs, "ask_user_response", None),
            })

            if prediction is None:
                print(f"  step {step}: prediction=None, stopping")
                break

            at = action.action_type
            print(f"  step {step}: action={at}")

            if at in (ENV_FAIL, FINISHED, UNKNOWN):
                break
            elif at == ANSWER:
                obs = env.execute_action(action)
                break
            else:
                obs = env.execute_action(action)

        # 5. Evaluate
        reward, eval_reason = env.get_task_score(task_type=task_name)
        print(f"  score={reward}  reason={eval_reason}")

        # 6. Teardown
        env.tear_down_task(task_type=task_name)
        agent.done()

        # 7. Token usage
        token_usage = agent.get_total_token_usage()

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"  ERROR: {error_msg}")
        traceback.print_exc()
        # Try teardown even on error
        try:
            env.tear_down_task(task_type=task_name)
        except Exception:
            pass

    elapsed = time.time() - t0

    result = {
        "task_name": task_name,
        "trial": trial,
        "task": str(task_goal),
        "reward": reward,
        "eval_reason": eval_reason,
        "step_count": step_count,
        "elapsed_seconds": round(elapsed, 1),
        "input_tokens": token_usage.get("prompt_tokens", 0),
        "output_tokens": token_usage.get("completion_tokens", 0),
        "cached_tokens": token_usage.get("cached_tokens", 0),
        "agent_type": agent_type,
        "model": model_name,
    }
    if error_msg:
        result["error"] = error_msg

    return result


# ---------------------------------------------------------------------------
# Orchestration: broker, parallel, sequential
# ---------------------------------------------------------------------------

def run_broker_mode(tasks, broker_url, pool_size, output_path, agent_kwargs):
    """Run tasks in parallel using broker for container allocation."""
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

            task_name = task_def["task_name"]
            container_info = None
            env_id = None
            healthy = True

            try:
                container_info = broker_acquire(broker_url)
                env_id = container_info["env_id"]
                server_port = container_info["server_port"]
                container_url = container_info.get(
                    "server_url", f"http://localhost:{server_port}"
                )
                device_id = container_info.get("device_id", "emulator-5554")

                print(f"  [w{worker_id}] Acquired env_id={env_id} "
                      f"port={server_port} for {task_name}")

                result = run_one_gui_task(
                    task_def=task_def,
                    container_url=container_url,
                    device_id=device_id,
                    **agent_kwargs,
                )

            except Exception as e:
                print(f"  [w{worker_id}] ERROR on {task_name}: {e}")
                result = {
                    "task_name": task_name,
                    "trial": task_def.get("trial", 1),
                    "reward": 0.0,
                    "error": str(e),
                }
                healthy = False

            finally:
                if env_id is not None:
                    broker_release(broker_url, env_id, healthy=healthy)
                    print(f"  [w{worker_id}] Released env_id={env_id}")

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
    print(f"Starting {num_workers} broker workers (pool_size={pool_size})...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)
        for f in futures:
            if f.exception():
                print(f"  Worker exception: {f.exception()}")

    out_file.close()
    return results


def run_sequential_mode(tasks, container_url, device_id, output_path, agent_kwargs):
    """Run tasks sequentially on a single container."""
    results = []

    with open(output_path, "w") as out_file:
        for i, task_def in enumerate(tasks):
            print(f"\n[{i+1}/{len(tasks)}]")
            result = run_one_gui_task(
                task_def=task_def,
                container_url=container_url,
                device_id=device_id,
                **agent_kwargs,
            )
            results.append(result)
            out_file.write(json.dumps(result) + "\n")
            out_file.flush()

            successes = sum(1 for r in results if r.get("reward", 0) > 0)
            print(f"  Running SR: {successes}/{len(results)} "
                  f"({100*successes/max(len(results),1):.0f}%)")

    return results


# ---------------------------------------------------------------------------
# Results summary
# ---------------------------------------------------------------------------

def finalize(results, output_path, args):
    """Print summary and save metrics."""
    successes = sum(1 for r in results if r.get("reward", 0) > 0)
    total = len(results)

    # Per-task aggregation
    from collections import defaultdict
    per_task = defaultdict(list)
    for r in results:
        per_task[r.get("task_name", "?")].append(r.get("reward", 0.0))

    tasks_with_success = sum(
        1 for rewards in per_task.values() if any(r > 0 for r in rewards)
    )
    unique_tasks = len(per_task)

    print(f"\n{'='*60}")
    print(f"FINAL RESULTS")
    print(f"{'='*60}")
    print(f"  Agent:  {args.agent_type}")
    print(f"  Model:  {args.model}")
    print(f"  Entries: {successes}/{total} ({100*successes/max(total,1):.0f}%)")
    print(f"  Tasks:   {tasks_with_success}/{unique_tasks} "
          f"({100*tasks_with_success/max(unique_tasks,1):.0f}%)")
    print(f"{'='*60}")

    for r in sorted(results, key=lambda x: (x.get("task_name", ""), x.get("trial", 0))):
        s = "OK" if r.get("reward", 0) > 0 else "FAIL"
        print(f"  {r.get('task_name','?')} (t{r.get('trial',1)}) [{s:4s}] "
              f"steps={r.get('step_count',0)} "
              f"time={r.get('elapsed_seconds',0):.0f}s")

    total_input = sum(r.get("input_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)

    output_dir = os.path.dirname(output_path)
    summary = {
        "agent_type": args.agent_type,
        "model": args.model,
        "api_url": args.api_url,
        "max_steps": args.max_steps,
        "total_entries": total,
        "success_entries": successes,
        "success_rate_by_entry": round(successes / max(total, 1), 4),
        "unique_tasks": unique_tasks,
        "tasks_with_any_success": tasks_with_success,
        "success_rate_by_task": round(tasks_with_success / max(unique_tasks, 1), 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "per_task_rewards": {k: v for k, v in sorted(per_task.items())},
    }
    summary_path = os.path.join(output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults: {output_path}")
    print(f"Summary: {summary_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Run MobileWorld GUI agents on MobileWorld containers via broker",
    )
    parser.add_argument(
        "--data", required=True,
        help="JSONL file with task definitions (task_name, trial, ...)",
    )
    parser.add_argument(
        "--tasks", type=str, default=None,
        help="Comma-separated task names to filter (default: all)",
    )
    parser.add_argument(
        "--agent-type", required=True,
        help="Agent registry key (e.g. general_e2e, qwen3vl, gelab_agent) "
             "or path to a .py file containing an agent class",
    )
    parser.add_argument(
        "--model", required=True,
        help="Model name passed to the agent (e.g. gpt-4o, Qwen/Qwen2.5-VL-72B-Instruct)",
    )
    parser.add_argument(
        "--api-url", required=True,
        help="LLM API base URL (e.g. https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="API key (default: $OPENAI_API_KEY or 'empty')",
    )
    parser.add_argument(
        "--max-steps", type=int, default=50,
        help="Max steps per task (default: 50)",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="LLM temperature (default: 0.0)",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=2048,
        help="LLM max tokens (default: 2048)",
    )
    parser.add_argument(
        "--history-n-images", type=int, default=3,
        help="Number of history images for the agent (default: 3)",
    )
    parser.add_argument(
        "--scale-factor", type=int, default=None,
        help="Coordinate scale factor (default: agent-specific)",
    )

    # Container mode
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--container-url",
        help="Single container URL for sequential mode",
    )
    group.add_argument(
        "--broker-url",
        help="Broker URL for parallel mode (e.g. http://localhost:9400)",
    )

    parser.add_argument(
        "--pool-size", type=int, default=4,
        help="Number of parallel workers in broker mode (default: 4)",
    )
    parser.add_argument(
        "--device-id", default="emulator-5554",
        help="Android device ID inside container (default: emulator-5554)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output JSONL path (auto-generated if not set)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "empty")

    # Load tasks
    with open(args.data) as f:
        tasks = [json.loads(line) for line in f if line.strip()]
    if args.tasks:
        names = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["task_name"] in names]
    if not tasks:
        print("No tasks to run.")
        return 0
    print(f"Loaded {len(tasks)} task entries from {args.data}")

    # Output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        agent_short = args.agent_type.replace("/", "_").replace(".py", "")
        ts = time.strftime("%y%m%d_%H%M")
        exp_name = f"GUIAgent_{agent_short}_{model_short}_{ts}"
        output_dir = os.path.join(_SKYRL_AGENT_ROOT, "results", exp_name)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Build runtime_conf for agent.
    # Only include standard OpenAI API params in runtime_conf — agent-specific
    # keys like history_n_images must be popped by agents that support them
    # (e.g. GeneralE2EAgentMCP) or excluded entirely for agents that don't
    # (e.g. Qwen3VLAgentMCP).
    runtime_conf_inner = {
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
    }
    agent_kwargs = {
        "agent_type": args.agent_type,
        "model_name": args.model,
        "api_url": args.api_url,
        "api_key": api_key,
        "max_steps": args.max_steps,
        "runtime_conf": {"runtime_conf": runtime_conf_inner},
        "log_dir": os.path.dirname(output_path),
    }
    if args.scale_factor is not None:
        agent_kwargs["runtime_conf"]["scale_factor"] = args.scale_factor

    print(f"Agent: {args.agent_type}  Model: {args.model}")
    print(f"API: {args.api_url}  Max steps: {args.max_steps}")
    print(f"Output: {output_path}")

    # Run
    if args.broker_url:
        if not check_health(args.broker_url):
            print(f"ERROR: Broker at {args.broker_url} is not healthy")
            return 1
        broker_status = http_get(f"{args.broker_url}/status")
        print(f"Broker: {args.broker_url} — "
              f"{broker_status.get('idle', '?')} idle / "
              f"{broker_status.get('total', '?')} total")
        results = run_broker_mode(
            tasks, args.broker_url, args.pool_size, output_path, agent_kwargs,
        )
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container at {args.container_url} is not healthy")
            return 1
        print(f"Container: {args.container_url} (sequential)")
        results = run_sequential_mode(
            tasks, args.container_url, args.device_id, output_path, agent_kwargs,
        )

    finalize(results, output_path, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
