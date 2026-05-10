"""Bridge between claude_cli_common task_runner pattern and the MobileWorld
GeneralE2E GUI agent (supports Gemini, GPT-4o, etc.).

Provides ``run_general_e2e_task_sync(task_def, container_url, **kwargs)``
with the same (task_def, container_url) -> result dict signature expected
by ``run_parallel`` / ``run_sequential`` in ``claude_cli_common``.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

_EVAL_RUNNERS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_AW_DIR = os.path.join(_EVAL_RUNNERS_DIR, "benchmarks", "androidworld")
if _AW_DIR not in sys.path:
    sys.path.insert(0, _AW_DIR)

_MW_SRC = os.path.join(
    _EVAL_RUNNERS_DIR, os.pardir, "MobileWorld", "src"
)
_MW_SRC = os.path.abspath(_MW_SRC)
if _MW_SRC not in sys.path:
    sys.path.insert(0, _MW_SRC)

from claude_cli_common import force_eval, http_post  # noqa: E402
from mobile_world.agents.implementations.general_e2e_agent import GeneralE2EAgentMCP  # noqa: E402
from qwen3vl_common import decode_screenshot, map_action_to_androidworld  # noqa: E402


def run_general_e2e_task_sync(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    api_url: str,
    api_key: str = "empty",
    max_steps: int = 30,
    temperature: float = 0.0,
    task_timeout: int = 1800,
    auto_finish: bool = True,
) -> dict:
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} (seed={seed}): {task_text[:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    # --- 1. Reset container ---
    try:
        reset_resp = http_post(f"{container_url}/reset", {
            "seed": seed,
            "options": {"task_id": task_id, "go_home_on_reset": True},
        })
        print(f"  Reset OK.")
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        return {
            "task_id": task_id, "seed": seed, "task": task_text,
            "reward": 0.0, "error": f"reset: {e}",
        }

    # --- 2. Decode initial screenshot ---
    obs_data = reset_resp.get("observation", {})
    screenshot = decode_screenshot(obs_data)
    if screenshot is None:
        print(f"  No screenshot from reset, aborting.")
        return {
            "task_id": task_id, "seed": seed, "task": task_text,
            "reward": 0.0, "error": "no_screenshot_on_reset",
        }

    # --- 3. Create agent ---
    agent = GeneralE2EAgentMCP(
        model_name=model,
        llm_base_url=api_url,
        api_key=api_key,
        runtime_conf={"temperature": temperature},
        tools=[],
    )
    agent.initialize(task_text)

    # --- 4. Agent loop ---
    print(f"  Running GeneralE2E (model={model}, max_steps={max_steps})...")
    sys.stdout.flush()

    start_time = time.time()
    step_count = 0
    reward = 0.0
    terminated = False
    truncated = False
    last_error = ""
    commands_log: list[dict] = []

    try:
        for step_idx in range(max_steps):
            elapsed = time.time() - start_time
            if elapsed > task_timeout:
                print(f"  TIMEOUT after {elapsed:.0f}s at step {step_idx}")
                last_error = "task_timeout"
                break

            raw_response, action = None, None
            for _attempt in range(3):
                try:
                    raw_response, action = agent.predict({"screenshot": screenshot})
                    break
                except Exception as e:
                    print(f"  Predict attempt {_attempt+1}/3 FAILED at step {step_idx}: {e}")
                    if _attempt == 2:
                        traceback.print_exc()
                        last_error = f"predict: {e}"
                    else:
                        time.sleep(3 * (_attempt + 1))
            if action is None:
                break

            action_dict = map_action_to_androidworld(action)
            mw_dump = action.model_dump(exclude_none=True)
            thought = (raw_response or "")[:500]

            print(f"  Step {step_idx}: {mw_dump.get('action_type')} -> {action_dict}")
            sys.stdout.flush()

            commands_log.append({
                "step_idx": step_idx,
                "mw_action": mw_dump,
                "aw_action": action_dict,
                "thought": thought[:200],
            })

            step_resp = None
            for _attempt in range(3):
                try:
                    step_resp = http_post(
                        f"{container_url}/step",
                        {"action": action_dict, "thought": thought},
                        timeout=120,
                    )
                    break
                except Exception as e:
                    print(f"  Step HTTP attempt {_attempt+1}/3 FAILED at step {step_idx}: {e}")
                    if _attempt == 2:
                        last_error = f"step_http: {e}"
                    else:
                        time.sleep(2 * (_attempt + 1))
            if step_resp is None:
                break

            step_count += 1
            reward = step_resp.get("reward", 0.0)
            terminated = step_resp.get("terminated", False)
            truncated = step_resp.get("truncated", False)

            if terminated or truncated:
                break

            if action_dict.get("action_type") == "answer":
                try:
                    fin_resp = http_post(
                        f"{container_url}/step",
                        {"action": {"action_type": "status",
                                    "goal_status": "complete"},
                         "thought": "terminate after answer"},
                        timeout=120,
                    )
                    reward = fin_resp.get("reward", 0.0)
                    terminated = True
                    print(f"  Answer+terminate -> reward={reward}")
                except Exception as e:
                    print(f"  Answer terminate FAILED: {e}")
                break

            obs_data = step_resp.get("observation", {})
            screenshot = decode_screenshot(obs_data)
            if screenshot is None:
                print(f"  No screenshot at step {step_idx}, ending.")
                last_error = "no_screenshot"
                break

    except Exception as e:
        print(f"  UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        last_error = str(e)

    elapsed = time.time() - start_time

    finished = terminated or truncated
    # if not finished and auto_finish:
    #     print(f"  Agent didn't finish — auto-finishing...")
    #     auto_reward = force_eval(container_url)
    #     reward = auto_reward
    #     finished = True
    #     print(f"  Auto-finish reward: {auto_reward}")

    token_usage = {}
    if hasattr(agent, "get_total_token_usage"):
        token_usage = agent.get_total_token_usage()
    input_tokens = token_usage.get("prompt_tokens", 0)
    output_tokens = token_usage.get("completion_tokens", 0)

    status = "OK" if reward > 0 else "FAIL"
    print(f"  >>> REWARD: {reward} ({status}), steps={step_count}, "
          f"finished={finished}")
    print(f"      tokens: in={input_tokens}, out={output_tokens}")
    sys.stdout.flush()

    return {
        "task_id": task_id,
        "seed": seed,
        "task": task_text,
        "reward": reward,
        "step_count": step_count,
        "finished": finished,
        "commands": commands_log,
        "finish_description": "",
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": 0.0,
        "num_turns": step_count,
        "claude_output": "",
        "last_error": last_error,
    }
