"""
Prompt message builders for each MobileUse sub-agent.

Each ``build_*_messages()`` function constructs a list of OpenAI-format
messages that can be fed directly to ``infer_engine.async_generate_ids()``
or the chat API.

Image handling: numpy → PIL → smart_resize() → base64 → image content block.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml
from PIL import Image

from .utils import diff_image, encode_image_base64, numpy_to_pil, smart_resize

# ---------------------------------------------------------------------------
# Prompt template loading
# ---------------------------------------------------------------------------

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompt_templates")
_PROMPT_CACHE: Dict[str, Dict] = {}

# Qwen2.5-VL vision placeholder tokens
IMAGE_PLACEHOLDER = "<|vision_start|><|image_pad|><|vision_end|>"


def load_prompt_config(yaml_name: str) -> Dict[str, str]:
    """Load a YAML prompt template from the ``prompt_templates/`` directory.

    Results are cached for the process lifetime.
    """
    if yaml_name not in _PROMPT_CACHE:
        path = os.path.join(_PROMPT_DIR, yaml_name)
        with open(path, "r") as f:
            _PROMPT_CACHE[yaml_name] = yaml.safe_load(f)
    return _PROMPT_CACHE[yaml_name]


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _make_image_content(
    image_np: np.ndarray,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> Dict:
    """Create an OpenAI-format image content block from a numpy array."""
    pil_img = numpy_to_pil(image_np)
    b64_url = encode_image_base64(pil_img)
    return {
        "type": "image_url",
        "image_url": {"url": b64_url},
        "min_pixels": min_pixels,
        "max_pixels": max_pixels,
    }


def _generate_message(
    role: str,
    prompt: str,
    images: Optional[List[np.ndarray]] = None,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> Dict:
    """Build a single message dict, splitting text on IMAGE_PLACEHOLDER to
    interleave images.

    Matches MobileUse's ``generate_message()`` utility.
    """
    content: List[Dict] = []
    parts = prompt.split(IMAGE_PLACEHOLDER)

    for i, part in enumerate(parts):
        if part.strip():
            content.append({"type": "text", "text": part})
        if images and i < len(parts) - 1 and i < len(images):
            content.append(_make_image_content(images[i], min_pixels, max_pixels))

    if not content:
        content.append({"type": "text", "text": prompt})

    return {"role": role, "content": content}


# ---------------------------------------------------------------------------
# History formatter (matches MobileUse get_history)
# ---------------------------------------------------------------------------

def format_history(
    step_history: List[Dict],
    num_histories: Optional[int] = None,
) -> str:
    """Format step history list into a text block for prompts.

    Each entry in ``step_history`` is a dict with keys:
    ``action_desc``, ``action_str``, ``summary`` (optional),
    ``reflection_outcome`` / ``reflection_error`` (optional),
    ``traj_reflection_outcome`` / ``traj_reflection_error`` (optional).

    Matches original MobileUse ``get_history()`` which includes
    trajectory reflection feedback as an elif fallback.
    """
    if not step_history:
        return "None"

    items = step_history if num_histories is None else step_history[-num_histories:]
    lines: List[str] = []
    for i, step in enumerate(items):
        idx = step.get("step_idx", i + 1)
        desc = step.get("action_desc", "")
        action_s = step.get("action_str", "")
        summary = step.get("summary", "")
        refl_outcome = step.get("reflection_outcome")
        refl_error = step.get("reflection_error")
        traj_outcome = step.get("traj_reflection_outcome")
        traj_error = step.get("traj_reflection_error")

        step_parts: List[str] = []
        step_parts.append(f"Action: {desc}")
        step_parts.append(f"<tool_call> {action_s} </tool_call>")
        if summary:
            step_parts.append(f"Summary: {summary}")
        # Reflection feedback (with trajectory reflection as elif fallback)
        if refl_outcome is not None:
            if refl_outcome == "A":
                step_parts.append("Successful")
            elif refl_outcome in ("B", "C"):
                step_parts.append("Failed")
                step_parts.append(f"Feedback: {refl_error}")
        elif traj_outcome is not None:
            if traj_outcome == "A":
                step_parts.append("Successful")
            elif traj_outcome == "B":
                step_parts.append("Failed")
                step_parts.append(f"Feedback: {traj_error}")
        lines.append(f"Step-{idx}: {'; '.join(step_parts)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Operator messages
# ---------------------------------------------------------------------------

def build_operator_messages(
    goal: str,
    plan: str,
    subgoal: str,
    step_history: List[Dict],
    memory: str,
    reflection: Optional[Dict],
    traj_reflection: Optional[Dict],
    global_reflection: Optional[str],
    progress: str,
    screenshot_np: np.ndarray,
    resized_w: int,
    resized_h: int,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
    device_time: Optional[str] = None,
    enable_planner: bool = True,
) -> Tuple[List[Dict], Tuple[int, int], Tuple[int, int]]:
    """Build operator prompt messages from scratch (MobileUse rebuilds every step).

    Returns:
        ``(messages, resized_size, raw_size)`` where sizes are ``(w, h)``
        tuples used later for coordinate scaling.
    """
    cfg = load_prompt_config("operator.yaml")

    raw_h, raw_w = screenshot_np.shape[:2]
    raw_size = (raw_w, raw_h)
    resized_size = (resized_w, resized_h)

    # System message with tool definition
    system_text = cfg["system_prompt"].format(
        resized_width=resized_w, resized_height=resized_h,
    )
    system_msg = {"role": "system", "content": [{"type": "text", "text": system_text}]}

    # Build user prompt sections (order matches original MobileUse)
    sections: List[str] = []

    # Task
    sections.append(cfg["task_prompt"].format(task_description=goal))

    # Device time
    if device_time is None:
        device_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections.append(cfg["device_time_prompt"].format(device_time=device_time))

    # Plan & subgoal (only if planner is enabled)
    if enable_planner and plan:
        sections.append(cfg["plan_prompt"].format(plan=plan))
    if enable_planner and subgoal:
        sections.append(cfg["subgoal_prompt"].format(subgoal=subgoal))

    # History (always included; empty → "No actions have been taken yet.")
    if step_history:
        history_text = format_history(step_history)
    else:
        history_text = "No actions have been taken yet."
    sections.append(cfg["history_prompt"].format(history=history_text))

    # Progress
    if progress:
        sections.append(cfg["progress_prompt"].format(progress=progress))

    # Memory
    if memory:
        sections.append(cfg["memory_prompt"].format(memory=memory))

    # Reflection feedback
    if reflection and reflection.get("outcome") in ("B", "C"):
        sections.append(cfg["reflection_prompt"].format(
            action_desc=reflection.get("action_desc", ""),
            action_s=reflection.get("action_str", ""),
            reflection_error=reflection.get("error", ""),
        ))

    # Trajectory reflection feedback
    if traj_reflection and traj_reflection.get("outcome") == "B":
        sections.append(cfg["trajectory_reflection_prompt"].format(
            trajectory_reflection_error=traj_reflection.get("error", ""),
        ))

    # Global reflection feedback
    if global_reflection:
        sections.append(cfg["global_reflection_prompt"].format(
            global_reflection_error=global_reflection,
        ))

    # Observation with screenshot
    obs_text = cfg["observation_prompt"].format(
        resized_width=resized_w,
        resized_height=resized_h,
        image_placeholder=IMAGE_PLACEHOLDER,
    )
    sections.append(obs_text)

    # Tips (placed near end, matching original MobileUse ordering)
    sections.append(cfg["init_tips"])

    # Response format
    sections.append(cfg["response_prompt"])

    user_text = "\n\n".join(sections)
    user_msg = _generate_message(
        "user", user_text, images=[screenshot_np],
        min_pixels=min_pixels, max_pixels=max_pixels,
    )

    return [system_msg, user_msg], resized_size, raw_size


# ---------------------------------------------------------------------------
# Planner messages
# ---------------------------------------------------------------------------

def build_planner_messages(
    goal: str,
    screenshot_np: np.ndarray,
    resized_w: int,
    resized_h: int,
    current_plan: Optional[str] = None,
    previous_subgoal: Optional[str] = None,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> List[Dict]:
    """Build planner prompt messages."""
    cfg = load_prompt_config("planner.yaml")

    system_msg = {"role": "system", "content": [{"type": "text", "text": cfg["system_prompt"]}]}

    # Task + screenshot section
    task_text = cfg["task_prompt"].format(
        task_description=goal,
        screenshot=IMAGE_PLACEHOLDER,
        resized_width=resized_w,
        resized_height=resized_h,
    )

    # Init or continue
    if current_plan is None:
        instruction = cfg["init_plan"]
    else:
        instruction = cfg["continue_plan"].format(
            current_plan=current_plan,
            previous_subgoal=previous_subgoal or "",
        )

    user_text = task_text + "\n\n" + instruction
    user_msg = _generate_message(
        "user", user_text, images=[screenshot_np],
        min_pixels=min_pixels, max_pixels=max_pixels,
    )

    return [system_msg, user_msg]


# ---------------------------------------------------------------------------
# Reflector messages
# ---------------------------------------------------------------------------

def build_reflector_messages(
    goal: str,
    subgoal: str,
    before_screenshot_np: np.ndarray,
    after_screenshot_np: np.ndarray,
    action_str: str,
    action_desc: str,
    resized_w: int,
    resized_h: int,
    same_image: bool = False,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> List[Dict]:
    """Build reflector prompt messages with before/after screenshots.

    When the screenshots differ, computes a visual diff and annotates
    both images with red bounding boxes (matching original MobileUse).
    """
    cfg = load_prompt_config("reflector.yaml")

    system_msg = {"role": "system", "content": [{"type": "text", "text": cfg["system_prompt"]}]}

    # Compute visual diff (red boxes on changed regions)
    diff_flag = False
    if not same_image:
        annotated_before, annotated_after = diff_image(
            before_screenshot_np.copy(), after_screenshot_np.copy(),
        )
        if annotated_before is not None:
            before_screenshot_np = annotated_before
            after_screenshot_np = annotated_after
            diff_flag = True

    sections: List[str] = []
    sections.append(cfg["task_prompt"].format(task_description=goal))
    sections.append(cfg["subgoal_prompt"].format(subgoal=subgoal))

    # Observation with two screenshots
    obs_text = cfg["observation_prompt"].format(
        screenshot1=IMAGE_PLACEHOLDER,
        screenshot2=IMAGE_PLACEHOLDER,
        resized_width=resized_w,
        resized_height=resized_h,
    )
    sections.append(obs_text)

    if same_image:
        sections.append(cfg["same_image_prompt"])
    elif diff_flag:
        sections.append(cfg["diff_image_prompt"])

    sections.append(cfg["expection_prompt"].format(
        action_s=action_str,
        action_desc=action_desc,
    ))
    sections.append(cfg["response_prompt"])

    user_text = "\n\n".join(sections)
    user_msg = _generate_message(
        "user", user_text,
        images=[before_screenshot_np, after_screenshot_np],
        min_pixels=min_pixels, max_pixels=max_pixels,
    )

    return [system_msg, user_msg]


# ---------------------------------------------------------------------------
# Trajectory reflector messages
# ---------------------------------------------------------------------------

def build_trajectory_reflector_messages(
    goal: str,
    plan: str,
    step_history: List[Dict],
    progress: str,
    recent_screenshots: List[np.ndarray],
    resized_w: int,
    resized_h: int,
    error_info: Optional[str] = None,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> List[Dict]:
    """Build trajectory reflector messages with recent screenshots."""
    cfg = load_prompt_config("trajectory_reflector.yaml")

    system_msg = {"role": "system", "content": [{"type": "text", "text": cfg["system_prompt"]}]}

    sections: List[str] = []
    sections.append(cfg["task_prompt"].format(task_description=goal))

    if plan:
        sections.append(cfg["plan_prompt"].format(plan=plan))

    history_text = format_history(step_history)
    sections.append(cfg["history_prompt"].format(history=history_text))

    if progress:
        sections.append(cfg["progress_prompt"].format(progress=progress))

    # Build image placeholders for multiple screenshots
    placeholders = " ".join([IMAGE_PLACEHOLDER] * len(recent_screenshots))
    obs_text = cfg["observation_prompt"].format(
        resized_width=resized_w,
        resized_height=resized_h,
        image_placeholders=placeholders,
    )
    sections.append(obs_text)

    if error_info:
        sections.append(cfg["error_info_prompt"].format(error=error_info))

    sections.append(cfg["response_prompt"])

    user_text = "\n\n".join(sections)
    user_msg = _generate_message(
        "user", user_text, images=recent_screenshots,
        min_pixels=min_pixels, max_pixels=max_pixels,
    )

    return [system_msg, user_msg]


# ---------------------------------------------------------------------------
# Global reflector messages
# ---------------------------------------------------------------------------

def build_global_reflector_messages(
    goal: str,
    plan: str,
    step_history: List[Dict],
    progress: str,
    recent_screenshots: List[np.ndarray],
    resized_w: int,
    resized_h: int,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> List[Dict]:
    """Build global reflector messages."""
    cfg = load_prompt_config("global_reflector.yaml")

    system_msg = {"role": "system", "content": [{"type": "text", "text": cfg["system_prompt"]}]}

    sections: List[str] = []
    sections.append(cfg["task_prompt"].format(task_description=goal))

    if plan:
        sections.append(cfg["plan_prompt"].format(plan=plan))

    history_text = format_history(step_history)
    sections.append(cfg["history_prompt"].format(history=history_text))

    if progress:
        sections.append(cfg["progress_prompt"].format(progress=progress))

    placeholders = " ".join([IMAGE_PLACEHOLDER] * len(recent_screenshots))
    obs_text = cfg["observation_prompt"].format(
        resized_width=resized_w,
        resized_height=resized_h,
        image_placeholders=placeholders,
    )
    sections.append(obs_text)
    sections.append(cfg["response_prompt"])

    user_text = "\n\n".join(sections)
    user_msg = _generate_message(
        "user", user_text, images=recent_screenshots,
        min_pixels=min_pixels, max_pixels=max_pixels,
    )

    return [system_msg, user_msg]


# ---------------------------------------------------------------------------
# Progressor messages
# ---------------------------------------------------------------------------

def build_progressor_messages(
    goal: str,
    step_history: List[Dict],
    progress: str,
    thought: str,
    action_desc: str,
    action_str: str,
    reflection_error: Optional[str] = None,
) -> List[Dict]:
    """Build progressor messages (text only, no screenshots)."""
    cfg = load_prompt_config("progressor.yaml")

    system_msg = {"role": "system", "content": [{"type": "text", "text": cfg["system_prompt"]}]}

    sections: List[str] = []
    # Note: task_prompt is intentionally excluded here, matching original
    # MobileUse which has it commented out in the progressor.

    if not progress:
        # First step: use init template
        sections.append(cfg["init_progress"].format(
            thought=thought,
            action_desc=action_desc,
            action=action_str,
        ))
    else:
        # Continuation
        history_text = format_history(step_history)
        sections.append(cfg["continue_progress_start"].format(
            history=history_text,
            progress=progress,
            action_desc=action_desc,
            action=action_str,
        ))
        if reflection_error:
            sections.append(cfg["continue_progress_reflection"].format(
                reflection_error=reflection_error,
            ))
        sections.append(cfg["continue_progress_response"])

    user_text = "\n\n".join(sections)
    user_msg = {"role": "user", "content": [{"type": "text", "text": user_text}]}

    return [system_msg, user_msg]


# ---------------------------------------------------------------------------
# Answer agent messages
# ---------------------------------------------------------------------------

def build_answer_messages(
    goal: str,
    plan: str,
    subgoal: str,
    step_history: List[Dict],
    memory: str,
    progress: str,
    screenshot_np: np.ndarray,
    resized_w: int,
    resized_h: int,
    reflection: Optional[Dict] = None,
    traj_reflection: Optional[Dict] = None,
    global_reflection: Optional[str] = None,
    device_time: Optional[str] = None,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> List[Dict]:
    """Build answer agent messages (same structure as operator but answer-only)."""
    cfg = load_prompt_config("answer_agent.yaml")

    system_text = cfg["system_prompt"].format(
        resized_width=resized_w, resized_height=resized_h,
    )
    system_msg = {"role": "system", "content": [{"type": "text", "text": system_text}]}

    sections: List[str] = []

    sections.append(cfg["init_tips"])
    sections.append(cfg["task_prompt"].format(task_description=goal))

    if device_time is None:
        device_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections.append(cfg["device_time_prompt"].format(device_time=device_time))

    if plan:
        sections.append(cfg["plan_prompt"].format(plan=plan))
    if subgoal:
        sections.append(cfg["subgoal_prompt"].format(subgoal=subgoal))

    if step_history:
        history_text = format_history(step_history)
        sections.append(cfg["history_prompt"].format(history=history_text))

    if progress:
        sections.append(cfg["progress_prompt"].format(progress=progress))

    if memory:
        sections.append(cfg["memory_prompt"].format(memory=memory))

    if reflection and reflection.get("outcome") in ("B", "C"):
        sections.append(cfg["reflection_prompt"].format(
            action_desc=reflection.get("action_desc", ""),
            action_s=reflection.get("action_str", ""),
            reflection_error=reflection.get("error", ""),
        ))

    if traj_reflection and traj_reflection.get("outcome") == "B":
        sections.append(cfg["trajectory_reflection_prompt"].format(
            long_reflection_error=traj_reflection.get("error", ""),
        ))

    if global_reflection:
        sections.append(cfg["global_reflection_prompt"].format(
            global_reflection_error=global_reflection,
        ))

    obs_text = cfg["observation_prompt"].format(
        resized_width=resized_w,
        resized_height=resized_h,
        image_placeholder=IMAGE_PLACEHOLDER,
    )
    sections.append(obs_text)

    sections.append(cfg["response_prompt"].format(goal=goal))

    user_text = "\n\n".join(sections)
    user_msg = _generate_message(
        "user", user_text, images=[screenshot_np],
        min_pixels=min_pixels, max_pixels=max_pixels,
    )

    return [system_msg, user_msg]
