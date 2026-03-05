"""
MobileUse utility functions.

- smart_resize: Qwen2.5-VL image dimension calculation (copied from MobileUse)
- mobileuse_action_to_skyrl: Translate MobileUse actions to skyrl-agent format
- numpy_to_pil: Convert numpy screenshot to PIL Image
- encode_image_base64: Encode PIL image as base64 data URL
- is_same_image: Compare two screenshots for similarity
"""

import io
import math
import base64
from typing import Dict, Tuple, Optional

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Image resize (from MobileUse utils/utils.py, matching Qwen2.5-VL)
# ---------------------------------------------------------------------------

def smart_resize(
    height: int,
    width: int,
    factor: int = 28,
    min_pixels: int = 4 * 28 * 28,        # 3136
    max_pixels: int = 16384 * 28 * 28,     # 12845056
) -> Tuple[int, int]:
    """Compute resized dimensions that Qwen2.5-VL expects.

    Copied verbatim from MobileUse to ensure identical image preprocessing.

    Returns:
        (resized_height, resized_width)
    """
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------

def numpy_to_pil(image_np: np.ndarray) -> Image.Image:
    """Convert a numpy array (H, W, 3) screenshot to a PIL Image."""
    return Image.fromarray(image_np)


def encode_image_base64(image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL Image as a base64 data URL string."""
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/{fmt.lower()};base64,{b64}"


def diff_image(
    img1: np.ndarray,
    img2: np.ndarray,
    crop_top_ratio: float = 0.035,
    pixel_threshold: int = 5,
    area_threshold: int = 1000,
    max_boxes: int = 2,
    merge_threshold: int = 20,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Compute visual diff between two screenshots.

    Draws red bounding boxes around changed regions on both images.
    Returns (annotated_img1, annotated_img2) or (None, None) if no
    suitable diff regions are found.

    Matches the original MobileUse ``diff_image()`` from ``utils/utils.py``.
    """
    try:
        import cv2
    except ImportError:
        return None, None

    if img1.shape != img2.shape:
        return None, None

    h = img1.shape[0]
    crop = int(h * crop_top_ratio)

    gray1 = cv2.cvtColor(img1[crop:], cv2.COLOR_RGB2GRAY)
    gray2 = cv2.cvtColor(img2[crop:], cv2.COLOR_RGB2GRAY)

    diff = cv2.absdiff(gray1, gray2)
    _, thresh = cv2.threshold(diff, pixel_threshold, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None

    # Filter by area
    boxes = []
    for cnt in contours:
        x, y, w, bh = cv2.boundingRect(cnt)
        if w * bh >= area_threshold:
            boxes.append([x, y + crop, x + w, y + crop + bh])

    if not boxes:
        return None, None

    # Merge nearby boxes
    def _merge(bxs, gap):
        merged = True
        while merged:
            merged = False
            new_bxs = []
            used = set()
            for i in range(len(bxs)):
                if i in used:
                    continue
                bx = list(bxs[i])
                for j in range(i + 1, len(bxs)):
                    if j in used:
                        continue
                    bj = bxs[j]
                    if (bx[0] - gap <= bj[2] and bx[2] + gap >= bj[0]
                            and bx[1] - gap <= bj[3] and bx[3] + gap >= bj[1]):
                        bx = [min(bx[0], bj[0]), min(bx[1], bj[1]),
                              max(bx[2], bj[2]), max(bx[3], bj[3])]
                        used.add(j)
                        merged = True
                new_bxs.append(bx)
                used.add(i)
            bxs = new_bxs
        return bxs

    boxes = _merge(boxes, merge_threshold)

    # Sort by area desc and keep top N
    boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    boxes = boxes[:max_boxes]

    # If too many large contours, images are too different for annotation
    if len(contours) > 50:
        return None, None

    out1 = img1.copy()
    out2 = img2.copy()
    for bx in boxes:
        # cv2 uses BGR but our images are RGB; red = (255, 0, 0) in RGB
        cv2.rectangle(out1, (bx[0], bx[1]), (bx[2], bx[3]), (255, 0, 0), 3)
        cv2.rectangle(out2, (bx[0], bx[1]), (bx[2], bx[3]), (255, 0, 0), 3)

    return out1, out2


def is_same_image(
    img1: np.ndarray,
    img2: np.ndarray,
    crop_top_ratio: float = 0.035,
) -> bool:
    """Check whether two screenshots are essentially identical.

    Crops the top portion (status bar) before comparison because the clock
    changes between screenshots.  Uses strict grayscale equality matching
    the original MobileUse implementation.
    """
    if img1.shape != img2.shape:
        return False
    h = img1.shape[0]
    crop = int(h * crop_top_ratio)
    # Convert to grayscale and compare strictly (matches original)
    from PIL import Image
    c1 = np.array(Image.fromarray(img1[crop:]).convert("L"))
    c2 = np.array(Image.fromarray(img2[crop:]).convert("L"))
    return np.array_equal(c1, c2)


# ---------------------------------------------------------------------------
# Action name mapping (from MobileUse sub_agent.py)
# ---------------------------------------------------------------------------

_ACTION_NAME_MAP = {
    "left_click": "click",
    "point": "coordinate",
    "start_point": "coordinate",
    "start_box": "coordinate",
    "end_point": "coordinate2",
    "end_box": "coordinate2",
    "scroll": "swipe",
    "content": "text",
    "open_app": "open",
}


def map_action_names(name: str) -> str:
    """Normalize action parameter names from various VLM output styles."""
    return _ACTION_NAME_MAP.get(name, name)


# ---------------------------------------------------------------------------
# Action translation: MobileUse → skyrl-agent
# ---------------------------------------------------------------------------

def _infer_scroll_direction(
    x1: float, y1: float, x2: float, y2: float,
) -> str:
    """Infer scroll direction from swipe start/end coordinates.

    AndroidWorld scroll semantics: ``scroll down`` means the *view* moves
    down the document (finger swipes UP).  So a swipe where dy < 0
    (finger up) maps to ``"down"`` and dy > 0 (finger down) to ``"up"``.
    """
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) > abs(dy):
        return "left" if dx > 0 else "right"
    else:
        return "up" if dy > 0 else "down"


def mobileuse_action_to_skyrl(
    action_dict: Dict,
    screen_w: int,
    screen_h: int,
) -> Dict:
    """Translate a MobileUse action dict to skyrl-agent action format.

    MobileUse actions use raw pixel coordinates; skyrl-agent expects
    normalized [0,1] touch_point values.

    Args:
        action_dict: Parsed MobileUse action with keys like
            ``{"action": "click", "coordinate": [x, y], ...}``
        screen_w: Raw screen width in pixels
        screen_h: Raw screen height in pixels

    Returns:
        skyrl-agent action dict, e.g.
        ``{"action_type": "click", "touch_point": [0.5, 0.3]}``
    """
    action_name = action_dict.get("action", "")
    params = {k: v for k, v in action_dict.items() if k != "action"}

    if action_name == "click":
        coord = params.get("coordinate", [0, 0])
        return {
            "action_type": "click",
            "touch_point": [coord[0] / screen_w, coord[1] / screen_h],
        }

    if action_name == "long_press":
        coord = params.get("coordinate", [0, 0])
        return {
            "action_type": "long_press",
            "touch_point": [coord[0] / screen_w, coord[1] / screen_h],
        }

    if action_name == "swipe":
        coord1 = params.get("coordinate", [0, 0])
        coord2 = params.get("coordinate2", [0, 0])
        direction = _infer_scroll_direction(
            coord1[0], coord1[1], coord2[0], coord2[1],
        )
        return {"action_type": "scroll", "direction": direction}

    if action_name == "type":
        text = params.get("text", "")
        return {"action_type": "input_text", "text": text}

    if action_name == "clear_text":
        # skyrl-agent has no dedicated clear_text; use input_text with
        # empty string as best-effort fallback
        return {"action_type": "input_text", "text": ""}

    if action_name == "open":
        app_name = params.get("text", "")
        return {"action_type": "open_app", "app_name": app_name}

    if action_name == "system_button":
        button = params.get("button", "Home")
        button_map = {
            "Home": "navigate_home",
            "Back": "navigate_back",
            "Enter": "keyboard_enter",
            "Menu": "navigate_home",  # no direct menu in skyrl, fallback
        }
        return {"action_type": button_map.get(button, "navigate_home")}

    if action_name == "key":
        key_text = params.get("text", "")
        # Map common key names to skyrl actions
        key_lower = key_text.lower()
        if key_lower in ("home",):
            return {"action_type": "navigate_home"}
        if key_lower in ("back",):
            return {"action_type": "navigate_back"}
        if key_lower in ("enter",):
            return {"action_type": "keyboard_enter"}
        # Generic fallback: treat as navigate_back
        return {"action_type": "navigate_back"}

    if action_name == "wait":
        return {"action_type": "wait"}

    if action_name == "terminate":
        status = params.get("status", "failure")
        goal_status = "complete" if status == "success" else "infeasible"
        return {"action_type": "status", "goal_status": goal_status}

    if action_name == "answer":
        text = params.get("text", "")
        return {"action_type": "answer", "text": text}

    if action_name == "take_note":
        # take_note is internal to MobileUse; no env execution needed.
        # Return a wait so the step still does something.
        return {"action_type": "wait"}

    # Fallback
    return {"action_type": "wait"}
