"""
AndroidT3AADBAgent - T3A prompt/observation framework with ADB command action space.

Combines:
  - T3A's rich M3A-style UI element descriptions, step summarization, and history
  - ADB shell commands as the action space (executed via step_adb)

Key features:
  - Text-only: observation = goal + history + UI element list (with bbox_pixels + tap_target)
  - ADB commands: tap, swipe, input text, keyevent, app management, system queries
  - Mandatory summarization: second LLM call with before/after UI + command output
  - Full prompt rebuild each step (no sliding window; summarization compresses context)

Optimizations over baseline:
  - Pre-computed tap_target center coordinates in UI element descriptions
  - Lenient answer/FINISH/INFEASIBLE parsing with regex fallbacks
  - Streamlined prompt with focused ADB command set
  - Explicit finish/answer guidance to increase finish ratio
"""

import copy
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from skyrl_agent.agents.android.base import AndroidAgent
from skyrl_agent.agents.android.m3a_agent import (
    validate_ui_element,
)
from skyrl_agent.agents.android.screen_adb_agent import (
    _parse_task_control,
    _normalize_adb_command,
    MAX_OUTPUT_CHARS,
)

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

DEFAULT_SCREEN_WIDTH = 1080
DEFAULT_SCREEN_HEIGHT = 2400


# ---------------------------------------------------------------------------
# UI description with pre-computed tap targets
# ---------------------------------------------------------------------------

def _generate_ui_element_with_tap_target(el: Dict, index: int) -> str:
    """Produce a UI element description with pre-computed tap_target center.

    Adds "tap_target": [cx, cy] so the model doesn't need to compute
    center coordinates from bounding boxes (reduces arithmetic errors).
    """
    desc = f'UI element {index}: {{"index": {index}, '
    cn = el.get("class_name") or ""
    if cn:
        desc += f'"class_name": "{cn}", '
    rid = el.get("resource_id") or ""
    if rid:
        desc += f'"resource_id": "{rid}", '
    text = el.get("text") or ""
    if text:
        desc += f'"text": "{text}", '
    cd = el.get("content_description") or ""
    if cd:
        desc += f'"content_description": "{cd}", '
    ht = el.get("hint_text") or ""
    if ht:
        desc += f'"hint_text": "{ht}", '
    bbox = el.get("bbox_pixels")
    if bbox and isinstance(bbox, dict):
        x_min = bbox.get("x_min", 0)
        x_max = bbox.get("x_max", 0)
        y_min = bbox.get("y_min", 0)
        y_max = bbox.get("y_max", 0)
        cx = (x_min + x_max) // 2
        cy = (y_min + y_max) // 2
        desc += f'"tap_target": [{cx}, {cy}], '
        desc += (
            f'"bbox_pixels": {{"x_min": {x_min}, '
            f'"x_max": {x_max}, '
            f'"y_min": {y_min}, '
            f'"y_max": {y_max}}}, '
        )
    desc += f'"is_clickable": {"True" if el.get("is_clickable") else "False"}, '
    desc += f'"is_long_clickable": {"True" if el.get("is_long_clickable") else "False"}, '
    desc += f'"is_editable": {"True" if el.get("is_editable") else "False"}, '
    if el.get("is_scrollable"):
        desc += '"is_scrollable": True, '
    if el.get("is_focusable"):
        desc += '"is_focusable": True, '
    desc += f'"is_selected": {"True" if el.get("is_selected") else "False"}, '
    desc += f'"is_checked": {"True" if el.get("is_checked") else "False"}'
    return desc + "}"


def generate_ui_elements_with_tap_targets(
    ui_elements: List[Dict], screen_size: Tuple[int, int],
) -> str:
    """Generate UI element descriptions with pre-computed tap_target centers."""
    lines: List[str] = []
    for index, el in enumerate(ui_elements):
        if validate_ui_element(el, screen_size):
            lines.append(_generate_ui_element_with_tap_target(el, index))
    return "\n".join(lines) if lines else "Not available"


# ---------------------------------------------------------------------------
# T3A-ADB prompt templates (optimized)
# ---------------------------------------------------------------------------

PROMPT_PREFIX = (
    'You are an agent who can operate an Android phone on behalf of a user.'
    " Based on user's goal/request, you may\n"
    '- Answer back if the request/goal is a question (or a chat message), like'
    ' user asks "What is my schedule for today?".\n'
    '- Complete some tasks described in the requests/goals by performing'
    ' actions (step by step) on the phone.\n\n'
    'When given a user request, you will try to complete it step by step. At'
    ' each step, a list of descriptions for most UI elements on the'
    ' current screen will be given to you. Each element has a pre-computed'
    ' "tap_target": [x, y] center coordinate that you can directly use'
    ' with `adb shell input tap x y`.\n\n'
    '## Available Actions\n\n'
    '### Touch & Input\n'
    '- `adb shell input tap <x> <y>` -- tap at coordinates (use tap_target from UI element)\n'
    '- `adb shell input swipe <x1> <y1> <x2> <y2> [duration_ms]` -- swipe gesture\n'
    '- `adb shell input text \'<text>\'` -- type text (must tap field first)\n'
    '- `adb shell input keyevent <keycode>` -- press a key\n'
    '  Common keycodes: KEYCODE_HOME (3), KEYCODE_BACK (4), KEYCODE_ENTER (66),'
    ' KEYCODE_DEL (67), KEYCODE_SEARCH (84), KEYCODE_TAB (61)\n\n'
    '### App & System\n'
    '- `adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1` -- launch app\n'
    '- `adb shell am start -a android.intent.action.VIEW -d <uri>` -- open a URI\n'
    '- `adb shell am force-stop <package>` -- force stop an app\n'
    '- `adb shell settings get/put <namespace> <key> [value]` -- get/set settings\n'
    '- `adb shell content query/insert/delete --uri <uri>` -- content provider operations\n'
    '- `adb shell date` -- get current date/time\n\n'
    '### File Operations\n'
    '- `adb shell ls/cat/rm/mv/cp/mkdir <path>` -- file system commands\n'
    '- `adb shell sh -c \'<script>\'` -- run a shell script (supports &&, pipes, redirection)\n'
    '  Example: `adb shell sh -c \'mkdir -p /sdcard/Foo && mv /sdcard/a.txt /sdcard/Foo/\'`\n'
    '  Example: `adb shell sh -c \'echo "hello" > /sdcard/note.txt\'`\n\n'
    '### Task Completion (IMPORTANT - you MUST use one of these to finish)\n'
    '- `FINISH(content=\'<result description>\')` -- task completed successfully\n'
    '- `INFEASIBLE(content=\'<reason>\')` -- task cannot be completed\n'
    '- `answer(content=\'<answer text>\')` -- answer a question and complete the task\n'
    '  Alternative formats also accepted: `answer(<answer text>)` or'
    ' `answer: <answer text>`\n'
)

GUIDANCE = (
    'Here are some useful guidelines you need to follow:\n\n'
    '## Completing Tasks\n'
    '- CRITICAL: You MUST end every task by calling FINISH(), INFEASIBLE(),'
    ' or answer(). If you have gathered the information or performed the'
    ' action, call the appropriate completion command immediately.\n'
    '- For questions: use `answer(content=\'<your answer>\')` to provide the'
    ' answer, then the task is complete. Do NOT just display the answer on'
    ' screen without calling answer().\n'
    '- If the desired state is already achieved, call'
    ' `FINISH(content=\'already done\')` right away.\n\n'
    '## Tapping UI Elements\n'
    '- Each UI element has a "tap_target": [x, y] field with pre-computed'
    ' center coordinates. Use these directly:'
    ' `adb shell input tap <x> <y>`.\n'
    '- Example: if element shows "tap_target": [540, 1200], use'
    ' `adb shell input tap 540 1200`.\n\n'
    '## General\n'
    '- Pick the easiest approach. If something fails, try an alternative.\n'
    '- Use `adb shell input text` to type instead of tapping keys one by one.\n'
    '- To scroll down: `adb shell input swipe 540 1800 540 600`.\n'
    '- To scroll up: `adb shell input swipe 540 600 540 1800`.\n'
    '- Issue ONE command per step.\n'
    '- Prefer shell commands (rm, mv, content query, content insert, settings)'
    ' when they can accomplish the goal more directly than UI navigation.\n'
    '- For file operations, use `adb shell sh -c \'...\'` to chain commands.\n'
    '- To clear text: tap field, then `adb shell input keyevent KEYCODE_CTRL_A`'
    ' followed by `adb shell input keyevent KEYCODE_DEL`.\n'
)

ACTION_SELECTION_PROMPT_TEMPLATE = (
    PROMPT_PREFIX
    + '\nThe current user goal/request is: {goal}'
    + '\n\nHere is a history of what you have done so far:\n{history}'
    + '\n\nHere is a list of descriptions for UI elements on the current'
    ' screen (each element has bounding box coordinates in pixels):\n'
    '{ui_elements_description}\n'
    '{installed_packages}'
    + GUIDANCE
    + '{additional_guidelines}'
    + '\n\nNow output an action from the above list in the correct format,'
    ' following the reason why you do that. Your answer should look like:\n'
    'Reason: ...\nAction: <adb shell command or task control>\n\n'
    'Your Answer:\n'
)

SUMMARIZATION_PROMPT_TEMPLATE = (
    PROMPT_PREFIX
    + '\nThe (overall) user goal/request is:{goal}\n'
    'Now I want you to summarize the latest step based on the action you'
    ' performed with the reason and descriptions for the before and after'
    ' (the action) screen states.\n'
    'Here is the description for the before'
    ' screen:\n{before_elements}\n'
    'Here is the description for the after screen:\n{after_elements}\n'
    'This is the action you performed: {action}\n'
    'Based on the reason: {reason}\n'
    'Command output: {command_output}\n\n'
    '\nBy comparing the descriptions for the two screen states, the action'
    ' performed, and the command output, give a brief summary of this step.'
    ' This summary will be added to action history and used in future action'
    ' selection, so try to include essential information you think that will'
    ' be most useful for future action selection like'
    ' what you intended to do, why, if it worked as expected, if not'
    ' what might be the reason (be critical, the action/reason might not be'
    ' correct), what should/should not be done next and so on. Some more'
    ' rules/tips you should follow:\n'
    '- Keep it short and in one line.\n'
    '- Given this summary will be added into action history, it can be used as'
    ' memory to include information that needs to be remembered, or shared'
    ' between different apps.\n\n'
    'Summary of this step: '
)


def _build_action_selection_prompt(
    goal: str,
    history: List[str],
    ui_elements_description: str,
    additional_guidelines: Optional[List[str]] = None,
    installed_packages: Optional[str] = None,
) -> str:
    """Build the T3A-ADB action selection prompt (text-only)."""
    if history:
        hist_text = "\n".join(history)
    else:
        hist_text = "You just started, no action has been performed yet."

    extra = ""
    if additional_guidelines:
        extra = "For The Current Task:\n"
        for g in additional_guidelines:
            extra += f"- {g}\n"

    pkg_section = ""
    if installed_packages:
        pkg_section = f"\n{installed_packages}\n"

    return ACTION_SELECTION_PROMPT_TEMPLATE.format(
        goal=goal,
        history=hist_text,
        ui_elements_description=ui_elements_description or "Not available",
        additional_guidelines=extra,
        installed_packages=pkg_section,
    )


def _build_summary_prompt(
    goal: str,
    action: str,
    reason: str,
    before_elements: str,
    after_elements: str,
    command_output: str,
) -> str:
    """Build the T3A-ADB summarization prompt (text-only)."""
    return SUMMARIZATION_PROMPT_TEMPLATE.format(
        goal=goal,
        action=action,
        reason=reason,
        before_elements=before_elements or "Not available",
        after_elements=after_elements or "Not available",
        command_output=command_output or "(no output)",
    )


def _try_extract_task_control(text: str) -> Optional[str]:
    """Try to extract a task-control command from free-form text using regex.

    Handles malformed variants like:
      - answer(content='...')  answer(content="...")  answer(content=...)
      - answer('...')  answer("...")  answer(...)  answer: ...
      - FINISH(content='...')  FINISH('...')  FINISH: ...
      - INFEASIBLE(content='...')  INFEASIBLE('...')
    """
    # Standard format: KEYWORD(content='...' or "...")
    for keyword in ("answer", "FINISH", "INFEASIBLE"):
        # content='...' or content="..."
        m = re.search(
            rf"{keyword}\s*\(\s*content\s*=\s*['\"]?(.*?)['\"]?\s*\)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m:
            return f"{keyword}(content='{m.group(1).strip()}')"
        # KEYWORD('...') or KEYWORD("...")
        m = re.search(
            rf"{keyword}\s*\(\s*['\"](.+?)['\"]?\s*\)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m:
            return f"{keyword}(content='{m.group(1).strip()}')"
        # KEYWORD(free text without quotes)
        m = re.search(
            rf"{keyword}\s*\(\s*([^)]+?)\s*\)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m and "content=" not in m.group(1).lower():
            return f"{keyword}(content='{m.group(1).strip()}')"
    # answer: <text> (colon variant)
    m = re.search(r"answer\s*:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        return f"answer(content='{m.group(1).strip()}')"
    return None


def _parse_action_response(text: str) -> Tuple[str, str]:
    """Extract (action_command, reason) from model output.

    Expected format:
      Reason: <reasoning>
      Action: <adb shell ... | FINISH(...) | INFEASIBLE(...) | answer(...)>

    Falls back to regex-based extraction for task control commands when
    the model doesn't use the exact expected format.

    Returns (command, reason). Raises ValueError if nothing can be parsed.
    """
    # Strip thinking tokens from reasoning models (e.g., Qwen3-*-Thinking)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    reason = ""
    if "Reason:" in text:
        parts = text.split("Reason:", 1)
        if len(parts) > 1:
            reason_section = parts[1]
            if "Action:" in reason_section:
                reason = reason_section.split("Action:", 1)[0].strip()
            else:
                reason = reason_section.strip()

    command = None

    if "Action:" in text:
        command_section = text.split("Action:", 1)[1].strip()
        # Take first line, but also handle multi-line task control
        first_line = command_section.split("\n")[0].strip().strip("`").strip()
        if first_line:
            command = first_line

    # Fallback: try regex extraction for task control commands
    if command is None or command == "":
        tc = _try_extract_task_control(text)
        if tc:
            command = tc

    if command is None or command == "":
        raise ValueError(f"No valid action found in model output: {text[:300]}")

    # Normalize task control commands for consistent parsing
    if command.lower().startswith("answer") or command.startswith("FINISH") or command.startswith("INFEASIBLE"):
        # Re-extract with lenient regex to fix formatting issues
        tc = _try_extract_task_control(command)
        if tc:
            command = tc
    else:
        command = _normalize_adb_command(command)

    return command, reason


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class AndroidT3AADBAgent(AndroidAgent):
    """T3A-ADB: T3A prompt/observation framework with ADB command action space.

    Each step:
      1. Build action selection prompt with goal, history, UI elements (text only)
      2. Generate response (no images)
      3. Parse Reason + Action (ADB command or task control)
      4. Execute via step_adb() for shell commands or step() for task control
      5. Summarize step via second LLM call (text-only: before/after UI + cmd output)
      6. Append step summary to history; rebuild prompt for next step
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.screen_width = DEFAULT_SCREEN_WIDTH
        self.screen_height = DEFAULT_SCREEN_HEIGHT
        self.goal = ""
        self.history: List[str] = []
        self.additional_guidelines: Optional[List[str]] = None
        self._installed_packages: Optional[str] = None  # cached package list

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Build the first set of messages with T3A-ADB prompt (text-only)."""
        self.goal = (observation or {}).get("task", "") or getattr(task, "goal", "")
        ui_elements = (observation or {}).get("ui_elements", [])

        image = (observation or {}).get("image")
        if image is not None and isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]

        screen_size = (self.screen_width, self.screen_height)
        ui_text = generate_ui_elements_with_tap_targets(ui_elements, screen_size)
        self._current_ui_elements = ui_elements

        prompt_text = _build_action_selection_prompt(
            self.goal, [], ui_text, self.additional_guidelines,
            installed_packages=self._installed_packages,
        )

        system_prompt = "You are a helpful assistant."
        if template_messages:
            first = template_messages[0]
            c = first.get("content")
            if isinstance(c, str):
                system_prompt = c
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        system_prompt = block.get("text", system_prompt)
                        break

        return [
            {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "text", "text": prompt_text}]},
        ]

    def extract_images_for_inference(self, messages: List[Dict]) -> Optional[List[Any]]:
        """No images -- pure text agent."""
        return None

    async def _query_installed_packages(self) -> str:
        """Query installed third-party packages from the device.

        Returns a formatted string like:
          Installed apps: Tasks → org.tasks.tasks, Calendar → com.simplemobiletools.calendar.pro, ...
        """
        try:
            payload = {"command": "adb shell pm list packages -3", "thought": "query installed packages"}
            _obs, cmd_output, _reward, _term, _trunc, _info = await self.env_handle.step_adb(payload)
            # Parse "package:com.foo.bar" lines into sorted list
            packages = []
            for line in cmd_output.strip().splitlines():
                line = line.strip()
                if line.startswith("package:"):
                    packages.append(line[len("package:"):])
            packages.sort()
            if packages:
                return "Installed third-party packages:\n" + "\n".join(f"  - {p}" for p in packages)
            return ""
        except Exception as e:
            if DEBUG_TIMING:
                print(f"[T3AADBAgent] Failed to query packages: {e}")
            return ""

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single T3A-ADB step: action selection -> execute -> summarize."""
        self.state.step_count += 1
        if DEBUG_TIMING:
            print(
                f"[T3AADBAgent Step {self.state.step_count}] "
                f"instance={self.state.instance_id} traj={self.state.trajectory_id}"
            )

        # 0. On first step, query installed packages and rebuild prompt
        if self.state.step_count == 1 and self._installed_packages is None:
            self._installed_packages = await self._query_installed_packages()
            if self._installed_packages:
                # Rebuild the user prompt to include package list
                current_ui_elements = getattr(self, "_current_ui_elements", [])
                screen_size = (self.screen_width, self.screen_height)
                ui_text = generate_ui_elements_with_tap_targets(
                    current_ui_elements, screen_size,
                )
                prompt_text = _build_action_selection_prompt(
                    self.goal, [], ui_text, self.additional_guidelines,
                    installed_packages=self._installed_packages,
                )
                # Replace last user message with enriched prompt
                self.state.messages = [
                    msg for msg in self.state.messages if msg["role"] != "user"
                ] + [
                    {"role": "user", "content": [{"type": "text", "text": prompt_text}]},
                ]

        # 1. Select messages for inference
        selected_messages = self.memory.get_inference_messages(self.state.messages)

        # 2. Tokenize (no images)
        inference_input_ids = self.prepare_input_ids(selected_messages)
        image_data = None

        # 3. Generate response
        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params.pop("max_tokens", None)

        if DEBUG_TIMING:
            print(
                f"[Context] step={self.state.step_count} "
                f"tokens={len(inference_input_ids)}"
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
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        # 4. Parse Reason + Action
        command = None
        reason = ""
        error_summary = None

        if "Action:" not in response_str:
            if DEBUG_TIMING:
                print("[T3AADBAgent] No 'Action:' found in response")
                print(f"[T3AADBAgent] Raw response: {response_str[:500]}")
            self.state.format_reward = -1.0
            error_summary = (
                "Output for action selection is not in the correct format,"
                " so no action is performed. Expected format: Reason: ...\nAction: <command>"
            )
        else:
            try:
                command, reason = _parse_action_response(response_str)
                self.state.format_reward = 0.0
            except Exception as e:
                if DEBUG_TIMING:
                    print(f"[T3AADBAgent] Parse error: {e}")
                    print(f"[T3AADBAgent] Raw response: {response_str[:500]}")
                self.state.format_reward = -1.0
                error_summary = (
                    "Cannot parse the output to a valid action. Please"
                    " output in the format: Reason: ...\nAction: <adb shell command or task control>"
                )

        current_ui_elements = getattr(self, "_current_ui_elements", [])

        # 4b. Handle parse error: no action executed, rebuild observation, continue
        if error_summary is not None:
            self.history.append(f"Step {self.state.step_count}: {error_summary}")
            self.state.step_records.append({
                "step_idx": self.state.step_count,
                "thought": reason,
                "raw_response": response_str,
                "action_type": "parse_error",
                "action_params": {},
                "command_output": None,
                "a11y_tree": None,
                "screenshot_idx": None,
                "input_tokens": len(_prompt_token_ids),
                "output_tokens": len(response_token_ids),
            })
            self.state.messages = self.append_assistant(self.state.messages, response_str)

            # Rebuild observation with same UI state (no action was executed)
            screen_size = (self.screen_width, self.screen_height)
            ui_text = generate_ui_elements_with_tap_targets(
                current_ui_elements, screen_size,
            )
            next_prompt = _build_action_selection_prompt(
                self.goal, self.history, ui_text, self.additional_guidelines,
                installed_packages=self._installed_packages,
            )
            self.state.messages = self.state.messages + [
                {"role": "user", "content": [{"type": "text", "text": next_prompt}]},
            ]

            _should_add, should_continue = self.training.add_step(
                self.state.messages, response_token_ids,
            )
            if not should_continue:
                self.state.is_done = True
                return True, "TRAINING_BUDGET_EXCEEDED", None

            return False, None, None

        # 5. Execute action
        is_task_control = (
            command.startswith("FINISH")
            or command.startswith("INFEASIBLE")
            or command.startswith("answer")
        )

        before_elements_text = generate_ui_elements_with_tap_targets(
            current_ui_elements, (self.screen_width, self.screen_height),
        )

        if DEBUG_TIMING:
            container_start = time.perf_counter()

        command_output = ""
        if is_task_control:
            action_dict = _parse_task_control(command)
            payload = {"action": action_dict, "thought": reason}
            observation, reward, terminated, truncated, info = await self.env_handle.step(
                payload
            )
        else:
            payload = {"command": command, "thought": reason}
            (
                observation,
                command_output,
                reward,
                terminated,
                truncated,
                info,
            ) = await self.env_handle.step_adb(payload)

        if DEBUG_TIMING:
            container_elapsed = time.perf_counter() - container_start
            print(
                f"[Timing] step={self.state.step_count} "
                f"vLLM={vllm_elapsed:.2f}s container={container_elapsed:.2f}s "
                f"total={vllm_elapsed + container_elapsed:.2f}s"
            )

        self.state.reward = reward

        # Truncate command output
        if len(command_output) > MAX_OUTPUT_CHARS:
            command_output = command_output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

        # 6. Get after-action UI elements
        after_ui_elements = []
        if observation is not None:
            after_ui_elements = observation.get("ui_elements", [])

        image = observation.get("image") if observation else None
        if image is not None and isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]

        after_elements_text = generate_ui_elements_with_tap_targets(
            after_ui_elements, (self.screen_width, self.screen_height),
        )

        # 7. Execution error handling
        if observation is not None and observation.get("error"):
            summary = (
                f"Error executing `{command}`: "
                f"{observation.get('error', '')[:100]}"
            )
            if command_output:
                summary += f" Output: {command_output[:100]}"
            self.history.append(f"Step {self.state.step_count}: {summary}")
            self.state.messages = self.append_assistant(self.state.messages, response_str)

            next_prompt = _build_action_selection_prompt(
                self.goal, self.history, after_elements_text, self.additional_guidelines,
                installed_packages=self._installed_packages,
            )
            self.state.messages = self.state.messages + [
                {"role": "user", "content": [{"type": "text", "text": next_prompt}]},
            ]
            self._current_ui_elements = after_ui_elements
            self.state.step_records.append({
                "step_idx": self.state.step_count,
                "thought": reason,
                "raw_response": response_str,
                "action_type": "adb_error",
                "action_params": {"command": command},
                "command_output": command_output,
                "a11y_tree": None,
                "screenshot_idx": None,
                "input_tokens": len(_prompt_token_ids),
                "output_tokens": len(response_token_ids),
            })
            _should_add, should_continue = self.training.add_step(
                self.state.messages, response_token_ids,
            )
            if not should_continue:
                self.state.is_done = True
                return True, "TRAINING_BUDGET_EXCEEDED", None
            return False, None, None

        # 8. Summarization
        if terminated or truncated:
            summary = f"Action: {command}. Reason: {reason}"
        else:
            summary = await self._summarize_step(
                command, reason, before_elements_text, after_elements_text,
                command_output,
            )
        self.history.append(f"Step {self.state.step_count}: {summary}")

        # 9. Record step
        _action_type = "task_control" if is_task_control else "adb"
        self.state.step_records.append({
            "step_idx": self.state.step_count,
            "thought": reason,
            "raw_response": response_str,
            "action_type": _action_type,
            "action_params": {"command": command},
            "command_output": command_output,
            "a11y_tree": None,
            "screenshot_idx": None,
            "input_tokens": len(_prompt_token_ids),
            "output_tokens": len(response_token_ids),
        })

        # 10. Update messages
        self.state.messages = self.append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "FINISH" if terminated else "TRUNCATED", self.state.reward

        # 11. Next observation
        self._current_ui_elements = after_ui_elements
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        # Include command output feedback in the next prompt
        cmd_feedback = ""
        if command_output and not is_task_control:
            cmd_feedback = f"\nOutput of last command (`{command}`):\n{command_output}\n"

        next_prompt = _build_action_selection_prompt(
            self.goal, self.history, after_elements_text, self.additional_guidelines,
            installed_packages=self._installed_packages,
        )
        if cmd_feedback:
            next_prompt = cmd_feedback + "\n" + next_prompt

        self.state.messages = self.state.messages + [
            {"role": "user", "content": [{"type": "text", "text": next_prompt}]},
        ]

        # 12. Training
        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids,
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None

    async def _summarize_step(
        self,
        action: str,
        reason: str,
        before_elements_text: str,
        after_elements_text: str,
        command_output: str,
    ) -> str:
        """Call the LLM (text-only) to summarize the step."""
        summary_prompt = _build_summary_prompt(
            self.goal, action, reason,
            before_elements_text, after_elements_text,
            command_output,
        )
        summary_messages = [
            {"role": "system", "content": [{"type": "text", "text": "You are a helpful assistant."}]},
            {"role": "user", "content": [{"type": "text", "text": summary_prompt}]},
        ]
        summary_input_ids = self.prepare_input_ids(summary_messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params.pop("max_tokens", None)

        try:
            result = await self.infer_engine.async_generate_ids(
                input_ids=summary_input_ids,
                sampling_params=sampling_params,
                request_id=self.agent_id + "_summary",
                image_data=None,
                return_token_ids=True,
                messages=summary_messages,
            )
            summary_response, _, summary_prompt_ids, summary_resp_ids = result
            self.state.total_input_tokens += len(summary_prompt_ids)
            self.state.total_output_tokens += len(summary_resp_ids)
            return f"Action: {action}. {summary_response.strip()}"
        except Exception as e:
            if DEBUG_TIMING:
                print(f"[T3AADBAgent] Summarization failed: {e}")
            return f"Action: {action}. Reason: {reason}"
