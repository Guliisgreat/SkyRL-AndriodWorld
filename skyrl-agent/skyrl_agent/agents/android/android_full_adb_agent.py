"""
AndroidFullADBAgent - Text-only ADB agent using a11y tree as input.

Subclass of AndroidAgent; uses the accessibility tree (ui_elements) as the sole
observation instead of screenshots. Generates raw ADB commands via step_adb().
This makes it a pure text-in / text-out agent compatible with non-VLM models.

Reuses parsing and safety validation from android_adb_agent.py.
"""

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from skyrl_agent.agents.android.android_agent import AndroidAgent
from skyrl_agent.agents.android.android_adb_agent import (
    _parse_adb_command,
    _parse_task_control,
    _apply_sliding_window,
    _append_assistant,
    MAX_OUTPUT_CHARS,
    DEFAULT_SYSTEM_PROMPT,
    _HEADER_SIZE,
)


# ---------------------------------------------------------------------------
# Prompt template (text-only, no screenshot references)
# ---------------------------------------------------------------------------

FULL_ADB_AGENT_PROMPT = """\
You are an Android automation agent. You control an Android device by issuing \
ADB shell commands. Instead of a screenshot you receive a structured \
accessibility tree (a11y tree) describing every UI element on screen, \
including its type, text, bounding-box coordinates, and interactive flags.

## Output Format
Respond with exactly two fields:
Thought: <your reasoning about what to do next>
Command: <single ADB shell command OR task control action>

## Available Commands

### Touch & Input
- `adb shell input tap <x> <y>` -- tap at pixel coordinates
- `adb shell input swipe <x1> <y1> <x2> <y2> [duration_ms]` -- swipe gesture
- `adb shell input text '<text>'` -- type text (must tap field first)
- `adb shell input keyevent <keycode>` -- press a key
  Common keycodes: KEYCODE_HOME (3), KEYCODE_BACK (4), KEYCODE_ENTER (66), \
KEYCODE_DEL (67), KEYCODE_SEARCH (84), KEYCODE_TAB (61)

### App Management
- `adb shell am start -n <package/activity>` -- start an activity
- `adb shell am start -a android.intent.action.VIEW -d <uri>` -- open a URI
- `adb shell am force-stop <package>` -- force stop an app
- `adb shell am broadcast -a <action>` -- send a broadcast
- `adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1` -- launch app
- `adb shell pm list packages` -- list installed packages

### System Queries
- `adb shell dumpsys <service>` -- dump system service info
- `adb shell settings get <namespace> <key>` -- get a system setting
- `adb shell settings put <namespace> <key> <value>` -- set a system setting
- `adb shell content query --uri <uri>` -- query content provider
- `adb shell content insert --uri <uri> --bind <col>:<type>:<val>` -- insert content
- `adb shell content delete --uri <uri>` -- delete content
- `adb shell getprop <property>` -- get system property

### File System (read-only)
- `adb shell ls <path>` -- list files
- `adb shell cat <path>` -- read file contents

### UI Inspection
- `adb shell uiautomator dump /dev/tty` -- dump UI hierarchy (XML)

### Display Info
- `adb shell wm size` -- get screen size
- `adb shell wm density` -- get display density
- `adb shell date` -- get current date/time
- `adb shell whoami` -- get current user

### Task Control
- `FINISH(content='<result description>')` -- task completed successfully
- `INFEASIBLE(content='<reason>')` -- task cannot be completed

## Reading the A11y Tree
Each line represents a UI element:
  [index] ClassName "visible text" (x_min,y_min)-(x_max,y_max) flags
Flags include: clickable, checkable, checked, editable.
Use the bounding-box centre for tap coordinates: x=(x_min+x_max)/2, y=(y_min+y_max)/2.

## Screen Coordinates
The screen resolution is {width}x{height} pixels. Coordinates use absolute pixels.
(0,0) is the top-left corner. x increases rightward, y increases downward.

## Important Notes
- Prefer achieving the goal via direct shell commands or system APIs when \
possible; use tap/swipe only when no such command exists or when the task \
explicitly requires interacting with on-screen UI.
- Issue ONE command per step.
- After touch/input commands, check the next a11y tree to verify the result.
- Use system query commands (dumpsys, settings get) to verify state when unsure.
- For text input: first tap the text field, then use `adb shell input text`.
- If return code is non-zero, try an alternative approach.

## User Instruction
{instruction}
"""


# ---------------------------------------------------------------------------
# A11y tree formatting
# ---------------------------------------------------------------------------

def format_ui_elements(ui_elements: List[Dict]) -> str:
    """Convert ui_elements list from the container into compact text.

    Each element becomes one line:
      [idx] ClassName "text" (x_min,y_min)-(x_max,y_max) flags

    Elements with no useful information (no text, no content_description,
    not clickable, not checkable) are omitted to save tokens.
    """
    if not ui_elements:
        return "(empty screen)"

    lines: List[str] = []
    for idx, el in enumerate(ui_elements):
        cls = (el.get("class_name") or "View").rsplit(".", 1)[-1]

        text = el.get("text") or ""
        content_desc = el.get("content_description") or ""
        hint = el.get("hint_text") or ""
        label = text or content_desc or hint

        bbox = el.get("bbox_pixels")
        if bbox and isinstance(bbox, dict):
            coords = (
                f"({bbox.get('x_min', 0)},{bbox.get('y_min', 0)})"
                f"-({bbox.get('x_max', 0)},{bbox.get('y_max', 0)})"
            )
        else:
            coords = ""

        flags: List[str] = []
        if el.get("is_clickable"):
            flags.append("clickable")
        if el.get("is_checkable"):
            flags.append("checkable")
        if el.get("is_checked"):
            flags.append("checked")
        if el.get("is_editable") or cls in ("EditText",):
            flags.append("editable")

        has_info = label or flags
        if not has_info and not el.get("is_clickable"):
            continue

        parts = [f"[{idx}]", cls]
        if label:
            parts.append(f'"{label}"')
        if coords:
            parts.append(coords)
        if flags:
            parts.append(" ".join(flags))

        lines.append(" ".join(parts))

    return "\n".join(lines) if lines else "(no interactive elements)"


# ---------------------------------------------------------------------------
# Message building (text-only, no images)
# ---------------------------------------------------------------------------

def _build_initial_messages(
    task_text: str,
    ui_elements: List[Dict],
    screen_resolution: Tuple[int, int],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> List[Dict]:
    """Build initial conversation: system prompt, task prompt, first a11y tree."""
    width, height = screen_resolution
    prompt_text = FULL_ADB_AGENT_PROMPT.format(
        width=width, height=height, instruction=task_text,
    )
    tree_text = format_ui_elements(ui_elements)
    return [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "text", "text": prompt_text}]},
        {"role": "user", "content": [{"type": "text", "text": f"## Current Screen (A11y Tree)\n{tree_text}"}]},
    ]


def _append_text_observation(
    messages: List[Dict],
    ui_elements: List[Dict],
    command: str,
    command_output: str,
    error_text: str,
    return_code: int,
    screen_resolution: Tuple[int, int],
) -> List[Dict]:
    """Append text-only feedback (command output + a11y tree) after an ADB command."""
    width, height = screen_resolution
    output_text = (command_output or "").strip()
    if error_text:
        output_text = f"{output_text}\n{error_text}".strip()
    if len(output_text) > MAX_OUTPUT_CHARS:
        output_text = output_text[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    tree_text = format_ui_elements(ui_elements)
    feedback = (
        f"$ {command}\n{output_text}\nReturn code: {return_code}\n"
        f"Screen: {width}x{height}\n\n## Current Screen (A11y Tree)\n{tree_text}"
    )
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": feedback.strip()}],
    })
    return messages


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class AndroidFullADBAgent(AndroidAgent):
    """
    Text-only ADB agent using accessibility tree instead of screenshots.

    Calls env_handle.step_adb() for shell commands and env_handle.step() for
    FINISH/INFEASIBLE. env_handle must be RuntimeClient.
    """

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Format initial instruction with a11y tree (no image)."""
        task_text = observation.get("task", "") or getattr(task, "goal", "")
        ui_elements = observation.get("ui_elements", [])

        image = observation.get("image")
        if image is not None and isinstance(image, np.ndarray):
            height, width = image.shape[0], image.shape[1]
        else:
            width, height = 1080, 2400

        system_prompt = DEFAULT_SYSTEM_PROMPT
        if template_messages and isinstance(template_messages[0].get("content"), str):
            system_prompt = template_messages[0]["content"]
        elif template_messages and isinstance(template_messages[0].get("content"), list):
            for block in template_messages[0]["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    system_prompt = block.get("text", system_prompt)
                    break

        return _build_initial_messages(
            task_text,
            ui_elements,
            (width, height),
            system_prompt=system_prompt,
        )

    def extract_images_for_inference(self, messages: List[Dict]) -> Optional[List[Any]]:
        """No images -- pure text agent."""
        return None

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single step: generate -> parse -> execute via step_adb/step -> update (text-only)."""
        self.state.step_count += 1
        max_history_steps = getattr(
            getattr(self.memory, "config", None), "max_steps", 10
        )

        selected_messages = _apply_sliding_window(
            self.state.messages, max_history_steps=max_history_steps,
        )

        inference_input_ids = self.prepare_input_ids(selected_messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        _cfg_max = sampling_params.pop("max_tokens", 2048)
        remaining = self.max_prompt_length - len(inference_input_ids)
        if remaining < _cfg_max:
            sampling_params["max_tokens"] = remaining

        result = await self.infer_engine.async_generate_ids(
            input_ids=inference_input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=None,
            return_token_ids=True,
        )
        response_str, stop_reason, _prompt_token_ids, response_token_ids = result

        if stop_reason == "length":
            self.state.messages = _append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        try:
            command, thought = _parse_adb_command(response_str)
            self.state.format_reward = 0.0
        except Exception:
            self.state.format_reward = -1.0
            command = "INFEASIBLE(content='parse error')"
            thought = f"parse error: {response_str[:200]}"

        if command.startswith("FINISH") or command.startswith("INFEASIBLE"):
            action_dict = _parse_task_control(command)
            payload = {"action": action_dict, "thought": thought}
            observation, reward, terminated, truncated, info = await self.env_handle.step(
                payload
            )
            command_output = ""
        else:
            payload = {"command": command, "thought": thought}
            (
                observation,
                command_output,
                reward,
                terminated,
                truncated,
                info,
            ) = await self.env_handle.step_adb(payload)

        self.state.reward = reward
        self.state.messages = _append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "FINISH" if terminated else "TRUNCATED", self.state.reward

        ui_elements = observation.get("ui_elements", []) if observation else []
        image = observation.get("image") if observation else None
        if image is not None and isinstance(image, np.ndarray):
            h, w = image.shape[0], image.shape[1]
        else:
            w, h = 1080, 2400

        self.state.messages = _append_text_observation(
            self.state.messages, ui_elements, command, command_output, "", 0, (w, h),
        )

        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None
