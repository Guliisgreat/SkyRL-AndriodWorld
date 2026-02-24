"""
AndroidADBAgent - ADB command agent for the VERL pipeline.

Subclass of AndroidAgent; overrides prompt, action parsing, and step execution
to use raw ADB commands via step_adb() / step() for task control.
Requires env_handle to be RuntimeClient (supports step_adb).

Self-contained module: prompt template, safety validation, message building,
sliding window, parsing, and agent class are all in this single file.
"""

import copy
import io
import re
import base64
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from skyrl_agent.agents.android.android_agent import AndroidAgent


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

ADB_AGENT_PROMPT = """\
You are an Android automation agent. You control an Android device by issuing \
ADB shell commands. You see a screenshot of the current screen and the text \
output from your previous command.

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

## Screen Coordinates
The screen resolution is {width}x{height} pixels. Coordinates use absolute pixels.
(0,0) is the top-left corner. x increases rightward, y increases downward.

## Important Notes
- Prefer achieving the goal via direct shell commands or system APIs when \
possible; use tap/swipe only when no such command exists or when the task \
explicitly requires interacting with on-screen UI.
- Issue ONE command per step.
- After touch/input commands, check the next screenshot to verify the result.
- Use system query commands (dumpsys, settings get) to verify state when unsure.
- For text input: first tap the text field, then use `adb shell input text`.
- If return code is non-zero, try an alternative approach.

## User Instruction
{instruction}
"""

# ---------------------------------------------------------------------------
# Safety: whitelist / blocklist
# ---------------------------------------------------------------------------

ALLOWED_PREFIXES = [
    "adb shell input tap",
    "adb shell input swipe",
    "adb shell input text",
    "adb shell input keyevent",
    "adb shell am start",
    "adb shell am force-stop",
    "adb shell am broadcast",
    "adb shell pm list packages",
    "adb shell pm list features",
    "adb shell monkey",
    "adb shell dumpsys",
    "adb shell settings get",
    "adb shell settings put",
    "adb shell content query",
    "adb shell content insert",
    "adb shell content delete",
    "adb shell getprop",
    "adb shell ls",
    "adb shell cat",
    "adb shell uiautomator dump",
    "adb shell wm size",
    "adb shell wm density",
    "adb shell date",
    "adb shell whoami",
]

BLOCKED_PATTERNS = [
    r"\brm\s", r"\brm$", r"\brmdir\b",
    r"\breboot\b", r"\bshutdown\b",
    r"\bformat\b", r"\bmkfs\b", r"\bdd\b", r"\bwipe\b",
    r";\s*rm", r"&&\s*rm", r"\|\s*rm",
]

MAX_OUTPUT_CHARS = 2000
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
_HEADER_SIZE = 3  # system + task prompt + initial screenshot


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _numpy_to_base64(image: np.ndarray) -> str:
    """Convert numpy array to base64-encoded PNG data URI."""
    pil_image = Image.fromarray(image)
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def build_initial_messages(
    task_text: str,
    screenshot: np.ndarray,
    screen_resolution: Tuple[int, int],
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> List[Dict]:
    """Build initial conversation: system prompt, task prompt, first screenshot."""
    width, height = screen_resolution
    prompt_text = ADB_AGENT_PROMPT.format(
        width=width, height=height, instruction=task_text,
    )
    return [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "text", "text": prompt_text}]},
        {"role": "user", "content": [{
            "type": "image",
            "image": _numpy_to_base64(screenshot),
            "min_pixels": 3136,
            "max_pixels": 1003520,
        }]},
    ]


def _append_assistant(messages: List[Dict], response_str: str) -> List[Dict]:
    """Append the model's raw response as an assistant message."""
    messages.append({
        "role": "assistant",
        "content": [{"type": "text", "text": response_str}],
    })
    return messages


def _append_adb_observation(
    messages: List[Dict],
    screenshot: np.ndarray,
    command: str,
    command_output: str,
    error_text: str,
    return_code: int,
    screen_resolution: Tuple[int, int],
) -> List[Dict]:
    """Append terminal-style text feedback + screenshot after an ADB command."""
    width, height = screen_resolution
    output_text = (command_output or "").strip()
    if error_text:
        output_text = f"{output_text}\n{error_text}".strip()
    if len(output_text) > MAX_OUTPUT_CHARS:
        output_text = output_text[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    feedback = f"$ {command}\n{output_text}\nReturn code: {return_code}\nScreen: {width}x{height}"
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": feedback.strip()},
            {"type": "image", "image": _numpy_to_base64(screenshot),
             "min_pixels": 3136, "max_pixels": 1003520},
        ],
    })
    return messages


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------

def _apply_sliding_window(
    messages: List[Dict],
    max_history_steps: int = 10,
) -> List[Dict]:
    """Keep header (3 msgs) + last N turns (each turn = assistant + observation)."""
    if len(messages) <= _HEADER_SIZE:
        return list(messages)
    header = messages[:_HEADER_SIZE]
    body = messages[_HEADER_SIZE:]
    max_body = max_history_steps * 2
    if len(body) <= max_body:
        return list(messages)
    return header + body[-max_body:]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_adb_command(text: str) -> Tuple[str, str]:
    """
    Extract (command, thought) from model output.

    Expected: Thought: <reasoning>\\nCommand: <adb shell ... | FINISH | INFEASIBLE>
    Raises ValueError if no Command: field or command is empty.
    """
    thought = ""
    if "Thought:" in text:
        parts = text.split("Thought:", 1)
        if len(parts) > 1:
            thought_section = parts[1]
            if "Command:" in thought_section:
                thought = thought_section.split("Command:", 1)[0].strip()
            else:
                thought = thought_section.strip()

    if "Command:" not in text:
        raise ValueError(f"No 'Command:' found in model output: {text[:200]}")

    command_section = text.split("Command:")[-1].strip()
    command = command_section.split("\n")[0].strip()
    command = command.strip("`").strip()
    if not command:
        raise ValueError("Empty command after 'Command:'")
    return command, thought


def _parse_task_control(command: str) -> Dict:
    """Convert FINISH/INFEASIBLE string to action dict."""
    if command.startswith("FINISH"):
        m = re.search(r"content=['\"]?(.*?)['\"]?\)", command)
        return {"action_type": "status", "goal_status": "complete",
                "text": m.group(1) if m else ""}
    if command.startswith("INFEASIBLE"):
        m = re.search(r"content=['\"]?(.*?)['\"]?\)", command)
        return {"action_type": "status", "goal_status": "infeasible",
                "text": m.group(1) if m else ""}
    raise ValueError(f"Not a task control command: {command}")


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class AndroidADBAgent(AndroidAgent):
    """
    Android agent that generates raw ADB commands and uses step_adb() for execution.

    Calls env_handle.step_adb() for shell commands and env_handle.step() for
    FINISH/INFEASIBLE. env_handle must be RuntimeClient.
    """

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Format initial instruction with ADB prompt and first screenshot."""
        task_text = observation.get("task", "") or getattr(task, "goal", "")
        image = observation.get("image")
        if image is None:
            raise ValueError("ADB agent requires observation with 'image'")
        if not isinstance(image, np.ndarray):
            image = np.array(image)
        height, width = image.shape[0], image.shape[1]
        screen_resolution = (width, height)
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if template_messages and isinstance(template_messages[0].get("content"), str):
            system_prompt = template_messages[0]["content"]
        elif template_messages and isinstance(template_messages[0].get("content"), list):
            for block in template_messages[0]["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    system_prompt = block.get("text", system_prompt)
                    break
        return build_initial_messages(
            task_text,
            image,
            screen_resolution,
            system_prompt=system_prompt,
        )

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single step: generate -> parse -> execute via step_adb/step -> update."""
        self.state.step_count += 1
        max_history_steps = getattr(
            getattr(self.memory, "config", None), "max_steps", 10
        )

        selected_messages = _apply_sliding_window(
            self.state.messages, max_history_steps=max_history_steps,
        )

        inference_input_ids = self.prepare_input_ids(selected_messages)
        image_data = self.extract_images_for_inference(selected_messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        _cfg_max = sampling_params.pop("max_tokens", 2048)
        remaining = self.max_prompt_length - len(inference_input_ids)
        if remaining < _cfg_max:
            sampling_params["max_tokens"] = remaining

        result = await self.infer_engine.async_generate_ids(
            input_ids=inference_input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=image_data,
            return_token_ids=True,
        )
        response_str, stop_reason, _prompt_token_ids, response_token_ids = result

        # Accumulate token counts
        self.state.total_input_tokens += len(_prompt_token_ids)
        self.state.total_output_tokens += len(response_token_ids)

        if stop_reason == "length":
            self.state.messages = _append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        try:
            command, thought = _parse_adb_command(response_str)
            self.state.format_reward = 0.0
        except Exception as e:
            self.state.format_reward = -1.0
            command = "INFEASIBLE(content='parse error')"
            thought = str(e)[:200]

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

        image = observation.get("image") if observation else None
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        if isinstance(image, np.ndarray):
            h, w = image.shape[0], image.shape[1]
        else:
            w, h = 1080, 1920
        self.state.messages = _append_adb_observation(
            self.state.messages, image, command, command_output, "", 0, (w, h),
        )
        self.state.images.append(image)

        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None
