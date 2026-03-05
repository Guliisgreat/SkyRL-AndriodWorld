"""
AndroidT3AAgent - Text-only Autonomous Agent for Android (T3A) in skyrl-agent.

Reimplements the T3A agent from AndroidWorld in the skyrl-agent framework.
Subclass of AndroidAgent; uses UI element list (accessibility tree) as the sole
observation, M3A-style index-based JSON actions, and mandatory text-only
step summarization.

Key features:
  - Text-only: no screenshots to the LLM; observation = goal + history + UI list
  - Same action space as M3A: click, long_press, input_text, status, answer, etc.
  - Execution via android_env tool (env_handle.step with action dict)
  - Mandatory summarization: second LLM call with before/after UI descriptions (no images)
"""

import copy
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from skyrl_agent.agents.android.base import AndroidAgent
from skyrl_agent.agents.android.m3a_agent import (
    generate_ui_elements_description_full,
    parse_m3a_action,
)

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

DEFAULT_SCREEN_WIDTH = 1080
DEFAULT_SCREEN_HEIGHT = 2400


# ---------------------------------------------------------------------------
# T3A prompt templates (text-only; from AndroidWorld t3a.py)
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
    ' current screen will be given to you (each element can be specified by an'
    ' index), together with a history of what you have done in previous steps.'
    ' Based on these pieces of information and the goal, you must choose to'
    ' perform one of the action in the following list (action description'
    ' followed by the JSON format) by outputing the action in the correct JSON'
    ' format.\n'
    '- If you think the task has been completed, finish the task by using the'
    ' status action with complete as goal_status:'
    ' `{{"action_type": "status", "goal_status": "complete"}}`\n'
    '- If you think the task is not'
    " feasible (including cases like you don't have enough information or can"
    ' not perform some necessary actions), finish by using the `status` action'
    ' with infeasible as goal_status:'
    ' `{{"action_type": "status", "goal_status": "infeasible"}}`\n'
    "- Answer user's question:"
    ' `{{"action_type": "answer", "text": "<answer_text>"}}`\n'
    '- Click/tap on a UI element (specified by its index) on the screen:'
    ' `{{"action_type": "click", "index": <target_index>}}`.\n'
    '- Long press on a UI element (specified by its index) on the screen:'
    ' `{{"action_type": "long_press", "index": <target_index>}}`.\n'
    '- Type text into an editable text field (specified by its index), this'
    ' action contains clicking the text field, typing in the text and pressing'
    ' the enter, so no need to click on the target field to start:'
    ' `{{"action_type": "input_text", "text": <text_input>, "index":'
    ' <target_index>}}`\n'
    '- Press the Enter key: `{{"action_type": "keyboard_enter"}}`\n'
    '- Navigate to the home screen: `{{"action_type": "navigate_home"}}`\n'
    '- Navigate back: `{{"action_type": "navigate_back"}}`\n'
    '- Scroll the screen or a scrollable UI element in one of the four'
    ' directions, use the same numeric index as above if you want to scroll a'
    ' specific UI element, leave it empty when scroll the whole screen:'
    ' `{{"action_type": "scroll", "direction": <up, down, left, right>,'
    ' "index": <optional_target_index>}}`\n'
    '- Open an app (nothing will happen if the app is not installed):'
    ' `{{"action_type": "open_app", "app_name": <name>}}`\n'
    '- Wait for the screen to update: `{{"action_type": "wait"}}`\n'
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
    ' "what is my schedule tomorrow", then you may want to open the calendar'
    ' app (using the `open_app` action), look up information there, answer'
    " user's question (using the `answer` action) and finish (using"
    ' the `status` action with complete as goal_status).\n'
    '- For requests that are questions (or chat messages), remember to use'
    ' the `answer` action to reply to user explicitly before finish!'
    ' Merely displaying the answer on the screen is NOT sufficient (unless'
    ' the goal is something like "show me ...").\n'
    '- If the desired state is already achieved (e.g., enabling Wi-Fi when'
    " it's already on), you can just complete the task.\n"
    'Action Related\n'
    '- Use the `open_app` action whenever you want to open an app'
    ' (nothing will happen if the app is not installed), do not use the'
    ' app drawer to open an app unless all other ways have failed.\n'
    '- Use the `input_text` action whenever you want to type'
    ' something (including password) instead of clicking characters on the'
    ' keyboard one by one. Sometimes there is some default text in the text'
    ' field you want to type in, remember to delete them before typing.\n'
    '- For `click`, `long_press` and `input_text`, the index parameter you'
    ' pick must be in the UI element list given to you.\n'
    '- Consider exploring the screen by using the `scroll`'
    ' action with different directions to reveal additional content.\n'
    '- The direction parameter for the `scroll` action can be confusing'
    " sometimes as it's opposite to swipe, for example, to view content at the"
    ' bottom, the `scroll` direction should be set to "down". It has been'
    ' observed that you have difficulties in choosing the correct direction, so'
    ' if one does not work, try the opposite as well.\n'
    'Text Related Operations\n'
    '- Normally to select some text on the screen: <i> Enter text selection'
    ' mode by long pressing the area where the text is, then some of the words'
    ' near the long press point will be selected (highlighted with two pointers'
    ' indicating the range) and usually a text selection bar will also appear'
    ' with options like `copy`, `paste`, `select all`, etc.'
    ' <ii> Select the exact text you need. Usually the text selected from the'
    ' previous step is NOT the one you want, you need to adjust the'
    ' range by dragging the two pointers. If you want to select all text in'
    ' the text field, simply click the `select all` button in the bar.\n'
    "- At this point, you don't have the ability to drag something around the"
    ' screen, so in general you can not select arbitrary text.\n'
    '- To delete some text: the most traditional way is to place the cursor'
    ' at the right place and use the backspace button in the keyboard to'
    ' delete the characters one by one (can long press the backspace to'
    ' accelerate if there are many to delete). Another approach is to first'
    ' select the text you want to delete, then click the backspace button'
    ' in the keyboard.\n'
    '- To copy some text: first select the exact text you want to copy, which'
    ' usually also brings up the text selection bar, then click the `copy`'
    ' button in bar.\n'
    '- To paste text into a text box, first long press the'
    ' text box, then usually the text selection bar will appear with a'
    ' `paste` button in it.\n'
    '- When typing into a text field, sometimes an auto-complete dropdown'
    ' list will appear. This usually indicating this is a enum field and you'
    ' should try to select the best match by clicking the corresponding one'
    ' in the list.\n'
)

ACTION_SELECTION_PROMPT_TEMPLATE = (
    PROMPT_PREFIX
    + '\nThe current user goal/request is: {goal}'
    + '\n\nHere is a history of what you have done so far:\n{history}'
    + '\n\nHere is a list of descriptions for some UI elements on the current'
    ' screen:\n{ui_elements_description}\n'
    + GUIDANCE
    + '{additional_guidelines}'
    + '\n\nNow output an action from the above list in the correct JSON format,'
    ' following the reason why you do that. Your answer should look like:\n'
    'Reason: ...\nAction: {{"action_type":...}}\n\n'
    'Your Answer:\n'
)

SUMMARIZATION_PROMPT_TEMPLATE = (
    PROMPT_PREFIX
    + '\nThe (overall) user goal/request is:{goal}\n'
    'Now I want you to summerize the latest step based on the action you'
    ' pick with the reason and descriptions for the before and after (the'
    ' action) screenshots.\n'
    'Here is the description for the before'
    ' screenshot:\n{before_elements}\n'
    'Here is the description for the after screenshot:\n{after_elements}\n'
    'This is the action you picked: {action}\n'
    'Based on the reason: {reason}\n\n'
    '\nBy comparing the descriptions for the two screenshots and the action'
    ' performed, give a brief summary of this step.'
    ' This summary will be added to action history and used in future action'
    ' selection, so try to include essential information you think that will'
    ' be most useful for future action selection like'
    ' what you intended to do, why, if it worked as expected, if not'
    ' what might be the reason (be critical, the action/reason might not be'
    ' correct), what should/should not be done next and so on. Some more'
    ' rules/tips you should follow:\n'
    '- Keep it short and in one line.\n'
    "- Some actions (like `answer`, `wait`) don't involve screen change,"
    ' you can just assume they work as expected.\n'
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
    """Build the T3A action selection prompt (text-only)."""
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
) -> str:
    """Build the T3A summarization prompt (text-only)."""
    return SUMMARIZATION_PROMPT_TEMPLATE.format(
        goal=goal,
        action=action,
        reason=reason,
        before_elements=before_elements or "Not available",
        after_elements=after_elements or "Not available",
    )


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class AndroidT3AAgent(AndroidAgent):
    """T3A (Text-only Autonomous Agent for Android) in the skyrl-agent framework.

    Each step:
      1. Build action selection prompt with goal, history, UI elements (text only)
      2. Generate response (no images)
      3. Parse Reason + Action JSON
      4. Validate index for click/long_press/input_text
      5. Execute action via android_env tool
      6. Summarize step via second LLM call (text-only: before/after UI descriptions)
      7. Append step summary to history; append assistant + next user message
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
        """Build the first set of messages with T3A prompt (text-only, no images)."""
        self.goal = (observation or {}).get("task", "") or getattr(task, "goal", "")
        ui_elements = (observation or {}).get("ui_elements", [])

        image = (observation or {}).get("image")
        if image is not None and isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]
        else:
            pass  # keep defaults

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
        """Single T3A step: action selection -> execute -> summarization (text-only)."""
        self.state.step_count += 1
        if DEBUG_TIMING:
            print(
                f"[T3AAgent Step {self.state.step_count}] "
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
        action_dict = None
        reason = ""
        error_summary = None

        if "Action:" not in response_str:
            if DEBUG_TIMING:
                print("[T3AAgent] No 'Action:' found in response")
                print(f"[T3AAgent] Raw response: {response_str[:500]}")
            self.state.format_reward = -1.0
            error_summary = (
                "Output for action selection is not in the correct format,"
                " so no action is performed."
            )
        else:
            try:
                action_dict, reason = parse_m3a_action(response_str)
                self.state.format_reward = 0.0
            except Exception as e:
                if DEBUG_TIMING:
                    print(f"[T3AAgent] Parse error: {e}")
                    print(f"[T3AAgent] Raw response: {response_str[:500]}")
                self.state.format_reward = -1.0
                error_summary = (
                    "Can not parse the output to a valid action. Please"
                    " make sure to pick the action from the list with"
                    " required parameters (if any) in the correct JSON"
                    " format!"
                )

        current_ui_elements = getattr(self, "_current_ui_elements", [])

        # 4b. Index validation for click, long_press, input_text, scroll
        if error_summary is None and action_dict is not None:
            action_type = action_dict.get("action_type", "")
            idx = action_dict.get("index")
            if action_type in ("click", "long_press", "input_text", "scroll") and idx is not None:
                if idx >= len(current_ui_elements):
                    if DEBUG_TIMING:
                        print(
                            f"[T3AAgent] Index out of range: {idx}"
                            f" >= {len(current_ui_elements)}"
                        )
                    error_summary = (
                        "The parameter index is out of range. Remember"
                        " the index must be in the UI element list!"
                    )

        # 4c. Handle error: no action executed, rebuild observation, continue
        if error_summary is not None:
            self.history.append(f"Step {self.state.step_count}: {error_summary}")
            self.state.step_records.append({
                "step_idx": self.state.step_count,
                "thought": reason,
                "raw_response": response_str,
                "action_type": (
                    action_dict.get("action_type", "parse_error")
                    if action_dict else "parse_error"
                ),
                "action_params": (
                    {k: v for k, v in action_dict.items() if k != "action_type"}
                    if action_dict else {}
                ),
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

        action_str = json.dumps(action_dict)
        action_type = action_dict.get("action_type", "")

        if action_type == "answer" and DEBUG_TIMING:
            print("Agent answered with:", action_dict.get("text", "")[:80])

        # 6. Execute via android_env tool (includes status/answer; env returns terminated for status)
        tool = self.tools["android_env"]
        before_elements_text = generate_ui_elements_description_full(
            current_ui_elements, (self.screen_width, self.screen_height),
        )

        if DEBUG_TIMING:
            container_start = time.perf_counter()

        output = await tool.async_call(
            action_dict,
            env_handle=self.env_handle,
            thought=reason,
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
        after_ui_elements = output.get("ui_elements", [])

        # 7. Execution error handling
        if output.get("error"):
            summary = f"Some error happened executing the action {action_type}: {output.get('error', '')[:100]}"
            self.history.append(f"Step {self.state.step_count}: {summary}")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            after_elements_text = generate_ui_elements_description_full(
                after_ui_elements, (self.screen_width, self.screen_height),
            )
            next_prompt = _build_action_selection_prompt(
                self.goal, self.history, after_elements_text, self.additional_guidelines,
            )
            self.state.messages = self.state.messages + [
                {"role": "user", "content": [{"type": "text", "text": next_prompt}]},
            ]
            self._current_ui_elements = after_ui_elements
            image = output.get("image")
            if image is not None and isinstance(image, np.ndarray) and image.ndim >= 2:
                self.screen_height, self.screen_width = image.shape[:2]
            self.state.step_records.append({
                "step_idx": self.state.step_count,
                "thought": reason,
                "raw_response": response_str,
                "action_type": action_type,
                "action_params": {k: v for k, v in action_dict.items() if k != "action_type"},
                "command_output": None,
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

        # 8. Summarization: mandatory for non-terminal steps (text-only)
        after_elements_text = generate_ui_elements_description_full(
            after_ui_elements, (self.screen_width, self.screen_height),
        )
        if terminated or truncated:
            summary = f"Action selected: {action_str}. Reason: {reason}"
        else:
            summary = await self._summarize_step(
                action_str, reason, before_elements_text, after_elements_text,
            )
        self.history.append(f"Step {self.state.step_count}: {summary}")

        # 9. Record step
        self.state.step_records.append({
            "step_idx": self.state.step_count,
            "thought": reason,
            "raw_response": response_str,
            "action_type": action_type,
            "action_params": {k: v for k, v in action_dict.items() if k != "action_type"},
            "command_output": None,
            "a11y_tree": None,
            "screenshot_idx": None,
            "input_tokens": len(_prompt_token_ids),
            "output_tokens": len(response_token_ids),
        })

        # 10. Update messages: assistant response + next user (action selection prompt)
        self.state.messages = self.append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "FINISH" if terminated else "TRUNCATED", self.state.reward

        # 11. Next observation (text-only)
        self._current_ui_elements = after_ui_elements
        image = output.get("image")
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        if isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]

        next_prompt = _build_action_selection_prompt(
            self.goal, self.history, after_elements_text, self.additional_guidelines,
        )
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
        action_str: str,
        reason: str,
        before_elements_text: str,
        after_elements_text: str,
    ) -> str:
        """Call the LLM (text-only) to summarize the step."""
        summary_prompt = _build_summary_prompt(
            self.goal, action_str, reason,
            before_elements_text, after_elements_text,
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
            return f"Action selected: {action_str}. {summary_response.strip()}"
        except Exception as e:
            if DEBUG_TIMING:
                print(f"[T3AAgent] Summarization failed: {e}")
            return f"Action selected: {action_str}. Reason: {reason}"
