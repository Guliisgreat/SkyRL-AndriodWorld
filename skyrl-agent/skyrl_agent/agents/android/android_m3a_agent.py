"""
AndroidM3AAgent - Multimodal Autonomous Agent for Android (M3A) in skyrl-agent.

Reimplements the M3A agent from AndroidWorld in the skyrl-agent framework.
Subclass of AndroidAgent; uses SOM (Set of Marks) annotated screenshots,
index-based JSON actions, and a summary-based step history.

Key features:
  - Two images per step: raw screenshot + SOM-marked screenshot with indexed bboxes
  - Index-based action format: {"action_type": "click", "index": 3}
  - Step summary history embedded in each prompt
  - Optional two-phase LLM (action selection + summarization)
"""

import ast
import copy
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from skyrl_agent.agents.android.android_agent import AndroidAgent
from .android_utils import numpy_to_base64

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

DEFAULT_SCREEN_WIDTH = 1080
DEFAULT_SCREEN_HEIGHT = 2400

# Colors for SOM bounding boxes (RGB). Cycles through for distinct elements.
_SOM_COLORS = [
    (255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 165, 0),
    (128, 0, 128), (0, 128, 128), (255, 0, 255), (0, 0, 128),
    (128, 128, 0), (220, 20, 60), (75, 0, 130), (0, 100, 0),
]


# ---------------------------------------------------------------------------
# SOM (Set of Marks) utilities
# ---------------------------------------------------------------------------

def validate_ui_element(
    el: Dict, screen_size: Tuple[int, int],
) -> bool:
    """Check that a UI element has a valid, on-screen bounding box."""
    bbox = el.get("bbox_pixels")
    if not bbox or not isinstance(bbox, dict):
        return False
    x_min = bbox.get("x_min", 0)
    y_min = bbox.get("y_min", 0)
    x_max = bbox.get("x_max", 0)
    y_max = bbox.get("y_max", 0)
    if x_max <= x_min or y_max <= y_min:
        return False
    sw, sh = screen_size
    if x_max < 0 or y_max < 0 or x_min >= sw or y_min >= sh:
        return False
    return True


def draw_som_marks(
    screenshot: np.ndarray,
    ui_elements: List[Dict],
    screen_size: Tuple[int, int],
) -> np.ndarray:
    """Draw SOM bounding boxes with numeric index labels on a screenshot copy.

    Returns a new numpy array; the original is not modified.
    """
    img = Image.fromarray(screenshot.copy())
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except (IOError, OSError):
        font = ImageFont.load_default()

    for index, el in enumerate(ui_elements):
        if not validate_ui_element(el, screen_size):
            continue
        bbox = el["bbox_pixels"]
        x0, y0 = bbox["x_min"], bbox["y_min"]
        x1, y1 = bbox["x_max"], bbox["y_max"]
        color = _SOM_COLORS[index % len(_SOM_COLORS)]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)

        label = str(index)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        tw = text_bbox[2] - text_bbox[0]
        th = text_bbox[3] - text_bbox[1]
        # Label background in the top-left corner of the bbox
        lx, ly = x0, max(y0 - th - 4, 0)
        draw.rectangle([lx, ly, lx + tw + 6, ly + th + 4], fill=color)
        draw.text((lx + 3, ly + 1), label, fill=(255, 255, 255), font=font)

    return np.array(img)


def add_screenshot_label(
    screenshot: np.ndarray, label: str,
) -> np.ndarray:
    """Add a text label (e.g. 'before', 'after') to the bottom-right corner."""
    img = Image.fromarray(screenshot.copy())
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except (IOError, OSError):
        font = ImageFont.load_default()
    text_bbox = draw.textbbox((0, 0), label, font=font)
    tw = text_bbox[2] - text_bbox[0]
    th = text_bbox[3] - text_bbox[1]
    x = img.width - tw - 16
    y = img.height - th - 16
    draw.rectangle([x - 4, y - 4, x + tw + 4, y + th + 4], fill=(0, 0, 0))
    draw.text((x, y), label, fill=(255, 255, 255), font=font)
    return np.array(img)


# ---------------------------------------------------------------------------
# UI element description (matches original M3A format)
# ---------------------------------------------------------------------------

def _generate_ui_element_description(el: Dict, index: int) -> str:
    """Produce an M3A-style text description for one UI element."""
    desc = f'UI element {index}: {{"index": {index}, '
    text = el.get("text") or ""
    if text:
        desc += f'"text": "{text}", '
    cd = el.get("content_description") or ""
    if cd:
        desc += f'"content_description": "{cd}", '
    ht = el.get("hint_text") or ""
    if ht:
        desc += f'"hint_text": "{ht}", '
    tp = el.get("tooltip") or ""
    if tp:
        desc += f'"tooltip": "{tp}", '

    desc += f'"is_clickable": {"True" if el.get("is_clickable") else "False"}, '
    desc += f'"is_long_clickable": {"True" if el.get("is_long_clickable") else "False"}, '
    desc += f'"is_editable": {"True" if el.get("is_editable") else "False"}, '
    if el.get("is_scrollable"):
        desc += '"is_scrollable": True, '
    if el.get("is_focusable"):
        desc += '"is_focusable": True, '
    desc += f'"is_selected": {"True" if el.get("is_selected") else "False"}, '
    desc += f'"is_checked": {"True" if el.get("is_checked") else "False"}, '
    return desc[:-2] + "}"


def generate_ui_elements_description(
    ui_elements: List[Dict], screen_size: Tuple[int, int],
) -> str:
    """Generate the full UI-element list string for the prompt."""
    lines: List[str] = []
    for index, el in enumerate(ui_elements):
        if validate_ui_element(el, screen_size):
            lines.append(_generate_ui_element_description(el, index))
    return "\n".join(lines) if lines else "Not available"


# ---------------------------------------------------------------------------
# Prompt templates (faithful to original M3A)
# ---------------------------------------------------------------------------

PROMPT_PREFIX = (
    'You are an agent who can operate an Android phone on behalf of a user.'
    " Based on user's goal/request, you may\n"
    '- Answer back if the request/goal is a question (or a chat message),'
    ' like user asks "What is my schedule for today?".\n'
    '- Complete some tasks described in the requests/goals by'
    ' performing actions (step by step) on the phone.\n\n'
    'When given a user request, you will try to complete it step by step.'
    ' At each step, you will be given the current screenshot (including the'
    ' original screenshot and the same screenshot with bounding'
    ' boxes and numeric indexes added to some UI elements) and a history of'
    ' what you have done (in text). Based on these pieces of information and'
    ' the goal, you must choose to perform one of the'
    ' action in the following list (action description followed by the JSON'
    ' format) by outputing the action in the correct JSON format.\n'
    '- If you think the task has been completed, finish the task by using the'
    ' status action with complete as goal_status:'
    ' `{{"action_type": "status", "goal_status": "complete"}}`\n'
    "- If you think the task is not feasible (including cases like you don't"
    ' have enough information or can not perform some necessary actions),'
    ' finish by using the `status` action with infeasible as goal_status:'
    ' `{{"action_type": "status", "goal_status": "infeasible"}}`\n'
    "- Answer user's question:"
    ' `{{"action_type": "answer", "text": "<answer_text>"}}`\n'
    '- Click/tap on an element on the screen. We have added marks (bounding'
    ' boxes with numeric indexes on their TOP LEFT corner) to most of the UI'
    ' elements in the screenshot, use the numeric index to indicate which'
    ' element you want to click:'
    ' `{{"action_type": "click", "index": <target_index>}}`.\n'
    '- Long press on an element on the screen, similar with the click action'
    ' above, use the numeric label on the bounding box to indicate which'
    ' element you want to long press:'
    ' `{{"action_type": "long_press", "index": <target_index>}}`.\n'
    '- Type text into a text field (this action contains clicking the text'
    ' field, typing in the text and pressing the enter, so no need to click on'
    ' the target field to start), use the numeric label'
    ' on the bounding box to indicate the target text field:'
    ' `{{"action_type": "input_text", "text": <text_input>,'
    ' "index": <target_index>}}`\n'
    '- Press the Enter key: `{{"action_type": "keyboard_enter"}}`\n'
    '- Navigate to the home screen: `{{"action_type": "navigate_home"}}`\n'
    '- Navigate back: `{{"action_type": "navigate_back"}}`\n'
    '- Scroll the screen or a scrollable UI element in one of the four'
    ' directions, use the same numeric index as above if you want to scroll a'
    ' specific UI element, leave it empty when scroll the whole screen:'
    ' `{{"action_type": "scroll", "direction": <up, down, left, right>,'
    ' "index": <optional_target_index>}}`\n'
    '- Open an app (nothing will happen if the app is not'
    ' installed): `{{"action_type": "open_app", "app_name": <name>}}`\n'
    '- Wait for the screen to update: `{{"action_type": "wait"}}`\n'
)

GUIDANCE = (
    'Here are some useful guidelines you need to follow:\n'
    'General:\n'
    '- Usually there will be multiple ways to complete a task, pick the'
    ' easiest one. Also when something does not work as expected (due'
    ' to various reasons), sometimes a simple retry can solve the problem,'
    " but if it doesn't (you can see that from the history),"
    ' SWITCH to other solutions.\n'
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
    'Action Related:\n'
    '- Use the `open_app` action whenever you want to open an app'
    ' (nothing will happen if the app is not installed), do not use the'
    ' app drawer to open an app unless all other ways have failed.\n'
    '- Use the `input_text` action whenever you want to type'
    ' something (including password) instead of clicking characters on the'
    ' keyboard one by one. Sometimes there is some default text in the text'
    ' field you want to type in, remember to delete them before typing.\n'
    '- For `click`, `long_press` and `input_text`, the index parameter you'
    ' pick must be VISIBLE in the screenshot and also in the UI element'
    ' list given to you (some elements in the list may NOT be visible on'
    ' the screen so you can not interact with them).\n'
    '- Consider exploring the screen by using the `scroll`'
    ' action with different directions to reveal additional content.\n'
    '- The direction parameter for the `scroll` action can be confusing'
    " sometimes as it's opposite to swipe, for example, to view content at the"
    ' bottom, the `scroll` direction should be set to "down". It has been'
    ' observed that you have difficulties in choosing the correct direction, so'
    ' if one does not work, try the opposite as well.\n'
    'Text Related Operations:\n'
    '- Normally to select certain text on the screen: <i> Enter text selection'
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
    + '\nThe current user goal/request is: {goal}\n\n'
    'Here is a history of what you have done so far:\n{history}\n\n'
    'The current screenshot and the same screenshot with bounding boxes'
    ' and labels added are also given to you.\n'
    'Here is a list of detailed'
    ' information for some of the UI elements (notice that some elements in'
    ' this list may not be visible in the current screen and so you can not'
    ' interact with it, can try to scroll the screen to reveal it first),'
    ' the numeric indexes are'
    ' consistent with the ones in the labeled screenshot:\n{ui_elements}\n'
    + GUIDANCE
    + '{additional_guidelines}'
    + '\nNow output an action from the above list in the correct JSON format,'
    ' following the reason why you do that. Your answer should look like:\n'
    'Reason: ...\nAction: {{"action_type":...}}\n\n'
    'Your Answer:\n'
)

SUMMARY_PROMPT_TEMPLATE = (
    PROMPT_PREFIX
    + '\nThe (overall) user goal/request is: {goal}\n'
    'Now I want you to summerize the latest step.\n'
    'You will be given the screenshot before you performed the action (which'
    ' has a text label "before" on the bottom right), the action you chose'
    ' (together with the reason) and the screenshot after the action was'
    ' performed (which has a text label "after" on the bottom right).\n'
    'Also here is the list of detailed information for some UI elements'
    ' in the before screenshot:\n{before_elements}\n'
    'Here is the list for the after screenshot:\n{after_elements}\n'
    'This is the action you picked: {action}\n'
    'Based on the reason: {reason}\n\n'
    'By comparing the two screenshots (plus the UI element lists) and the'
    ' action performed, give a brief summary of this step. This summary'
    ' will be added to action history and used in future action selection,'
    ' so try to include essential information you think that will be most'
    ' useful for future action selections like what you'
    ' intended to do, why, if it worked as expected, if not'
    ' what might be the reason (be critical, the action/reason might be'
    ' wrong), what should/should not be done next and so on. Some more'
    ' rules/tips you should follow:\n'
    '- Keep it short (better less than 50 words) and in a single line\n'
    "- Some actions (like `answer`, `wait`) don't involve screen change,"
    ' you can just assume they work as expected.\n'
    '- Given this summary will be added into action history, it can be used as'
    ' memory to include information that needs to be remembered, or shared'
    ' between different apps.\n\n'
    'Summary of this step: '
)


# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Dict:
    """Extract a JSON object from a string (handles markdown fences)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    json_match = re.search(r"\{[^{}]*\}", cleaned)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return ast.literal_eval(cleaned)
    except (ValueError, SyntaxError):
        pass
    raise ValueError(f"Could not extract JSON from: {text[:200]}")


def parse_m3a_action(text: str) -> Tuple[Dict, str]:
    """Parse M3A response into (action_dict, reason).

    Expected format:
        Reason: ...
        Action: {"action_type": ...}

    Returns:
        (action_dict, reason_str)
    Raises ValueError on parse failure.
    """
    reason = ""
    action_str = ""

    if "Reason:" in text:
        after_reason = text.split("Reason:", 1)[1]
        if "Action:" in after_reason:
            reason = after_reason.split("Action:", 1)[0].strip()
        else:
            reason = after_reason.strip()

    if "Action:" in text:
        action_str = text.split("Action:")[-1].strip()
    else:
        raise ValueError(f"No 'Action:' in response: {text[:200]}")

    if not action_str:
        raise ValueError("Empty action after 'Action:'")

    action_dict = _extract_json(action_str)
    if "action_type" not in action_dict:
        raise ValueError(f"action_type missing in parsed JSON: {action_dict}")
    return action_dict, reason


def _build_action_selection_prompt(
    goal: str,
    history: List[str],
    ui_elements_text: str,
    additional_guidelines: Optional[List[str]] = None,
) -> str:
    """Build the M3A action selection prompt text."""
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
        ui_elements=ui_elements_text,
        additional_guidelines=extra,
    )


def _build_summary_prompt(
    action: str,
    reason: str,
    goal: str,
    before_elements: str,
    after_elements: str,
) -> str:
    """Build the M3A summarization prompt text."""
    return SUMMARY_PROMPT_TEMPLATE.format(
        goal=goal,
        before_elements=before_elements,
        after_elements=after_elements,
        action=action,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Helper: build observation messages (text prompt + two images)
# ---------------------------------------------------------------------------

def _build_observation_messages(
    prompt_text: str,
    raw_screenshot: np.ndarray,
    som_screenshot: np.ndarray,
    min_pixels: int,
    max_pixels: int,
) -> List[Dict]:
    """Build a user message list with text prompt and two screenshots."""
    raw_b64 = numpy_to_base64(raw_screenshot)
    som_b64 = numpy_to_base64(som_screenshot)
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_text},
            {
                "type": "image",
                "image": f"data:image/png;base64,{raw_b64}",
                "min_pixels": min_pixels,
                "max_pixels": max_pixels,
            },
            {
                "type": "image",
                "image": f"data:image/png;base64,{som_b64}",
                "min_pixels": min_pixels,
                "max_pixels": max_pixels,
            },
        ],
    }]


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class AndroidM3AAgent(AndroidAgent):
    """M3A (Multimodal Autonomous Agent for Android) in the skyrl-agent framework.

    Each step:
      1. Draw SOM marks on the current screenshot
      2. Build an action selection prompt with goal, history, UI elements
      3. Send raw + SOM screenshots to the LLM
      4. Parse Reason + Action JSON
      5. Execute action via android_env tool
      6. Optionally summarize the step via a second LLM call
      7. Append step summary to history
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.screen_width = DEFAULT_SCREEN_WIDTH
        self.screen_height = DEFAULT_SCREEN_HEIGHT
        self.goal = ""
        self.history: List[str] = []
        self.additional_guidelines: Optional[List[str]] = None
        self.enable_summarization = False

    # ------------------------------------------------------------------
    # Initial instruction
    # ------------------------------------------------------------------

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Build the first set of messages with M3A prompt and initial screenshots."""
        self.goal = (observation or {}).get("task", "") or getattr(task, "goal", "")
        ui_elements = (observation or {}).get("ui_elements", [])

        image = (observation or {}).get("image")
        if image is not None and isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]
        else:
            image = np.zeros((self.screen_height, self.screen_width, 3), dtype=np.uint8)

        screen_size = (self.screen_width, self.screen_height)
        ui_text = generate_ui_elements_description(ui_elements, screen_size)
        som_img = draw_som_marks(image, ui_elements, screen_size)

        prompt_text = _build_action_selection_prompt(
            self.goal, [], ui_text, self.additional_guidelines,
        )

        # System prompt from template_messages or default
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

        system_msg = {"role": "system", "content": [{"type": "text", "text": system_prompt}]}
        obs_msgs = _build_observation_messages(
            prompt_text, image, som_img, self.min_pixels, self.max_pixels,
        )
        return [system_msg] + obs_msgs

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Single M3A step: action selection -> execute -> (optional) summarize."""
        self.state.step_count += 1
        print(
            f"[M3AAgent Step {self.state.step_count}] "
            f"instance={self.state.instance_id} traj={self.state.trajectory_id}"
        )

        # 1. Select messages for inference
        selected_messages = self.memory.get_inference_messages(self.state.messages)

        # 2. Tokenize & extract images
        inference_input_ids = self.prepare_input_ids(selected_messages)
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
            print(f"[M3AAgent] Stopping reason: {stop_reason}. Stopping agent.")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        # 4. Parse M3A action
        try:
            action_dict, reason = parse_m3a_action(response_str)
            self.state.format_reward = 0.0
        except Exception as e:
            print(f"[M3AAgent] Parse error: {e}")
            print(f"[M3AAgent] Raw response: {response_str[:500]}")
            self.state.format_reward = -1.0
            action_dict = {"action_type": "status", "goal_status": "infeasible"}
            reason = f"Parse error: {response_str[:200]}"

        action_str = json.dumps(action_dict)

        # 5. Execute via AndroidEnvTool
        tool = self.tools["android_env"]

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

        # 6. Build step summary
        summary = f"Action selected: {action_str}. Reason: {reason}"

        if self.enable_summarization and not terminated and not truncated:
            summary = await self._summarize_step(
                action_str, reason, after_ui_elements, output,
            )

        self.history.append(
            f"Step {self.state.step_count}- {summary}"
        )

        # 7. Record step for trajectory saving
        self.state.step_records.append({
            "step_idx": self.state.step_count,
            "thought": reason,
            "raw_response": response_str,
            "action_type": action_dict.get("action_type", "unknown"),
            "action_params": {k: v for k, v in action_dict.items() if k != "action_type"},
            "command_output": None,
            "a11y_tree": None,
            "screenshot_idx": len(self.state.images),
            "input_tokens": len(_prompt_token_ids),
            "output_tokens": len(response_token_ids),
        })

        # 8. Update conversation messages (assistant response)
        self.state.messages = self.append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            finish_reason = "FINISH" if terminated else "TRUNCATED"
            return True, finish_reason, self.state.reward

        # 9. Build next observation
        image = output.get("image")
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        if isinstance(image, np.ndarray) and image.ndim >= 2:
            self.screen_height, self.screen_width = image.shape[:2]

        screen_size = (self.screen_width, self.screen_height)
        ui_text = generate_ui_elements_description(after_ui_elements, screen_size)
        som_img = draw_som_marks(image, after_ui_elements, screen_size)

        prompt_text = _build_action_selection_prompt(
            self.goal, self.history, ui_text, self.additional_guidelines,
        )

        obs_msgs = _build_observation_messages(
            prompt_text, image, som_img, self.min_pixels, self.max_pixels,
        )
        self.state.messages = self.state.messages + obs_msgs
        self.state.images.append(image)

        # 10. Training accumulator
        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids,
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None

    # ------------------------------------------------------------------
    # Optional summarization (second LLM call)
    # ------------------------------------------------------------------

    async def _summarize_step(
        self,
        action_str: str,
        reason: str,
        after_ui_elements: List[Dict],
        output: Dict,
    ) -> str:
        """Call the LLM a second time to summarize the step."""
        after_image = output.get("image")
        if after_image is None:
            return f"Action selected: {action_str}. Reason: {reason}"

        screen_size = (self.screen_width, self.screen_height)

        # Reconstruct "before" info from the last observation in messages
        before_elements_text = "Not available"
        after_elements_text = generate_ui_elements_description(
            after_ui_elements, screen_size,
        )

        summary_text = _build_summary_prompt(
            action_str, reason, self.goal,
            before_elements_text, after_elements_text,
        )

        # Build summary messages with before/after screenshots
        before_img = self.state.images[-1] if self.state.images else after_image
        before_labeled = add_screenshot_label(before_img, "before")
        after_som = draw_som_marks(after_image, after_ui_elements, screen_size)
        after_labeled = add_screenshot_label(after_som, "after")

        summary_messages = [
            {"role": "system", "content": [{"type": "text", "text": "You are a helpful assistant."}]},
        ] + _build_observation_messages(
            summary_text, before_labeled, after_labeled,
            self.min_pixels, self.max_pixels,
        )

        summary_input_ids = self.prepare_input_ids(summary_messages)
        summary_image_data = self.extract_images_for_inference(summary_messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params.pop("max_tokens", None)

        try:
            result = await self.infer_engine.async_generate_ids(
                input_ids=summary_input_ids,
                sampling_params=sampling_params,
                request_id=self.agent_id + "_summary",
                image_data=summary_image_data,
                return_token_ids=True,
                messages=summary_messages,
            )
            summary_response, _, summary_prompt_ids, summary_resp_ids = result
            self.state.total_input_tokens += len(summary_prompt_ids)
            self.state.total_output_tokens += len(summary_resp_ids)
            return f"Action selected: {action_str}. {summary_response.strip()}"
        except Exception as e:
            print(f"[M3AAgent] Summarization failed: {e}")
            return f"Action selected: {action_str}. Reason: {reason}"
