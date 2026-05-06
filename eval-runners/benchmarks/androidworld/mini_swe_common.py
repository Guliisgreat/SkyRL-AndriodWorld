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

import importlib.util as _ilu

import yaml

# Ensure this directory is on sys.path so `claude_cli_common` resolves whether
# mini_swe_common is loaded as a script-relative sibling or imported from
# another runner (e.g. benchmarks/androidlab/run_mini_swe.py).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from claude_cli_common import (  # noqa: E402
    ANDROID_ENV_SCRIPT,
    force_eval,
    reset_container,
)

# Load AndroidWorldEnvironment by direct file path. The agent module lives at
# eval-runners/agents/cli/mini_swe/environment.py and is a single-file leaf
# with no relative imports, so no parent-package machinery is needed.
_EVAL_RUNNERS_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir, os.pardir))
_MINI_SWE_ENV_FILE = os.path.join(
    _EVAL_RUNNERS_ROOT, "agents", "cli", "mini_swe", "environment.py",
)

_spec = _ilu.spec_from_file_location("mini_swe_environment", _MINI_SWE_ENV_FILE)
_env_mod = _ilu.module_from_spec(_spec)
# Register before exec so @dataclass can find the module via cls.__module__.
sys.modules["mini_swe_environment"] = _env_mod
_spec.loader.exec_module(_env_mod)
AndroidWorldEnvironment = _env_mod.AndroidWorldEnvironment
_ALLOWED_VERBS_BASH_ONLY = _env_mod._ALLOWED_VERBS_BASH_ONLY
_ALLOWED_VERBS_BASH_PLUS_TOOLS = _env_mod._ALLOWED_VERBS_BASH_PLUS_TOOLS


def _detect_allowed_verbs(config: dict) -> tuple[str, ...]:
    """Pick the env's verb allowlist from what the YAML's system_template
    actually advertises.

    A template that mentions the typed-tool verbs (e.g. `write-file` and
    `find-files`) needs the bash-plus-tools allowlist or the model will see
    "verb not recognized" for every typed-tool call. Anything else stays on
    the historical bash-only allowlist (`adb`, `finish`) — same deny list
    every existing v6-bash-only run has shipped with.

    Sniffing the rendered template means new templates Just Work without a
    new flag wired through ``run_mini_swe.py``; the YAML's surface advertises
    its needs, so the env honors them.
    """
    sys_tpl = config.get("agent", {}).get("system_template", "") or ""
    has_write_file = "write-file" in sys_tpl
    has_find_files = "find-files" in sys_tpl
    if has_write_file and has_find_files:
        return _ALLOWED_VERBS_BASH_PLUS_TOOLS
    return _ALLOWED_VERBS_BASH_ONLY


def load_config(config_path: str) -> dict:
    """Load androidworld.yaml config."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def _aggregate_usage(messages: list[dict], model_name: str) -> tuple[int, int, float]:
    """Sum prompt/completion tokens and per-call cost across a trajectory.

    Mirrors what Harbor's ``Chat`` does for terminus2 but reads from the
    *dumped* response objects that ``LitellmModel.query`` stores on each
    assistant message at ``extra.response.usage``. The cost extraction has
    three fallbacks, in order of accuracy:

    1. ``usage.cost`` returned inline by the upstream provider — OpenRouter
       populates this (e.g. ``"cost": 0.00034044``) along with a
       ``cost_details`` breakdown. This is the ground-truth, post-routing cost
       and survives ``response.model_dump()``.
    2. ``litellm.cost_per_token(model, prompt_tokens, completion_tokens)`` —
       works for any model in litellm's price table (OpenAI, Anthropic,
       and most commercial providers).
    3. ``0.0`` — used only when both upstream cost and litellm's price table
       are unavailable (unmapped local/finetuned models).

    Returns ``(total_input_tokens, total_output_tokens, total_cost_usd)``.
    """
    import litellm  # local import: keeps module load cheap when unused

    total_in = 0
    total_out = 0
    total_cost = 0.0

    for msg in messages:
        usage = (
            (msg.get("extra") or {})
            .get("response", {})
            .get("usage") or {}
        )
        if not usage:
            continue

        ptok = int(usage.get("prompt_tokens") or 0)
        ctok = int(usage.get("completion_tokens") or 0)
        total_in += ptok
        total_out += ctok

        # Tier 1: provider-reported cost (OpenRouter etc.). Use only when the
        # field is actually present and numeric — providers that don't return
        # it leave the key missing entirely, which is different from a
        # zero-cost call.
        upstream_cost = usage.get("cost")
        if upstream_cost is not None:
            try:
                total_cost += float(upstream_cost)
                continue
            except (TypeError, ValueError):
                pass

        # Tier 2: compute from litellm's price registry. Wrap in a broad
        # except because cost_per_token raises a bare Exception for unmapped
        # models and we don't want any of that surfacing to the runner.
        try:
            in_cost, out_cost = litellm.cost_per_token(
                model=model_name,
                prompt_tokens=ptok,
                completion_tokens=ctok,
            )
            total_cost += float(in_cost) + float(out_cost)
        except Exception:
            pass

    return total_in, total_out, total_cost


def _make_terminated_aware_agent_class():
    """Build a DefaultAgent subclass that exits when the state file shows
    `terminated=True` (i.e. the LLM called `python <env_script> finish ...`).

    Mirrors the explicit completion signal terminus2 uses (a `task_complete`
    field that breaks its loop) so we don't burn the rest of the step budget
    re-emitting commands that the env answers with "Task already finished".
    Subclassing — instead of modifying the env adapter — keeps
    `AndroidWorldEnvironment` free of any minisweagent imports.
    """
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.exceptions import Submitted

    class _TerminatedAwareAgent(DefaultAgent):
        def __init__(self, *args, _state_file: str, **kwargs):
            super().__init__(*args, **kwargs)
            self._state_file = _state_file

        def execute_actions(self, message: dict) -> list[dict]:
            added = super().execute_actions(message)
            try:
                with open(self._state_file) as f:
                    state = json.load(f)
            except (OSError, json.JSONDecodeError):
                return added
            if state.get("terminated"):
                raise Submitted(
                    {
                        "role": "exit",
                        "content": "android_env.py finish() called",
                        "extra": {
                            "exit_status": state.get("finish_status") or "submitted",
                            "submission": state.get("finish_description", ""),
                        },
                    }
                )
            return added

    return _TerminatedAwareAgent


def run_mini_swe_task(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    config: dict,
    task_timeout: int = 900,
    auto_finish: bool = True,
    traj_dir: str | None = None,
    traj_suffix: str = "",
) -> dict:
    """Run one mini-swe-agent attempt on an AndroidWorld task.

    If ``traj_dir`` is given, mini-swe-agent's native trajectory JSON
    (full message list including each ``bash`` tool call and its
    observation) is saved to ``{traj_dir}/task_{task_id:03d}.json``.
    DefaultAgent.save() runs after every step, so partial trajectories
    survive crashes/timeouts.

    Returns a result dict compatible with ``claude_cli_common.finalize_results``.
    """
    # Suppress mini-swe-agent startup banner
    os.environ["MSWEA_SILENT_STARTUP"] = "1"

    from minisweagent.models import get_model

    AgentClass = _make_terminated_aware_agent_class()

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
    allowed_verbs = _detect_allowed_verbs(config)
    env = AndroidWorldEnvironment(
        container_url=container_url,
        state_file=state_file,
        android_env_script=ANDROID_ENV_SCRIPT,
        timeout=env_config.get("timeout", 120),
        allowed_verbs=allowed_verbs,
    )

    model_config = config.get("model", {})
    model_obj = get_model(model, model_config)

    agent_config = config.get("agent", {})
    agent = AgentClass(model_obj, env, _state_file=state_file, **agent_config)

    # Auto-save the native mini-swe-agent trajectory after every step. Vital
    # for debugging at scale — the ATIF export is keyed off claude_sdk's
    # `result["commands"]` shape, which we don't populate.
    if traj_dir:
        os.makedirs(traj_dir, exist_ok=True)
        from pathlib import Path
        agent.config.output_path = (
            Path(traj_dir) / f"task_{task_id:03d}{traj_suffix}.json"
        )

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

    # Aggregate real token counts and a best-effort cost estimate from the
    # per-call response objects that LitellmModel.query stashes on each
    # assistant message. ``agent.cost`` itself is unreliable here because we
    # set ``cost_tracking: ignore_errors`` (required to avoid crashing on
    # models that aren't in litellm's price table) — _aggregate_usage uses
    # OpenRouter's inline ``usage.cost`` first, then litellm's price table.
    model_name = getattr(getattr(agent, "model", None), "config", None)
    model_name = getattr(model_name, "model_name", "") or ""
    total_input_tokens, total_output_tokens, total_cost = _aggregate_usage(
        getattr(agent, "messages", []), model_name,
    )

    status = "OK" if reward > 0 else "FAIL"
    print(f"  >>> REWARD: {reward} ({status}), steps={step_count}, "
          f"finished={finished}")
    print(f"      agent_steps={agent.n_calls}, "
          f"tokens in={total_input_tokens} out={total_output_tokens}, "
          f"cost=${total_cost:.4f}")
    sys.stdout.flush()

    return {
        "task_id": task_id,
        "seed": seed,
        "task": task_text,
        "reward": reward,
        "step_count": step_count,
        "finished": finished,
        "elapsed_seconds": elapsed,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": total_cost,
        "num_turns": agent.n_calls,
        "claude_output": "",
        "finish_description": state.get("finish_description", ""),
    }
