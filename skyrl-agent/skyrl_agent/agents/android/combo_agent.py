"""
AndroidAPIComboAgent - GPT-friendly agent using both screenshot and a11y tree.

Subclass of AndroidAPIScreenAgent; adds the accessibility tree alongside
screenshots for richer context. Uses the same JSON action format and
pixel-based coordinates as the parent.

Shares runner (AndroidAgentRunner) and trajectory (AndroidTrajectory).
"""

import copy
import os
import time
from typing import List, Dict, Any, Tuple, Optional

import numpy as np

from skyrl_agent.agents.android.screen_agent import (
    AndroidAPIScreenAgent,
    parse_gpt_gui_action,
    DEFAULT_SCREEN_WIDTH,
    DEFAULT_SCREEN_HEIGHT,
)
from skyrl_agent.agents.android.tree_adb_agent import format_ui_elements
from .utils import init_messages, load_content, numpy_to_base64

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

API_COMBO_AGENT_PROMPT = """\
You are a mobile device agent. You can see the device screen (screenshot) AND \
a structured accessibility tree (a11y tree) describing every UI element. Use \
both sources to understand the screen and complete the task.

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

## Reading the A11y Tree
Each line represents a UI element:
  [index] ClassName "visible text" (x_min,y_min)-(x_max,y_max) flags
Flags include: clickable, checkable, checked, editable.
Use the bounding-box centre for tap coordinates: x=(x_min+x_max)/2, y=(y_min+y_max)/2.

## Guidelines
- Use the screenshot for visual context and the a11y tree for precise element locations.
- Prefer a11y tree coordinates over guessing from the screenshot.
- Estimate tap coordinates at the **center** of the target element.
- To scroll a list **down**, swipe from a lower point to a higher point (e.g. start_y=1800, end_y=600).
- Tap a text field before using `type`.
- Work step by step; verify each action's effect in the next screenshot.

## Task
{instruction}"""


class AndroidAPIComboAgent(AndroidAPIScreenAgent):
    """
    GPT-friendly agent combining screenshot and a11y tree inputs.

    Extends AndroidAPIScreenAgent by injecting a formatted accessibility tree
    into each observation message alongside the screenshot.
    """

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Format initial instruction with combo prompt, screenshot, and a11y tree."""
        if observation and "image" in observation:
            img = observation["image"]
            if isinstance(img, np.ndarray) and img.ndim >= 2:
                self.screen_height, self.screen_width = img.shape[:2]

        def prompt_formatter(task_instruction: str) -> str:
            return API_COMBO_AGENT_PROMPT.format(
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

        ui_elements = observation.get("ui_elements", []) if observation else []
        tree_text = format_ui_elements(ui_elements)
        observation_messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"## Current Screen (A11y Tree)\n{tree_text}"}],
        })

        return template_messages + observation_messages

    # ------------------------------------------------------------------
    # Observation: append screenshot + a11y tree
    # ------------------------------------------------------------------

    def append_observation(self, messages: List[Dict], image, ui_elements=None) -> List[Dict]:
        """Append screenshot followed by a11y tree text."""
        messages = super().append_observation(messages, image)

        tree_text = format_ui_elements(ui_elements) if ui_elements else "(no a11y tree)"
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"## Current Screen (A11y Tree)\n{tree_text}"}],
        })
        return messages

    # ------------------------------------------------------------------
    # Step (override to pass ui_elements through)
    # ------------------------------------------------------------------

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single step with screenshot + a11y tree context."""
        self.state.step_count += 1
        print(
            f"[APIComboAgent Step {self.state.step_count}] "
            f"instance={self.state.instance_id} traj={self.state.trajectory_id}"
        )

        selected_messages = self.memory.get_inference_messages(self.state.messages)
        inference_input_ids = self.prepare_input_ids(selected_messages)
        image_data = self.extract_images_for_inference(selected_messages)

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
            print(f"[APIComboAgent] Stopping reason: {stop_reason}. Stopping agent.")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        try:
            action_dict, thought = parse_gpt_gui_action(
                response_str, self.screen_width, self.screen_height
            )
            self.state.format_reward = 0.0
        except Exception as e:
            print(f"[APIComboAgent] Parse error: {e}")
            print(f"[APIComboAgent] Raw response: {response_str[:500]}")
            self.state.format_reward = -1.0
            action_dict = {"action_type": "status", "goal_status": "infeasible"}
            thought = f"Parse error: {response_str[:200]}"

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
        ui_elements = output.get("ui_elements", [])
        a11y_tree_text = format_ui_elements(ui_elements) if ui_elements else None

        self.state.step_records.append({
            "step_idx": self.state.step_count,
            "thought": thought,
            "raw_response": response_str,
            "action_type": action_dict.get("action_type", "unknown"),
            "action_params": {k: v for k, v in action_dict.items() if k != "action_type"},
            "command_output": None,
            "a11y_tree": a11y_tree_text,
            "screenshot_idx": len(self.state.images),
            "input_tokens": len(_prompt_token_ids),
            "output_tokens": len(response_token_ids),
        })

        self.state.messages = self.append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            finish_reason = "FINISH" if terminated else "TRUNCATED"
            return True, finish_reason, self.state.reward

        image = output.get("image")
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        if isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]

        self.state.messages = self.append_observation(
            self.state.messages, image, ui_elements=ui_elements
        )
        self.state.images.append(image)

        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None
