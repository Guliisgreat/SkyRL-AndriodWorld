"""Bridge between claude_cli_common.py task_runner pattern and the async
Terminus_2 agent.

Provides ``run_terminus2_task_sync(task_def, container_url, **kwargs)``
with the same (task_def, container_url) → result dict signature expected
by ``run_parallel`` / ``run_sequential`` in ``claude_cli_common``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time

logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# Ensure this directory is on sys.path for claude_cli_common
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
_EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from claude_cli_common import force_eval, reset_container  # noqa: E402
from atif_utils import (  # noqa: E402
    make_agent_step,
    make_system_note_step,
    make_system_step,
    make_user_step,
    truncate_observation,
    unwrap_command,
    wrap_trajectory,
)

# Import terminus2 subpackage directly (avoids skyrl_agent.__init__ pulling
# in torch/transformers which may not be available on lightweight hosts).
# We register stub parent packages so relative imports within the terminus2
# package work correctly.
import importlib.util as _ilu
import types as _types

_EVAL_RUNNERS_ROOT = os.path.abspath(os.path.join(_EXAMPLES_DIR, os.pardir))
_T2_PKG = os.path.join(
    _EVAL_RUNNERS_ROOT,
    "agents", "cli", "terminus2",
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
        os.path.join(_EVAL_RUNNERS_ROOT, "agents"),
    )
    _ensure_stub_package(
        "skyrl_agent.agents",
        os.path.join(_EVAL_RUNNERS_ROOT, "agents"),
    )
    _ensure_stub_package(
        "skyrl_agent.agents.android",
        os.path.join(_EVAL_RUNNERS_ROOT, "agents", "cli"),
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
    _EVAL_RUNNERS_ROOT,
    "agents", "cli", "claude_sdk", "android_env.py",
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
    template_override: str | None = None,
    max_tokens: int | None = None,
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
    await asyncio.sleep(2)

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
        template_override=template_override,
        max_tokens=max_tokens,
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

    # if not finished and auto_finish:
    #     print(f"  Agent didn't call finish — auto-finishing...")
    #     auto_reward = force_eval(container_url)
    #     reward = auto_reward
    #     finished = True
    #     print(f"  Auto-finish reward: {auto_reward}")

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


def load_system_prompt(
    parser: str = "json",
    template_override: str | None = None,
) -> str:
    """Return the rendered system-prompt body for ATIF's step 1.

    Reads the same template that ``AndroidTerminus2Agent.run`` will send
    to the LLM, and strips the per-turn substitution slots
    (``%INSTRUCTION%`` / ``{instruction}`` for the task — captured in
    ATIF step 2 as a user message; ``%COMMAND_OUTPUT%`` /
    ``{terminal_state}`` for the running terminal — captured per-step
    in observations) so the system step shows just the standing
    instructions, comparable to what the other two harnesses store.
    """
    if template_override:
        from pathlib import Path
        template = Path(template_override).read_text()
    else:
        template = _agent_mod._load_harbor_template(parser)
    # Strip the runtime-substituted slots so the system step shows just
    # the standing instructions.
    for slot in ("%INSTRUCTION%", "%COMMAND_OUTPUT%",
                 "{instruction}", "{terminal_state}"):
        template = template.replace(slot, "")
    return template.strip()


# ---------------------------------------------------------------------------
# ATIF trajectory export — Terminus_2 specific
# ---------------------------------------------------------------------------


def _format_terminus2_observation(entry: dict) -> str:
    """Combine stdout / stderr / blocked-status into a single observation string.

    ``agent_commands_log`` entries come in two shapes:

    1. Successful exec (``_execute_commands``):
       ``{command, stdout, stderr, return_code, assistant_message}``
    2. Blocked / rejected (parse-error, parse-warning, no-command,
       multi-command, REJECT-prefix, forbidden adb, llm-error):
       ``{command, stdout, stderr, return_code, blocked: True,
       assistant_message}``

    Either way we expose what the agent saw as feedback, prefixed with
    a ``[blocked]`` marker for clarity when no real device call occurred.
    """
    stdout = (entry.get("stdout") or "").rstrip()
    stderr = (entry.get("stderr") or "").rstrip()
    blocked = bool(entry.get("blocked"))
    rc = entry.get("return_code")

    parts: list[str] = []
    if blocked:
        parts.append("[blocked]")
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(stderr)
    if not parts and rc is not None:
        parts.append(f"[return_code={rc}]")
    obs = "\n".join(parts) if parts else "(no output)"
    return truncate_observation(obs)


def result_to_atif(result, model, system_prompt, *, output_dir=None):
    """Convert a Terminus_2 task result to an ATIF-v1.6 trajectory.

    Reads ``result["agent_commands_log"]`` as the single source of truth
    so EVERY turn the agent took lands in the trajectory:
      * successful adb / passthrough-verb commands,
      * the final ``finish`` invocation (which is logged by
        ``_execute_commands`` like any other command, not skipped),
      * REJECT-prefix verb rejections,
      * forbidden-adb deny-list blocks,
      * parse-error / parse-warning turns (LLM emitted unparsable text),
      * no-command turns (LLM provided no actionable command),
      * multi-command rejections (LLM emitted >1 command in one turn),
      * llm-error turns (provider call failed mid-loop).

    Each entry becomes ONE agent step with all four required fields
    (``message`` from ``assistant_message``, ``model_name``,
    ``tool_calls`` carrying the bare verb form via ``unwrap_command``,
    ``observation`` carrying the device or framework reply).

    ``output_dir`` is accepted for signature parity with the other
    converters but ignored here — Terminus2 has no native trajectory
    file on disk.
    """
    del output_dir
    steps: list = []
    step_id = 1

    steps.append(make_system_step(step_id, system_prompt))
    step_id += 1

    steps.append(make_user_step(step_id, result.get("task", "")))
    step_id += 1

    log = result.get("agent_commands_log") or []
    for entry in log:
        raw_cmd = entry.get("command", "") or ""
        # Un-wrap the host-side ``python <android_env.py> <verb> ...``
        # form so the recorded action matches what the model emitted —
        # the same shape mini-swe and claude-cli store.
        bare_cmd = unwrap_command(raw_cmd)
        # Sentinel commands like ``<parse-error>`` never reach the host
        # shell, so they're not wrapped — pass them through as-is.
        if bare_cmd.startswith("<") and bare_cmd.endswith(">"):
            bare_cmd = bare_cmd
        message = (
            entry.get("assistant_message")
            or entry.get("thought")
            or f"Execute: {bare_cmd}"
        )
        observation = _format_terminus2_observation(entry)
        steps.append(make_agent_step(
            step_id,
            message=message,
            command=bare_cmd,
            observation=observation,
            model_name=model,
        ))
        step_id += 1

    # Surface runtime failures the runner reported instead of an action.
    err = result.get("error") or result.get("last_error")
    if err:
        steps.append(make_system_note_step(
            step_id, f"ENVIRONMENT_ERROR: {err}",
        ))
        step_id += 1

    # Degenerate case: agent never produced a single shell call (timeout
    # before turn 1, container reset failure, etc.). Emit an explicit
    # marker so the trajectory isn't a 2-step stub.
    if len(steps) == 2:
        note = (
            f"agent never executed (step_count={result.get('step_count', 0)}, "
            f"num_turns={result.get('num_turns', 0)}); no commands recorded "
            f"in agent_commands_log"
        )
        steps.append(make_system_note_step(step_id, note))
        step_id += 1

    return wrap_trajectory(
        agent_name="Terminus2",
        model=model,
        result=result,
        steps=steps,
    )
