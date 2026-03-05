# M3A / T3A Parity Review: skyrl-agent vs Original AndroidWorld

**Date**: 2026-03-03
**Branch**: `feat/cc-baseline-select-gui-agent`
**Related ticket**: ALE-33

## Files Compared

| Component | Original (AndroidWorld) | skyrl-agent |
|---|---|---|
| M3A agent | `aw_g_original/.../agents/m3a.py` (604 lines) | `skyrl_agent/agents/android/android_m3a_agent.py` (776 lines) |
| T3A agent | `aw_g_original/.../agents/t3a.py` (487 lines) | `skyrl_agent/agents/android/android_t3a_agent.py` (590 lines) |
| Utilities | `aw_g_original/.../agents/m3a_utils.py` (558 lines) | Inlined into `android_m3a_agent.py` |

---

## Prompts — Faithful

All prompt templates (`PROMPT_PREFIX`, `GUIDANCE`, `ACTION_SELECTION_PROMPT_TEMPLATE`, `SUMMARY_PROMPT_TEMPLATE`) are **identical** between original and skyrl for both M3A and T3A. The action space definition (11 actions) matches exactly.

---

## Critical Differences

### 1. `validate_ui_element` — Missing `is_visible` check

**Original** (`m3a_utils.py:529-557`):
```python
def validate_ui_element(ui_element, screen_width_height_px):
    if not ui_element.is_visible:        # <-- checks visibility first
        return False
    if ui_element.bbox_pixels:
        # ... bbox bounds check ...
    return True
```

**skyrl** (`android_m3a_agent.py:46-62`):
```python
def validate_ui_element(el, screen_size):
    bbox = el.get("bbox_pixels")
    if not bbox or not isinstance(bbox, dict):
        return False
    # ... bbox bounds check only, NO is_visible check ...
    return True
```

**Impact**: Invisible UI elements (e.g., off-screen or hidden views) may be included in the prompt and SOM annotations, adding noise and confusing the LLM. Both M3A and T3A are affected since T3A imports `validate_ui_element` from `android_m3a_agent.py`.

**Fix**: Add `if not el.get("is_visible", True): return False` at the top of the function.

---

### 2. T3A UI element description — Wrong format (uses M3A's selective format)

**Original T3A** (`t3a.py:186-203`):
```python
def _generate_ui_elements_description_list_full(ui_elements, screen_size):
    for index, ui_element in enumerate(ui_elements):
        if validate_ui_element(ui_element, screen_size):
            tree_info += f'UI element {index}: {str(ui_element)}\n'
    # str(ui_element) includes ALL fields: class_name, resource_id,
    # bbox_pixels, text, content_description, all boolean flags, etc.
```

**skyrl T3A** (`android_t3a_agent.py:25-29`):
```python
from skyrl_agent.agents.android.android_m3a_agent import (
    generate_ui_elements_description,   # <-- M3A's selective format
)
```

The M3A format (`_generate_ui_element_description` in `android_m3a_agent.py:127-152`) only includes: `index`, `text`, `content_description`, `hint_text`, `tooltip`, and boolean flags (`is_clickable`, `is_long_clickable`, `is_editable`, `is_scrollable`, `is_focusable`, `is_selected`, `is_checked`).

The original T3A format additionally includes: **`class_name`**, **`resource_id`**, **`bbox_pixels`** coordinates, and any other fields from `UIElement.__str__()`.

**Impact**: T3A relies entirely on text (no screenshots), so the richer description is important for grounding. Missing `class_name` and `resource_id` deprives the agent of key context (e.g., knowing an element is a `Button` vs `TextView`, or identifying elements by resource ID).

**Fix**: Create a separate `generate_ui_elements_description_full()` for T3A that includes `class_name`, `resource_id`, and `bbox_pixels`.

---

### 3. Parse error handling — Premature episode termination

**Original M3A** (`m3a.py:435-450`):
```python
reason, action = m3a_utils.parse_reason_action_output(action_output)
if (not reason) or (not action):
    step_data['summary'] = (
        'Output for action selection is not in the correct format, '
        'so no action is performed.'
    )
    self.history.append(step_data)
    return AgentInteractionResult(False, step_data)   # <-- continues
```

**skyrl M3A** (`android_m3a_agent.py:606-614`):
```python
try:
    action_dict, reason = parse_m3a_action(response_str)
except Exception as e:
    action_dict = {"action_type": "status", "goal_status": "infeasible"}
    # ^^^ terminates the episode
```

**Impact**: In the original, a single malformed LLM response is recorded as a "no-op" step and the agent retries on the next step. In skyrl, it immediately terminates the episode as infeasible. This can significantly reduce success rates since VLMs occasionally produce malformed output that would be recoverable.

The same issue exists in T3A (`android_t3a_agent.py:362-370`).

**Fix**: On parse failure, record an error summary in history, append the next observation prompt, and return `(False, None, None)` to continue the episode.

---

### 4. M3A summarization — Off by default

**Original M3A** (`m3a.py:567-573`): Always calls `self.llm.predict_mm()` for summarization after every non-terminal step. This is mandatory — no configuration flag.

**skyrl M3A** (`android_m3a_agent.py:502,646`):
```python
self.enable_summarization = False   # <-- off by default
```

When disabled, the step history contains raw strings like `"Action selected: {...}. Reason: ..."` instead of LLM-generated concise summaries.

**Impact**: The original M3A's summarization serves as a "reflection" mechanism — the LLM evaluates whether the action worked by comparing before/after screenshots and produces a concise summary used as memory. Without it, the history is less informative and the agent loses the ability to reason about past successes/failures.

**Fix**: Change default to `self.enable_summarization = True`, or at minimum document this as a known deviation from the original.

---

### 5. SOM drawing — Different library and coordinate handling

| Aspect | Original (`m3a_utils.py`) | skyrl (`android_m3a_agent.py`) |
|---|---|---|
| Library | OpenCV (`cv2`) | PIL/Pillow |
| Coordinate transform | Logical → physical with 4-orientation support | None — uses `bbox_pixels` dict directly |
| Color | Green only `(0, 255, 0)` | 12-color rotation |
| Label | White bg + black text | Color bg + white text |
| Mutation | In-place | Returns copy |

The original code handles a critical pipeline:
1. UI element bounding boxes are in **logical coordinates** (from the a11y tree)
2. `_logical_to_physical()` converts to **physical screenshot coordinates** accounting for orientation (0=portrait, 1=landscape-left, 2=reverse-portrait, 3=landscape-right)
3. Physical coordinates are scaled to screenshot pixel dimensions

The skyrl version skips this entirely and reads `bbox_pixels` directly as pixel coordinates.

**Impact**: If the skyrl environment already provides pre-converted physical pixel coordinates in `bbox_pixels`, this works correctly for portrait mode. However, for non-portrait orientations, the bounding boxes may be incorrect. Additionally, the visual appearance differs (multiple colors vs green-only), which may subtly affect VLM behavior if it was trained/tuned on green-box annotations.

**Fix**: Verify that the skyrl environment provides `bbox_pixels` in physical screenshot coordinates. If orientation handling is needed, port the `_logical_to_physical()` function.

---

### 6. M3A index validation — Missing entirely

**Original M3A** (`m3a.py:476-493`):
```python
if (converted_action.action_type
    in ['click', 'long_press', 'input_text', 'scroll']
    and action_index is not None):
    if action_index >= num_ui_elements:
        step_data['summary'] = 'The parameter index is out of range...'
        self.history.append(step_data)
        return AgentInteractionResult(False, step_data)
```

**skyrl M3A** (`android_m3a_agent.py`): No index validation code. An out-of-range index is sent directly to the environment tool.

skyrl **T3A** does validate indices (`android_t3a_agent.py:383-419`) for `click`, `long_press`, `input_text` but not `scroll`.

**Impact**: Out-of-range indices in M3A are passed to the environment, which may cause tool errors or silent failures instead of informative error summaries that help the agent self-correct.

**Fix**: Add index validation in M3A's `step()` matching the original (check for `click`, `long_press`, `input_text`, `scroll`). Also add `scroll` to T3A's validation.

---

### 7. T3A history format — Minor separator difference

**Original T3A** (`t3a.py:331`): `'Step ' + str(i + 1) + ': ' + step_info['summary']` (colon separator)

**skyrl T3A** (`android_t3a_agent.py:500`): `f"Step {self.state.step_count}- {summary}"` (dash separator)

Note: Original M3A uses dash (`-`), original T3A uses colon (`:`). skyrl uses dash for both.

**Impact**: Minimal — unlikely to affect LLM behavior significantly. But for strict parity, T3A should use colon.

---

## Correctly Handled

- **T3A index validation action types**: Original T3A checks `['click', 'long-press', 'input-text']` (hyphenated), which is inconsistent with the prompt's underscored names. skyrl correctly checks `('click', 'long_press', 'input_text')`. This is a **bug fix** over the original.
- **T3A mandatory summarization**: Both always summarize non-terminal steps. ✅
- **T3A text-only inference**: `extract_images_for_inference()` returns `None`. ✅
- **T3A error feedback on execution failure**: Properly records error and continues. ✅
- **Prompt functions**: `_build_action_selection_prompt()` and `_build_summary_prompt()` match original logic. ✅
- **Action space**: All 11 action types are identical between original and skyrl. ✅

---

## Fix Priority

| # | Issue | Severity | Effort |
|---|---|---|---|
| 1 | Parse error → premature termination | **High** — directly reduces success rate | Small |
| 2 | T3A element description missing class_name/resource_id/bbox | **High** — degrades T3A observation quality | Medium |
| 3 | M3A summarization off by default | **High** — removes step reflection mechanism | Small |
| 4 | Missing `is_visible` check in `validate_ui_element` | **Medium** — adds noise to prompts | Small |
| 5 | M3A missing index validation | **Medium** — misses error recovery opportunity | Small |
| 6 | SOM coordinate/orientation handling | **Low** — only matters if non-portrait is used | Medium |
| 7 | T3A history separator (colon vs dash) | **Low** — cosmetic | Trivial |
