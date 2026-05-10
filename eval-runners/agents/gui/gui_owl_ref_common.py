"""Reference-faithful GUI-Owl-1.5 runner for androidworld:2026 containers.

Matches the paper's original implementation (Mobile-Agent-v3.5) as
documented in REFERENCE_IMPLEMENTATION.md.  Differences from
gui_owl_common.py:

  1. System prompt: verbatim from the paper (no Tips section, no extra
     actions like ``interact``).
  2. User prompt: ``"Previous actions:\\nStep1: …"`` with action text
     extracted by splitting on ``"Action:"`` / ``"<tool_call>"``.
  3. Conversation always 2 messages (system + user) — never multi-turn.
  4. ``tap`` → ``click`` replacement.
  5. Coordinate conversion uses ``int()`` (truncation), matching reference.
  6. History format matches reference ``convert_format()`` output.

Swipe is still mapped to ``scroll`` with direction because
androidworld:2026 containers do not support pixel-coordinate drag.
"""

from __future__ import annotations

import base64
import copy
import io
import json
import os
import re
import sys
import time
import traceback

import numpy as np
from PIL import Image

_EVAL_RUNNERS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_AW_DIR = os.path.join(_EVAL_RUNNERS_DIR, "benchmarks", "androidworld")
if _AW_DIR not in sys.path:
    sys.path.insert(0, _AW_DIR)

from claude_cli_common import force_eval, http_post  # noqa: E402


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def decode_screenshot(obs: dict) -> Image.Image | None:
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


def pil_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def smart_resize(height, width, factor=28, min_pixels=56*56,
                 max_pixels=14*14*4*1280, max_long_side=50000):
    """Resize dimensions to multiples of factor (Qwen-VL patch size).

    Matches the reference implementation's coordinate_resize.smart_resize.
    """
    import math
    def round_by_factor(n, f):
        return round(n / f) * f
    def ceil_by_factor(n, f):
        return math.ceil(n / f) * f
    def floor_by_factor(n, f):
        return math.floor(n / f) * f

    if max(height, width) > max_long_side:
        beta = max(height, width) / max_long_side
        height, width = int(height / beta), int(width / beta)
    h_bar = round_by_factor(height, factor)
    w_bar = round_by_factor(width, factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = floor_by_factor(height / beta, factor)
        w_bar = floor_by_factor(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = ceil_by_factor(height * beta, factor)
        w_bar = ceil_by_factor(width * beta, factor)
    return h_bar, w_bar


# ---------------------------------------------------------------------------
# System prompt — verbatim from the paper (section 3.4)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = '# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>\n{"type": "function", "function": {"name_for_human": "mobile_use", "name": "mobile_use", "description": "Use a touchscreen to interact with a mobile device, and take screenshots.\n* This is an interface to a mobile device with touchscreen. You can perform actions like clicking, typing, swiping, etc.\n* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions.\n* The screen\'s resolution is 1000x1000.\n* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don\'t click boxes on their edges unless asked.", "parameters": {"properties": {"action": {"description": "The action to perform. The available actions are:\n* `key`: Perform a key event on the mobile device.\n    - This supports adb\'s `keyevent` syntax.\n    - Examples: "volume_up", "volume_down", "power", "camera", "clear".\n* `click`: Click the point on the screen with coordinate (x, y).\n* `long_press`: Press the point on the screen with coordinate (x, y) for specified seconds.\n* `swipe`: Swipe from the starting point with coordinate (x, y) to the end point with coordinates2 (x2, y2).\n* `type`: Input the specified text into the activated input box.\n* `system_button`: Press the system button.\n* `open`: Open an app on the device.\n* `wait`: Wait specified seconds for the change to happen.\n* `answer`: Terminate the current task and output the answer.\n* `terminate`: Terminate the current task and report its completion status.", "enum": ["key", "click", "long_press", "swipe", "type", "system_button", "open", "wait", "answer", "terminate"], "type": "string"}, "coordinate": {"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=click`, `action=long_press`, and `action=swipe`.", "type": "array"}, "coordinate2": {"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=swipe`.", "type": "array"}, "text": {"description": "Required only by `action=key`, `action=type`, `action=open`, `action=answer`.", "type": "string"}, "time": {"description": "The seconds to wait. Required only by `action=long_press` and `action=wait`.", "type": "number"}, "button": {"description": "Back means returning to the previous interface, Home means returning to the desktop, Menu means opening the application background menu, and Enter means pressing the enter. Required only by `action=system_button`", "enum": ["Back", "Home", "Menu", "Enter"], "type": "string"}, "status": {"description": "The status of the task. Required only by `action=terminate`.", "type": "string", "enum": ["success", "failure"]}}, "required": ["action"], "type": "object"}, "args_format": "Format the arguments as a JSON object."}}\n</tools>\n\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>\n\n# Response format\n\nResponse format for every step:\n1) Action: a short imperative describing what to do in the UI.\n2) A single <tool_call>...</tool_call> block containing only the JSON: {"name": <function-name>, "arguments": <args-json-object>}.\n\nRules:\n- Output exactly in the order: Action, <tool_call>.\n- Be brief: one for Action.\n- Do not output anything else outside those two parts.\n- If finishing, use action=terminate in the tool call.'


# ---------------------------------------------------------------------------
# History extraction — matches reference convert_format()
# ---------------------------------------------------------------------------

def cut_current_messages(messages, last_image=5):
    """Keep only the last N user messages with images; clear older ones.

    Matches the reference gui_owl.py cut_current_messages exactly.
    """
    non_empty_user_indices = []
    for i, msg in enumerate(messages):
        if msg.get('role') == 'user' and msg.get('content') and len(msg['content']) > 0:
            non_empty_user_indices.append(i)

    if len(non_empty_user_indices) > last_image:
        indices_to_clear = non_empty_user_indices[:-last_image]
    else:
        indices_to_clear = []

    for index in indices_to_clear:
        if index == 1:
            messages[index]['content'] = [messages[index]['content'][0]]
        else:
            messages[index]['content'] = []

    return messages


def convert_format(goal, messages):
    """Flatten multi-turn conversation into [system, user] with history text.

    Matches the reference gui_owl.py convert_format exactly.
    """
    new_messages = copy.deepcopy(messages[:1])
    history = []
    for i, msg in enumerate(messages):
        if msg.get('role') == 'user' and (
            msg["content"] == []
            or (len(msg["content"]) == 1 and msg["content"][0]["type"] == "text")
        ):
            history.append(
                messages[i + 1]["content"][0]["text"]
                .split("Action:")[-1]
                .split("<tool_call>")[0]
                .strip()
            )
        if i != 1 and msg.get('role') == 'user' and msg["content"] != []:
            if len(history) == 0:
                new_messages = copy.deepcopy(messages)
                new_messages[1]["content"][0]["text"] = (
                    f"Please generate the next move according to the UI screenshot, "
                    f"instruction and previous actions.\n\n"
                    f"Instruction: {goal}\n\n"
                    f"Previous actions:\nNo previous action."
                )
                return new_messages
            history_string = ""
            for j, h in enumerate(history):
                history_string += f"Step{j + 1}: {h}\n"
            history_string = history_string[:-1]
            new_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Please generate the next move according to the UI screenshot, "
                                f"instruction and previous actions.\n\n"
                                f"Instruction: {goal}\n\n"
                                f"Previous actions:\n{history_string}"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": msg["content"][0]["image_url"]["url"]},
                        },
                    ],
                }
            )
            new_messages += copy.deepcopy(messages[i + 1 :])
            return new_messages

    return copy.deepcopy(messages)


def extract_action_text(response: str) -> str:
    """Extract text between 'Action:' and '<tool_call>' from a model response."""
    parts = response.split("Action:")
    if len(parts) < 2:
        text = response.split("<tool_call>")[0].strip()
        return text[:120] if text else "(no action text)"
    after_action = parts[-1]
    text = after_action.split("<tool_call>")[0].strip()
    return text[:120] if text else "(no action text)"


# ---------------------------------------------------------------------------
# Response parsing — reference-faithful
# ---------------------------------------------------------------------------

def parse_response(text, orig_w, orig_h):
    """Parse model response.  Coordinates 0-999 → original screen pixels."""
    tc_match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
    if not tc_match:
        raise ValueError(f"No <tool_call> found in: {text[:200]}")

    tool_json = json.loads(tc_match.group(1))
    args = tool_json.get("arguments", {})
    action = args.get("action", "")

    # Reference: replace ``tap`` with ``click``
    action = action.replace("tap", "click")

    def to_orig(coord):
        """Convert from 0-999 normalised to original screen using int() (truncation)."""
        if coord and len(coord) >= 2:
            x = int(coord[0] / 999 * orig_w)
            y = int(coord[1] / 999 * orig_h)
            return [x, y]
        return coord

    if action == "click":
        c = to_orig(args.get("coordinate"))
        return {"action_type": "click", "x": c[0], "y": c[1]}
    if action == "long_press":
        c = to_orig(args.get("coordinate"))
        return {"action_type": "long_press", "x": c[0], "y": c[1]}
    if action == "swipe":
        s = to_orig(args.get("coordinate"))
        e = to_orig(args.get("coordinate2"))
        # Pixel-coordinate swipe (androidworld:2026swipe compatible)
        return {"action_type": "swipe", "direction": [s[0], s[1], e[0], e[1]]}
    if action == "type":
        return {"action_type": "input_text", "text": args.get("text", "")}
    if action == "system_button":
        b = (args.get("button") or "").lower()
        if b == "back":
            return {"action_type": "navigate_back"}
        if b == "home":
            return {"action_type": "navigate_home"}
        if b in ("enter", "menu"):
            return {"action_type": "keyboard_enter"}
        return {"action_type": "navigate_back"}
    if action in ("open", "open_app"):
        return {"action_type": "open_app", "app_name": args.get("text", "")}
    if action == "answer":
        return {"action_type": "answer", "text": args.get("text", "")}
    if action == "terminate":
        status = args.get("status", "failure")
        gs = "complete" if status == "success" else "infeasible"
        return {"action_type": "status", "goal_status": gs}
    if action == "wait":
        return {"action_type": "wait"}
    if action == "key":
        key_text = (args.get("text") or "").lower()
        if key_text in ("enter", "return"):
            return {"action_type": "keyboard_enter"}
        return {"action_type": "wait"}
    raise ValueError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Core task runner
# ---------------------------------------------------------------------------

def run_gui_owl_ref_task_sync(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    api_url: str,
    api_key: str = "empty",
    max_steps: int = 50,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    task_timeout: int = 1800,
    auto_finish: bool = True,
    history_n: int = 1,  # unused, kept for CLI compat
) -> dict:
    """Run reference-faithful GUI-Owl-1.5 on an AndroidWorld task."""
    from openai import OpenAI

    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*70}")
    print(f"TASK {task_id} (seed={seed}): {task_text[:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    def _error_result(error_msg):
        return {
            "task_id": task_id, "seed": seed, "task": task_text,
            "reward": 0.0, "step_count": 0, "finished": False,
            "commands": [], "finish_description": "",
            "elapsed_seconds": 0.0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "num_turns": 0, "claude_output": "",
            "last_error": error_msg,
        }

    # 1. Reset
    try:
        reset_resp = http_post(f"{container_url}/reset", {
            "seed": seed,
            "options": {"task_id": task_id, "go_home_on_reset": True},
        })
    except Exception as e:
        return _error_result(f"reset: {e}")

    # 2. Initial screenshot
    obs_data = reset_resp.get("observation", {})
    screenshot = decode_screenshot(obs_data)
    if screenshot is None:
        return _error_result("no_screenshot_on_reset")

    orig_w, orig_h = screenshot.width, screenshot.height
    print(f"  Screen: {orig_w}x{orig_h}, coord space: 0-999 normalised")
    sys.stdout.flush()

    # 3. Create LLM client (reference: timeout=30)
    client = OpenAI(base_url=api_url, api_key=api_key, timeout=30)

    start_time = time.time()
    step_count = 0
    reward = 0.0
    terminated = False
    truncated = False
    last_error = ""
    commands_log = []
    total_input_tokens = 0
    total_output_tokens = 0
    prev_action_was_answer = False
    prev_actions = []  # raw dummy_action dicts for answer tracking

    # -- Multi-turn conversation (reference gui_owl.py) --
    history_action_texts: list[str] = []
    cur_messages: list[dict] = []

    try:
        for step_idx in range(max_steps):
            if time.time() - start_time > task_timeout:
                last_error = "task_timeout"
                break

            # Auto-terminate after answer (reference two-step flow)
            if prev_action_was_answer:
                action_dict = {"action_type": "status", "goal_status": "complete"}
                print(f"  Step {step_idx}: auto-terminate after answer")
                try:
                    step_resp = http_post(
                        f"{container_url}/step",
                        {"action": action_dict, "thought": "terminate after answer"},
                        timeout=120,
                    )
                    reward = step_resp.get("reward", 0.0)
                    terminated = True
                    step_count += 1
                except Exception as e:
                    last_error = f"terminate_http: {e}"
                break

            # Encode screenshot (raw 1080x2400, matching reference)
            img_b64 = pil_to_base64(screenshot)
            screenshot_url = f"data:image/png;base64,{img_b64}"

            # Multi-turn conversation format (matching reference gui_owl.py)
            if step_idx == 0:
                cur_messages = [
                    {"role": "system", "content": [
                        {"type": "text", "text": SYSTEM_PROMPT},
                    ]},
                    {"role": "user", "content": [
                        {"type": "text", "text": (
                            "Please generate the next move according to the UI "
                            "screenshot, instruction and previous actions.\n\n"
                            f"Instruction: {task_text}\n\n"
                            "Previous actions:\nNo previous action."
                        )},
                        {"type": "image_url", "image_url": {"url": screenshot_url}},
                    ]},
                ]
            else:
                cur_messages.append(
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": screenshot_url}},
                    ]}
                )

            # Cut old images + flatten to 2-msg (matching reference)
            cur_messages = cut_current_messages(cur_messages, last_image=5)
            messages = convert_format(task_text, cur_messages)

            # LLM call with retry (reference doesn't pass temperature)
            prediction = None
            for llm_attempt in range(10):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                    )
                    prediction = response.choices[0].message.content or ""
                    if response.usage:
                        total_input_tokens += response.usage.prompt_tokens
                        total_output_tokens += response.usage.completion_tokens
                    break
                except Exception as e:
                    print(f"  LLM error attempt {llm_attempt+1}: {e}")
                    if llm_attempt < 9:
                        time.sleep(20)
                    else:
                        last_error = f"llm: {e}"

            if prediction is None:
                break

            # Parse — on failure, use UNKNOWN action
            try:
                action_dict = parse_response(prediction, orig_w, orig_h)
            except Exception as e:
                print(f"  Parse FAILED at step {step_idx}: {e}")
                action_dict = {"action_type": "unknown"}

            at = action_dict.get("action_type", "")
            print(f"  Step {step_idx}: {at} -> {action_dict}")
            sys.stdout.flush()

            # Append assistant response to multi-turn conversation (matching reference)
            cur_messages.append(
                {"role": "assistant", "content": [
                    {"type": "text", "text": prediction},
                ]}
            )

            action_text = extract_action_text(prediction)
            history_action_texts.append(action_text)
            commands_log.append({
                "step_idx": step_idx,
                "action": action_dict,
                "action_text": action_text,
            })

            # Reference answer flow: if PREVIOUS action was answer,
            # force current to terminate+success and cache the text
            if prev_actions and prev_actions[-1].get("action_type") == "answer":
                action_dict = {"action_type": "status", "goal_status": "complete"}
                at = "status"

            if at == "answer":
                prev_action_was_answer = True
            prev_actions.append(action_dict)

            # Execute (sleep is inside actuation.py in the container)
            try:
                step_resp = http_post(
                    f"{container_url}/step",
                    {"action": action_dict, "thought": action_text[:500]},
                    timeout=120,
                )
            except Exception as e:
                last_error = f"step_http: {e}"
                break

            step_count += 1
            reward = step_resp.get("reward", 0.0)
            terminated = step_resp.get("terminated", False)
            truncated = step_resp.get("truncated", False)

            if terminated or truncated:
                break

            if at == "answer":
                continue

            # Next screenshot
            obs_data = step_resp.get("observation", {})
            screenshot = decode_screenshot(obs_data)
            if screenshot is None:
                last_error = "no_screenshot"
                break

    except Exception as e:
        traceback.print_exc()
        last_error = str(e)

    elapsed = time.time() - start_time

    finished = terminated or truncated
    # if not finished and auto_finish:
    #     auto_reward = force_eval(container_url)
    #     reward = auto_reward
    #     finished = True

    status = "OK" if reward > 0 else "FAIL"
    print(f"  >>> REWARD: {reward} ({status}), steps={step_count}, finished={finished}")
    print(f"      tokens: in={total_input_tokens}, out={total_output_tokens}")
    sys.stdout.flush()

    return {
        "task_id": task_id, "seed": seed, "task": task_text,
        "reward": reward, "step_count": step_count, "finished": finished,
        "commands": commands_log, "finish_description": "",
        "elapsed_seconds": elapsed,
        "input_tokens": total_input_tokens, "output_tokens": total_output_tokens,
        "cost_usd": 0.0, "num_turns": step_count, "claude_output": "",
        "last_error": last_error,
    }
