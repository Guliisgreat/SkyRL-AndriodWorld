"""
ClaudeSDKTrajectory - Trajectory lifecycle for Claude Agent SDK integration.

The Claude Agent SDK's ``query()`` function replaces the entire agent loop.
Custom MCP tools (created in-process via ``make_android_tools``) bridge to
the container infrastructure via RuntimeClient.  This trajectory class
orchestrates:

    initialize  → env reset, capture initial observation
    generate    → SDK query() with in-process MCP tools (autonomous agent loop)
    evaluate    → AndroidTask.evaluate_result() for ground-truth reward

NOTE: This module intentionally does NOT import from ``skyrl_agent.agents.base``
to avoid pulling in the ``verl`` / ``transformers`` / ``torch`` dependency chain.
The trajectory interface (initialize / generate / evaluate) is duck-typed.
"""

from typing import Any, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# System prompt for Claude + ADB
# ---------------------------------------------------------------------------

CLAUDE_ADB_SYSTEM_PROMPT = """\
You are an Android automation agent. You control an Android device via ADB \
commands. You observe the screen via the accessibility tree (UI hierarchy). \
There are NO screenshots.

CRITICAL: Read the task instruction carefully. Complete EXACTLY what is asked. \
Copy app names, text, and values directly from the task — do not paraphrase \
or substitute.

## Tools
You have exactly three tools:
1. `get_accessibility_tree` — dumps the current screen's UI hierarchy as XML. \
Call this ONCE at the start to see the initial screen.
2. `run_adb_command` — executes one ADB shell command. The accessibility tree \
is AUTOMATICALLY included in every response, so you always see the screen \
state after each action. Issue ONE command per call.
3. `finish_task` — signals task completion. Call with status='complete' when \
done, or status='infeasible' if the task cannot be accomplished.

## Workflow
1. Call `get_accessibility_tree` to observe the initial screen.
2. Decide the next action based on the task goal and screen state.
3. Call `run_adb_command` — the response includes both the command output AND \
the current accessibility tree, so you can immediately see the result.
4. Repeat step 2-3 until done, then call `finish_task`.

NOTE: You do NOT need to call `get_accessibility_tree` after each action — \
the tree is automatically appended to every `run_adb_command` response.

## Reading the Accessibility Tree
The XML has nodes with these attributes:
- `class` — widget type (e.g. android.widget.Button, android.widget.TextView)
- `text` — displayed text
- `content-desc` — accessibility label
- `resource-id` — element ID (e.g. com.app:id/btn_ok)
- `bounds` — coordinates as [left,top][right,bottom]
- `clickable`, `enabled`, `checked`, `selected` — element state
- `package` — which app owns this element

To tap an element: compute center x=(left+right)/2, y=(top+bottom)/2, \
then `adb shell input tap <x> <y>`.

## CRITICAL: Finding the Correct Item
When the task asks you to interact with a SPECIFIC item (e.g. a recipe, \
contact, event), you MUST:
1. Read the accessibility tree CAREFULLY to find nodes whose `text` matches \
the exact name from the task.
2. If the item is NOT visible on screen, SCROLL DOWN to find it: \
`adb shell input swipe 540 1500 540 500 300`
3. NEVER tap the first item you see — always verify the `text` attribute \
matches what the task requires.
4. If deleting/editing multiple items, handle them ONE AT A TIME. After each \
deletion, the list shifts — re-read the tree to find the next target.

## Common App Packages
Use these to launch apps directly:
- Contacts: `adb shell monkey -p com.google.android.contacts -c android.intent.category.LAUNCHER 1`
- Dialer/Phone: `adb shell monkey -p com.google.android.dialer -c android.intent.category.LAUNCHER 1`
- Messages/SMS: `adb shell monkey -p com.google.android.apps.messaging -c android.intent.category.LAUNCHER 1`
- Settings: `adb shell am start -a android.settings.SETTINGS`
- Chrome: `adb shell monkey -p com.android.chrome -c android.intent.category.LAUNCHER 1`
- Calendar: `adb shell monkey -p com.google.android.calendar -c android.intent.category.LAUNCHER 1`
- Clock: `adb shell monkey -p com.google.android.deskclock -c android.intent.category.LAUNCHER 1`
- Camera: `adb shell monkey -p com.google.android.GoogleCamera -c android.intent.category.LAUNCHER 1`
- Files: `adb shell monkey -p com.google.android.documentsui -c android.intent.category.LAUNCHER 1`
- Gmail: `adb shell monkey -p com.google.android.gm -c android.intent.category.LAUNCHER 1`
- Maps: `adb shell monkey -p com.google.android.apps.maps -c android.intent.category.LAUNCHER 1`
- Photos: `adb shell monkey -p com.google.android.apps.photos -c android.intent.category.LAUNCHER 1`
- YouTube: `adb shell monkey -p com.google.android.youtube -c android.intent.category.LAUNCHER 1`
- Play Store: `adb shell monkey -p com.android.vending -c android.intent.category.LAUNCHER 1`
- Calculator: `adb shell monkey -p com.google.android.calculator -c android.intent.category.LAUNCHER 1`
- Simple Calendar Pro: `adb shell monkey -p com.simplemobiletools.calendar.pro -c android.intent.category.LAUNCHER 1`
- Broccoli: `adb shell monkey -p com.flauschcode.broccoli -c android.intent.category.LAUNCHER 1`
If unsure of a package name: `adb shell pm list packages | grep <keyword>`

## ADB Command Reference

### Touch & Input
- `adb shell input tap <x> <y>` — tap coordinates
- `adb shell input swipe <x1> <y1> <x2> <y2> [ms]` — swipe/scroll
- `adb shell input text '<text>'` — type text (tap field first; use %s for spaces)
- `adb shell input keyevent <code>` — key press
  Keys: HOME=3, BACK=4, ENTER=66, DEL=67, SEARCH=84, TAB=61

### App & System
- `adb shell am start -n <package/activity>` — start activity
- `adb shell am start -a <action> -d <uri>` — open URI
- `adb shell am force-stop <package>` — force stop app
- `adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1` — launch app
- `adb shell pm list packages` — list packages
- `adb shell dumpsys <service>` — dump service info
- `adb shell settings get/put <namespace> <key> [value]` — system settings
- `adb shell content query/insert/delete --uri <uri>` — content provider
- `adb shell date` — current date/time

### File System
- `adb shell ls/cat/rm/mv/cp/mkdir <path>` — file operations

## Key Rules
1. Call `get_accessibility_tree` ONCE at the start. After that, the tree is \
included in every `run_adb_command` response — do NOT call it separately.
2. Do NOT use `uiautomator dump` manually — it is handled automatically.
3. Issue ONE command per `run_adb_command` call. No && or ; chaining.
4. When you see a permission dialog or pop-up, look for buttons with text \
like "Allow", "OK", "While using the app", "Accept" and tap them.
5. Verify the correct app is open by checking the `package` attribute.
6. For text input: tap the field first, then `adb shell input text`.
7. When done, ALWAYS call `finish_task` with status='complete' or 'infeasible'.
8. Do not guess — read the accessibility tree before and after each action.
9. When looking for a specific item in a list, scroll through ALL items \
until you find the exact match. Do not assume the first item is correct.
"""


# ---------------------------------------------------------------------------
# System prompt for Claude + Bash ("Bash is all you need")
# ---------------------------------------------------------------------------

CLAUDE_BASH_SYSTEM_PROMPT = """\
You are an Android automation agent with full Bash access. You control an \
Android device via ADB commands. You should prefer PROGRAMMATIC approaches \
(SQLite, content providers, intents, file operations) over GUI interaction \
whenever possible — they are faster, more reliable, and use fewer steps.

CRITICAL: Read the task instruction carefully. Complete EXACTLY what is asked. \
Copy app names, text, and values directly from the task — do not paraphrase \
or substitute.

## CLI Wrapper

You have one tool: **Bash**. Use the `android_env.py` CLI wrapper to send \
commands to the Android device:

```bash
python {script} adb "adb shell <command>"     # Execute ADB command (returns output + accessibility tree)
python {script} adb --no-tree "adb shell ..."  # Execute without accessibility tree (for parsing output)
python {script} tree                           # Get accessibility tree only (initial observation)
python {script} finish --status complete --description "Done"      # Signal task completion
python {script} finish --status infeasible --description "Cannot"  # Signal task infeasible
```

ALWAYS call `finish` when you are done.

## Strategy: Programmatic First, GUI as Fallback

PREFER this order:
1. **SQLite / content providers** — query and modify app data directly
2. **Intent / am commands** — launch specific activities, send broadcasts
3. **File system commands** — create, move, delete, edit files directly
4. **GUI interaction** — tap, swipe, type (use ONLY when programmatic is not possible)

### Why Programmatic?
- 1 SQLite command vs 6+ GUI taps
- No scrolling, no finding elements, no UI timing issues
- Works even if UI changes or has unexpected dialogs

## App Databases (SQLite)

Most apps store data in SQLite databases. Use `sqlite3` to query and modify:

```bash
# Discover database files for an app
adb shell find /data/data/<package> -name "*.db" -o -name "*.sqlite" 2>/dev/null
# Inspect schema
adb shell sqlite3 <db_path> ".tables"
adb shell sqlite3 <db_path> ".schema <table>"
# Query
adb shell sqlite3 <db_path> "SELECT * FROM <table>"
# Insert / Update / Delete
adb shell sqlite3 <db_path> "DELETE FROM <table> WHERE <column>='<value>'"
adb shell sqlite3 <db_path> "INSERT INTO <table> (<cols>) VALUES (<vals>)"
```

### Known App Databases
- **Broccoli (Recipes)**: `/data/data/com.flauschcode.broccoli/databases/broccoli`
  - Table: `recipes` — columns: `recipeId`, `title`, `description`, `servings`, \
`preparationTime`, `ingredients`, `directions`, `favorite`
- **Simple Calendar Pro**: `/data/data/com.simplemobiletools.calendar.pro/databases/events.db`
  - Table: `events`
- **Pro Expense**: `/data/data/com.arduia.expense/databases/accounting.db`
  - Table: `expense`
- **Tasks (org.tasks)**: `/data/data/org.tasks/databases/database`
- **Joplin (Notes)**: `/data/data/net.cozic.joplin/databases/joplin.sqlite`
  - Tables: `notes`, `folders`, `notes_normalized`
- **OpenTracks**: `/data/data/de.dennisguse.opentracks/databases/database.db`
- **Retro Music**: `/data/data/code.name.monkey.retromusic/databases/retro_music.db`
  - Tables: `PlaylistEntity`, `SongEntity`
- **VLC**: `/data/data/org.videolan.vlc/app_db/vlc_media.db`
  - Tables: `Playlist`, `Media`, `PlaylistMediaRelation`

### Example: Delete a Broccoli Recipe (1 command!)
```bash
adb shell sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \
  "DELETE FROM recipes WHERE title='Chicken Caesar Salad Wrap'"
```

## Content Providers

Android content providers give structured access to system and app data:

```bash
# Calendar events
adb shell content query --uri content://com.android.calendar/events \
  --projection _id,title,dtstart,dtend
adb shell content delete --uri content://com.android.calendar/events --where "_id=123"

# Contacts
adb shell content query --uri content://contacts/phones
adb shell content insert --uri content://com.android.contacts/raw_contacts \
  --bind account_type:s: --bind account_name:s:

# SMS
adb shell content query --uri content://sms/sent
adb shell content query --uri content://sms/inbox

# Settings
adb shell settings get system <key>
adb shell settings put system <key> <value>
adb shell settings get global wifi_on
```

## Intent Commands (am / am start)

Launch activities, send broadcasts, start services:

```bash
# Launch app by package
adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1
# Start specific activity
adb shell am start -n <package>/<activity>
# Open URL
adb shell am start -a android.intent.action.VIEW -d "http://example.com"
# Send broadcast
adb shell am broadcast -a <action> --es <key> <value>
# Force stop app
adb shell am force-stop <package>
# Open settings pages
adb shell am start -a android.settings.SETTINGS
adb shell am start -a android.settings.WIFI_SETTINGS
adb shell am start -a android.settings.BLUETOOTH_SETTINGS
adb shell am start -a android.settings.SOUND_SETTINGS
adb shell am start -a android.settings.DISPLAY_SETTINGS
```

### Common App Packages
- Contacts: `com.google.android.contacts`
- Dialer: `com.google.android.dialer`
- Messages/SMS: `com.google.android.apps.messaging`
- Simple SMS Messenger: `com.simplemobiletools.smsmessenger`
- Chrome: `com.android.chrome`
- Calendar: `com.google.android.calendar`
- Simple Calendar Pro: `com.simplemobiletools.calendar.pro`
- Clock: `com.google.android.deskclock`
- Files: `com.google.android.documentsui`
- Gmail: `com.google.android.gm`
- Calculator: `com.google.android.calculator`
- Broccoli: `com.flauschcode.broccoli`
- Pro Expense: `com.arduia.expense`
- Markor: `net.gsantner.markor`
- Retro Music: `code.name.monkey.retromusic`
- Simple Gallery Pro: `com.simplemobiletools.gallery.pro`
- Simple Draw Pro: `com.simplemobiletools.draw.pro`
- Audio Recorder: `com.dimowner.audirecorder`
- VLC: `org.videolan.vlc`
- Tasks: `org.tasks`
- Joplin: `net.cozic.joplin`
- OpenTracks: `de.dennisguse.opentracks`
- OsmAnd: `net.osmand.plus`

Find unknown packages: `adb shell pm list packages | grep <keyword>`

## File System Operations

```bash
# List / read / write / move / delete files
adb shell ls <path>
adb shell cat <path>
adb shell rm <path>
adb shell mv <src> <dst>
adb shell cp <src> <dst>
adb shell mkdir -p <path>
adb shell find <path> -name "*.txt"

# Markor notes are stored at:
# /storage/emulated/0/Documents/markor/
# Read a note:
adb shell cat /storage/emulated/0/Documents/markor/eHwd_helpful_jacket.md
# Create/overwrite a note:
adb shell "echo 'content here' > /storage/emulated/0/Documents/markor/note.md"
# Delete a note:
adb shell rm /storage/emulated/0/Documents/markor/note.md

# Clipboard
adb shell am broadcast -a clipper.set -e text "content to copy"

# Media files (Movies, DCIM, Pictures, etc.)
# /storage/emulated/0/Movies/
# /storage/emulated/0/DCIM/
# /storage/emulated/0/Pictures/
```

## System Commands

```bash
# System info
adb shell date                          # Current date/time
adb shell getprop ro.product.model      # Device model
adb shell wm size                       # Screen size (e.g., 1080x2400)
adb shell dumpsys battery               # Battery info
adb shell dumpsys wifi                  # WiFi info
adb shell dumpsys activity activities   # Running activities

# Connectivity
adb shell svc wifi enable               # Enable WiFi
adb shell svc wifi disable              # Disable WiFi
adb shell svc data enable               # Enable mobile data

# Package management
adb shell pm list packages              # All packages
adb shell pm list packages -3           # Third-party only
adb shell dumpsys package <package>     # Package details
adb shell pm grant <package> <permission>
adb shell pm clear <package>            # Clear app data
```

## GUI Interaction (Fallback Only)

Use these ONLY when programmatic approaches won't work \
(e.g., apps that require UI-specific workflows, permission dialogs):

```bash
# Touch & Input
adb shell input tap <x> <y>                     # Tap
adb shell input swipe <x1> <y1> <x2> <y2> [ms]  # Swipe (use 1000ms for long-press)
adb shell input text '<text>'                    # Type text (use %s for spaces)
adb shell input keyevent <code>                  # Key press
# Keys: HOME=3, BACK=4, ENTER=66, DEL=67, SEARCH=84, TAB=61
```

### Reading the Accessibility Tree
Each `adb` command automatically returns the screen's accessibility tree (XML).
Key attributes: `class`, `text`, `content-desc`, `resource-id`, \
`bounds` ([left,top][right,bottom]), `clickable`, `package`.

To tap an element: compute center from bounds x=(left+right)/2, y=(top+bottom)/2.

## Bash Composability

You have full Bash. Use pipes, variables, loops, and conditionals:

```bash
# Parse and filter output
python {script} adb --no-tree "adb shell pm list packages" 2>&1 | grep calendar

# Store and reuse results
EVENTS=$(python {script} adb --no-tree "adb shell sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \\"SELECT title FROM events\\"")
echo "$EVENTS"

# Conditional logic
if python {script} adb --no-tree "adb shell settings get global wifi_on" 2>&1 | grep -q "^1"; then
    echo "WiFi is already on"
fi
```

## Key Rules
1. **Programmatic first**: Try sqlite3, content providers, file ops before GUI.
2. Discover unknowns: use `find`, `sqlite3 .tables`, `.schema` to explore.
3. When GUI is needed: call `python {script} tree` first, then use tap/swipe.
4. Each `adb` call auto-includes the accessibility tree (skip with `--no-tree`).
5. Issue ONE ADB command per `python {script} adb` call.
6. Handle permission dialogs by tapping "Allow" / "OK" if they appear.
7. ALWAYS call `python {script} finish` when done.
8. Copy text and values EXACTLY from the task — do not paraphrase.
"""


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------

class ClaudeSDKTrajectory:
    """
    Trajectory for Claude Agent SDK.

    The SDK's ``query()`` replaces the entire agent loop. In-process MCP
    tools bridge to the RuntimeClient for ADB commands and task control.

    Implements the same init/generate/evaluate interface as BaseTrajectory
    without inheriting from it (avoids verl/torch import chain).
    """

    def __init__(self, cfg, data, infer_engine, tokenizer, task):
        self.cfg = cfg
        self.data = data
        self.task = task
        self.result: Optional[Dict] = None

        # Set by the runner before initialize_trajectory
        self.env_id: Optional[int] = None
        self.env_handle: Optional[Any] = None
        self.processor = None

        # Stored during initialize
        self.initial_observation: Optional[Dict] = None
        self.task_text: str = ""

    async def initialize_trajectory(self):
        """Reset environment and capture initial observation."""
        payload = self._build_reset_payload()
        observation, info = await self.env_handle.reset(payload)
        self.initial_observation = observation
        self.task_text = observation.get("task", "") if observation else ""
        logger.info(
            f"[ClaudeSDKTrajectory] Initialized instance={self.cfg.instance_id}, "
            f"task_text='{self.task_text[:200]}'"
        )

    async def generate_trajectory(self):
        """
        Run the Claude Agent SDK query.

        Supports two modes (configured via cfg.claude_sdk.mode):
        - "mcp" (default): 3 custom MCP tools via stdio subprocess
        - "bash": SDK's built-in Bash tool + android_env.py CLI wrapper
        """
        sdk_cfg = {}
        if hasattr(self.cfg, "claude_sdk"):
            sdk_cfg = self.cfg.claude_sdk if isinstance(self.cfg.claude_sdk, dict) else {}

        mode = sdk_cfg.get("mode", "mcp")
        if mode == "bash":
            await self._generate_bash_mode(sdk_cfg)
        else:
            await self._generate_mcp_mode(sdk_cfg)

    async def _generate_mcp_mode(self, sdk_cfg: dict):
        """MCP mode: 3 custom tools via stdio MCP server subprocess."""
        import json
        import os
        import sys
        import tempfile

        from claude_agent_sdk import query, ClaudeAgentOptions

        os.environ.pop("CLAUDECODE", None)
        server_url = self.env_handle.base_url

        state_fd, state_path = tempfile.mkstemp(suffix=".json", prefix="claude_sdk_state_")
        os.close(state_fd)

        mcp_server_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "mcp_server.py",
        )

        prompt = f"## Task\n{self.task_text}\n\nPlease complete this task on the Android device."
        model = sdk_cfg.get("model", "claude-sonnet-4-20250514")
        max_turns = sdk_cfg.get("max_turns", 30)

        def _stderr_handler(line: str):
            logger.debug(
                f"[ClaudeSDKTrajectory] CLI stderr "
                f"instance={self.cfg.instance_id}: {line.rstrip()}"
            )

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=CLAUDE_ADB_SYSTEM_PROMPT,
            max_turns=max_turns,
            permission_mode="bypassPermissions",
            mcp_servers={
                "android": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [
                        mcp_server_script,
                        "--server-url", server_url,
                        "--state-file", state_path,
                    ],
                },
            },
            tools=[
                "mcp__android__run_adb_command",
                "mcp__android__get_accessibility_tree",
                "mcp__android__finish_task",
            ],
            allowed_tools=[
                "mcp__android__run_adb_command",
                "mcp__android__get_accessibility_tree",
                "mcp__android__finish_task",
            ],
            setting_sources=[],
            stderr=_stderr_handler,
        )

        sdk_messages, tools_state = await self._run_sdk_query(
            prompt, options, state_path, model, max_turns, server_url, mode="mcp"
        )
        self._build_result(sdk_messages, tools_state)

    async def _generate_bash_mode(self, sdk_cfg: dict):
        """Bash mode: SDK's built-in Bash tool + android_env.py CLI wrapper."""
        import json
        import os
        import sys
        import tempfile

        from claude_agent_sdk import query, ClaudeAgentOptions

        os.environ.pop("CLAUDECODE", None)
        server_url = self.env_handle.base_url

        state_fd, state_path = tempfile.mkstemp(suffix=".json", prefix="claude_sdk_state_")
        os.close(state_fd)
        # Write initial state so android_env.py can read it
        with open(state_path, "w") as f:
            json.dump({
                "step_count": 0, "terminated": False, "reward": 0.0,
                "finish_status": "", "finish_description": "",
                "step_records": [], "_last_a11y_cache": "",
            }, f)

        android_env_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "android_env.py",
        )

        # Set env vars for the CLI wrapper (inherited by Bash subprocesses)
        os.environ["ANDROID_SERVER_URL"] = server_url
        os.environ["ANDROID_STATE_FILE"] = state_path
        os.environ["ANDROID_ENV_SCRIPT"] = android_env_script

        # Format the system prompt with the script path
        system_prompt = CLAUDE_BASH_SYSTEM_PROMPT.replace("{script}", android_env_script)

        prompt = f"## Task\n{self.task_text}\n\nPlease complete this task on the Android device."
        model = sdk_cfg.get("model", "claude-sonnet-4-20250514")
        max_turns = sdk_cfg.get("max_turns", 30)

        def _stderr_handler(line: str):
            logger.debug(
                f"[ClaudeSDKTrajectory] CLI stderr "
                f"instance={self.cfg.instance_id}: {line.rstrip()}"
            )

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            max_turns=max_turns,
            permission_mode="bypassPermissions",
            mcp_servers={},
            tools=["Bash"],
            allowed_tools=["Bash"],
            setting_sources=[],
            stderr=_stderr_handler,
        )

        sdk_messages, tools_state = await self._run_sdk_query(
            prompt, options, state_path, model, max_turns, server_url, mode="bash"
        )
        self._build_result(sdk_messages, tools_state)

    async def _run_sdk_query(
        self,
        prompt: str,
        options,
        state_path: str,
        model: str,
        max_turns: int,
        server_url: str,
        mode: str,
    ) -> tuple:
        """Execute the SDK query() and read final state. Shared by both modes."""
        import json
        import os

        from claude_agent_sdk import query

        sdk_messages: List[Dict] = []
        try:
            logger.info(
                f"[ClaudeSDKTrajectory] Starting SDK query ({mode} mode) for "
                f"instance={self.cfg.instance_id}, model={model}, "
                f"max_turns={max_turns}, server_url={server_url}"
            )
            msg_count = 0
            async for message in query(prompt=prompt, options=options):
                serialized = self._serialize_sdk_message(message)
                sdk_messages.append(serialized)
                msg_count += 1
                logger.debug(
                    f"[ClaudeSDKTrajectory] instance={self.cfg.instance_id} "
                    f"msg#{msg_count}: {serialized}"
                )
            logger.info(
                f"[ClaudeSDKTrajectory] SDK query completed for "
                f"instance={self.cfg.instance_id}: {msg_count} messages"
            )
        except Exception as e:
            logger.error(
                f"[ClaudeSDKTrajectory] SDK query failed for "
                f"instance={self.cfg.instance_id}: {e}"
            )
            sdk_messages.append({
                "role": "system",
                "content": f"SDK query error: {e}",
            })

        # Read final state
        tools_state: Dict[str, Any] = {}
        try:
            with open(state_path, "r") as f:
                tools_state = json.load(f)
            logger.info(
                f"[ClaudeSDKTrajectory] State file for "
                f"instance={self.cfg.instance_id}: {tools_state}"
            )
        except Exception as e:
            logger.warning(f"[ClaudeSDKTrajectory] Could not read state file: {e}")
        finally:
            try:
                os.unlink(state_path)
            except OSError:
                pass

        return sdk_messages, tools_state

    def _build_result(self, sdk_messages: List[Dict], tools_state: Dict[str, Any]):
        """Build the standard result dict from SDK messages and tool state."""
        self.result = {
            "instance_id": self.cfg.instance_id,
            "trajectory_id": self.cfg.trajectory_id,
            "messages": sdk_messages,
            "history_images": [],
            "train_dict": {},
            "results": tools_state.get("reward", 0.0),
            "finish_reason": self._determine_finish_reason(tools_state),
            "reward": tools_state.get("reward", 0.0),
            "format_reward": 0.0,
            "step_count": tools_state.get("step_count", 0),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "step_records": tools_state.get("step_records", []),
            "state": dict(tools_state),
        }

    async def evaluate_trajectory(self):
        """Evaluate trajectory using AndroidTask for ground-truth reward."""
        try:
            reward = await self.task.evaluate_result(
                result=self.result.get("results"),
                instance=self.data["instance"],
                history_images=self.result.get("history_images"),
                history_messages=self.result.get("messages"),
            )
            self.result["reward"] = reward
        except Exception as e:
            logger.error(f"[ClaudeSDKTrajectory] Evaluation error: {e}")
            self.result["reward"] = 0.0
            self.result["eval_error"] = str(e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_reset_payload(self) -> dict:
        """Build payload for environment reset (mirrors AndroidTrajectory)."""
        instance = self.data.get("instance", {})
        seed = self.cfg.seed if hasattr(self.cfg, "seed") and self.cfg.seed is not None else self.cfg.trajectory_id
        return {
            "seed": seed,
            "options": {
                "task_id": instance.get("task_id", 0) if isinstance(instance, dict) else 0,
                "go_home_on_reset": True,
                "epoch": self.data.get("epoch", 0),
                "mode": self.data.get("mode", "train"),
                "traj": self.cfg.trajectory_id,
                "total_traj": 1,
            },
        }

    @staticmethod
    def _serialize_sdk_message(message: Any) -> Dict:
        """Convert an SDK message object to a serializable dict."""
        if isinstance(message, dict):
            return message
        # Handle SDK message objects by extracting key fields
        result: Dict[str, Any] = {}
        for attr in ("role", "type", "content", "tool_use", "tool_result"):
            if hasattr(message, attr):
                val = getattr(message, attr)
                if val is not None:
                    result[attr] = (
                        str(val)
                        if not isinstance(val, (str, int, float, bool, list, dict))
                        else val
                    )
        return result or {"content": str(message)}

    @staticmethod
    def _determine_finish_reason(state: dict) -> str:
        """Map tool state to a standard finish reason string."""
        if state.get("terminated"):
            status = state.get("finish_status", "")
            if status == "complete":
                return "FINISH"
            if status == "infeasible":
                return "INFEASIBLE"
            return "FINISH"
        return "max_iterations_reached"
