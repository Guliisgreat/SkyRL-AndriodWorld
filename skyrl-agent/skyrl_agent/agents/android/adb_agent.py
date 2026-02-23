"""
ADB Agent core module - prompt, parser, message building, and sliding window.

Provides the action space, output format, and message management for the ADB
command agent. The agent generates raw ADB shell commands instead of abstract
GUI actions; see docs/ADB_AGENT_PROMPT_DESIGN_GUIDE.md for details.

Functions exported (used by android_adb_agent.py):
    build_initial_messages  - system + task prompt + initial screenshot
    append_assistant        - add model response to conversation
    append_adb_observation  - add command output + screenshot observation
    apply_sliding_window    - keep header + last N turns
    parse_adb_command       - extract (command, thought) from model output
    parse_task_control      - convert FINISH/INFEASIBLE to action dict
"""

import io
import re
import base64
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image


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
# Whitelist / blocklist (shared with server_adb.py)
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
    system_prompt: str = "You are a helpful assistant.",
) -> List[Dict]:
    """
    Build the initial conversation: system prompt, task prompt, and first screenshot.

    Args:
        task_text: The task instruction (e.g. "Open the contacts app ...").
        screenshot: Initial screenshot as numpy array (H, W, 3).
        screen_resolution: (width, height) in pixels.
        system_prompt: System-level prompt text.

    Returns:
        List of OpenAI-format messages [system, user-text, user-image].
    """
    width, height = screen_resolution
    prompt_text = ADB_AGENT_PROMPT.format(
        width=width,
        height=height,
        instruction=task_text,
    )

    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": system_prompt}],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt_text}],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": _numpy_to_base64(screenshot),
                    "min_pixels": 3136,
                    "max_pixels": 1003520,
                }
            ],
        },
    ]


def append_assistant(
    messages: List[Dict],
    response_str: str,
) -> List[Dict]:
    """
    Append the model's raw response as an assistant message.

    Args:
        messages: Current conversation messages.
        response_str: Raw model output (e.g. "Thought: ... Command: ...").

    Returns:
        Updated messages list (same object, mutated).
    """
    messages.append({
        "role": "assistant",
        "content": [{"type": "text", "text": response_str}],
    })
    return messages


def append_adb_observation(
    messages: List[Dict],
    screenshot: np.ndarray,
    command: str,
    command_output: str,
    error_text: str,
    return_code: int,
    screen_resolution: Tuple[int, int],
) -> List[Dict]:
    """
    Append the observation after an ADB command: text feedback + new screenshot.

    The text feedback uses a terminal-style format:
        $ <command>
        <stdout/stderr>
        Return code: <code>
        Screen: <width>x<height>

    Args:
        messages: Current conversation messages.
        screenshot: New screenshot as numpy array.
        command: The ADB command that was executed.
        command_output: stdout + stderr from the command.
        error_text: Additional error text (empty string if none).
        return_code: Process return code (0 = success).
        screen_resolution: (width, height) in pixels.

    Returns:
        Updated messages list (same object, mutated).
    """
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
            {
                "type": "image",
                "image": _numpy_to_base64(screenshot),
                "min_pixels": 3136,
                "max_pixels": 1003520,
            },
        ],
    })
    return messages


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------

# Header = system + task prompt + initial screenshot (first 3 messages)
_HEADER_SIZE = 3


def apply_sliding_window(
    messages: List[Dict],
    max_history_steps: int = 10,
) -> List[Dict]:
    """
    Keep the header (system + task prompt + screenshot) and the last N turns.

    Each turn = 1 assistant message + 1 user observation = 2 messages.
    So we keep header + last (max_history_steps * 2) messages from the body.

    Args:
        messages: Full conversation messages.
        max_history_steps: Maximum number of agent steps (turns) to keep.

    Returns:
        Subset of messages for inference.
    """
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

def parse_adb_command(text: str) -> Tuple[str, str]:
    """
    Extract (command, thought) from the model's raw output.

    Expected format:
        Thought: <reasoning>
        Command: <adb shell ... | FINISH(...) | INFEASIBLE(...)>

    Args:
        text: Raw model output string.

    Returns:
        (command, thought) tuple.

    Raises:
        ValueError: If no Command: field is found or command is empty.
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

    if not command:
        raise ValueError("Empty command after 'Command:'")

    return command, thought


def parse_task_control(command: str) -> Dict:
    """
    Convert FINISH/INFEASIBLE command string to action dict.

    Args:
        command: e.g. "FINISH(content='Task completed')" or
                 "INFEASIBLE(content='Cannot find app')".

    Returns:
        Action dict with action_type, goal_status, and text fields.

    Raises:
        ValueError: If command is not a valid task control action.
    """
    if command.startswith("FINISH"):
        m = re.search(r"content=['\"]?(.*?)['\"]?\)", command)
        return {
            "action_type": "status",
            "goal_status": "complete",
            "text": m.group(1) if m else "",
        }
    if command.startswith("INFEASIBLE"):
        m = re.search(r"content=['\"]?(.*?)['\"]?\)", command)
        return {
            "action_type": "status",
            "goal_status": "infeasible",
            "text": m.group(1) if m else "",
        }
    raise ValueError(f"Not a task control command: {command}")
