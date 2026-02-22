# ADB Agent Prompt Design Guide

A practical guide to understanding, modifying, and extending the prompt for the ADB command agent (`cli_adb_agent.py`).

---

## 1. Architecture: How the Prompt Fits In

The ADB agent has a simple loop:

```
                ┌──────────────────────────────────┐
                │           LLM (VLM)              │
                │  Input: screenshot + text prompt  │
                │  Output: Thought + Command        │
                └─────────────┬────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   parse_adb_command │  ← extracts (command, thought)
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │ Task control  │  ADB command   │
              │ (FINISH /     │ (adb shell …)  │
              │  INFEASIBLE)  │                │
              └──────┬────────┘───────┬────────┘
                     │                │
                env.step()      subprocess.run()
                     │                │
                     └────────┬───────┘
                              │
                    ┌─────────▼─────────┐
                    │  Observation:      │
                    │  screenshot +      │
                    │  stdout/stderr +   │
                    │  return code       │
                    └───────────────────┘
```

**Key insight:** There are zero translation layers between the model's output and the device. The model generates an exact ADB command string, and that string is executed directly. This is the core advantage over the GUI agent, which has [4 rule-based translation layers](../docs/CLI%20agent/UITARS_TO_ADB_MAPPING.md) between model output and ADB execution.

---

## 2. Prompt Structure

The full prompt lives in `skyrl_agent/agents/android/adb_agent.py` as `ADB_AGENT_PROMPT`. It has 7 sections:

### 2.1 Role Statement (1 sentence)

```
You are an Android automation agent. You control an Android device by issuing
ADB shell commands. You see a screenshot of the current screen and the text
output from your previous command.
```

**Why it matters:** Sets the model's identity as a command-line tool user, not a GUI user. This primes it to think in terms of shell commands, not visual interactions.

### 2.2 Output Format

```
Thought: <your reasoning about what to do next>
Command: <single ADB shell command OR task control action>
```

**Design decisions:**
- **Two-field format** (not JSON, not XML): Simpler to generate and parse. The parser just splits on `Thought:` and `Command:`.
- **Thought first**: Forces the model to reason before acting (chain-of-thought). This is critical for RL training — the thought provides the reasoning trace.
- **Single command per step**: Prevents multi-command injection. The parser enforces this by taking only the first line after `Command:`.

### 2.3 Available Commands (the action space)

The prompt explicitly lists every allowed command category with examples:

| Category | Commands | Purpose |
|----------|----------|---------|
| **Touch & Input** | `input tap`, `input swipe`, `input text`, `input keyevent` | Direct UI interaction |
| **App Management** | `am start`, `am force-stop`, `pm list packages`, `monkey` | Programmatic app control |
| **System Queries** | `dumpsys`, `settings get/put`, `content query`, `getprop` | State verification |
| **File System** | `ls`, `cat` | Read-only inspection |
| **UI Inspection** | `uiautomator dump` | Accessibility tree |
| **Task Control** | `FINISH(content='...')`, `INFEASIBLE(content='...')` | Episode termination |

**Design decisions:**
- **Explicit examples with flags**: e.g. `adb shell am start -n <package/activity>` not just "start an app". The model needs to see the exact syntax.
- **Common keycodes listed**: `KEYCODE_HOME (3)`, `KEYCODE_BACK (4)`, etc. Without these, models often hallucinate wrong keycodes.
- **System queries are crucial**: `dumpsys` and `settings get` let the model verify its own actions, reducing blind retries.

### 2.4 Screen Coordinates

```
The screen resolution is {width}x{height} pixels. Coordinates use absolute pixels.
(0,0) is the top-left corner. x increases rightward, y increases downward.
```

**Why:** The model sees a screenshot and must output pixel coordinates for `tap`/`swipe`. Without explicit resolution info, models guess wrong or use normalized coordinates.

The `{width}` and `{height}` are filled at runtime from the emulator's actual screen size (typically 1080x2400).

### 2.5 Behavioral Guidelines (the "Important Notes")

These are the most impactful lines for agent performance:

```
- Prefer achieving the goal via direct shell commands or system APIs when 
  possible; use tap/swipe only when no such command exists or when the task 
  explicitly requires interacting with on-screen UI.
- Issue ONE command per step.
- After touch/input commands, check the next screenshot to verify.
- Use system query commands (dumpsys, settings get) to verify state when unsure.
- For text input: first tap the text field, then use `adb shell input text`.
```

**Why each matters:**
| Guideline | Effect on Behavior |
|-----------|-------------------|
| "Prefer direct shell commands" | Model uses `am start` to open apps instead of swiping to find icons (saves 3-4 steps) |
| "ONE command per step" | Prevents hallucinated command chains that can't be validated |
| "Check the next screenshot" | Model self-corrects instead of blindly continuing |
| "Use system query commands" | Model uses `dumpsys` to verify success before calling FINISH |
| "First tap, then input text" | Prevents the common failure of typing text with no field focused |

### 2.6 User Instruction

```
## User Instruction
{instruction}
```

The actual task text (e.g., "Open the contacts app. Clear any pop-ups...") is injected here at the bottom of the prompt, after all the command documentation.

### 2.7 What's NOT in the Prompt

Equally important is what's deliberately excluded:
- **No coordinate grounding**: The prompt doesn't map UI elements to coordinates. The model must read the screenshot to determine coordinates.
- **No app-specific knowledge**: The model doesn't know package names or activity names a priori. It must discover them (via `pm list packages`) or use common conventions.
- **No multi-step plans**: The prompt doesn't ask for a full plan upfront. The model plans one step at a time in "Thought".

---

## 3. Message Flow (Multi-Turn)

The conversation structure for a complete episode:

```
Message 0:  system     "You are a helpful assistant."
Message 1:  user       [text: ADB_AGENT_PROMPT with task instruction]
Message 2:  user       [image: initial screenshot]
Message 3:  assistant  "Thought: ... Command: adb shell am start ..."
Message 4:  user       [text: "$ adb shell am start ...\nStarting: Intent{...}\nReturn code: 0\nScreen: 1080x2400",
                         image: new screenshot]
Message 5:  assistant  "Thought: ... Command: FINISH(content='done')"
```

### Observation Format (what the model sees after each command)

```
$ adb shell am start -n com.android.contacts/.DialtactsActivity
Starting: Intent { cmp=com.android.contacts/.DialtactsActivity }
Return code: 0
Screen: 1080x2400
```

**Design decisions:**
- **Terminal-style prefix** (`$ command`): Natural for models trained on code. The `$` signals "this is what was executed".
- **Stdout included**: The model can read command output (e.g., from `dumpsys`, `pm list packages`).
- **Return code**: Signals success (0) vs failure (non-zero). Models learn to retry on failure.
- **Screen resolution repeated**: Reinforces coordinate system for next tap/swipe.
- **Truncation at 2000 chars**: Prevents context explosion from verbose commands like `uiautomator dump`.

### Sliding Window

When the conversation grows beyond `max_history_steps` (default: 10), older turns are dropped but the **header is always kept**:

```
Always kept:  [system prompt, task prompt, initial screenshot]
Sliding:      last N * 2 messages (N assistant + N observation pairs)
```

This ensures the model always sees the full task description and initial context, even in long episodes.

---

## 4. Safety: Whitelist and Blocklist

### Whitelist (`ALLOWED_PREFIXES`)

Every command must start with one of 22 allowed prefixes:

```python
ALLOWED_PREFIXES = [
    "adb shell input tap",
    "adb shell input swipe",
    "adb shell input text",
    "adb shell input keyevent",
    "adb shell am start",
    "adb shell am force-stop",
    # ... (22 total)
]
```

Anything not matching is rejected with a `ValueError`. This is the **primary safety mechanism**.

### Blocklist (`BLOCKED_PATTERNS`)

Regex patterns that catch dangerous commands even if they pass the whitelist:

```python
BLOCKED_PATTERNS = [
    r"\brm\s", r"\brm$", r"\brmdir\b",
    r"\breboot\b", r"\bshutdown\b",
    r"\bformat\b", r"\bmkfs\b", r"\bdd\b", r"\bwipe\b",
    r";\s*rm", r"&&\s*rm", r"\|\s*rm",  # command chaining
]
```

**Note:** In practice, the whitelist catches most dangerous commands first (e.g., `adb shell rm` doesn't match any `ALLOWED_PREFIXES`). The blocklist is a defense-in-depth layer for commands that might chain `rm` after an allowed prefix.

---

## 5. How to Modify the Prompt

### Adding a New Command

1. **Add to `ALLOWED_PREFIXES`** in `adb_agent.py`:
   ```python
   "adb shell screencap",  # new: screen capture to file
   ```

2. **Add to prompt** (in the appropriate category):
   ```
   ### Screenshots
   - `adb shell screencap -p /sdcard/screen.png` -- save screenshot to file
   ```

3. **Add a unit test** in `tests/unit/agent/androidworld/test_adb_agent.py`:
   ```python
   def test_parse_screencap_command(self):
       text = "Thought: Save screen.\nCommand: adb shell screencap -p /sdcard/screen.png"
       command, thought = parse_adb_command(text)
       assert command.startswith("adb shell screencap")
   ```

### Changing Agent Behavior

The most effective levers are the **behavioral guidelines** in "Important Notes":

| Want the model to... | Add/change this guideline |
|----------------------|--------------------------|
| Use intents more, tap less | Strengthen: "Always try `am start` or `monkey` before tapping icons" |
| Verify more before FINISH | Add: "Before calling FINISH, use `dumpsys` to verify the target app is in foreground" |
| Be more concise in Thought | Add: "Keep Thought under 2 sentences" |
| Handle errors better | Add: "If return code is non-zero, try an alternative approach" |
| Use UIAutomator for grounding | Add: "When unsure of element positions, use `uiautomator dump /dev/tty` to get element bounds" |

### Changing the Output Format

If you change the format (e.g., adding a `Plan:` field), you must also update:
- `parse_adb_command()` in `adb_agent.py` — the parser
- `append_assistant()` — how the response is stored
- `android_adb_agent.py` — the VERL integration agent (if used for training)

---

## 6. Comparison with GUI Agent Prompt

| Aspect | ADB Agent | GUI Agent (UI-TARS) |
|--------|-----------|---------------------|
| **Action space** | 22 ADB command prefixes | 8 abstract actions (click, scroll, type...) |
| **Coordinate system** | Absolute pixels (`tap 540 960`) | Normalized 0-1000 (`click(start_box='(500,400)')`) |
| **App launching** | `am start`, `monkey` (direct) | `open_app(content='name')` (env translates) |
| **State verification** | `dumpsys`, `settings get` | Not available (blind) |
| **Text feedback** | stdout + stderr + return code | Screenshot only |
| **Translation layers** | 0 (model output = executed command) | 4 (parse → action dict → env → ADB) |
| **Prompt size** | ~600 tokens (command docs) | ~200 tokens (action list) |

The ADB prompt is larger because it documents exact command syntax, but this investment pays off: the model generates precise commands that skip the translation pipeline.

---

## 7. Evaluation Results

From the [GUI vs ADB evaluation](../skyrl-agent/docs/EXPERIMENT_GUI_VS_ADB_EVAL.md) on 10 tasks:

| Metric | GUI Agent | ADB Agent |
|--------|-----------|-----------|
| Success rate | 55.6% | **62.5%** |
| Mean steps | 5.6 | **4.9** |
| Mean tokens | 52,612 | **42,669** (-19%) |

On 5 easy open-app tasks, ADB agent achieves **5/5 (100%)** vs GUI agent's **3/5 (60%)**.

**Key behavioral differences observed:**
- ADB agent uses `am start` to open apps directly (1 step) vs GUI agent tapping through launchers (3+ steps)
- ADB agent uses `dumpsys` to verify state before FINISH, reducing false completions
- ADB agent recovers from tap misses by falling back to intent-based launching

---

## 8. Files Reference

| File | Role |
|------|------|
| `skyrl_agent/agents/android/adb_agent.py` | Prompt, parser, command execution, message building |
| `scripts/cli_adb_agent.py` | CLI runner (thin wrapper over adb_agent.py) |
| `skyrl_agent/agents/android/android_adb_agent.py` | VERL training integration (subclass of AndroidAgent) |
| `docker/android/server/server_adb.py` | Docker container endpoint for `/step_adb` |
| `tests/unit/agent/androidworld/test_adb_agent.py` | Unit tests for parser and validation |

---

## 9. Quick Reference: Full Prompt Template

```
You are an Android automation agent. You control an Android device by issuing
ADB shell commands. You see a screenshot of the current screen and the text
output from your previous command.

## Output Format
Thought: <your reasoning about what to do next>
Command: <single ADB shell command OR task control action>

## Available Commands
[... 22 command categories with examples ...]

## Task Control
- FINISH(content='<result>')
- INFEASIBLE(content='<reason>')

## Screen Coordinates
The screen resolution is {width}x{height} pixels.
(0,0) is top-left. x increases rightward, y increases downward.

## Important Notes
- Prefer shell commands over tap/swipe
- ONE command per step
- Verify with dumpsys/settings after actions
- For text input: tap field first, then input text

## User Instruction
{instruction}
```
