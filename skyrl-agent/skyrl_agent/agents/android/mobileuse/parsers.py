"""
Response parsers for each MobileUse sub-agent.

Each parser takes the raw LLM response string and returns structured data.
Parsing logic matches MobileUse's ``sub_agent.py`` parse_response methods.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

from .utils import map_action_names


# ---------------------------------------------------------------------------
# Operator parser
# ---------------------------------------------------------------------------

def parse_operator_response(
    content: str,
    resized_size: Tuple[int, int],
    raw_size: Tuple[int, int],
) -> Tuple[str, Dict, str, str]:
    """Parse operator LLM response into thought + action.

    The operator outputs::

        Thought: ...
        Action: ...
        <tool_call>
        {"name": "mobile_use", "arguments": {"action": "click", "coordinate": [x, y]}}
        </tool_call>

    Coordinates in the response are in *resized_size* space (what Qwen sees).
    We scale them to *raw_size* (actual device pixels).

    Args:
        content: Raw LLM response string.
        resized_size: ``(width, height)`` of the resized image shown to the VLM.
        raw_size: ``(width, height)`` of the actual device screen.

    Returns:
        ``(thought, action_dict, action_str, action_desc)``
        - thought: The "Thought:" line.
        - action_dict: Parsed action with raw-pixel coordinates,
          e.g. ``{"action": "click", "coordinate": [540, 1200]}``.
        - action_str: The raw ``<tool_call>`` JSON string (for logging).
        - action_desc: The "Action:" line (human-readable description).

    Raises:
        ValueError: If no valid ``<tool_call>`` block is found.
    """
    # Extract thought
    thought_match = re.search(r"Thought:\s*(.*?)(?:\nAction:|\n<tool_call>|$)", content, re.DOTALL)
    thought = thought_match.group(1).strip() if thought_match else ""

    # Extract action description
    desc_match = re.search(r"Action:\s*(.*?)(?:\n<tool_call>|$)", content, re.DOTALL)
    action_desc = desc_match.group(1).strip() if desc_match else ""

    # Extract tool_call JSON
    tc_match = re.search(
        r'{"name":\s*"mobile_use",(.*?)}}',
        content,
        flags=re.DOTALL,
    )
    if tc_match is None:
        raise ValueError(f"No <tool_call> found in operator response: {content[:300]}")

    action_str = '{"name": "mobile_use",' + tc_match.group(1).strip() + "}}"

    try:
        action_json = json.loads(action_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in tool_call: {action_str[:300]}") from exc

    arguments = action_json.get("arguments", {})

    # Normalize parameter names (e.g. start_box → coordinate)
    normalized: Dict = {}
    for key, value in arguments.items():
        normalized[map_action_names(key)] = value

    # Scale coordinates from resized space to raw space
    rw, rh = resized_size   # resized
    pw, ph = raw_size        # raw pixels
    for coord_key in ("coordinate", "coordinate2"):
        if coord_key in normalized:
            v = normalized[coord_key]
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                x = round(v[0] / rw * pw)
                y = round(v[1] / rh * ph)
                normalized[coord_key] = [x, y]

    # Build clean action dict
    action_dict = {"action": normalized.get("action", "wait")}
    for k in ("coordinate", "coordinate2", "text", "time", "button", "status"):
        if k in normalized:
            action_dict[k] = normalized[k]

    return thought, action_dict, action_str, action_desc


# ---------------------------------------------------------------------------
# Planner parser
# ---------------------------------------------------------------------------

def parse_planner_response(content: str) -> Tuple[str, str, str]:
    """Parse planner response into thought, plan, and current subgoal.

    Expected format::

        ### Thought ###
        ...
        ### Plan ###
        1. ...
        2. ...
        ### Current Subgoal ###
        ...

    Returns:
        ``(thought, plan, subgoal)``
    """
    thought = _extract_section(content, "Thought")
    plan = _extract_section(content, "Plan")
    subgoal = _extract_section(content, "Current Subgoal")
    return thought, plan, subgoal


# ---------------------------------------------------------------------------
# Reflector parser
# ---------------------------------------------------------------------------

def parse_reflector_response(content: str) -> Tuple[str, str]:
    """Parse reflector response into outcome and error description.

    Expected format::

        ### Outcome ###
        A: Successful ...
        ### Error Description ###
        None

    Returns:
        ``(outcome, error_desc)`` where outcome is one of "A", "B", "C", "D".
    """
    outcome_section = _extract_section(content, "Outcome")
    error_desc = _extract_section(content, "Error Description")

    # Extract the letter grade
    outcome = "D"  # default: uncertain
    match = re.search(r"\b([ABCD])\b", outcome_section)
    if match:
        outcome = match.group(1)

    return outcome, error_desc


# ---------------------------------------------------------------------------
# Trajectory reflector parser
# ---------------------------------------------------------------------------

def parse_trajectory_reflector_response(content: str) -> Tuple[str, str]:
    """Parse trajectory reflector response.

    Returns:
        ``(outcome, error_desc)`` where outcome is "A" or "B".
    """
    outcome_section = _extract_section(content, "Outcome")
    error_desc = _extract_section(content, "Error Description")

    outcome = "A"  # default: successful
    match = re.search(r"\b([AB])\b", outcome_section)
    if match:
        outcome = match.group(1)

    return outcome, error_desc


# ---------------------------------------------------------------------------
# Global reflector parser
# ---------------------------------------------------------------------------

def parse_global_reflector_response(content: str) -> Tuple[str, str]:
    """Parse global reflector response.

    Expected format::

        ### Result ###
        Success / Failed / Uncertain
        ### Reason ###
        ...

    Returns:
        ``(result, reason)`` where result is "Success", "Failed", or "Uncertain".
    """
    result_section = _extract_section(content, "Result")
    reason = _extract_section(content, "Reason")

    result = "Uncertain"
    for label in ("Success", "Failed", "Uncertain"):
        if label.lower() in result_section.lower():
            result = label
            break

    return result, reason


# ---------------------------------------------------------------------------
# Progressor parser
# ---------------------------------------------------------------------------

def parse_progressor_response(content: str) -> str:
    """Parse progressor response into progress string.

    Expected format::

        ### Completed contents ###
        ...

    Returns:
        Progress summary string.
    """
    progress = _extract_section(content, "Completed contents")
    if not progress:
        # Fallback: return the entire content stripped
        progress = content.strip()
    return progress


# ---------------------------------------------------------------------------
# Answer agent parser
# ---------------------------------------------------------------------------

def parse_answer_response(content: str) -> str:
    """Parse answer agent response to extract the answer text.

    The answer agent outputs a ``<tool_call>`` with action=answer and text=<answer>.
    Falls back to extracting any text after "Answer:" or the full content.

    Returns:
        The answer text string.
    """
    # Try to extract from tool_call JSON
    tc_match = re.search(
        r'{"name":\s*"mobile_use",(.*?)}}',
        content,
        flags=re.DOTALL,
    )
    if tc_match:
        try:
            action_str = '{"name": "mobile_use",' + tc_match.group(1).strip() + "}}"
            action_json = json.loads(action_str)
            text = action_json.get("arguments", {}).get("text", "")
            if text:
                return text
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: look for text in quotes after "text":
    text_match = re.search(r'"text"\s*:\s*"(.*?)"', content, re.DOTALL)
    if text_match:
        return text_match.group(1)

    # Last resort: return trimmed content
    return content.strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_section(text: str, header: str) -> str:
    """Extract the content under a ``### Header ###`` section.

    Looks for ``### {header} ###`` and returns everything until the next
    ``###`` header or end of string.
    """
    pattern = rf"###\s*{re.escape(header)}\s*###\s*(.*?)(?=###|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
