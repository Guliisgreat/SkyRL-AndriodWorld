"""
Shared infrastructure for Claude Code CLI experiment runners.

Extracted from run_claude_cli.py so that run_mode1.py and run_mode2.py
can reuse HTTP helpers, broker logic, prompt loading, ATIF export, and
parallel/sequential orchestration without duplication.
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
import urllib.request
import urllib.error
import uuid

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ANDROID_ENV_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir,
    "agents", "cli", "claude_sdk", "android_env.py",
)
ANDROID_ENV_SCRIPT = os.path.abspath(ANDROID_ENV_SCRIPT)

# ---------------------------------------------------------------------------
# Prompt modules
# ---------------------------------------------------------------------------

PROMPT_MODULES = {
    "adb_baseline": "skyrl_agent.agents.android.claude_sdk.prompts.adb_baseline",
    "adb_baseline_v2": "skyrl_agent.agents.android.claude_sdk.prompts.adb_baseline_v2",
    "codegen": "skyrl_agent.agents.android.claude_sdk.prompts.codegen",
    "shell_script": "skyrl_agent.agents.android.claude_sdk.prompts.shell_script",
    "hybrid": "skyrl_agent.agents.android.claude_sdk.prompts.hybrid",
    "minimal_terminal": "skyrl_agent.agents.android.claude_sdk.prompts.minimal_terminal",
    "minimal_shell_escaping": "skyrl_agent.agents.android.claude_sdk.prompts.minimal_shell_escaping",
    "minimal_shell_escaping_no_gui": "skyrl_agent.agents.android.claude_sdk.prompts.minimal_shell_escaping_no_gui",
    "optimized_terminal_v1": "skyrl_agent.agents.android.claude_sdk.prompts.optimized_terminal_v1",
    "optimized_terminal_v2": "skyrl_agent.agents.android.claude_sdk.prompts.optimized_terminal_v2",
    "clean_optimized": "agents.cli.claude_sdk.prompts.clean_optimized",
}
DEFAULT_PROMPT = "adb_baseline"


def load_prompt_module(prompt_name: str):
    """Load a prompt module by name (avoids torch/transformers imports)."""
    import importlib.util
    if prompt_name not in PROMPT_MODULES:
        raise ValueError(
            f"Unknown prompt '{prompt_name}'. "
            f"Available: {list(PROMPT_MODULES.keys())}"
        )
    module_path = PROMPT_MODULES[prompt_name]
    parts = module_path.split(".")
    file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        os.pardir, os.pardir,
        *parts[:-1],
        parts[-1] + ".py",
    )
    file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(prompt_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_system_prompt(prompt_name: str) -> str:
    """Load a system prompt by name and format it with ANDROID_ENV_SCRIPT."""
    mod = load_prompt_module(prompt_name)
    return mod.build_system_prompt(ANDROID_ENV_SCRIPT)


def get_allowed_tools(prompt_name: str) -> str:
    """Get required tools for a prompt (default: Bash only)."""
    mod = load_prompt_module(prompt_name)
    return getattr(mod, "REQUIRED_TOOLS", "Bash(command:*)")


# ---------------------------------------------------------------------------
# HTTP / container helpers
# ---------------------------------------------------------------------------

def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def reset_container(base_url, task_id, seed):
    return http_post(f"{base_url}/reset", {
        "seed": seed,
        "options": {"task_id": task_id, "go_home_on_reset": True},
    })


def check_health(base_url):
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ready", False) or data.get("status") == "ok"
    except Exception:
        return False


def force_eval(container_url):
    """Force task evaluation by sending a 'status' action to the container.

    Use this when the agent didn't call finish (e.g., timeout) but we still
    want to check if its partial work achieved the task goal.
    Returns the reward (0.0 or 1.0).
    """
    try:
        resp = http_post(f"{container_url}/step", {
            "action": {
                "action_type": "status",
                "goal_status": "complete",
                "text": "forced evaluation",
            },
            "thought": "forced evaluation",
        })
        return resp.get("reward", 0.0)
    except Exception:
        return 0.0


def _http_post_quiet(url, payload):
    """POST without raising on failure."""
    try:
        return http_post(url, payload, timeout=30)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Broker helpers
# ---------------------------------------------------------------------------

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
# Core: run a single task attempt
# ---------------------------------------------------------------------------

def run_one_task(task_def, container_url, model, max_turns, system_prompt,
                 effort=None, allowed_tools="Bash(command:*)",
                 disable_tree=True, prompt_suffix="",
                 skip_reset=False, task_timeout=900, auto_finish=True):
    """Run one Claude attempt on a task. Returns a result dict.

    Parameters
    ----------
    skip_reset : bool
        If True, skip the container reset (caller already did it).
    prompt_suffix : str
        Extra text appended after the task description (e.g., feedback).
    task_timeout : int
        Max seconds for the Claude subprocess.
    """
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} (seed={seed}): {task_text[:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    # Create state file
    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"claude_task{task_id}_",
    )
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({
            "step_count": 0, "terminated": False, "reward": 0.0,
            "finish_status": "", "finish_description": "",
            "step_records": [], "_last_a11y_cache": "",
        }, f)

    # Reset container
    if not skip_reset:
        try:
            reset_container(container_url, task_id, seed)
            print(f"  Reset OK.")
        except Exception as e:
            print(f"  Reset FAILED: {e}")
            os.unlink(state_file)
            return {"task_id": task_id, "seed": seed, "task": task_text,
                    "reward": 0.0, "error": f"reset: {e}"}
        time.sleep(10)

    # Build prompt
    prompt = f"{system_prompt}\n\n## Task\n\n{task_text}\n\nComplete this task on the Android device."
    if prompt_suffix:
        prompt += f"\n\n{prompt_suffix}"

    # Set env vars for android_env.py
    env = os.environ.copy()
    env["ANDROID_SERVER_URL"] = container_url
    env["ANDROID_STATE_FILE"] = state_file
    if disable_tree:
        env["ANDROID_DISABLE_TREE"] = "1"
    env.pop("CLAUDECODE", None)

    # Run claude CLI
    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--max-turns", str(max_turns),
        "--output-format", "json",
        "--allowedTools", allowed_tools,
    ]
    if effort:
        cmd.extend(["--effort", effort])

    print(f"  Running claude CLI (model={model}, max_turns={max_turns})...")
    sys.stdout.flush()

    start_time = time.time()
    elapsed = 0
    claude_json = {}
    try:
        with tempfile.TemporaryDirectory(prefix=f"claude_task{task_id}_cwd_") as run_cwd:
            result = subprocess.run(
                cmd, env=env, cwd=run_cwd,
                capture_output=True, text=True,
                timeout=task_timeout,
            )
        elapsed = time.time() - start_time
        print(f"  Claude finished in {elapsed:.0f}s (exit={result.returncode})")

        if result.stdout:
            try:
                claude_json = json.loads(result.stdout)
                result_text = claude_json.get("result", "")
                if result_text:
                    for line in result_text.strip().split("\n")[-5:]:
                        print(f"    {line[:120]}")
            except json.JSONDecodeError:
                for line in result.stdout.strip().split("\n")[-5:]:
                    print(f"    {line[:120]}")

        if result.returncode != 0 and result.stderr:
            print(f"  stderr: {result.stderr[-200:]}")

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

    reward = state.get("reward", 0.0)
    step_count = state.get("step_count", 0)
    finished = state.get("terminated", False)

    if not finished and auto_finish:
        print(f"  Agent didn't call finish — auto-finishing...")
        auto_reward = force_eval(container_url)
        reward = auto_reward
        finished = True
        print(f"  Auto-finish reward: {auto_reward}")

    status = "OK" if reward > 0 else "FAIL"
    print(f"  >>> REWARD: {reward} ({status}), steps={step_count}, finished={finished}")
    print(f"      tokens: in={input_tokens}, out={output_tokens}, cost=${cost_usd:.4f}")
    sys.stdout.flush()

    return {
        "task_id": task_id,
        "seed": seed,
        "task": task_text,
        "reward": reward,
        "step_count": step_count,
        "finished": finished,
        "commands": state.get("step_records", []),
        "finish_description": state.get("finish_description", ""),
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "num_turns": num_turns,
        "claude_output": claude_json.get("result", "")[-3000:] if claude_json else (
            result.stdout[-3000:] if result and result.stdout else ""
        ),
    }


# ---------------------------------------------------------------------------
# Orchestration: sequential and parallel runners
# ---------------------------------------------------------------------------

def run_sequential(tasks, container_url, output_path, task_runner):
    """Run tasks sequentially on a single container.

    task_runner(task_def, container_url) -> result dict
    """
    results = []
    with open(output_path, "w") as out:
        for i, task_def in enumerate(tasks):
            if not check_health(container_url):
                print(f"  Container unhealthy, waiting 30s...")
                time.sleep(30)
                if not check_health(container_url):
                    print(f"  Still unhealthy, skipping task {task_def['task_id']}")
                    results.append({
                        "task_id": task_def["task_id"], "reward": 0.0,
                        "error": "container_unhealthy",
                    })
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
    """Run tasks in parallel using the broker for container allocation.

    task_runner(task_def, container_url) -> result dict
    """
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
                print(f"  [worker {worker_id}] Acquired container env_id={env_id} "
                      f"port={server_port} for task {task_id}")

                result = task_runner(task_def, container_url)
                healthy = True

            except Exception as e:
                print(f"  [worker {worker_id}] ERROR on task {task_id}: {e}")
                result = {
                    "task_id": task_id, "seed": task_def.get("seed", 0),
                    "task": task_def.get("task", ""), "reward": 0.0,
                    "error": str(e),
                }
                healthy = False

            finally:
                if env_id is not None:
                    broker_release(broker_url, env_id, healthy=healthy)
                    print(f"  [worker {worker_id}] Returned container env_id={env_id}")

            with results_lock:
                results.append(result)
                completed[0] += 1
                successes = sum(1 for r in results if r.get("reward", 0) > 0)
                print(f"\n  Progress: {completed[0]}/{len(tasks)}, "
                      f"Success: {successes}/{len(results)} "
                      f"({100*successes/max(len(results),1):.0f}%)")

            with out_lock:
                out_file.write(json.dumps(result) + "\n")
                out_file.flush()

            task_queue.task_done()

    num_workers = min(pool_size, len(tasks))
    print(f"Starting {num_workers} parallel workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)
        for f in futures:
            if f.exception():
                print(f"  Worker exception: {f.exception()}")

    out_file.close()
    return results


# ---------------------------------------------------------------------------
# ATIF trajectory export
# ---------------------------------------------------------------------------

def result_to_atif(result, model, system_prompt):
    """Convert a task result dict to an ATIF-v1.6 trajectory dict."""
    task_id = result.get("task_id", 0)
    session_id = f"androidworld-task{task_id}-{uuid.uuid4().hex[:8]}"

    steps = []
    step_id = 1

    steps.append({
        "step_id": step_id,
        "source": "system",
        "message": system_prompt,
    })
    step_id += 1

    steps.append({
        "step_id": step_id,
        "source": "user",
        "message": result.get("task", ""),
    })
    step_id += 1

    for rec in result.get("commands", []):
        action_type = rec.get("action_type", "")
        params = rec.get("action_params", {})
        cmd_output = rec.get("command_output", "")

        if action_type == "adb":
            command = params.get("command", "")
            tool_call_id = f"call_{step_id}"
            no_tree = params.get("no_tree", False)
            tree_flag = " --no-tree" if no_tree else ""
            bash_cmd = f"python android_env.py adb{tree_flag} \"{command}\""

            steps.append({
                "step_id": step_id,
                "source": "agent",
                "message": rec.get("thought", "") or f"Execute: {command}",
                "model_name": model,
                "tool_calls": [{
                    "tool_call_id": tool_call_id,
                    "function_name": "Bash",
                    "arguments": {"command": bash_cmd},
                }],
                "observation": {
                    "results": [{
                        "source_call_id": tool_call_id,
                        "content": cmd_output[:8000] if cmd_output else "(no output)",
                    }],
                },
            })
            step_id += 1

        elif action_type == "tree":
            tool_call_id = f"call_{step_id}"
            steps.append({
                "step_id": step_id,
                "source": "agent",
                "message": rec.get("thought", "Get accessibility tree"),
                "model_name": model,
                "tool_calls": [{
                    "tool_call_id": tool_call_id,
                    "function_name": "Bash",
                    "arguments": {"command": "python android_env.py tree"},
                }],
                "observation": {
                    "results": [{
                        "source_call_id": tool_call_id,
                        "content": cmd_output[:8000] if cmd_output else "(no output)",
                    }],
                },
            })
            step_id += 1

        elif action_type == "finish":
            tool_call_id = f"call_{step_id}"
            status = params.get("status", "complete")
            desc = params.get("description", "")
            bash_cmd = f'python android_env.py finish --status {status} --description "{desc}"'

            steps.append({
                "step_id": step_id,
                "source": "agent",
                "message": rec.get("thought", "") or f"Finish: {desc}",
                "model_name": model,
                "tool_calls": [{
                    "tool_call_id": tool_call_id,
                    "function_name": "Bash",
                    "arguments": {"command": bash_cmd},
                }],
                "observation": {
                    "results": [{
                        "source_call_id": tool_call_id,
                        "content": cmd_output[:8000] if cmd_output else "Task finished.",
                    }],
                },
            })
            step_id += 1

    if len(steps) == 2:
        steps.append({
            "step_id": step_id,
            "source": "agent",
            "message": result.get("claude_output", "")[:3000] or "(no output captured)",
            "model_name": model,
        })

    trajectory = {
        "schema_version": "ATIF-v1.6",
        "session_id": session_id,
        "agent": {
            "name": "ClaudeCodeCLI",
            "version": "1.0",
            "model_name": model,
            "tool_definitions": [{
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "Execute a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The command to execute"},
                        },
                        "required": ["command"],
                    },
                },
            }],
        },
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": result.get("input_tokens", 0),
            "total_completion_tokens": result.get("output_tokens", 0),
            "total_cost_usd": result.get("cost_usd", 0.0),
            "total_steps": result.get("step_count", 0),
            "extra": {
                "task_id": task_id,
                "seed": result.get("seed", 0),
                "reward": result.get("reward", 0.0),
                "finished": result.get("finished", False),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
                "finish_description": result.get("finish_description", ""),
                "num_turns": result.get("num_turns", 0),
            },
        },
        "extra": {
            "benchmark": "AndroidWorld",
            "task_text": result.get("task", ""),
        },
    }

    return trajectory


def save_atif_trajectories(results, output_dir, model, system_prompt):
    """Save each task result as an individual ATIF JSON file."""
    atif_dir = os.path.join(output_dir, "atif_trajectories")
    os.makedirs(atif_dir, exist_ok=True)

    for result in results:
        task_id = result.get("task_id", 0)
        traj = result_to_atif(result, model, system_prompt)
        path = os.path.join(atif_dir, f"task_{task_id:03d}.json")
        with open(path, "w") as f:
            json.dump(traj, f, indent=2, default=str)

    print(f"ATIF trajectories saved to {atif_dir}/ ({len(results)} files)")


# ---------------------------------------------------------------------------
# Common CLI arguments and finalization
# ---------------------------------------------------------------------------

def build_common_parser(description="Run Claude Code CLI on AndroidWorld tasks"):
    """Build argparse parser with common arguments."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task IDs (default: all)")
    parser.add_argument("--model", default="claude-opus-4-6",
                        help="Claude model to use")
    parser.add_argument("--max-turns", type=int, default=30,
                        help="Max turns for Claude")
    parser.add_argument("--output", default=None,
                        help="Output JSONL file (auto-generated if not set)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url",
                       help="Single container URL (sequential mode)")
    group.add_argument("--broker-url",
                       help="Broker URL for parallel mode")

    parser.add_argument("--pool-size", type=int, default=8,
                        help="Number of parallel workers (broker mode only)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT,
                        choices=list(PROMPT_MODULES.keys()),
                        help=f"System prompt variant (default: {DEFAULT_PROMPT})")
    parser.add_argument("--effort", default=None,
                        choices=["low", "medium", "high", "max"],
                        help="Claude reasoning effort level")
    return parser


def load_tasks(data_path, task_ids=None):
    """Load task definitions from JSONL, optionally filtering by IDs."""
    with open(data_path) as f:
        tasks = [json.loads(l) for l in f if l.strip()]
    if task_ids:
        ids = set(int(x) for x in task_ids.split(","))
        tasks = [t for t in tasks if t["task_id"] in ids]
    return tasks


def resolve_output_path(args):
    """Determine output path and create directories."""
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        ts = time.strftime("%y%m%d_%H%M")
        exp_name = f"ClaudeCodeCLI_{model_short}_{ts}"
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir, os.pardir, "results", exp_name,
        )
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    return output_path


def finalize_results(results, output_path, model, system_prompt, args,
                     extra_summary=None):
    """Print summary, save summary.json, ATIF trajectories, and prompt metadata."""
    successes = sum(1 for r in results if r.get("reward", 0) > 0)
    print(f"\n{'='*70}")
    print(f"FINAL: {successes}/{len(results)} ({100*successes/max(len(results),1):.0f}%)")
    print(f"{'='*70}")
    for r in sorted(results, key=lambda x: x.get("task_id", 0)):
        s = "OK" if r.get("reward", 0) > 0 else "FAIL"
        print(f"  task_id={r['task_id']:3d} [{s:4s}] {r.get('task', '')[:55]}")

    total_input = sum(r.get("input_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)
    total_cost = sum(r.get("cost_usd", 0) for r in results)

    mode = "parallel" if args.broker_url else "sequential"
    summary = {
        "total": len(results),
        "success": successes,
        "success_rate": successes / max(len(results), 1),
        "model": model,
        "max_turns": args.max_turns,
        "mode": mode,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "avg_input_tokens": total_input // max(len(results), 1),
        "avg_output_tokens": total_output // max(len(results), 1),
        "total_cost_usd": round(total_cost, 4),
    }
    if extra_summary:
        summary.update(extra_summary)

    output_dir = os.path.dirname(output_path)
    summary_path = os.path.join(output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    save_atif_trajectories(results, output_dir, model, system_prompt)

    prompt_meta_path = os.path.join(output_dir, "prompt_variant.txt")
    with open(prompt_meta_path, "w") as f:
        f.write(f"{args.prompt}\n")

    print(f"\nResults saved to {output_path}")
    print(f"Summary saved to {summary_path}")


def preflight_checks(args, system_prompt, allowed_tools, disable_tree):
    """Print config info and verify prerequisites."""
    print(f"Prompt variant: {args.prompt}")
    if allowed_tools != "Bash(command:*)":
        print(f"Allowed tools: {allowed_tools}")
    if not disable_tree:
        print(f"A11y tree: enabled")

    if not os.path.exists(ANDROID_ENV_SCRIPT):
        print(f"ERROR: android_env.py not found at {ANDROID_ENV_SCRIPT}")
        return False

    try:
        subprocess.run(["claude", "--version"], capture_output=True, check=True)
    except Exception:
        print("ERROR: claude CLI not found")
        return False

    return True
