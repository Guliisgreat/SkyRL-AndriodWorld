"""Bridge between mini-swe-agent and AndroidWorld container infrastructure.

Provides ``run_mini_swe_task_sync(task_def, container_url, **kwargs)``
with the same (task_def, container_url) → result dict signature expected
by ``run_parallel`` / ``run_sequential`` in ``claude_cli_common``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import yaml

# Add run_claude_sdk to path for claude_cli_common helpers
_EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLAUDE_SDK_DIR = os.path.join(_EXAMPLES_DIR, "run_claude_sdk")
if _CLAUDE_SDK_DIR not in sys.path:
    sys.path.insert(0, _CLAUDE_SDK_DIR)

from claude_cli_common import force_eval, reset_container  # noqa: E402

# Import AndroidWorldEnvironment via direct import to avoid heavy skyrl_agent deps
import importlib.util as _ilu
import types as _types

_SKYRL_AGENT_ROOT = os.path.abspath(os.path.join(_EXAMPLES_DIR, os.pardir))
_MINI_SWE_PKG = os.path.join(
    _SKYRL_AGENT_ROOT,
    "skyrl_agent", "agents", "android", "mini_swe",
)


def _ensure_stub_package(dotted_name: str, path: str | None = None):
    if dotted_name not in sys.modules:
        mod = _types.ModuleType(dotted_name)
        mod.__path__ = [path] if path else []
        mod.__package__ = dotted_name
        sys.modules[dotted_name] = mod


def _import_mini_swe_env():
    """Import AndroidWorldEnvironment without pulling in torch/transformers."""
    for name, path in [
        ("skyrl_agent", os.path.join(_SKYRL_AGENT_ROOT, "skyrl_agent")),
        ("skyrl_agent.agents", os.path.join(_SKYRL_AGENT_ROOT, "skyrl_agent", "agents")),
        ("skyrl_agent.agents.android", os.path.join(_SKYRL_AGENT_ROOT, "skyrl_agent", "agents", "android")),
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

# Path to android_env.py
ANDROID_ENV_SCRIPT = os.path.join(
    _SKYRL_AGENT_ROOT,
    "skyrl_agent", "agents", "android", "claude_sdk", "android_env.py",
)
ANDROID_ENV_SCRIPT = os.path.abspath(ANDROID_ENV_SCRIPT)


def load_config(config_path: str) -> dict:
    """Load androidworld.yaml config."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def run_mini_swe_task(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    config: dict,
    task_timeout: int = 900,
    auto_finish: bool = True,
) -> dict:
    """Run one mini-swe-agent attempt on an AndroidWorld task.

    Returns a result dict compatible with ``claude_cli_common.finalize_results``.
    """
    # Suppress mini-swe-agent startup banner
    os.environ["MSWEA_SILENT_STARTUP"] = "1"

    from minisweagent.models import get_model
    from minisweagent.agents.default import DefaultAgent

    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} (seed={seed}): {task_text[:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    # --- 1. Create state file ---
    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"mswe_task{task_id}_",
    )
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({
            "step_count": 0, "terminated": False, "reward": 0.0,
            "finish_status": "", "finish_description": "",
            "step_records": [], "_last_a11y_cache": "",
        }, f)

    # --- 2. Reset container ---
    try:
        reset_container(container_url, task_id, seed)
        print(f"  Reset OK.")
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        os.unlink(state_file)
        return {
            "task_id": task_id, "seed": seed, "task": task_text,
            "reward": 0.0, "error": f"reset: {e}",
        }

    # --- 3. Create environment + agent ---
    env_config = config.get("environment", {})
    env = AndroidWorldEnvironment(
        container_url=container_url,
        state_file=state_file,
        android_env_script=ANDROID_ENV_SCRIPT,
        timeout=env_config.get("timeout", 120),
    )

    model_config = config.get("model", {})
    model_obj = get_model(model, model_config)

    agent_config = config.get("agent", {})
    agent = DefaultAgent(model_obj, env, **agent_config)

    # --- 4. Run agent loop ---
    print(f"  Running mini-swe-agent (model={model}, "
          f"step_limit={agent_config.get('step_limit', 30)})...")
    sys.stdout.flush()

    start_time = time.time()
    try:
        result = agent.run(task=task_text)
        elapsed = time.time() - start_time
        exit_status = result.get("exit_status", "unknown")
        print(f"  Agent finished in {elapsed:.0f}s "
              f"(steps={agent.n_calls}, exit={exit_status})")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ERROR: {e}")
        result = {"exit_status": str(type(e).__name__), "submission": ""}

    # --- 5. Read state file ---
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
    print(f"  >>> REWARD: {reward} ({status}), steps={step_count}, "
          f"finished={finished}")
    print(f"      agent_steps={agent.n_calls}, cost=${agent.cost:.4f}")
    sys.stdout.flush()

    return {
        "task_id": task_id,
        "seed": seed,
        "task": task_text,
        "reward": reward,
        "step_count": step_count,
        "finished": finished,
        "elapsed_seconds": elapsed,
        "input_tokens": 0,  # mini-swe-agent tracks cost, not tokens directly
        "output_tokens": 0,
        "cost_usd": agent.cost,
        "num_turns": agent.n_calls,
        "claude_output": "",
        "finish_description": state.get("finish_description", ""),
    }
