"""Bridge between claude_cli_common task_runner pattern and the VenusNaviAgent
for AndroidWorld evaluation.

Provides ``run_venus_task_sync(task_def, container_url, **kwargs)``
with the same (task_def, container_url) -> result dict signature expected
by ``run_parallel`` / ``run_sequential`` in ``claude_cli_common``.

The agent source lives in the MobileWorld package but evaluation targets
AndroidWorld containers (``androidworld:2026``).
"""

from __future__ import annotations

import base64
import os
import sys
import time
import traceback

import numpy as np
from PIL import Image

_EXAMPLES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLAUDE_SDK_DIR = os.path.join(_EXAMPLES_DIR, "run_claude_sdk")
if _CLAUDE_SDK_DIR not in sys.path:
    sys.path.insert(0, _CLAUDE_SDK_DIR)

_MW_SRC = os.path.join(
    os.path.dirname(_EXAMPLES_DIR), os.pardir, "MobileWorld", "src"
)
_MW_SRC = os.path.abspath(_MW_SRC)
if _MW_SRC not in sys.path:
    sys.path.insert(0, _MW_SRC)

from claude_cli_common import force_eval, http_post  # noqa: E402
from mobile_world.agents.implementations.ui_venus_agent import VenusNaviAgent  # noqa: E402


# ---------------------------------------------------------------------------
# Screenshot decoding (shared with qwen3vl_common)
# ---------------------------------------------------------------------------

def decode_screenshot(obs: dict) -> Image.Image | None:
    """Decode the base64-encoded numpy screenshot from a container response."""
    if obs is None:
        return None
    raw_b64 = obs.get("image")
    if raw_b64 is None:
        return None
    shape = obs.get("image_shape")
    dtype = obs.get("image_dtype", "uint8")
    buf = base64.b64decode(raw_b64)
    arr = np.frombuffer(buf, dtype=np.dtype(dtype)).reshape(shape)
    return Image.fromarray(arr)


# ---------------------------------------------------------------------------
# Action mapping: JSONAction -> AndroidWorld /step payload
# ---------------------------------------------------------------------------

def map_action_to_androidworld(action) -> dict:
    """Convert a JSONAction to an AndroidWorld action dict.

    The container's ``/step`` endpoint creates ``json_action.JSONAction(**action)``
    which only accepts fields: action_type, index, x, y, text, direction,
    goal_status, app_name, keycode.
    """
    d = action.model_dump(exclude_none=True)
    at = d.get("action_type")

    if at == "click":
        return {"action_type": "click", "x": d.get("x"), "y": d.get("y")}

    if at == "long_press":
        return {"action_type": "long_press", "x": d.get("x"), "y": d.get("y")}

    if at == "input_text":
        return {"action_type": "input_text", "text": d.get("text", "")}

    if at == "drag":
        sx, sy = d.get("start_x", 0), d.get("start_y", 0)
        ex, ey = d.get("end_x", 0), d.get("end_y", 0)
        dx, dy = ex - sx, ey - sy
        if abs(dy) >= abs(dx):
            direction = "down" if dy < 0 else "up"
        else:
            direction = "right" if dx < 0 else "left"
        return {"action_type": "scroll", "direction": direction}

    if at == "scroll":
        return {"action_type": "scroll", "direction": d.get("direction", "down")}

    if at == "finished":
        return {"action_type": "status", "goal_status": "complete"}

    if at == "answer":
        return {"action_type": "answer", "text": d.get("text", "")}

    if at == "navigate_home":
        return {"action_type": "navigate_home"}

    if at == "navigate_back":
        return {"action_type": "navigate_back"}

    if at == "keyboard_enter":
        return {"action_type": "keyboard_enter"}

    if at == "open_app":
        return {"action_type": "open_app", "app_name": d.get("app_name", "")}

    if at == "wait":
        return {"action_type": "wait"}

    return {"action_type": "status", "goal_status": "infeasible"}


# ---------------------------------------------------------------------------
# Core task runner
# ---------------------------------------------------------------------------

def run_venus_task_sync(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    api_url: str,
    api_key: str = "empty",
    max_steps: int = 30,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    history_length: int = 5,
    task_timeout: int = 1800,
    auto_finish: bool = True,
) -> dict:
    """Run one VenusNaviAgent attempt on an AndroidWorld task.

    Returns a result dict compatible with ``claude_cli_common.finalize_results``.
    """
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} (seed={seed}): {task_text[:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    def _error_result(error_msg: str) -> dict:
        return {
            "task_id": task_id, "seed": seed, "task": task_text,
            "reward": 0.0, "step_count": 0, "finished": False,
            "commands": [], "finish_description": "",
            "elapsed_seconds": 0.0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "num_turns": 0, "claude_output": "",
            "last_error": error_msg,
        }

    # --- 1. Reset AndroidWorld container ---
    try:
        reset_resp = http_post(f"{container_url}/reset", {
            "seed": seed,
            "options": {"task_id": task_id, "go_home_on_reset": True},
        })
        print(f"  Reset OK.")
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        return _error_result(f"reset: {e}")

    # --- 2. Decode initial screenshot ---
    obs_data = reset_resp.get("observation", {})
    screenshot = decode_screenshot(obs_data)
    if screenshot is None:
        print(f"  No screenshot from reset, aborting.")
        return _error_result("no_screenshot_on_reset")

    # --- 3. Create Venus agent ---
    agent = VenusNaviAgent(
        llm_base_url=api_url,
        model_name=model,
        api_key=api_key,
        model_config={
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        history_length=history_length,
    )
    agent.initialize(task_text)

    # --- 4. Agent loop ---
    print(f"  Running Venus (model={model}, max_steps={max_steps}, "
          f"history={history_length})...")
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

            # 4a. Agent predict
            try:
                raw_response, action = agent.predict({"screenshot": screenshot})
            except Exception as e:
                print(f"  Predict FAILED at step {step_idx}: {e}")
                traceback.print_exc()
                last_error = f"predict: {e}"
                break

            # 4b. Map action to AndroidWorld format
            action_dict = map_action_to_androidworld(action)
            venus_dump = action.model_dump(exclude_none=True)
            thought = (raw_response or "")[:500]

            print(f"  Step {step_idx}: {venus_dump.get('action_type')} -> {action_dict}")
            sys.stdout.flush()

            commands_log.append({
                "step_idx": step_idx,
                "venus_action": venus_dump,
                "aw_action": action_dict,
                "thought": thought[:200],
            })

            # 4c. Send to AndroidWorld container
            try:
                step_resp = http_post(
                    f"{container_url}/step",
                    {"action": action_dict, "thought": thought},
                    timeout=120,
                )
            except Exception as e:
                print(f"  Step HTTP FAILED at step {step_idx}: {e}")
                last_error = f"step_http: {e}"
                break

            step_count += 1
            reward = step_resp.get("reward", 0.0)
            terminated = step_resp.get("terminated", False)
            truncated = step_resp.get("truncated", False)

            if terminated or truncated:
                break

            # 4c-2. answer action must be followed by status/complete
            # so the AndroidWorld server evaluates the cached answer text.
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

            # 4d. Decode next screenshot
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

    # --- 5. Auto-finish if needed ---
    finished = terminated or truncated
    if not finished and auto_finish:
        print(f"  Agent didn't finish -- auto-finishing...")
        auto_reward = force_eval(container_url)
        reward = auto_reward
        finished = True
        print(f"  Auto-finish reward: {auto_reward}")

    # --- 6. Token usage ---
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
