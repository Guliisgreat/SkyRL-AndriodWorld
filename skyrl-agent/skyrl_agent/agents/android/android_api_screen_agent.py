"""
AndroidAPIScreenAgent - GPT-friendly GUI agent using screenshots + JSON actions.

Same input/output space as AndroidAgent (screenshot in, screen interaction out),
but uses a GPT-compatible prompt with absolute pixel coordinates and JSON action
format instead of UI-TARS box-token notation.

Shares runner (AndroidAgentRunner) and trajectory (AndroidTrajectory) with
the UI-TARS agent -- only the prompt and parser differ.
"""

import copy
import json
import os
import re
import time
from typing import List, Dict, Any, Tuple, Optional

import numpy as np

from skyrl_agent.agents.android.android_agent import AndroidAgent, TrajectoryState
from .android_utils import init_messages, load_content, numpy_to_base64

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

# Default screen dimensions (standard Android emulator); overridden at runtime
# from the initial screenshot if available.
DEFAULT_SCREEN_WIDTH = 1080
DEFAULT_SCREEN_HEIGHT = 2400

GPT_GUI_AGENT_PROMPT = """\
You are a mobile device agent. You can see the device screen and interact with it to complete a task.

## Screen
Resolution: {width} x {height} pixels.
Coordinates use pixels: x ranges from 0 (left) to {width} (right), y from 0 (top) to {height} (bottom).

## Response Format
Reply with **exactly one** JSON object (no extra text):
```json
{{
  "thought": "your reasoning",
  "action": "action_name",
  "params": {{...}}
}}
```

## Available Actions
| Action | Params | Description |
|---|---|---|
| tap | {{"x": int, "y": int}} | Tap a point on screen |
| long_press | {{"x": int, "y": int}} | Long-press a point |
| swipe | {{"start_x": int, "start_y": int, "end_x": int, "end_y": int}} | Swipe between two points |
| type | {{"text": "..."}} | Type text into the focused field. Use "\\n" to press Enter. |
| press_home | {{}} | Press the Home button |
| press_back | {{}} | Press the Back button |
| open_app | {{"app_name": "..."}} | Open an installed application |
| wait | {{}} | Wait for the screen to update |
| finished | {{"success": true}} | Mark task as complete |
| answer | {{"text": "..."}} | Answer a question |

## Guidelines
- Carefully examine the screenshot to locate UI elements before acting.
- Estimate tap coordinates at the **center** of the target element.
- To scroll a list **down**, swipe from a lower point to a higher point (e.g. start_y=1800, end_y=600).
- Tap a text field before using `type`.
- Work step by step; verify each action's effect in the next screenshot.

## Task
{instruction}"""


def parse_gpt_gui_action(
    text: str,
    screen_width: int = DEFAULT_SCREEN_WIDTH,
    screen_height: int = DEFAULT_SCREEN_HEIGHT,
) -> Tuple[Dict[str, Any], str]:
    """
    Parse a GPT JSON response into an AndroidEnvTool action_dict.

    Handles markdown code fences and minor formatting issues.

    Returns:
        (action_dict, thought_str)
    """
    # Strip markdown code fences if present
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    # Try to find the outermost JSON object
    json_match = re.search(r"\{[\s\S]*\}", cleaned)
    if not json_match:
        raise ValueError(f"No JSON object found in response: {text[:300]}")

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in response: {exc} — {text[:300]}") from exc

    thought = str(data.get("thought", ""))
    action_name = str(data.get("action", "")).lower().strip()
    params = data.get("params") or {}

    def _norm_x(val):
        return max(0.0, min(1.0, float(val) / screen_width))

    def _norm_y(val):
        return max(0.0, min(1.0, float(val) / screen_height))

    if action_name == "tap":
        action_dict = {
            "action_type": "click",
            "touch_point": [_norm_x(params["x"]), _norm_y(params["y"])],
        }
    elif action_name == "long_press":
        action_dict = {
            "action_type": "long_press",
            "touch_point": [_norm_x(params["x"]), _norm_y(params["y"])],
        }
    elif action_name == "swipe":
        sx, sy = float(params["start_x"]), float(params["start_y"])
        ex, ey = float(params["end_x"]), float(params["end_y"])
        dx = sx - ex
        dy = sy - ey
        direction = (
            ("right" if dx > 0 else "left")
            if abs(dx) > abs(dy)
            else ("down" if dy > 0 else "up")
        )
        action_dict = {"action_type": "scroll", "direction": direction}
    elif action_name == "type":
        action_dict = {"action_type": "input_text", "text": str(params.get("text", ""))}
    elif action_name == "press_home":
        action_dict = {"action_type": "navigate_home"}
    elif action_name == "press_back":
        action_dict = {"action_type": "navigate_back"}
    elif action_name == "open_app":
        action_dict = {
            "action_type": "open_app",
            "app_name": str(params.get("app_name", "")),
        }
    elif action_name == "wait":
        action_dict = {"action_type": "wait"}
    elif action_name == "finished":
        action_dict = {"action_type": "status", "goal_status": "complete"}
    elif action_name == "answer":
        action_dict = {"action_type": "answer", "text": str(params.get("text", ""))}
    else:
        raise ValueError(f"Unknown action '{action_name}' in response")

    return action_dict, thought


class AndroidAPIScreenAgent(AndroidAgent):
    """
    GPT-friendly GUI agent.

    Identical to AndroidAgent except for prompt template and action parser.
    Uses absolute pixel coordinates in a JSON action format that works well
    with general-purpose LLMs (GPT-4o, GPT-5, Claude, etc.).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.screen_width = DEFAULT_SCREEN_WIDTH
        self.screen_height = DEFAULT_SCREEN_HEIGHT

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Format initial instruction using the GPT-friendly prompt."""
        # Try to get screen dimensions from the initial screenshot
        if observation and "image" in observation:
            img = observation["image"]
            if isinstance(img, np.ndarray) and img.ndim >= 2:
                self.screen_height, self.screen_width = img.shape[:2]

        def prompt_formatter(task_instruction: str) -> str:
            return GPT_GUI_AGENT_PROMPT.format(
                width=self.screen_width,
                height=self.screen_height,
                instruction=task_instruction,
            )

        observation_messages = task.format_observation(
            observation,
            prompt_formatter=prompt_formatter,
            min_pixels=self.min_pixels,
            max_pixels=self.max_pixels,
        )

        return template_messages + observation_messages

    # ------------------------------------------------------------------
    # Step (override only to swap the parser)
    # ------------------------------------------------------------------

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single step with GPT JSON parsing instead of UI-TARS parsing."""
        self.state.step_count += 1
        print(
            f"[GPTGUIAgent Step {self.state.step_count}] "
            f"instance={self.state.instance_id} traj={self.state.trajectory_id}"
        )

        # 1. Select messages for LLM (sliding window)
        selected_messages = self.memory.get_inference_messages(self.state.messages)

        # 2. Tokenize
        inference_input_ids = self.prepare_input_ids(selected_messages)

        # 2b. Extract images for VLM inference
        image_data = self.extract_images_for_inference(selected_messages)

        # 3. Generate response
        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params.pop("max_tokens", None)

        if DEBUG_TIMING:
            num_images = len(image_data) if image_data else 0
            print(
                f"[Context] step={self.state.step_count} "
                f"tokens={len(inference_input_ids)} images={num_images}"
            )
            vllm_start = time.perf_counter()

        result = await self.infer_engine.async_generate_ids(
            input_ids=inference_input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=image_data,
            return_token_ids=True,
            messages=selected_messages,
        )

        response_str, stop_reason, _prompt_token_ids, response_token_ids = result

        self.state.total_input_tokens += len(_prompt_token_ids)
        self.state.total_output_tokens += len(response_token_ids)

        if DEBUG_TIMING:
            vllm_elapsed = time.perf_counter() - vllm_start

        if stop_reason == "length":
            print(f"[GPTGUIAgent] Stopping reason: {stop_reason}. Stopping agent.")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        # 4. Parse action  ----  GPT JSON parser instead of UI-TARS parser
        try:
            action_dict, thought = parse_gpt_gui_action(
                response_str, self.screen_width, self.screen_height
            )
            self.state.format_reward = 0.0
        except Exception as e:
            print(f"[GPTGUIAgent] Parse error: {e}")
            print(f"[GPTGUIAgent] Raw response: {response_str[:500]}")
            self.state.format_reward = -1.0
            action_dict = {"action_type": "status", "goal_status": "infeasible"}
            thought = f"Parse error: {response_str[:200]}"

        # 5. Execute via AndroidEnvTool
        tool = self.tools["android_env"]

        if DEBUG_TIMING:
            container_start = time.perf_counter()

        output = await tool.async_call(
            action_dict,
            env_handle=self.env_handle,
            thought=thought,
        )

        if DEBUG_TIMING:
            container_elapsed = time.perf_counter() - container_start
            print(
                f"[Timing] step={self.state.step_count} "
                f"vLLM={vllm_elapsed:.2f}s container={container_elapsed:.2f}s "
                f"total={vllm_elapsed + container_elapsed:.2f}s"
            )

        self.state.reward = output.get("reward", 0.0)
        terminated = output.get("terminated", False)
        truncated = output.get("truncated", False)

        # Record step for trajectory saving
        self.state.step_records.append({
            "step_idx": self.state.step_count,
            "thought": thought,
            "raw_response": response_str,
            "action_type": action_dict.get("action_type", "unknown"),
            "action_params": {k: v for k, v in action_dict.items() if k != "action_type"},
            "command_output": None,
            "a11y_tree": None,
            "screenshot_idx": len(self.state.images),
            "input_tokens": len(_prompt_token_ids),
            "output_tokens": len(response_token_ids),
        })

        # 6. Update messages
        self.state.messages = self.append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            finish_reason = "FINISH" if terminated else "TRUNCATED"
            return True, finish_reason, self.state.reward

        # 7. Append new observation
        image = output.get("image")
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        # Update screen dimensions from latest screenshot
        if isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]

        self.state.messages = self.append_observation(self.state.messages, image)
        self.state.images.append(image)

        # 8. Training accumulator check
        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None
