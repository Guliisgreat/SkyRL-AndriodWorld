"""
Shared infrastructure for Claude Code CLI MobileWorld experiment runners.

Adapted from claude_cli_common.py (AndroidWorld). Key differences:
- Tasks identified by task_name (str) instead of task_id + seed
- Task lifecycle: /task/init -> agent runs -> /task/eval -> /task/tear_down
- ADB executed directly (not via /step_adb), so no reward from ADB calls
- Evaluation is a separate HTTP call (/task/eval) after agent finishes
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

MW_ENV_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir,
    "skyrl_agent", "agents", "mobileworld", "claude_sdk", "mw_env.py",
)
MW_ENV_SCRIPT = os.path.abspath(MW_ENV_SCRIPT)

# ---------------------------------------------------------------------------
# Prompt modules
# ---------------------------------------------------------------------------

PROMPT_MODULES = {
    "mw_adb_baseline": "skyrl_agent.agents.mobileworld.claude_sdk.prompts.mw_adb_baseline",
    "mw_adb_api": "skyrl_agent.agents.mobileworld.claude_sdk.prompts.mw_adb_api",
}
DEFAULT_PROMPT = "mw_adb_baseline"


def load_prompt_module(prompt_name: str):
    """Load a prompt module by name."""
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
    """Load a system prompt by name and format it with MW_ENV_SCRIPT."""
    mod = load_prompt_module(prompt_name)
    return mod.build_system_prompt(MW_ENV_SCRIPT)


def get_allowed_tools(prompt_name: str) -> str:
    """Get required tools for a prompt (default: Bash only)."""
    mod = load_prompt_module(prompt_name)
    return getattr(mod, "REQUIRED_TOOLS", "Bash(command:*)")


# ---------------------------------------------------------------------------
# HTTP helpers
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
# MobileWorld task lifecycle
# ---------------------------------------------------------------------------

def init_task(base_url, task_name, device_id="emulator-5554"):
    """Initialize a MobileWorld task."""
    return http_post(f"{base_url}/task/init", {
        "task_name": task_name,
        "req_device": device_id,
    })


def eval_task(base_url, task_name, device_id="emulator-5554"):
    """Evaluate task success. Returns (score, reason).

    Note: MobileWorld's /task/eval is a GET endpoint but uses a Pydantic body
    (TaskOperationRequest), so we must send JSON in the body of a GET request.
    """
    url = f"{base_url}/task/eval"
    payload = json.dumps({"task_name": task_name, "req_device": device_id}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    if isinstance(data, dict):
        return data.get("score", 0.0), data.get("reason", "")
    return float(data), ""


def teardown_task(base_url, task_name, device_id="emulator-5554"):
    """Tear down a task."""
    return http_post(f"{base_url}/task/tear_down", {
        "task_name": task_name,
        "req_device": device_id,
    })


def reset_container(base_url, device_id="emulator-5554", timeout=60):
    """Full state reset — snapshot + backend stop + config clear.

    Calls the /reset endpoint which resets all three layers:
    server Python state, Docker-in-Docker backends, and Android emulator.
    """
    try:
        return http_post(f"{base_url}/reset", {
            "task_name": "_reset",
            "req_device": device_id,
        }, timeout=timeout)
    except Exception as e:
        print(f"  WARNING: reset failed: {e}")
        return None


def get_task_goal(base_url, task_name):
    """Get human-readable task goal."""
    return http_get(f"{base_url}/task/goal", {"task_name": task_name})


def check_health(base_url):
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("ok", False) or data.get("status") == "ok"
    except Exception:
        return False


def force_eval(container_url, task_name, device_id="emulator-5554"):
    """Force task evaluation after agent finishes without calling finish.

    Returns (score, reason).
    """
    try:
        score, reason = eval_task(container_url, task_name, device_id)
        return score, reason
    except Exception:
        return 0.0, "eval_failed"


# ---------------------------------------------------------------------------
# Core: run a single task attempt
# ---------------------------------------------------------------------------

def run_one_task(task_def, container_url, model, max_turns, system_prompt,
                 effort=None, allowed_tools="Bash(command:*)",
                 disable_tree=True, prompt_suffix="",
                 task_timeout=900, adb_serial="localhost:5556",
                 device_id="emulator-5554"):
    """Run one Claude attempt on a MobileWorld task. Returns a result dict."""
    task_name = task_def["task_name"]
    trial = task_def.get("trial", 1)

    print(f"\n{'='*70}")
    print(f"TASK {task_name} (trial={trial})")
    print(f"{'='*70}")
    sys.stdout.flush()

    # Create state file
    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"mw_{task_name[:30]}_",
    )
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({
            "step_count": 0, "terminated": False,
            "finish_status": "", "finish_description": "",
            "step_records": [], "_last_a11y_cache": "",
        }, f)

    # Teardown any previous task, then init
    try:
        teardown_task(container_url, task_name, device_id)
    except Exception:
        pass

    try:
        init_task(container_url, task_name, device_id)
        print(f"  Task init OK.")
    except Exception as e:
        print(f"  Task init FAILED: {e}")
        os.unlink(state_file)
        return {"task_name": task_name, "trial": trial,
                "task": "", "reward": 0.0, "error": f"init: {e}"}

    time.sleep(5)  # Let emulator stabilize after snapshot restore

    # Get task goal
    try:
        goal = get_task_goal(container_url, task_name)
        if isinstance(goal, dict):
            goal = str(goal)
        print(f"  Goal: {str(goal)[:100]}")
    except Exception as e:
        print(f"  Failed to get goal: {e}")
        goal = task_def.get("task", task_name)

    # Build prompt
    prompt = f"{system_prompt}\n\n## Task\n\n{goal}\n\nComplete this task on the Android device."
    if prompt_suffix:
        prompt += f"\n\n{prompt_suffix}"

    # Set env vars for mw_env.py
    env = os.environ.copy()
    env["MW_SERVER_URL"] = container_url
    env["MW_ADB_SERIAL"] = adb_serial
    env["MW_DEVICE_ID"] = device_id
    env["MW_STATE_FILE"] = state_file
    if disable_tree:
        env["MW_DISABLE_TREE"] = "1"
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

    # Read state file
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

    # Evaluate task via /task/eval
    score, eval_reason = 0.0, ""
    try:
        score, eval_reason = eval_task(container_url, task_name, device_id)
        print(f"  Eval score: {score} ({eval_reason})")
    except Exception as e:
        print(f"  Eval FAILED: {e}")

    # Teardown
    try:
        teardown_task(container_url, task_name, device_id)
    except Exception:
        pass

    status = "OK" if score > 0 else "FAIL"
    print(f"  >>> REWARD: {score} ({status}), steps={step_count}, finished={finished}")
    print(f"      tokens: in={input_tokens}, out={output_tokens}, cost=${cost_usd:.4f}")
    sys.stdout.flush()

    return {
        "task_name": task_name,
        "task_id": task_def.get("task_id", 0),
        "trial": trial,
        "task": str(goal),
        "reward": score,
        "eval_reason": eval_reason,
        "step_count": step_count,
        "finished": finished,
        "finish_description": finish_description,
        "commands": state.get("step_records", []),
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "num_turns": num_turns,
        "claude_output": claude_json.get("result", "")[-3000:] if claude_json else "",
    }


# ---------------------------------------------------------------------------
# Orchestration: sequential and parallel runners
# ---------------------------------------------------------------------------

def run_sequential(tasks, container_url, output_path, task_runner):
    """Run tasks sequentially on a single container."""
    results = []
    with open(output_path, "w") as out:
        for i, task_def in enumerate(tasks):
            if not check_health(container_url):
                print(f"  Container unhealthy, waiting 30s...")
                time.sleep(30)
                if not check_health(container_url):
                    print(f"  Still unhealthy, skipping task {task_def['task_name']}")
                    results.append({
                        "task_name": task_def["task_name"], "reward": 0.0,
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


def run_parallel(tasks, containers, output_path, task_runner):
    """Run tasks in parallel across multiple containers.

    containers: list of (server_url, adb_serial) tuples.
    task_runner: callable(task_def, container_url, adb_serial) -> result dict.
    """
    task_queue = queue.Queue()
    for t in tasks:
        task_queue.put(t)

    # Build a pool of available containers
    container_pool = queue.Queue()
    for server_url, adb_serial in containers:
        container_pool.put((server_url, adb_serial))

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

            # Acquire a container
            server_url, adb_serial = container_pool.get()
            task_name = task_def["task_name"]

            try:
                print(f"  [worker {worker_id}] Running {task_name} on "
                      f"{server_url} (adb={adb_serial})")
                result = task_runner(task_def, server_url,
                                     adb_serial=adb_serial, device_id=adb_serial)
            except Exception as e:
                print(f"  [worker {worker_id}] ERROR on {task_name}: {e}")
                result = {
                    "task_name": task_name, "trial": task_def.get("trial", 1),
                    "task": task_def.get("task", ""), "reward": 0.0,
                    "error": str(e),
                }
            finally:
                # Return container to pool
                container_pool.put((server_url, adb_serial))

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

    num_workers = min(len(containers), len(tasks))
    print(f"Starting {num_workers} parallel workers across {len(containers)} containers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)
        for f in futures:
            if f.exception():
                print(f"  Worker exception: {f.exception()}")

    out_file.close()
    return results


def run_broker(tasks, broker_url, pool_size, output_path, task_runner):
    """Run tasks in parallel using the broker for container allocation.

    The broker manages container health, failover, and pool sizing.
    task_runner: callable(task_def, container_url, adb_serial=...) -> result dict.
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

            task_name = task_def["task_name"]
            container_info = None
            env_id = None

            try:
                container_info = broker_acquire(broker_url)
                env_id = container_info["env_id"]
                server_port = container_info["server_port"]
                container_url = container_info.get(
                    "server_url", f"http://localhost:{server_port}"
                )
                device_id = container_info.get("device_id", "emulator-5554")
                emulator_port = container_info.get("emulator_port", 5554)
                adb_serial = device_id

                print(f"  [worker {worker_id}] Acquired env_id={env_id} "
                      f"port={server_port} emu={emulator_port} for {task_name}")

                result = task_runner(
                    task_def, container_url,
                    adb_serial=adb_serial, device_id=device_id,
                )
                healthy = True

            except Exception as e:
                print(f"  [worker {worker_id}] ERROR on {task_name}: {e}")
                result = {
                    "task_name": task_name, "trial": task_def.get("trial", 1),
                    "task": task_def.get("task", ""), "reward": 0.0,
                    "error": str(e),
                }
                healthy = False

            finally:
                if env_id is not None:
                    broker_release(broker_url, env_id, healthy=healthy)
                    print(f"  [worker {worker_id}] Returned env_id={env_id}")

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
    print(f"Starting {num_workers} broker workers (pool_size={pool_size})...")
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
    task_name = result.get("task_name", "unknown")
    trial = result.get("trial", 1)
    session_id = f"mobileworld-{task_name}-t{trial}-{uuid.uuid4().hex[:8]}"

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
        action_type = rec.get("action_type", "unknown")
        params = rec.get("action_params", {})
        cmd_output = rec.get("command_output", "")

        if action_type == "adb":
            tool_call_id = f"call_{step_id}"
            bash_cmd = f'python mw_env.py adb "{params.get("command", "")}"'

            steps.append({
                "step_id": step_id,
                "source": "agent",
                "message": rec.get("thought", "") or bash_cmd[:200],
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

        elif action_type in ("sql", "write-file", "read-file", "find-files"):
            tool_call_id = f"call_{step_id}"
            bash_cmd = f'python mw_env.py {action_type} ...'

            steps.append({
                "step_id": step_id,
                "source": "agent",
                "message": rec.get("thought", "") or bash_cmd[:200],
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

        elif action_type == "finish":
            tool_call_id = f"call_{step_id}"
            status = params.get("status", "complete")
            desc = params.get("description", "")
            bash_cmd = f'python mw_env.py finish --status {status} --description "{desc}"'

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
            "name": "ClaudeCodeCLI_MW",
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
                "task_name": task_name,
                "trial": trial,
                "reward": result.get("reward", 0.0),
                "eval_reason": result.get("eval_reason", ""),
                "finished": result.get("finished", False),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
                "finish_description": result.get("finish_description", ""),
                "num_turns": result.get("num_turns", 0),
            },
        },
        "extra": {
            "benchmark": "MobileWorld",
            "task_text": result.get("task", ""),
        },
    }

    return trajectory


def save_atif_trajectories(results, output_dir, model, system_prompt):
    """Save each task result as an individual ATIF JSON file."""
    atif_dir = os.path.join(output_dir, "atif_trajectories")
    os.makedirs(atif_dir, exist_ok=True)

    for result in results:
        task_name = result.get("task_name", "unknown")
        trial = result.get("trial", 1)
        safe_name = task_name.replace("/", "_")[:50]
        path = os.path.join(atif_dir, f"{safe_name}_t{trial}.json")
        traj = result_to_atif(result, model, system_prompt)
        with open(path, "w") as f:
            json.dump(traj, f, indent=2, default=str)

    print(f"ATIF trajectories saved to {atif_dir}/ ({len(results)} files)")


# ---------------------------------------------------------------------------
# Common CLI arguments and finalization
# ---------------------------------------------------------------------------

def build_common_parser(description="Run Claude Code CLI on MobileWorld tasks"):
    """Build argparse parser with common arguments."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data", required=True,
                        help="JSONL file with task definitions")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task names (default: all)")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Claude model to use")
    parser.add_argument("--max-turns", type=int, default=30,
                        help="Max turns for Claude")
    parser.add_argument("--output", default=None,
                        help="Output JSONL file (auto-generated if not set)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url",
                       help="Single container URL (sequential mode)")
    group.add_argument("--containers", type=str,
                       help="Container specs for parallel mode. "
                            "Format: 'server_url=adb_serial,...' "
                            "Example: 'http://localhost:6800=localhost:5556,"
                            "http://localhost:6801=localhost:5557'")
    group.add_argument("--broker-url", type=str,
                       help="Broker URL for pool-managed parallel mode. "
                            "Example: 'http://localhost:9200'")

    parser.add_argument("--pool-size", type=int, default=4,
                        help="Number of parallel workers (parallel mode only)")
    parser.add_argument("--adb-serial", default="localhost:5556",
                        help="ADB serial for single-container mode (default: localhost:5556)")
    parser.add_argument("--device-id", default="emulator-5554",
                        help="Device ID inside the container (default: emulator-5554)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT,
                        choices=list(PROMPT_MODULES.keys()),
                        help=f"System prompt variant (default: {DEFAULT_PROMPT})")
    parser.add_argument("--effort", default=None,
                        choices=["low", "medium", "high", "max"],
                        help="Claude reasoning effort level")
    return parser


def parse_containers(containers_str):
    """Parse container specs string into list of (server_url, adb_serial) tuples.

    Format: 'http://host:6800=localhost:5556,http://host:6801=localhost:5557'
    """
    containers = []
    for spec in containers_str.split(","):
        spec = spec.strip()
        if "=" in spec:
            server_url, adb_serial = spec.split("=", 1)
            containers.append((server_url.strip(), adb_serial.strip()))
        else:
            raise ValueError(
                f"Invalid container spec '{spec}'. "
                f"Expected format: 'server_url=adb_serial'. "
                f"Example: 'http://localhost:6800=localhost:5556'"
            )
    return containers


def load_tasks(data_path, task_names=None):
    """Load task definitions from JSONL, optionally filtering by names."""
    with open(data_path) as f:
        tasks = [json.loads(l) for l in f if l.strip()]
    if task_names:
        names = set(task_names.split(","))
        tasks = [t for t in tasks if t["task_name"] in names]
    return tasks


def resolve_output_path(args):
    """Determine output path and create directories."""
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        model_short = args.model.replace("-", "").replace(".", "").replace("/", "")
        ts = time.strftime("%y%m%d_%H%M")
        exp_name = f"ClaudeCodeCLI_MW_{model_short}_{ts}"
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
    total = len(results)

    print(f"\n{'='*70}")
    print(f"FINAL: {successes}/{total} ({100*successes/max(total,1):.0f}%)")
    print(f"{'='*70}")
    for r in sorted(results, key=lambda x: (x.get("task_name", ""), x.get("trial", 0))):
        s = "OK" if r.get("reward", 0) > 0 else "FAIL"
        trial = r.get("trial", 1)
        name = r.get("task_name", "?")
        print(f"  {name} (t{trial}) [{s:4s}] {str(r.get('task', ''))[:50]}")

    # Per-task aggregation (across trials)
    from collections import defaultdict
    per_task = defaultdict(list)
    for r in results:
        per_task[r.get("task_name", "?")].append(r.get("reward", 0.0))

    tasks_with_any_success = sum(1 for rewards in per_task.values() if any(r > 0 for r in rewards))
    unique_tasks = len(per_task)

    total_input = sum(r.get("input_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)
    total_cost = sum(r.get("cost_usd", 0) for r in results)

    mode = "broker" if getattr(args, 'broker_url', None) else ("parallel" if args.containers else "sequential")
    summary = {
        "total_entries": total,
        "success_entries": successes,
        "success_rate_by_entry": round(successes / max(total, 1), 4),
        "unique_tasks": unique_tasks,
        "tasks_with_any_success": tasks_with_any_success,
        "success_rate_by_task": round(tasks_with_any_success / max(unique_tasks, 1), 4),
        "model": model,
        "max_turns": args.max_turns,
        "mode": mode,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "avg_input_tokens": total_input // max(total, 1),
        "avg_output_tokens": total_output // max(total, 1),
        "total_cost_usd": round(total_cost, 4),
        "per_task_rewards": {k: v for k, v in sorted(per_task.items())},
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
    print(f"\nPer-task success rate: {tasks_with_any_success}/{unique_tasks} "
          f"({100*tasks_with_any_success/max(unique_tasks,1):.0f}%)")


def preflight_checks(args, system_prompt, allowed_tools, disable_tree):
    """Print config info and verify prerequisites."""
    print(f"Prompt variant: {args.prompt}")
    if allowed_tools != "Bash(command:*)":
        print(f"Allowed tools: {allowed_tools}")
    if not disable_tree:
        print(f"A11y tree: enabled")

    if not os.path.exists(MW_ENV_SCRIPT):
        print(f"ERROR: mw_env.py not found at {MW_ENV_SCRIPT}")
        return False

    try:
        subprocess.run(["claude", "--version"], capture_output=True, check=True)
    except Exception:
        print("ERROR: claude CLI not found")
        return False

    return True
