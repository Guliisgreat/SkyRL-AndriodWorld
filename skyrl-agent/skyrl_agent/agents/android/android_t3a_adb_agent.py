"""
AndroidT3AADBAgent - T3A prompt/observation framework with ADB command action space.

Combines:
  - T3A's rich M3A-style UI element descriptions, step summarization, and history
  - ADB shell commands as the action space (executed via step_adb)

Key features:
  - Text-only: observation = goal + history + UI element list (with bbox_pixels)
  - ADB commands: tap, swipe, input text, keyevent, app management, system queries
  - Mandatory summarization: second LLM call with before/after UI + command output
  - Full prompt rebuild each step (no sliding window; summarization compresses context)
"""

import copy
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from skyrl_agent.agents.android.android_agent import AndroidAgent
from skyrl_agent.agents.android.android_m3a_agent import (
    generate_ui_elements_description_full,
)
from skyrl_agent.agents.android.android_api_screen_adb_agent import (
    _parse_task_control,
    _normalize_adb_command,
    MAX_OUTPUT_CHARS,
)

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

DEFAULT_SCREEN_WIDTH = 1080
DEFAULT_SCREEN_HEIGHT = 2400


# ---------------------------------------------------------------------------
# T3A-ADB prompt templates
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
    ' current screen will be given to you (each element has bounding box'
    ' coordinates in pixels), together with a history of what you have done'
    ' in previous steps.'
    ' Based on these pieces of information and the goal, you must choose to'
    ' perform one of the actions in the following list by outputting the'
    ' action in the correct format.\n\n'
    '## Available Actions\n\n'
    '### Touch & Input\n'
    '- `adb shell input tap <x> <y>` -- tap at pixel coordinates\n'
    '- `adb shell input swipe <x1> <y1> <x2> <y2> [duration_ms]` -- swipe gesture\n'
    '- `adb shell input text \'<text>\'` -- type text (must tap field first)\n'
    '- `adb shell input keyevent <keycode>` -- press a key\n'
    '  Common keycodes: KEYCODE_HOME (3), KEYCODE_BACK (4), KEYCODE_ENTER (66),'
    ' KEYCODE_DEL (67), KEYCODE_SEARCH (84), KEYCODE_TAB (61)\n\n'
    '### App Management\n'
    '- `adb shell am start -n <package/activity>` -- start an activity\n'
    '- `adb shell am start -a android.intent.action.VIEW -d <uri>` -- open a URI\n'
    '- `adb shell am force-stop <package>` -- force stop an app\n'
    '- `adb shell am broadcast -a <action>` -- send a broadcast\n'
    '- `adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1` -- launch app\n'
    '- `adb shell pm list packages` -- list installed packages\n\n'
    '### System Queries\n'
    '- `adb shell dumpsys <service>` -- dump system service info\n'
    '- `adb shell settings get <namespace> <key>` -- get a system setting\n'
    '- `adb shell settings put <namespace> <key> <value>` -- set a system setting\n'
    '- `adb shell content query --uri <uri>` -- query content provider\n'
    '- `adb shell content insert --uri <uri> --bind <col>:<type>:<val>` -- insert content\n'
    '- `adb shell content delete --uri <uri>` -- delete content\n'
    '- `adb shell getprop <property>` -- get system property\n\n'
    '### UI Inspection\n'
    '- `adb shell uiautomator dump /dev/tty` -- dump UI hierarchy (XML)\n\n'
    '### Display & System\n'
    '- `adb shell wm size` -- get screen size\n'
    '- `adb shell date` -- get current date/time\n\n'
    '### Task Control\n'
    '- `FINISH(content=\'<result description>\')` -- task completed successfully\n'
    '- `INFEASIBLE(content=\'<reason>\')` -- task cannot be completed\n'
    '- `answer(content=\'<answer text>\')` -- answer user\'s question and complete\n'
)

GUIDANCE = (
    'Here are some useful guidelines you need to follow:\n'
    'General\n'
    '- Usually there will be multiple ways to complete a task, pick the'
    ' easiest one. Also when something does not work as expected (due'
    ' to various reasons), sometimes a simple retry can solve the problem,'
    " but if it doesn't (you can see that from the history), try to"
    ' switch to other solutions.\n'
    '- Sometimes you may need to navigate the phone to gather information'
    ' needed to complete the task, for example if user asks'
    ' "what is my schedule tomorrow", then you may want to launch the calendar'
    ' app, look up information there, answer'
    " user's question (using the `answer` action) and finish.\n"
    '- For requests that are questions (or chat messages), remember to use'
    ' the `answer` action to reply to user explicitly before finish!'
    ' Merely displaying the answer on the screen is NOT sufficient (unless'
    ' the goal is something like "show me ...").\n'
    '- If the desired state is already achieved (e.g., enabling Wi-Fi when'
    " it's already on), you can just complete the task.\n"
    'Action Related\n'
    '- To tap a UI element, compute its center from the bounding box:'
    ' x=(x_min+x_max)/2, y=(y_min+y_max)/2, then use'
    ' `adb shell input tap <x> <y>`.\n'
    '- Use `adb shell input text` to type text instead of tapping characters'
    ' on the keyboard one by one. Tap the text field first, then type.\n'
    '- Use `adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1`'
    ' to open an app.\n'
    '- Prefer achieving the goal via direct shell commands or system APIs'
    ' (settings, content providers, am/pm) when possible; use tap/swipe only'
    ' when no such command exists or when the task explicitly requires'
    ' interacting with on-screen UI.\n'
    '- To scroll, use `adb shell input swipe` in the appropriate direction.'
    ' For example, to scroll down: swipe from (540, 1800) to (540, 600).\n'
    '- Issue ONE command per step.\n'
    '- After touch/input commands, check the UI element list in the next step'
    ' to verify the result.\n'
    '- If a command fails (non-zero return code), try an alternative approach.\n'
    'Text Related Operations\n'
    '- To delete text: tap the text field, then use'
    ' `adb shell input keyevent KEYCODE_MOVE_END` followed by repeated'
    ' `adb shell input keyevent KEYCODE_DEL` or select all and delete.\n'
    '- Sometimes there is default text in the text field; remember to clear'
    ' it before typing new text.\n'
    '- When typing into a text field, sometimes an auto-complete dropdown'
    ' will appear. Select the best match by tapping on it.\n'
)

ACTION_SELECTION_PROMPT_TEMPLATE = (
    PROMPT_PREFIX
    + '\nThe current user goal/request is: {goal}'
    + '\n\nHere is a history of what you have done so far:\n{history}'
    + '\n\nHere is a list of descriptions for UI elements on the current'
    ' screen (each element has bounding box coordinates in pixels):\n'
    '{ui_elements_description}\n'
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

    return ACTION_SELECTION_PROMPT_TEMPLATE.format(
        goal=goal,
        history=hist_text,
        ui_elements_description=ui_elements_description or "Not available",
        additional_guidelines=extra,
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


def _parse_action_response(text: str) -> Tuple[str, str]:
    """Extract (action_command, reason) from model output.

    Expected format:
      Reason: <reasoning>
      Action: <adb shell ... | FINISH(...) | INFEASIBLE(...) | answer(...)>

    Returns (command, reason). Raises ValueError if no Action: field.
    """
    reason = ""
    if "Reason:" in text:
        parts = text.split("Reason:", 1)
        if len(parts) > 1:
            reason_section = parts[1]
            if "Action:" in reason_section:
                reason = reason_section.split("Action:", 1)[0].strip()
            else:
                reason = reason_section.strip()

    if "Action:" not in text:
        raise ValueError(f"No 'Action:' found in model output: {text[:200]}")

    command_section = text.split("Action:", 1)[1].strip()
    command = command_section.split("\n")[0].strip()
    command = command.strip("`").strip()
    if not command:
        raise ValueError("Empty command after 'Action:'")

    if not (command.startswith("FINISH") or command.startswith("INFEASIBLE") or command.startswith("answer")):
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
        ui_text = generate_ui_elements_description_full(ui_elements, screen_size)
        self._current_ui_elements = ui_elements

        prompt_text = _build_action_selection_prompt(
            self.goal, [], ui_text, self.additional_guidelines,
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

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single T3A-ADB step: action selection -> execute -> summarize."""
        self.state.step_count += 1
        if DEBUG_TIMING:
            print(
                f"[T3AADBAgent Step {self.state.step_count}] "
                f"instance={self.state.instance_id} traj={self.state.trajectory_id}"
            )

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
            ui_text = generate_ui_elements_description_full(
                current_ui_elements, screen_size,
            )
            next_prompt = _build_action_selection_prompt(
                self.goal, self.history, ui_text, self.additional_guidelines,
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

        before_elements_text = generate_ui_elements_description_full(
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

        after_elements_text = generate_ui_elements_description_full(
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
