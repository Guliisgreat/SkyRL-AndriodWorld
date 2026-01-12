"""
Android agent utilities - pure functions for parsing, formatting, and selection.

These functions are extracted from AndroidAgent for:
- Testability: Test parsing without instantiating agent
- Reusability: Other agents can use select_messages()
- Clarity: Separates utilities from orchestration logic
"""

import io
import re
import base64
from typing import List, Dict, Tuple, Any
from PIL import Image
import numpy as np


# === MESSAGE UTILITIES ===

def init_messages(instruction: List[Dict]) -> List[Dict]:
    """
    Initialize messages from instruction.
    
    Args:
        instruction: Initial messages in OpenAI format
        
    Returns:
        New message list (copy of instruction)
    """
    return list(instruction)


def select_messages(
    messages: List[Dict],
    mode: str = "full",
    last_n: int = 2,
    start_idx: int = 0,
) -> List[Dict]:
    """
    Select messages based on memory mode.
    
    Args:
        messages: Full message list
        mode: Selection mode
            - "full": All messages
            - "last_n": Last N messages
            - "last_step": Last 2 messages (assistant + observation)
            - "incremental": Messages from start_idx onwards
        last_n: Number of messages for "last_n" mode
        start_idx: Starting index for "incremental" mode
        
    Returns:
        Selected subset of messages
    """
    if mode == "full":
        return messages
    elif mode == "last_n":
        return messages[-last_n:] if len(messages) > last_n else messages
    elif mode == "last_step":
        return messages[-2:] if len(messages) > 2 else messages
    elif mode == "incremental":
        return messages[start_idx:]
    return messages


def load_content(content: Any) -> str:
    """
    Load content from message for processing.
    
    Handles string, list, and dict content types.
    
    Args:
        content: Message content (str, list, or dict)
        
    Returns:
        Extracted text content with image placeholders
    """
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        return ''.join([load_content(c) for c in content])
    
    if isinstance(content, dict):
        if "text" in content:
            return content["text"]
        elif "image" in content:
            return "<|vision_start|><|image_pad|><|vision_end|>"
    
    return ""


# === IMAGE UTILITIES ===

def numpy_to_base64(nparray: np.ndarray) -> str:
    """
    Convert numpy array to base64 string.
    
    Args:
        nparray: Image as numpy array
        
    Returns:
        Base64-encoded PNG string
    """
    image = Image.fromarray(nparray)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# === UI-TARS ACTION PARSING ===

def parse_uitars_action(text: str) -> Tuple[Dict, str]:
    """
    Parse UI-TARS 'Thought: ... Action: ...' format to action dict.

    Refactored from mobile_agent.py lines 54-120.

    Args:
        text: Raw model output containing Thought and Action

    Returns:
        (action_dict, thought_str)

    Raises:
        ValueError: If action format is not supported or text is malformed
    """
    # Defensive parsing for Thought
    thought_str = ""
    if "Thought:" in text:
        thought_parts = text.split("Thought:", 1)
        if len(thought_parts) > 1:
            # Extract thought (everything between "Thought:" and "Action:" or end)
            thought_section = thought_parts[1]
            if "Action:" in thought_section:
                thought_str = thought_section.split("Action:", 1)[0].strip()
            else:
                thought_str = thought_section.strip()

    # Defensive parsing for Action
    if "Action:" not in text:
        raise ValueError(f"No 'Action:' found in model output: {text[:200]}")

    action_str = text.split("Action:")[-1]
    action_str = action_str.replace("'", "")
    action_str = "".join(action_str.split())
    
    action_str = re.sub(r"\\\(", "(", action_str)
    action_str = re.sub(r"\\\)", ")", action_str)
    action_str = re.sub(r"\\\'", "'", action_str)
    
    if match := re.match(r"click\(start_box='?\((\d+),(\d+)\)'?\)", action_str):
        action = {
            "action_type": "click",
            "touch_point": [int(match[1]) / 1000, int(match[2]) / 1000]
        }
    
    elif match := re.match(r"long_press\(start_box='?\((\d+),(\d+)\)'?.*\)", action_str):
        action = {
            "action_type": "long_press",
            "touch_point": [int(match[1]) / 1000, int(match[2]) / 1000]
        }
    
    elif match := re.match(r"type\(content=(.*?)\)", action_str):
        if match_text := re.search(r".*?\(content='?(.*?)'?\).*?", text):
            action = {
                "action_type": "input_text",
                "text": match_text.group(1).strip().replace("'", "")
            }
        else:
            action = {"action_type": "input_text", "text": match[1]}
    
    elif match := re.match(r"answer\(content=(.*?)\)", action_str):
        if match_text := re.search(r".*?\(content='?(.*?)'?\).*?", text):
            action = {
                "action_type": "answer",
                "text": match_text.group(1).strip().replace("'", "")
            }
        else:
            action = {"action_type": "answer", "text": match[1]}
    
    elif match := re.match(
        r"scroll\(start_box='?\((\d+),(\d+)\)'?,end_box='?\((\d+),(\d+)\)'?\)",
        action_str
    ):
        x_start = int(match[1])
        y_start = int(match[2])
        x_end = int(match[3])
        y_end = int(match[4])
        dx = x_start - x_end
        dy = y_start - y_end
        direction = (
            ("right" if dx > 0 else "left")
            if abs(dx) > abs(dy)
            else ("down" if dy > 0 else "up")
        )
        action = {"action_type": "scroll", "direction": direction}
    
    elif re.search(r"press_home", action_str):
        action = {"action_type": "navigate_home"}
    
    elif re.search(r"press_back", action_str):
        action = {"action_type": "navigate_back"}
    
    elif re.search(r"open_app", action_str):
        if match := re.search(r".*?\(content='?(.*?)'?\).*?", text):
            action = {
                "action_type": "open_app",
                "app_name": match.group(1).strip().replace("'", "")
            }
        else:
            raise ValueError(f"Action {action_str} is not supported")
    
    elif re.search(r"finished", action_str):
        action = {"action_type": "status", "goal_status": "complete"}
    
    elif re.search(r"wait", action_str):
        action = {"action_type": "wait"}
    
    else:
        raise ValueError(f"Action {action_str} is not supported")
    
    return action, thought_str


def add_box_token(input_string: str) -> str:
    """
    Add box tokens to coordinates in action strings.
    
    Refactored from mobile_agent.py lines 122-143.
    
    Args:
        input_string: String potentially containing coordinate expressions
    
    Returns:
        String with box tokens added around coordinates
    """
    if "Action: " in input_string and "start_box=" in input_string:
        suffix = input_string.split("Action: ")[0] + "Action: "
        actions = input_string.split("Action: ")[1:]
        processed_actions = []
        
        for action in actions:
            action = action.strip()
            # Extract coordinates (start_box or end_box) using regex
            coordinates = re.findall(
                r"(start_box|end_box)='\((\d+),\s*(\d+)\)'",
                action
            )
            
            updated_action = action
            for coord_type, x, y in coordinates:
                updated_action = updated_action.replace(
                    f"{coord_type}='({x},{y})'",
                    f"{coord_type}='<|box_start|>({x},{y})<|box_end|>'"
                )
            processed_actions.append(updated_action)
        
        final_string = suffix + "\n\n".join(processed_actions)
    else:
        final_string = input_string
    
    return final_string
