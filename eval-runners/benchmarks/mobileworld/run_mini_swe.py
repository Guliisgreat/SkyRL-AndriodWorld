#!/usr/bin/env python3
"""Run mini-swe-agent on MobileWorld with a Tier 1a-style YAML config.

Usage:
    python run_mini_swe.py --data gui_only_tasks.jsonl \\
        --broker-url http://localhost:9400 --pool-size 16 \\
        --model openrouter/minimax/minimax-m2.7 \\
        --config mobileworld_tier1a.yaml

Default config = mobileworld_tier1a.yaml (14 helpers + Android encyclopedia).
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import sys
import tempfile
import time
import types as _types
from functools import partial

import yaml

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from mw_cli_common import (
    MW_TOOLS_SCRIPT,
    build_common_parser,
    check_health,
    eval_task,
    finalize_results,
    get_task_goal,
    init_task,
    load_tasks,
    parse_containers,
    resolve_output_path,
    run_broker,
    run_parallel,
    run_sequential,
    teardown_task,
    _extract_answer,
    _http_post_quiet,
)


# ---------------------------------------------------------------------------
# Import the mini_swe AndroidWorldEnvironment via file loader (avoids
# pulling in skyrl_agent's heavy deps).
# ---------------------------------------------------------------------------

_EVAL_RUNNERS_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir, os.pardir))
_MINI_SWE_PKG = os.path.join(_EVAL_RUNNERS_ROOT, "agents", "cli", "mini_swe")


def _ensure_stub_package(dotted_name: str, path: str | None = None):
    if dotted_name not in sys.modules:
        mod = _types.ModuleType(dotted_name)
        mod.__path__ = [path] if path else []
        mod.__package__ = dotted_name
        sys.modules[dotted_name] = mod


def _import_mini_swe_env():
    for name, path in [
        ("skyrl_agent", os.path.join(_EVAL_RUNNERS_ROOT, "agents")),
        ("skyrl_agent.agents", os.path.join(_EVAL_RUNNERS_ROOT, "agents")),
        ("skyrl_agent.agents.android", os.path.join(_EVAL_RUNNERS_ROOT, "agents", "cli")),
        ("skyrl_agent.agents.android.mini_swe", _MINI_SWE_PKG),
    ]:
        _ensure_stub_package(name, path)
    fqn = "skyrl_agent.agents.android.mini_swe.environment"
    file_path = os.path.join(_MINI_SWE_PKG, "environment.py")
    spec = _ilu.spec_from_file_location(fqn, file_path, submodule_search_locations=[])
    mod = _ilu.module_from_spec(spec)
    mod.__package__ = "skyrl_agent.agents.android.mini_swe"
    sys.modules[fqn] = mod
    spec.loader.exec_module(mod)
    return mod


_env_mod = _import_mini_swe_env()
AndroidWorldEnvironment = _env_mod.AndroidWorldEnvironment


def _make_mw_env(container_url: str, state_file: str, bridge_script: str,
                 timeout: int, adb_serial: str, device_id: str):
    """Construct AndroidWorldEnvironment and patch its env dict to include
    MobileWorld's MW_SERVER_URL / MW_DEVICE_ID / etc."""
    env = AndroidWorldEnvironment(
        container_url=container_url,
        state_file=state_file,
        android_env_script=bridge_script,
        timeout=timeout,
    )
    env._env.update({
        "MW_SERVER_URL": container_url,
        "MW_ADB_SERIAL": adb_serial,
        "MW_DEVICE_ID": device_id,
        "MW_STATE_FILE": state_file,
        "MW_DISABLE_TREE": "1",
    })
    return env


# ---------------------------------------------------------------------------
# Per-task runner — broker init/eval is the same as mw_cli_common; the inner
# loop is mini-swe-agent's DefaultAgent.
# ---------------------------------------------------------------------------

def run_mini_swe_task(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    config: dict,
    task_timeout: int = 900,
    bridge_script: str = MW_TOOLS_SCRIPT,
    adb_serial: str = "localhost:5556",
    device_id: str = "emulator-5554",
) -> dict:
    # Suppress mini-swe-agent startup banner + ignore cost-tracking errors
    # for OpenRouter models that LiteLLM doesn't have pricing data for
    # (e.g. minimax-m2.7).
    os.environ["MSWEA_SILENT_STARTUP"] = "1"
    os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

    from minisweagent.models import get_model
    from minisweagent.agents.default import DefaultAgent

    task_name = task_def["task_name"]
    trial = task_def.get("trial", 1)

    print(f"\n{'='*70}")
    print(f"TASK {task_name} (trial={trial})")
    print(f"{'='*70}")
    sys.stdout.flush()

    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"mw_mswe_{task_name[:30]}_",
    )
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({
            "step_count": 0, "terminated": False,
            "finish_status": "", "finish_description": "",
            "step_records": [], "_last_a11y_cache": "",
        }, f)

    try:
        teardown_task(container_url, task_name, device_id)
    except Exception:
        pass

    try:
        init_task(container_url, task_name, device_id)
        print("  Task init OK.")
    except Exception as e:
        print(f"  Task init FAILED: {e}")
        os.unlink(state_file)
        return {"task_name": task_name, "trial": trial,
                "task": "", "reward": 0.0, "error": f"init: {e}"}

    time.sleep(5)

    try:
        goal = get_task_goal(container_url, task_name)
        if isinstance(goal, dict):
            goal = str(goal)
        print(f"  Goal: {str(goal)[:100]}")
    except Exception as e:
        print(f"  Failed to get goal: {e}")
        goal = task_def.get("task", task_name)

    env_config = config.get("environment", {})
    env = _make_mw_env(
        container_url=container_url,
        state_file=state_file,
        bridge_script=bridge_script,
        timeout=env_config.get("timeout", 120),
        adb_serial=adb_serial,
        device_id=device_id,
    )

    model_config = config.get("model", {})
    model_obj = get_model(model, model_config)

    agent_config = config.get("agent", {})
    agent = DefaultAgent(model_obj, env, **agent_config)

    print(f"  Running mini-swe-agent (model={model}, "
          f"step_limit={agent_config.get('step_limit', 30)})...")
    sys.stdout.flush()

    start_time = time.time()
    elapsed = 0
    submission = ""
    exit_status = "unknown"
    try:
        result = agent.run(task=str(goal))
        elapsed = time.time() - start_time
        exit_status = result.get("exit_status", "unknown")
        submission = result.get("submission", "") or ""
        print(f"  Agent finished in {elapsed:.0f}s "
              f"(steps={agent.n_calls}, exit={exit_status})")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ERROR: {type(e).__name__}: {str(e)[:200]}")
        exit_status = type(e).__name__

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

    # Auto-finish: if agent didn't call finish, try to extract an answer
    # from its submission (the text before/after the final code block).
    if not finished and submission:
        answer = _extract_answer(submission)
        if answer:
            print(f"  Auto-finish: submitting extracted answer ({len(answer)} chars)")
            try:
                _http_post_quiet(
                    f"{container_url}/step",
                    {"device": device_id,
                     "action": {"action_type": "answer", "text": answer}},
                )
                finish_description = answer
            except Exception:
                pass

    score, eval_reason = 0.0, ""
    try:
        score, eval_reason = eval_task(container_url, task_name, device_id)
        print(f"  Eval score: {score} ({eval_reason})")
    except Exception as e:
        print(f"  Eval FAILED: {e}")

    try:
        teardown_task(container_url, task_name, device_id)
    except Exception:
        pass

    status = "OK" if score > 0 else "FAIL"
    print(f"  >>> REWARD: {score} ({status}), steps={step_count}, "
          f"finished={finished}, agent_steps={agent.n_calls}")
    try:
        print(f"      cost=${agent.cost:.4f}")
    except Exception:
        pass
    sys.stdout.flush()

    cost = 0.0
    try:
        cost = float(agent.cost)
    except Exception:
        pass

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
        "input_tokens": 0,  # mini-swe-agent tracks cost not tokens
        "output_tokens": 0,
        "cost_usd": cost,
        "num_turns": agent.n_calls,
        "claude_output": submission[-3000:] if submission else "",
        "exit_status": exit_status,
    }


def build_parser():
    parser = build_common_parser(description="mini-swe-agent on MobileWorld")
    parser.set_defaults(prompt="mini_swe_mw_tier1a")
    parser.add_argument("--config", default=None,
                        help="YAML config (default: mobileworld_tier1a.yaml)")
    parser.add_argument("--task-timeout", type=int, default=900)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    config_path = args.config or os.path.join(_THIS_DIR, "mobileworld_tier1a.yaml")
    if not os.path.exists(config_path):
        print(f"ERROR: Config not found at {config_path}")
        return 1
    with open(config_path) as f:
        config = yaml.safe_load(f)

    bridge_script = MW_TOOLS_SCRIPT
    if not os.path.exists(bridge_script):
        print(f"ERROR: bridge script not found at {bridge_script}")
        return 1

    tasks = load_tasks(args.data, args.tasks)
    if not tasks:
        print("No tasks to run.")
        return 0

    output_path = resolve_output_path(args)

    task_runner = partial(
        run_mini_swe_task,
        model=args.model,
        config=config,
        task_timeout=args.task_timeout,
        bridge_script=bridge_script,
        adb_serial=args.adb_serial,
        device_id=args.device_id,
    )

    if args.broker_url:
        mode = "broker"
        if not check_health(args.broker_url):
            print(f"ERROR: Broker at {args.broker_url} is not healthy")
            return 1
        print(f"Broker {args.broker_url} is healthy. Pool size: {args.pool_size}")
    elif args.containers:
        mode = "parallel"
    else:
        mode = "sequential"

    print(f"Mode: {mode} (mini-swe-agent on MobileWorld)")
    print(f"Tasks: {len(tasks)}, model={args.model}")
    print(f"Config: {config_path}")
    print(f"Bridge: {os.path.basename(bridge_script)}")
    print(f"Output: {output_path}")

    if mode == "broker":
        results = run_broker(tasks, args.broker_url, args.pool_size,
                             output_path, task_runner)
    elif mode == "parallel":
        containers = parse_containers(args.containers)
        results = run_parallel(tasks, containers, output_path, task_runner)
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container at {args.container_url} is not healthy")
            return 1
        print(f"Container {args.container_url} is healthy.")
        results = run_sequential(tasks, args.container_url, output_path, task_runner)

    system_prompt = (
        f"[mini-swe-agent + MobileWorld, model={args.model}, "
        f"step_limit={config.get('agent',{}).get('step_limit', 30)}, "
        f"prompt=tier1a]"
    )
    finalize_results(results, output_path, args.model, system_prompt, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
