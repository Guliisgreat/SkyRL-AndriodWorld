"""Bridge between claude_cli_common.py task_runner pattern and the async
Terminus_2 agent.

Provides ``run_terminus2_task_sync(task_def, container_url, **kwargs)``
with the same (task_def, container_url) → result dict signature expected
by ``run_parallel`` / ``run_sequential`` in ``claude_cli_common``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time

# Add parent dir (run_claude_sdk) to path so we can import claude_cli_common
_EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLAUDE_SDK_DIR = os.path.join(_EXAMPLES_DIR, "run_claude_sdk")
if _CLAUDE_SDK_DIR not in sys.path:
    sys.path.insert(0, _CLAUDE_SDK_DIR)

from claude_cli_common import force_eval, reset_container  # noqa: E402

# Import terminus2 subpackage directly (avoids skyrl_agent.__init__ pulling
# in torch/transformers which may not be available on lightweight hosts).
# We register stub parent packages so relative imports within the terminus2
# package work correctly.
import importlib.util as _ilu
import types as _types

_SKYRL_AGENT_ROOT = os.path.abspath(os.path.join(_EXAMPLES_DIR, os.pardir))
_T2_PKG = os.path.join(
    _SKYRL_AGENT_ROOT,
    "skyrl_agent", "agents", "android", "terminus2",
)


def _ensure_stub_package(dotted_name: str, path: str | None = None):
    """Register a stub package in sys.modules if not already present."""
    if dotted_name not in sys.modules:
        mod = _types.ModuleType(dotted_name)
        mod.__path__ = [path] if path else []
        mod.__package__ = dotted_name
        sys.modules[dotted_name] = mod


def _import_t2_module(module_name: str, file_name: str):
    """Import a terminus2 submodule with proper package hierarchy."""
    # Ensure parent stubs exist so relative imports resolve
    _ensure_stub_package(
        "skyrl_agent",
        os.path.join(_SKYRL_AGENT_ROOT, "skyrl_agent"),
    )
    _ensure_stub_package(
        "skyrl_agent.agents",
        os.path.join(_SKYRL_AGENT_ROOT, "skyrl_agent", "agents"),
    )
    _ensure_stub_package(
        "skyrl_agent.agents.android",
        os.path.join(_SKYRL_AGENT_ROOT, "skyrl_agent", "agents", "android"),
    )
    _ensure_stub_package(
        "skyrl_agent.agents.android.terminus2",
        _T2_PKG,
    )

    fqn = f"skyrl_agent.agents.android.terminus2.{module_name}"
    file_path = os.path.join(_T2_PKG, file_name)
    spec = _ilu.spec_from_file_location(
        fqn, file_path,
        submodule_search_locations=[],
    )
    mod = _ilu.module_from_spec(spec)
    mod.__package__ = "skyrl_agent.agents.android.terminus2"
    sys.modules[fqn] = mod
    spec.loader.exec_module(mod)
    return mod


_env_mod = _import_t2_module("environment", "environment.py")
SkyrlServerEnvironment = _env_mod.SkyrlServerEnvironment

_prompts_mod = _import_t2_module("prompts", "prompts.py")  # needed by agent
_agent_mod = _import_t2_module("agent", "agent.py")
AndroidTerminus2Agent = _agent_mod.AndroidTerminus2Agent

# Path to android_env.py (same resolution as claude_cli_common)
ANDROID_ENV_SCRIPT = os.path.join(
    _SKYRL_AGENT_ROOT,
    "skyrl_agent", "agents", "android", "claude_sdk", "android_env.py",
)
ANDROID_ENV_SCRIPT = os.path.abspath(ANDROID_ENV_SCRIPT)


async def run_terminus2_task(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    max_turns: int = 30,
    parser: str = "json",
    temperature: float = 0.7,
    api_base: str | None = None,
    command_timeout: int = 60,
    task_timeout: int = 900,
    auto_finish: bool = True,
    reasoning_effort: str | None = None,
) -> dict:
    """Run one Terminus_2 attempt on a task. Returns a result dict compatible
    with ``claude_cli_common.finalize_results``.
    """
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} (seed={seed}): {task_text[:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    # --- 1. Create state file ---
    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"t2_task{task_id}_",
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
    # Brief pause for emulator to settle after reset
    await asyncio.sleep(10)

    # --- 3. Create environment + agent ---
    env = SkyrlServerEnvironment(
        container_url=container_url,
        state_file=state_file,
        android_env_script=ANDROID_ENV_SCRIPT,
    )

    agent = AndroidTerminus2Agent(
        model_name=model,
        android_env_script=ANDROID_ENV_SCRIPT,
        max_turns=max_turns,
        parser_name=parser,
        temperature=temperature,
        api_base=api_base,
        command_timeout=command_timeout,
        reasoning_effort=reasoning_effort,
    )
    agent.setup(env)

    # --- 4. Run agent loop ---
    print(f"  Running Terminus_2 (model={model}, max_turns={max_turns}, "
          f"parser={parser})...")
    sys.stdout.flush()

    start_time = time.time()
    try:
        agent_result = await asyncio.wait_for(
            agent.run(task_text),
            timeout=task_timeout,
        )
        elapsed = time.time() - start_time
        print(f"  Agent finished in {elapsed:.0f}s "
              f"(turns={agent_result['turns']}, "
              f"complete={agent_result['task_complete']})")
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"  TIMEOUT after {elapsed:.0f}s")
        agent_result = {
            "task_complete": False, "turns": 0,
            "commands_log": [], "elapsed_seconds": elapsed,
            "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "last_error": "timeout",
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ERROR: {e}")
        agent_result = {
            "task_complete": False, "turns": 0,
            "commands_log": [], "elapsed_seconds": elapsed,
            "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "last_error": str(e),
        }

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
    print(f"      tokens: in={agent_result['input_tokens']}, "
          f"out={agent_result['output_tokens']}, "
          f"cost=${agent_result['cost_usd']:.4f}")
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
        "input_tokens": agent_result["input_tokens"],
        "output_tokens": agent_result["output_tokens"],
        "cost_usd": agent_result["cost_usd"],
        "num_turns": agent_result["turns"],
        "claude_output": "",  # No single text blob like Claude CLI
        "agent_commands_log": agent_result["commands_log"],
    }


def run_terminus2_task_sync(task_def: dict, container_url: str, **kwargs) -> dict:
    """Synchronous wrapper for ``run_terminus2_task``.

    Runs a fresh event loop — safe to call from thread-pool workers
    (``claude_cli_common.run_parallel`` uses threads).
    """
    return asyncio.run(run_terminus2_task(task_def, container_url, **kwargs))
