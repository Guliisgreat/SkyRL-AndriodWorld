#!/usr/bin/env python3
"""
Ground Truth Trajectory Generator for AndroidWorld 116 Tasks.

Generates minimal ADB/CLI command trajectories for each task,
verifies them using the container's built-in evaluator,
and saves results in AITF-v1.6 format.

Usage:
    python run_ground_truth.py --broker-url http://localhost:9300 --pool-size 16

Requirements:
    - Pool broker running with androidworld:2026 containers
    - Tasks seeded with seed=7
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# ─── Configuration ────────────────────────────────────────────────────────────

SEED = 7
SCHEMA_VERSION = "ATIF-v1.6"
AGENT_NAME = "GroundTruth"
AGENT_MODEL = "oracle"
BROKER_TIMEOUT = 300.0
ADB_TIMEOUT = 60
RESET_TIMEOUT = 180
FINISH_TIMEOUT = 120

# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class StepRecord:
    command: str
    output: str
    thought: str = ""


@dataclass
class TaskResult:
    task_id: int
    task_name: str
    goal: str
    reward: float
    steps: List[StepRecord] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    finish_description: str = ""
    error: str = ""


# ─── Broker Helpers ───────────────────────────────────────────────────────────

def broker_acquire(broker_url: str, timeout: float = BROKER_TIMEOUT) -> Dict:
    resp = requests.post(
        f"{broker_url}/acquire",
        json={"pid": os.getpid(), "timeout": timeout},
        timeout=timeout + 10,
    )
    resp.raise_for_status()
    return resp.json()


def broker_return(broker_url: str, env_id: int, healthy: bool = True):
    resp = requests.post(
        f"{broker_url}/return",
        json={"env_id": env_id, "healthy": healthy},
        timeout=30,
    )
    resp.raise_for_status()


# ─── Container API Helpers ────────────────────────────────────────────────────

def container_reset(base_url: str, task_id: int, seed: int = SEED) -> Dict:
    resp = requests.post(
        f"{base_url}/reset",
        json={"seed": seed, "options": {"task_id": task_id}},
        timeout=RESET_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def container_step_adb(base_url: str, command: str, timeout: int = ADB_TIMEOUT) -> Dict:
    resp = requests.post(
        f"{base_url}/step_adb",
        json={"command": command},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def container_finish(base_url: str, description: str) -> Dict:
    resp = requests.post(
        f"{base_url}/step_adb",
        json={"command": f"FINISH(content='{description}')"},
        timeout=FINISH_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def container_answer(base_url: str, answer_text: str) -> Dict:
    """Submit an answer for info retrieval tasks (sets interaction_cache)."""
    resp = requests.post(
        f"{base_url}/step",
        json={"action": {"action_type": "answer", "text": answer_text}, "thought": f"Answer: {answer_text}"},
        timeout=FINISH_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ─── AITF Writer ──────────────────────────────────────────────────────────────

def build_aitf(task_id: int, task_name: str, goal: str, result: TaskResult) -> Dict:
    session_id = f"androidworld-task{task_id}-{uuid.uuid4().hex[:8]}"
    steps = []

    # Step 1: system
    steps.append({
        "step_id": 1,
        "source": "system",
        "message": f"[GroundTruth oracle, seed={SEED}]",
    })

    # Step 2: user (goal)
    steps.append({
        "step_id": 2,
        "source": "user",
        "message": goal,
    })

    # Agent steps
    for i, sr in enumerate(result.steps):
        step = {
            "step_id": i + 3,
            "source": "agent",
            "message": sr.thought or f"Execute: {sr.command}",
            "model_name": AGENT_MODEL,
            "tool_calls": [{
                "tool_call_id": f"call_{i + 3}",
                "function_name": "Bash",
                "arguments": {"command": sr.command},
            }],
            "observation": {
                "results": [{
                    "source_call_id": f"call_{i + 3}",
                    "content": sr.output,
                }]
            },
        }
        steps.append(step)

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "agent": {
            "name": AGENT_NAME,
            "version": "1.0",
            "model_name": AGENT_MODEL,
            "tool_definitions": [{
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "Execute a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                },
            }],
        },
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cost_usd": 0,
            "total_steps": len(result.steps),
            "extra": {
                "task_id": task_id,
                "seed": SEED,
                "reward": result.reward,
                "finished": True,
                "elapsed_seconds": result.elapsed_seconds,
                "finish_description": result.finish_description,
                "num_turns": len(result.steps),
            },
        },
        "extra": {
            "benchmark": "AndroidWorld",
            "task_text": goal,
            "task_name": task_name,
        },
    }


def build_result_entry(result: TaskResult) -> Dict:
    return {
        "task_id": result.task_id,
        "seed": SEED,
        "task": result.goal,
        "task_name": result.task_name,
        "reward": result.reward,
        "step_count": len(result.steps),
        "finished": True,
        "commands": [
            {
                "step_idx": i + 1,
                "thought": s.thought,
                "action_type": "adb",
                "action_params": {"command": s.command},
                "command_output": s.output[:500],
            }
            for i, s in enumerate(result.steps)
        ],
        "finish_description": result.finish_description,
        "elapsed_seconds": result.elapsed_seconds,
        "error": result.error,
    }


# ─── Ground Truth Commands ────────────────────────────────────────────────────

# For info retrieval tasks, ground truth can include:
# - "answer_from_output": callable(last_output) -> answer_string
# This allows the runner to query data, then submit the parsed answer.

def get_ground_truth_commands(task_name: str, goal: str) -> Optional[List[Dict]]:
    """Return list of {"command": str, "thought": str} for the given task.

    Returns None if no ground truth is available (GUI-only tasks).
    Commands should use 'adb shell ...' prefix.

    For info retrieval tasks, the last command may have an "answer_from_output"
    key with a callable that parses the query output into the answer string.
    """
    commands = _GROUND_TRUTH.get(task_name)
    if commands is not None:
        return commands

    # Dynamic command generation based on goal text
    gen = _DYNAMIC_GENERATORS.get(task_name)
    if gen is not None:
        return gen(goal)

    return None


# ─── Static Ground Truth Commands ─────────────────────────────────────────────

_GROUND_TRUTH: Dict[str, List[Dict]] = {}


def _cmd(command: str, thought: str = "") -> Dict:
    return {"command": command, "thought": thought}


def _cmd_fn(fn, thought: str = "") -> Dict:
    """Create a dynamic command spec where command depends on previous outputs."""
    return {"command_fn": fn, "thought": thought}


# ─── Output Parsing Helpers ──────────────────────────────────────────────────

def _extract_contact_id(output: str) -> str:
    """Extract _id value from content query output like 'Row: 0 _id=5'."""
    m = re.search(r'_id=(\d+)', output)
    return m.group(1) if m else "1"


def _extract_int(output: str) -> str:
    """Extract first integer from output."""
    m = re.search(r'(\d+)', output.strip())
    return m.group(1) if m else "0"


def _extract_clipboard(output: str) -> str:
    """Extract clipboard data from clipper broadcast output."""
    m = re.search(r'data="([^"]*)"', output)
    return m.group(1) if m else ""


def _parse_media_fields(output: str) -> Dict[str, str]:
    """Parse content query output like 'Row: 0 _id=123, duration=456, ...'
    Values may contain spaces (album names, artist names, file paths).
    Fields are separated by ', key=' patterns."""
    fields = {}
    all_keys = ['_id', 'title', 'duration', '_data', 'album_id', 'album', 'artist_id', 'artist', 'date_modified']
    # Sort longest first so album_id matches before album, artist_id before artist
    sorted_keys = sorted(all_keys, key=len, reverse=True)
    next_key_pattern = '|'.join(re.escape(k) for k in sorted_keys)
    for key in all_keys:
        m = re.search(rf'(?:^|[\s,]){re.escape(key)}=(.*?)(?:,\s*(?:{next_key_pattern})=|$)', output)
        if m:
            fields[key] = m.group(1).strip()
    return fields


def _parse_day_and_ts(output: str) -> Tuple[int, int]:
    """Parse 'DOW:TS' output from 'echo $(date +%u):$(date +%s)'."""
    parts = output.strip().split(":")
    if len(parts) >= 2:
        return int(parts[0]), int(parts[1])
    return 1, 0


# --- System Tasks ---

_GROUND_TRUTH["SystemWifiTurnOff"] = [
    _cmd("adb shell svc wifi disable", "Turn off WiFi"),
]
_GROUND_TRUTH["SystemWifiTurnOffVerify"] = _GROUND_TRUTH["SystemWifiTurnOff"]

_GROUND_TRUTH["SystemWifiTurnOn"] = [
    _cmd("adb shell svc wifi enable", "Turn on WiFi"),
]
_GROUND_TRUTH["SystemWifiTurnOnVerify"] = _GROUND_TRUTH["SystemWifiTurnOn"]

_GROUND_TRUTH["SystemBluetoothTurnOff"] = [
    _cmd("adb shell svc bluetooth disable", "Turn off Bluetooth"),
]
_GROUND_TRUTH["SystemBluetoothTurnOffVerify"] = _GROUND_TRUTH["SystemBluetoothTurnOff"]

_GROUND_TRUTH["SystemBluetoothTurnOn"] = [
    _cmd("adb shell svc bluetooth enable", "Turn on Bluetooth"),
]
_GROUND_TRUTH["SystemBluetoothTurnOnVerify"] = _GROUND_TRUTH["SystemBluetoothTurnOn"]

_GROUND_TRUTH["SystemBrightnessMax"] = [
    _cmd("adb shell settings put system screen_brightness 255", "Set brightness to max"),
]
_GROUND_TRUTH["SystemBrightnessMaxVerify"] = _GROUND_TRUTH["SystemBrightnessMax"]

_GROUND_TRUTH["SystemBrightnessMin"] = [
    _cmd("adb shell settings put system screen_brightness 1", "Set brightness to min"),
]
_GROUND_TRUTH["SystemBrightnessMinVerify"] = _GROUND_TRUTH["SystemBrightnessMin"]

# Composite system tasks
_GROUND_TRUTH["TurnOffWifiAndTurnOnBluetooth"] = [
    _cmd("adb shell svc wifi disable", "Turn off WiFi"),
    _cmd("adb shell svc bluetooth enable", "Turn on Bluetooth"),
]

# --- Markor Tasks ---

_GROUND_TRUTH["MarkorDeleteAllNotes"] = [
    _cmd("adb shell rm -rf /storage/emulated/0/Documents/Markor/*", "Delete all notes in Markor"),
]

# --- File Tasks ---
# These need dynamic commands based on file names from the goal


# ─── Dynamic Command Generators ──────────────────────────────────────────────

_DYNAMIC_GENERATORS: Dict[str, Any] = {}


def _gen_system_copy_to_clipboard(goal: str) -> List[Dict]:
    """Extract clipboard content from goal and generate command."""
    # Goal format: "Copy the following text to the clipboard: <content>"
    prefix = "Copy the following text to the clipboard: "
    if prefix in goal:
        content = goal[goal.index(prefix) + len(prefix):]
        # Escape single quotes for shell; wrap in double quotes to avoid URI parsing
        content_escaped = content.replace("'", "'\\''")
        return [
            _cmd("adb shell am start ca.zgrs.clipper/.Main", "Launch clipper app"),
            _cmd("adb shell sleep 1", "Wait for clipper"),
            _cmd(f"""adb shell "am broadcast -a clipper.set --es text '{content_escaped}'" """.strip(),
                 f"Copy to clipboard: {content[:50]}"),
        ]
    return None

_DYNAMIC_GENERATORS["SystemCopyToClipboard"] = _gen_system_copy_to_clipboard


def _gen_open_app(goal: str) -> List[Dict]:
    """Extract app name from goal and generate launch command."""
    # Goal: "Open the <app_name> app. Clear any pop-ups..."
    app_packages = {
        "contacts": "com.google.android.contacts/com.android.contacts.activities.PeopleActivity",
        "camera": "com.android.camera2/com.android.camera.CameraLauncher",
        "clock": "com.google.android.deskclock/com.android.deskclock.DeskClock",
        "settings": "com.android.settings/.Settings",
        "dialer": "com.google.android.dialer/com.google.android.dialer.extensions.GoogleDialtactsActivity",
        "messages": "com.simplemobiletools.smsmessenger/.activities.MainActivity",
        "files": "com.google.android.documentsui/.files.FilesActivity",
        "calculator": "com.google.android.calculator/com.android.calculator2.Calculator",
        "calendar": "com.simplemobiletools.calendar.pro/.activities.MainActivity",
    }
    goal_lower = goal.lower()
    for app_name, component in app_packages.items():
        if app_name in goal_lower:
            return [_cmd(f"adb shell am start -n {component}", f"Open {app_name}")]
    return None

_DYNAMIC_GENERATORS["OpenAppTaskEval"] = _gen_open_app


def _gen_turn_on_wifi_and_open_app(goal: str) -> List[Dict]:
    """Turn on wifi + open app."""
    cmds = [_cmd("adb shell svc wifi enable", "Turn on WiFi")]
    app_cmds = _gen_open_app(goal)
    if app_cmds:
        cmds.extend(app_cmds)
    return cmds

_DYNAMIC_GENERATORS["TurnOnWifiAndOpenApp"] = _gen_turn_on_wifi_and_open_app


def _gen_markor_delete_note(goal: str) -> List[Dict]:
    """Delete specific note from Markor."""
    # Goal: "Delete the note in Markor named <file_name>."
    import re
    m = re.search(r"named\s+(\S+)", goal)
    if m:
        fname = m.group(1).rstrip(".")
        # Try with and without .md extension
        return [
            _cmd(f"adb shell rm -f /storage/emulated/0/Documents/Markor/{fname} /storage/emulated/0/Documents/Markor/{fname}.md",
                 f"Delete note {fname}"),
        ]
    return None

_DYNAMIC_GENERATORS["MarkorDeleteNote"] = _gen_markor_delete_note


def _gen_markor_delete_newest(goal: str) -> List[Dict]:
    """Delete the newest note in Markor."""
    return [
        _cmd('adb shell "rm /storage/emulated/0/Documents/Markor/$(ls -t /storage/emulated/0/Documents/Markor/ | head -1)"',
             "Delete newest note"),
    ]

_DYNAMIC_GENERATORS["MarkorDeleteNewestNote"] = _gen_markor_delete_newest


def _gen_markor_create_folder(goal: str) -> List[Dict]:
    """Create folder in Markor."""
    import re
    m = re.search(r"named\s+(\S+)", goal)
    if m:
        folder_name = m.group(1).rstrip(".")
        return [_cmd(f"adb shell mkdir -p /storage/emulated/0/Documents/Markor/{folder_name}",
                     f"Create folder {folder_name}")]
    return None

_DYNAMIC_GENERATORS["MarkorCreateFolder"] = _gen_markor_create_folder


def _b64_write(content: str, filepath: str, thought: str = "") -> List[Dict]:
    """Write content to a file using base64 encoding to avoid shell quoting issues."""
    b64 = base64.b64encode(content.encode()).decode()
    return [_cmd(f'adb shell "echo {b64} | base64 -d > {filepath}"', thought)]


def _gen_markor_create_note(goal: str) -> List[Dict]:
    """Create note in Markor with content."""
    m = re.search(r"named\s+(\S+)\s+with the following text:\s*(.*)", goal, re.DOTALL)
    if m:
        fname = m.group(1)
        content = m.group(2).strip()
        path = f"/storage/emulated/0/Documents/Markor/{fname}"
        cmds = [_cmd("adb shell mkdir -p /storage/emulated/0/Documents/Markor", "Ensure Markor dir exists")]
        cmds.extend(_b64_write(content, path, f"Create note {fname}"))
        return cmds
    return None

_DYNAMIC_GENERATORS["MarkorCreateNote"] = _gen_markor_create_note


def _gen_markor_edit_note(goal: str) -> List[Dict]:
    """Edit note in Markor - replace content."""
    m = re.search(r"Edit\s+(\S+)\s+in Markor.*?Replace the text with\s+(.*)", goal, re.DOTALL)
    if m:
        fname = m.group(1)
        content = m.group(2).strip()
        path = f"/storage/emulated/0/Documents/Markor/{fname}"
        return _b64_write(content, path, f"Edit note {fname}")
    return None

_DYNAMIC_GENERATORS["MarkorEditNote"] = _gen_markor_edit_note


def _gen_markor_change_content(goal: str) -> List[Dict]:
    """Update content of Markor note and optionally rename."""
    m = re.search(r'Update the content of\s+(\S+)\s+to\s+"([^"]+)"\s+in Markor.*?name to\s+(\S+)', goal)
    if m:
        old_name = m.group(1)
        content = m.group(2)
        new_name = m.group(3).rstrip(".")
        base_path = "/storage/emulated/0/Documents/Markor"
        cmds = _b64_write(content, f"{base_path}/{old_name}", f"Update content of {old_name}")
        if old_name != new_name:
            cmds.append(_cmd(f"adb shell mv {base_path}/{old_name} {base_path}/{new_name}",
                             f"Rename {old_name} to {new_name}"))
        return cmds
    return None

_DYNAMIC_GENERATORS["MarkorChangeNoteContent"] = _gen_markor_change_content


def _gen_markor_add_header(goal: str) -> List[Dict]:
    """Add header text to existing Markor note, optionally rename.
    Uses individual commands: read file, write with header prepended, rename."""
    m = re.search(r'note\s+(\S+)\s+by adding.*?(?:existing content|beginning of the note):\s*"?([^"]+)"?', goal, re.DOTALL)
    if m:
        fname = m.group(1)
        header = m.group(2).strip().rstrip(",").strip()
        base_path = "/storage/emulated/0/Documents/Markor"

        # Check for rename
        new_name = fname
        rename_m = re.search(r"rename it to\s+(\S+)", goal)
        if rename_m:
            new_name = rename_m.group(1).rstrip(".")

        cmds = [
            _cmd(f'adb shell "cat {base_path}/{fname}"', f"Read existing note {fname}"),
            _cmd_fn(lambda outs, h=header, bp=base_path, fn=fname: (
                lambda content: f'adb shell "echo {base64.b64encode((h + chr(10) + chr(10) + content + chr(10)).encode()).decode()} | base64 -d > {bp}/{fn}"'
            )(outs[-1].strip()),
                f"Write note with header prepended"),
        ]
        if new_name != fname:
            cmds.append(_cmd(f"adb shell mv {base_path}/{fname} {base_path}/{new_name}",
                             f"Rename {fname} to {new_name}"))
        return cmds
    return None

_DYNAMIC_GENERATORS["MarkorAddNoteHeader"] = _gen_markor_add_header


def _gen_markor_move_note(goal: str) -> List[Dict]:
    """Move note between Markor folders."""
    import re
    m = re.search(r"move the note\s+(\S+)\s+from\s+(\S+)\s+to\s+(\S+)", goal, re.IGNORECASE)
    if m:
        fname = m.group(1)
        src = m.group(2).rstrip(".")
        dst = m.group(3).rstrip(".")
        base = "/storage/emulated/0/Documents/Markor"
        return [
            _cmd(f"adb shell mkdir -p {base}/{dst}", f"Create destination folder {dst}"),
            _cmd(f"adb shell mv {base}/{src}/{fname} {base}/{dst}/{fname}", f"Move {fname} to {dst}"),
        ]
    return None

_DYNAMIC_GENERATORS["MarkorMoveNote"] = _gen_markor_move_note


def _gen_markor_merge_notes(goal: str) -> List[Dict]:
    """Merge multiple Markor notes using individual read + write commands."""
    # Various patterns:
    # "Merge ... into a new note named <f>" or "into a new Markor note named <f>"
    m = re.search(r"Merge the contents of Markor notes\s+(.*?)\s+into a new\s+(?:Markor\s+)?note named\s+(\S+)", goal)
    if m:
        files_str = m.group(1)
        new_name = m.group(2).rstrip(".")
        # Clean up parenthetical notes like "(in the same order)"
        files_str = re.sub(r'\s*\([^)]*\)\s*', ' ', files_str).strip()
        # Parse file names: "f1, f2 and f3" or "f1, f2, f3"
        files_str = files_str.replace(" and ", ", ")
        files = [f.strip() for f in files_str.split(",") if f.strip()]
        base = "/storage/emulated/0/Documents/Markor"

        # Read each file individually
        cmds = []
        for f in files:
            cmds.append(_cmd(f'adb shell "cat {base}/{f}"', f"Read note {f}"))

        # Merge all read outputs into a single write
        num_files = len(files)
        def _merge_fn(outs, n=num_files, bp=base, nn=new_name):
            # The last N outputs are the file contents
            contents = [outs[-(n - i)] for i in range(n)]
            merged = "\n\n".join(c.strip() for c in contents)
            b64 = base64.b64encode((merged + "\n").encode()).decode()
            return f'adb shell "echo {b64} | base64 -d > {bp}/{nn}"'

        cmds.append(_cmd_fn(_merge_fn, f"Merge {num_files} notes into {new_name}"))
        return cmds
    return None

_DYNAMIC_GENERATORS["MarkorMergeNotes"] = _gen_markor_merge_notes


def _gen_files_delete(goal: str) -> List[Dict]:
    """Delete file from filesystem."""
    import re
    # Goal: "Delete the file <name> from the Android filesystem located in the <folder> folder..."
    m = re.search(r"Delete the file\s+(\S+).*?(?:in the|located in the)\s+(\S+)\s+folder", goal, re.IGNORECASE)
    if m:
        fname = m.group(1)
        folder = m.group(2)
        return [_cmd(f"adb shell rm -f /storage/emulated/0/{folder}/{fname}",
                     f"Delete {fname} from {folder}")]
    return None

_DYNAMIC_GENERATORS["FilesDeleteFile"] = _gen_files_delete


def _gen_files_move(goal: str) -> List[Dict]:
    """Move file between folders."""
    import re
    m = re.search(r"Move the file\s+(\S+)\s+from\s+(\S+).*?to the\s+(\S+)\s+", goal, re.IGNORECASE)
    if m:
        fname = m.group(1)
        src = m.group(2)
        dst = m.group(3)
        base = "/storage/emulated/0"
        return [_cmd(f"adb shell mv {base}/{src}/{fname} {base}/{dst}/{fname}",
                     f"Move {fname} from {src} to {dst}")]
    return None

_DYNAMIC_GENERATORS["FilesMoveFile"] = _gen_files_move


def _gen_contacts_add(goal: str) -> List[Dict]:
    """Add a contact via content provider using individual ADB commands.
    Discovers the newly-created raw_contact_id via a query step.
    """
    m = re.search(r"contact for\s+(.*?)\.\s+Their number is\s+(\S+)", goal)
    if m:
        name = m.group(1)
        number = m.group(2).rstrip(".")
        name_esc = name.replace("'", "'\\''")
        number_esc = number.replace("'", "'\\''")
        return [
            _cmd("adb shell content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:",
                 "Create raw contact"),
            _cmd('adb shell "content query --uri content://com.android.contacts/raw_contacts --projection _id --sort \'_id DESC\' | head -1"',
                 "Query last raw_contact_id"),
            _cmd_fn(lambda outs, n=name_esc: f'adb shell "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:{_extract_contact_id(outs[-1])} --bind mimetype:s:vnd.android.cursor.item/name --bind \'data1:s:{n}\'"',
                    f"Set contact name: {name}"),
            _cmd_fn(lambda outs, nu=number_esc: f'adb shell "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:{_extract_contact_id(outs[-2])} --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind \'data1:s:{nu}\'"',
                    f"Set contact number: {number}"),
        ]
    return None

_DYNAMIC_GENERATORS["ContactsAddContact"] = _gen_contacts_add


def _sms_insert_cmd(number: str, message: str) -> str:
    """Build sqlite3 command to insert SMS into sent table."""
    msg_escaped = message.replace("'", "''")
    ts_expr = "$(date +%s)000"
    db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
    sql = f"INSERT INTO sms (address, body, type, date, read, seen) VALUES ('{number}', '{msg_escaped}', 2, {ts_expr}, 1, 1);"
    return f'adb shell "sqlite3 {db} \\"{sql}\\""'


def _gen_sms_send(goal: str) -> List[Dict]:
    """Send SMS message via sqlite insert + launch SMS app."""
    m = re.search(r"to\s+(\S+)\s+with message:\s+(.*?)(?:\s+in Simple SMS|\s*$)", goal, re.DOTALL)
    if m:
        number = m.group(1)
        message = m.group(2).strip()
        if message.endswith("."):
            # Keep the period - it's part of the message
            pass
        return [
            _cmd(_sms_insert_cmd(number, message), f"Insert SMS to {number}"),
            _cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                 "Launch SMS app"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleSmsSend"] = _gen_sms_send


def _gen_sms_reply(goal: str) -> List[Dict]:
    """Reply to SMS."""
    m = re.search(r"Reply to\s+(\S+)\s+with message:\s+(.*?)(?:\s+in Simple SMS|\s*$)", goal, re.DOTALL)
    if m:
        number = m.group(1)
        message = m.group(2).strip()
        return [
            _cmd(_sms_insert_cmd(number, message), f"Reply SMS to {number}"),
            _cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                 "Launch SMS app"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleSmsReply"] = _gen_sms_reply


def _gen_sms_reply_most_recent(goal: str) -> List[Dict]:
    """Reply to the most recent SMS."""
    m = re.search(r"with message:\s+(.*?)(?:\s+in Simple SMS|\s*$)", goal, re.DOTALL)
    if m:
        message = m.group(1).strip()
        msg_esc = message.replace("'", "''")
        db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        # Use INSERT ... SELECT to get the address from the most recent inbox message
        sql = f"INSERT INTO sms (address, body, type, date, read, seen) SELECT address, '{msg_esc}', 2, strftime('%s','now')*1000, 1, 1 FROM sms WHERE type=1 ORDER BY date DESC LIMIT 1;"
        return [
            _cmd(f'adb shell "sqlite3 {db} \\"{sql}\\""',
                 f"Reply to most recent with: {message[:40]}"),
            _cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                 "Launch SMS app"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleSmsReplyMostRecent"] = _gen_sms_reply_most_recent


def _gen_sms_resend(goal: str) -> List[Dict]:
    """Resend the last sent message to a contact."""
    m = re.search(r"Resend the message I just sent to\s+(.*?)\s+in Simple SMS", goal)
    if m:
        db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        # Re-insert the most recent sent message (type=2)
        sql = "INSERT INTO sms (address, body, type, date, read, seen) SELECT address, body, 2, strftime('%s','now')*1000, 1, 1 FROM sms WHERE type=2 ORDER BY date DESC LIMIT 1;"
        return [
            _cmd(f'adb shell "sqlite3 {db} \\"{sql}\\""',
                 "Resend last sent message"),
            _cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                 "Launch SMS app"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleSmsResend"] = _gen_sms_resend


def _gen_sms_send_clipboard(goal: str) -> List[Dict]:
    """Send clipboard content as SMS using individual ADB commands."""
    m = re.search(r"to\s+(\S+)\s+with the clipboard content", goal)
    if m:
        number = m.group(1)
        db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        return [
            _cmd("adb shell am start ca.zgrs.clipper/.Main", "Launch clipper"),
            _cmd("adb shell sleep 1", "Wait for clipper"),
            _cmd('adb shell "am broadcast -a clipper.get 2>&1"', "Read clipboard content"),
            _cmd_fn(lambda outs, num=number, d=db: (
                f'adb shell "sqlite3 {d} \\"INSERT INTO sms (address, body, type, date, read, seen) '
                f"VALUES ('{num}', '{_extract_clipboard(outs[-1]).replace(chr(39), chr(39)+chr(39))}', 2, $(date +%s)000, 1, 1);\\\"\""),
                f"Send clipboard as SMS to {number}"),
            _cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                 "Launch SMS app"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleSmsSendClipboardContent"] = _gen_sms_send_clipboard


def _gen_sms_send_received_address(goal: str) -> List[Dict]:
    """Forward a received address to another contact via SMS using individual commands."""
    db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
    # Extract target name
    m = re.search(r"to\s+(\w+\s+\w+)\s+that", goal)
    if m:
        name = m.group(1)
        return [
            _cmd(f'adb shell "sqlite3 {db} \\"SELECT body FROM sms WHERE type=1 ORDER BY date DESC LIMIT 1;\\""',
                 "Read most recent received SMS"),
            _cmd(f"""adb shell "content query --uri content://contacts/phones/ --projection number --where \\"display_name='{name}'\\" | head -1" """.strip(),
                 f"Look up contact number for {name}"),
            _cmd_fn(lambda outs, d=db: (
                lambda body, number: (
                    f'adb shell "sqlite3 {d} \\"INSERT INTO sms (address, body, type, date, read, seen) '
                    f"VALUES ('{number}', '{body.replace(chr(39), chr(39)+chr(39))}', 2, $(date +%s)000, 1, 1);\\\"\"")
                )(
                    outs[-2].strip(),
                    re.search(r'number=([^\s,]+)', outs[-1]).group(1) if re.search(r'number=([^\s,]+)', outs[-1]) else
                    outs[-1].strip().split("=")[-1]
                ),
                f"Send received address to {name}"),
            _cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                 "Launch SMS app"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleSmsSendReceivedAddress"] = _gen_sms_send_received_address


# --- Markor Remaining ---

def _gen_markor_create_note_from_clipboard(goal: str) -> List[Dict]:
    """Create note from clipboard content."""
    m = re.search(r"named\s+(\S+)", goal)
    if m:
        fname = m.group(1).rstrip(".")
        base_path = "/storage/emulated/0/Documents/Markor"
        return [
            _cmd(f"adb shell mkdir -p {base_path}", "Ensure Markor dir"),
            _cmd("adb shell am start ca.zgrs.clipper/.Main", "Launch clipper"),
            _cmd("adb shell sleep 1", "Wait"),
            _cmd(f'adb shell "am broadcast -a clipper.get 2>&1 | grep -o \'data=\\\"[^\\\"]*\\\"\' | sed \'s/data=\\\"//;s/\\\"//\' > {base_path}/{fname}"',
                 f"Write clipboard to {fname}"),
        ]
    return None

_DYNAMIC_GENERATORS["MarkorCreateNoteFromClipboard"] = _gen_markor_create_note_from_clipboard


def _gen_markor_create_note_and_sms(goal: str) -> List[Dict]:
    """Create note and send SMS."""
    # Multiple goal patterns:
    # "Create a new note ... with text: <content>. Then send the text to <number>..."
    # "Create a new note ... with text: <content>. Share the entire content ... with <number> via SMS..."
    m = re.search(r"named\s+(\S+)\s+with the following text:\s*(.*?)(?:\.\s*(?:Then send|Share the entire))", goal, re.DOTALL)
    if m:
        fname = m.group(1)
        content = m.group(2).strip()
        # Find the phone number
        num_m = re.search(r"(?:to|with)\s+(?:the\s+)?(?:phone\s+)?(?:number\s+)?(\+?\d[\d\s-]+)", goal)
        if num_m:
            number = num_m.group(1).strip()
            base_path = "/storage/emulated/0/Documents/Markor"
            cmds = [_cmd(f"adb shell mkdir -p {base_path}", "Ensure Markor dir")]
            cmds.extend(_b64_write(content, f"{base_path}/{fname}", f"Create note {fname}"))
            cmds.append(_cmd(_sms_insert_cmd(number, content), f"Send SMS to {number}"))
            cmds.append(_cmd("adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity",
                             "Launch SMS app"))
            return cmds
    return None

_DYNAMIC_GENERATORS["MarkorCreateNoteAndSms"] = _gen_markor_create_note_and_sms


# --- Gallery ---

def _gen_save_receipt_copy(goal: str) -> List[Dict]:
    """Copy receipt image from one folder to another."""
    # "copy <fname> in <src> and save a copy with the same name in <dst>"
    # "copy <fname> in <src> and save a copy ... in the <dst> folder"
    m = re.search(r"copy\s+(\S+)\s+in\s+(\S+)\s+and.*?in\s+(?:the\s+)?(\S+?)(?:\s+folder)?\.?\s*$", goal, re.IGNORECASE)
    if m:
        fname = m.group(1)
        src_folder = m.group(2)
        dst_folder = m.group(3)
        base = "/storage/emulated/0"
        return [
            _cmd(f"adb shell cp {base}/{src_folder}/{fname} {base}/{dst_folder}/{fname}",
                 f"Copy {fname} from {src_folder} to {dst_folder}"),
        ]
    return None

_DYNAMIC_GENERATORS["SaveCopyOfReceiptTaskEval"] = _gen_save_receipt_copy


# --- Calendar Operations (SQLite) ---

_CALENDAR_DB = "/data/data/com.simplemobiletools.calendar.pro/databases/events.db"


def _gen_calendar_delete_events(goal: str) -> List[Dict]:
    """Delete all events on a specific date."""
    m = re.search(r"delete all.*?events.*?on\s+(\d{4}-\d{2}-\d{2})", goal, re.IGNORECASE)
    if m:
        date_str = m.group(1)
        # Convert date to timestamp range
        from datetime import datetime as dt
        import calendar
        d = dt.strptime(date_str, "%Y-%m-%d")
        start_ts = int(calendar.timegm(d.timetuple()))
        end_ts = start_ts + 86400
        return [
            _cmd(f"adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd(f'adb shell "sqlite3 {_CALENDAR_DB} \\"DELETE FROM events WHERE start_ts >= {start_ts} AND start_ts < {end_ts};\\""',
                 f"Delete events on {date_str}"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarDeleteEvents"] = _gen_calendar_delete_events


def _gen_calendar_delete_one_event(goal: str) -> List[Dict]:
    """Delete a specific calendar event."""
    m = re.search(r"delete.*?event.*?on\s+(\d{4}-\d{2}-\d{2})\s+at\s+(\d+)h.*?title\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        date_str = m.group(1)
        hour = int(m.group(2))
        title = m.group(3)
        from datetime import datetime as dt
        import calendar
        d = dt.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M")
        ts = int(calendar.timegm(d.timetuple()))
        return [
            _cmd(f"adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd(f'adb shell "sqlite3 {_CALENDAR_DB} \\"DELETE FROM events WHERE title=\'{title}\' AND start_ts={ts};\\""',
                 f"Delete event '{title}' at {date_str} {hour}h"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarDeleteOneEvent"] = _gen_calendar_delete_one_event


def _gen_calendar_delete_events_relative(goal: str) -> List[Dict]:
    """Delete events on a relative day (e.g., this Wednesday) using command_fn."""
    m = re.search(r"delete all events.*?for this\s+(\w+)", goal, re.IGNORECASE)
    if m:
        day_name = m.group(1)
        day_num_map = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
                       "Friday": 5, "Saturday": 6, "Sunday": 7}
        target_dow = day_num_map.get(day_name, 1)
        db = _CALENDAR_DB

        def _build_relative_day_delete(outs, tgt=target_dow, database=db):
            dow, now = _parse_day_and_ts(outs[-1])
            diff = (tgt - dow + 7) % 7
            if diff == 0:
                diff = 7
            midnight = (now // 86400) * 86400
            start_ts = midnight + diff * 86400
            end_ts = start_ts + 86400
            return f'adb shell "sqlite3 {database} \\"DELETE FROM events WHERE start_ts >= {start_ts} AND start_ts < {end_ts};\\""'

        return [
            _cmd("adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd('adb shell "echo $(date +%u):$(date +%s)"', "Get current day of week and timestamp"),
            _cmd_fn(_build_relative_day_delete, f"Delete events on this {day_name}"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarDeleteEventsOnRelativeDay"] = _gen_calendar_delete_events_relative


def _calendar_insert_sql(start_ts: int, end_ts: int, title: str,
                         description: str = "", location: str = "",
                         repeat_interval: int = 0, repeat_rule: int = 0) -> str:
    """Build full calendar event INSERT SQL with all NOT NULL fields."""
    title_esc = title.replace("'", "''")
    desc_esc = description.replace("'", "''")
    loc_esc = location.replace("'", "''")
    return (f"INSERT INTO events (start_ts, end_ts, title, location, description, "
            f"reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
            f"reminder_1_type, reminder_2_type, reminder_3_type, "
            f"repeat_interval, repeat_rule, repeat_limit, repetition_exceptions, "
            f"attendees, import_id, time_zone, flags, event_type, parent_id, "
            f"last_updated, source, availability, color, type) VALUES "
            f"({start_ts}, {end_ts}, '{title_esc}', '{loc_esc}', '{desc_esc}', "
            f"-1, -1, -1, 0, 0, 0, {repeat_interval}, {repeat_rule}, 0, '[]', "
            f"'', '', 'UTC', 0, 1, 0, 0, 'imported-ics', 0, 0, 0);")


def _calendar_insert_sql_template(title: str, description: str = "",
                                  location: str = "",
                                  repeat_interval: int = 0,
                                  repeat_rule: int = 0) -> str:
    """Build calendar INSERT SQL using shell variables $START_TS and $END_TS.
    For use inside shell scripts that compute timestamps dynamically."""
    return (f"INSERT INTO events (start_ts, end_ts, title, location, description, "
            f"reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
            f"reminder_1_type, reminder_2_type, reminder_3_type, "
            f"repeat_interval, repeat_rule, repeat_limit, repetition_exceptions, "
            f"attendees, import_id, time_zone, flags, event_type, parent_id, "
            f"last_updated, source, availability, color, type) VALUES "
            f"($START_TS, $END_TS, '{title}', '{location}', '{description}', "
            f"-1, -1, -1, 0, 0, 0, {repeat_interval}, {repeat_rule}, 0, '[]', "
            f"'', '', 'UTC', 0, 1, 0, 0, 'imported-ics', 0, 0, 0);")


def _gen_calendar_add_event(goal: str) -> List[Dict]:
    """Add a calendar event on a specific date."""
    m = re.search(r"create.*?event.*?on\s+(\d{4}-\d{2}-\d{2})\s+at\s+(\d+)h.*?title\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        date_str = m.group(1)
        hour = int(m.group(2))
        title = m.group(3)
        # Extract description if present
        desc = ""
        desc_m = re.search(r"description.*?'([^']+)'", goal)
        if desc_m:
            desc = desc_m.group(1)
        # Extract duration
        duration_min = 60
        dur_m = re.search(r"last for\s+(\d+)\s+min", goal)
        if dur_m:
            duration_min = int(dur_m.group(1))
        from datetime import datetime as dt
        import calendar
        d = dt.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M")
        start_ts = int(calendar.timegm(d.timetuple()))
        end_ts = start_ts + duration_min * 60
        sql = _calendar_insert_sql(start_ts, end_ts, title, desc)
        return [
            _cmd(f"adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd(f'adb shell "sqlite3 {_CALENDAR_DB} \\"{sql}\\""',
                 f"Add event '{title}' on {date_str}"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarAddOneEvent"] = _gen_calendar_add_event


def _gen_calendar_add_tomorrow(goal: str) -> List[Dict]:
    """Add event for tomorrow using inline shell arithmetic in a single SQL command."""
    m = re.search(r"for tomorrow at\s+(\d+)h.*?title\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        title = m.group(2)
        desc = ""
        desc_m = re.search(r"description.*?'([^']+)'", goal)
        if desc_m:
            desc = desc_m.group(1)
        duration_min = 60
        dur_m = re.search(r"last for\s+(\d+)\s+min", goal)
        if dur_m:
            duration_min = int(dur_m.group(1))
        title_esc = title.replace("'", "''")
        desc_esc = desc.replace("'", "''")
        db = _CALENDAR_DB
        dur_sec = duration_min * 60
        # Use inline $(()) for timestamp computation in a single adb command
        start_expr = f"$(( ($(date +%s) / 86400) * 86400 + 86400 + {hour} * 3600 ))"
        end_expr = f"$(( ($(date +%s) / 86400) * 86400 + 86400 + {hour} * 3600 + {dur_sec} ))"
        sql = (f"INSERT INTO events (start_ts, end_ts, title, location, description, "
               f"reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
               f"reminder_1_type, reminder_2_type, reminder_3_type, "
               f"repeat_interval, repeat_rule, repeat_limit, repetition_exceptions, "
               f"attendees, import_id, time_zone, flags, event_type, parent_id, "
               f"last_updated, source, availability, color, type) VALUES "
               f"({start_expr}, {end_expr}, '{title_esc}', '', '{desc_esc}', "
               f"-1, -1, -1, 0, 0, 0, 0, 0, 0, '[]', '', '', 'UTC', 0, 1, 0, 0, 'imported-ics', 0, 0, 0);")
        return [
            _cmd("adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd(f'adb shell "sqlite3 {db} \\"{sql}\\""',
                 f"Add event '{title}' tomorrow at {hour}h"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarAddOneEventTomorrow"] = _gen_calendar_add_tomorrow


def _gen_calendar_add_in_two_weeks(goal: str) -> List[Dict]:
    """Add event in two weeks using inline shell arithmetic."""
    m = re.search(r"in two weeks.*?at\s+(\d+)h.*?title\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        title = m.group(2)
        desc = ""
        desc_m = re.search(r"description.*?'([^']+)'", goal)
        if desc_m:
            desc = desc_m.group(1)
        duration_min = 60
        dur_m = re.search(r"last for\s+(\d+)\s+min", goal)
        if dur_m:
            duration_min = int(dur_m.group(1))
        title_esc = title.replace("'", "''")
        desc_esc = desc.replace("'", "''")
        db = _CALENDAR_DB
        dur_sec = duration_min * 60
        start_expr = f"$(( ($(date +%s) / 86400) * 86400 + 14 * 86400 + {hour} * 3600 ))"
        end_expr = f"$(( ($(date +%s) / 86400) * 86400 + 14 * 86400 + {hour} * 3600 + {dur_sec} ))"
        sql = (f"INSERT INTO events (start_ts, end_ts, title, location, description, "
               f"reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
               f"reminder_1_type, reminder_2_type, reminder_3_type, "
               f"repeat_interval, repeat_rule, repeat_limit, repetition_exceptions, "
               f"attendees, import_id, time_zone, flags, event_type, parent_id, "
               f"last_updated, source, availability, color, type) VALUES "
               f"({start_expr}, {end_expr}, '{title_esc}', '', '{desc_esc}', "
               f"-1, -1, -1, 0, 0, 0, 0, 0, 0, '[]', '', '', 'UTC', 0, 1, 0, 0, 'imported-ics', 0, 0, 0);")
        return [
            _cmd("adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd(f'adb shell "sqlite3 {db} \\"{sql}\\""',
                 f"Add event '{title}' in 2 weeks at {hour}h"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarAddOneEventInTwoWeeks"] = _gen_calendar_add_in_two_weeks


def _gen_calendar_add_relative_day(goal: str) -> List[Dict]:
    """Add event on a relative day (this Wednesday, etc.) using command_fn
    to compute timestamp from device clock output."""
    m = re.search(r"for this\s+(\w+)\s+at\s+(\d+)h.*?title\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        day_name = m.group(1)
        hour = int(m.group(2))
        title = m.group(3)
        desc = ""
        desc_m = re.search(r"description.*?'([^']+)'", goal)
        if desc_m:
            desc = desc_m.group(1)
        duration_min = 60
        dur_m = re.search(r"last for\s+(\d+)\s+min", goal)
        if dur_m:
            duration_min = int(dur_m.group(1))
        day_num_map = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
                       "Friday": 5, "Saturday": 6, "Sunday": 7}
        target_dow = day_num_map.get(day_name, 1)
        title_esc = title.replace("'", "''")
        desc_esc = desc.replace("'", "''")
        db = _CALENDAR_DB

        def _build_relative_day_insert(outs, tgt=target_dow, h=hour, dur=duration_min,
                                        t=title_esc, d=desc_esc, database=db):
            dow, now = _parse_day_and_ts(outs[-1])
            diff = (tgt - dow + 7) % 7
            if diff == 0:
                diff = 7
            midnight = (now // 86400) * 86400
            start_ts = midnight + diff * 86400 + h * 3600
            end_ts = start_ts + dur * 60
            sql = _calendar_insert_sql(start_ts, end_ts, t, d)
            return f'adb shell "sqlite3 {database} \\"{sql}\\""'

        return [
            _cmd("adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar app"),
            _cmd('adb shell "echo $(date +%u):$(date +%s)"', "Get current day of week and timestamp"),
            _cmd_fn(_build_relative_day_insert, f"Add event '{title}' this {day_name} at {hour}h"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarAddOneEventRelativeDay"] = _gen_calendar_add_relative_day


def _gen_calendar_add_repeating(goal: str) -> List[Dict]:
    """Add a repeating calendar event."""
    m = re.search(r"recurring.*?titled\s+'([^']+)'.*?starting on\s+(\d{4}-\d{2}-\d{2})\s+at\s+(\d+)h", goal, re.IGNORECASE)
    if m:
        title = m.group(1)
        date_str = m.group(2)
        hour = int(m.group(3))
        desc = ""
        desc_m = re.search(r"description.*?'([^']+)'", goal)
        if desc_m:
            desc = desc_m.group(1)
        duration_min = 60
        dur_m = re.search(r"last for\s+(\d+)\s+min", goal)
        if dur_m:
            duration_min = int(dur_m.group(1))
        # Determine repeat interval
        repeat_interval = 0
        repeat_rule = 0
        if "daily" in goal.lower():
            repeat_interval = 86400
        elif "weekly" in goal.lower():
            repeat_interval = 604800
            # Calculate repeat_rule bitmask from the day of week
            import calendar as cal_mod
            from datetime import datetime as dt
            d = dt.strptime(date_str, "%Y-%m-%d")
            # Python weekday: Mon=0..Sun=6 → Calendar Pro: Mon=1..Sun=7
            day_of_week = d.weekday() + 1
            repeat_rule = 1 << (day_of_week - 1)

        import calendar as cal_mod
        from datetime import datetime as dt
        d = dt.strptime(f"{date_str} {hour:02d}:00", "%Y-%m-%d %H:%M")
        start_ts = int(cal_mod.timegm(d.timetuple()))
        end_ts = start_ts + duration_min * 60
        sql = _calendar_insert_sql(start_ts, end_ts, title, desc,
                                   repeat_interval=repeat_interval, repeat_rule=repeat_rule)
        return [
            _cmd("adb shell am force-stop com.simplemobiletools.calendar.pro", "Stop calendar"),
            _cmd(f'adb shell "sqlite3 {_CALENDAR_DB} \\"{sql}\\""',
                 f"Add repeating event '{title}'"),
        ]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarAddRepeatingEvent"] = _gen_calendar_add_repeating


# --- Calendar Info Retrieval ---

def _calendar_query_cmd(sql: str) -> str:
    return f'adb shell "sqlite3 {_CALENDAR_DB} \\"{sql}\\""'


def _gen_calendar_next_event(goal: str) -> List[Dict]:
    """Query: what is the next upcoming event. Uses device clock for 'now'."""
    sql = "SELECT title FROM events WHERE start_ts > $(date +%s) ORDER BY start_ts ASC LIMIT 1;"
    return [{
        "command": f'adb shell "sqlite3 {_CALENDAR_DB} \\"{sql}\\""',
        "thought": "Query next upcoming event (using device clock for current time)",
        "answer_from_output": lambda out: out.strip(),
    }]

_DYNAMIC_GENERATORS["SimpleCalendarNextEvent"] = _gen_calendar_next_event


def _gen_calendar_events_on_date(goal: str) -> List[Dict]:
    """Query: what events on a specific date."""
    m = re.search(r"(\w+)\s+(\d+)\s+(\d{4})", goal)
    if m:
        import calendar as cal_mod
        from datetime import datetime as dt
        month_name = m.group(1)
        day = int(m.group(2))
        year = int(m.group(3))
        month = list(cal_mod.month_name).index(month_name)
        d = dt(year, month, day)
        start_ts = int(cal_mod.timegm(d.timetuple()))
        end_ts = start_ts + 86400
        sql = f"SELECT title FROM events WHERE start_ts >= {start_ts} AND start_ts < {end_ts} ORDER BY start_ts;"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query events on {month_name} {day} {year}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarEventsOnDate"] = _gen_calendar_events_on_date
_DYNAMIC_GENERATORS["SimpleCalendarAnyEventsOnDate"] = _gen_calendar_events_on_date


def _gen_calendar_event_at_time(goal: str) -> List[Dict]:
    """Query event on date at specific time."""
    m = re.search(r"(\w+)\s+(\d+)\s+(\d{4})\s+at\s+(\d+):(\d+)(am|pm)?", goal, re.IGNORECASE)
    if m:
        import calendar as cal_mod
        from datetime import datetime as dt
        month_name = m.group(1)
        day = int(m.group(2))
        year = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        ampm = m.group(6)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm and ampm.lower() == "am" and hour == 12:
            hour = 0
        month = list(cal_mod.month_name).index(month_name)
        d = dt(year, month, day, hour, minute)
        ts = int(cal_mod.timegm(d.timetuple()))
        sql = f"SELECT title FROM events WHERE start_ts <= {ts} AND end_ts > {ts};"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query event at {month_name} {day} {year} {hour}:{minute:02d}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarEventOnDateAtTime"] = _gen_calendar_event_at_time


def _gen_calendar_location(goal: str) -> List[Dict]:
    """Query event location."""
    # Goal: "What is the location of my <title> event in Simple Calendar Pro?"
    m = re.search(r"location of (?:my\s+)?(.+?)\s+event", goal, re.IGNORECASE)
    if not m:
        m = re.search(r"location.*?'([^']+)'", goal)
    if m:
        title = m.group(1).strip()
        sql = f"SELECT location FROM events WHERE title LIKE '%{title}%' LIMIT 1;"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query location of '{title}'",
            "answer_from_output": lambda out: out.strip() if out.strip() else "No location",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarLocationOfEvent"] = _gen_calendar_location


def _gen_calendar_next_meeting_with(goal: str) -> List[Dict]:
    """Query next meeting with person. Uses device clock for 'now'."""
    m = re.search(r"next meeting with\s+(\w+)", goal, re.IGNORECASE)
    if m:
        person = m.group(1)
        from datetime import datetime as dt
        sql = f"SELECT start_ts FROM events WHERE title LIKE '%{person}%' AND start_ts > $(date +%s) ORDER BY start_ts ASC LIMIT 1;"
        def format_answer(out):
            ts = out.strip()
            if not ts:
                return "No meeting found"
            d = dt.utcfromtimestamp(int(ts))
            return d.strftime("%B %d %Y %H:%M")
        return [{
            "command": f'adb shell "sqlite3 {_CALENDAR_DB} \\"{sql}\\""',
            "thought": f"Query next meeting with {person} (using device clock for current time)",
            "answer_from_output": format_answer,
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarNextMeetingWithPerson"] = _gen_calendar_next_meeting_with


def _gen_calendar_events_next_week(goal: str) -> List[Dict]:
    """Query events in next week (starting Monday) using command_fn."""
    db = _CALENDAR_DB

    def _build_next_week_query(outs, database=db):
        dow, now = _parse_day_and_ts(outs[-1])
        days_to_mon = (8 - dow) % 7
        if days_to_mon == 0:
            days_to_mon = 7
        midnight = (now // 86400) * 86400
        start_ts = midnight + days_to_mon * 86400
        end_ts = start_ts + 7 * 86400
        sql = f"SELECT title FROM events WHERE start_ts >= {start_ts} AND start_ts < {end_ts} ORDER BY start_ts;"
        return f'adb shell "sqlite3 {database} \\"{sql}\\""'

    return [
        _cmd('adb shell "echo $(date +%u):$(date +%s)"', "Get current day of week and timestamp"),
        {
            "command_fn": _build_next_week_query,
            "thought": "Query events in next week",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        },
    ]

_DYNAMIC_GENERATORS["SimpleCalendarEventsInNextWeek"] = _gen_calendar_events_next_week


def _resolve_date_from_goal(goal: str) -> Optional['datetime']:
    """Try to resolve an absolute or relative date from goal text.
    Returns datetime object or None. Device date is Oct 15, 2023."""
    import calendar as cal_mod
    from datetime import datetime as dt, timedelta

    # Try absolute with year: "October 20 2023"
    m = re.search(r"(\w+)\s+(\d{1,2})\s+(\d{4})", goal)
    if m:
        try:
            month = list(cal_mod.month_name).index(m.group(1))
            return dt(int(m.group(3)), month, int(m.group(2)))
        except (ValueError, IndexError):
            pass

    # Try month + day without year: "October 20" (default year 2023)
    m = re.search(r"(\w+)\s+(\d{1,2})(?:\s|,|\.|$)", goal)
    if m:
        try:
            month = list(cal_mod.month_name).index(m.group(1))
            return dt(2023, month, int(m.group(2)))
        except (ValueError, IndexError):
            pass

    # Try relative day: "Friday", "this Friday", "for Friday"
    day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
               "Friday": 4, "Saturday": 5, "Sunday": 6}
    for day_name, wd in day_map.items():
        if re.search(r'\b' + day_name + r'\b', goal, re.IGNORECASE):
            base = dt(2023, 10, 15)
            diff = (wd - base.weekday()) % 7
            if diff == 0:
                diff = 7
            return base + timedelta(days=diff)

    return None


def _gen_calendar_first_after(goal: str) -> List[Dict]:
    """First event after a start time on a date."""
    import calendar as cal_mod
    from datetime import datetime as dt

    m = re.search(r"after\s+(\d+):(\d+)(am|pm)?", goal, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm and ampm.lower() == "am" and hour == 12:
            hour = 0

        base_date = _resolve_date_from_goal(goal)
        if base_date is None:
            base_date = dt(2023, 10, 15)

        d = dt(base_date.year, base_date.month, base_date.day, hour, minute)
        ts = int(cal_mod.timegm(d.timetuple()))
        sql = f"SELECT title FROM events WHERE start_ts >= {ts} ORDER BY start_ts ASC LIMIT 1;"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query first event at or after {hour}:{minute:02d}",
            "answer_from_output": lambda out: out.strip() if out.strip() else "No events",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarFirstEventAfterStartTime"] = _gen_calendar_first_after


def _gen_calendar_events_time_range(goal: str) -> List[Dict]:
    """Events in a time range on a date."""
    m = re.search(r"between\s+(\d+)(am|pm)?\s+and\s+(\d+)(am|pm)?\s+(\w+)\s+(\d+)\s+(\d{4})", goal, re.IGNORECASE)
    if m:
        import calendar as cal_mod
        from datetime import datetime as dt
        h1 = int(m.group(1))
        ap1 = m.group(2)
        h2 = int(m.group(3))
        ap2 = m.group(4)
        if ap1 and ap1.lower() == "pm" and h1 < 12: h1 += 12
        if ap2 and ap2.lower() == "pm" and h2 < 12: h2 += 12
        month_name = m.group(5)
        day = int(m.group(6))
        year = int(m.group(7))
        month = list(cal_mod.month_name).index(month_name)
        ts1 = int(cal_mod.timegm(dt(year, month, day, h1, 0).timetuple()))
        ts2 = int(cal_mod.timegm(dt(year, month, day, h2, 0).timetuple()))
        sql = f"SELECT title FROM events WHERE start_ts >= {ts1} AND start_ts < {ts2} ORDER BY start_ts;"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query events between {h1}:00 and {h2}:00",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarEventsInTimeRange"] = _gen_calendar_events_time_range


# Update calendar queries to handle relative days (reuse _resolve_date_from_goal)

def _gen_calendar_events_on_date_v2(goal: str) -> List[Dict]:
    """Query events on a date (absolute or relative day name)."""
    import calendar as cal_mod
    from datetime import datetime as dt

    resolved = _resolve_date_from_goal(goal)
    if resolved:
        start_ts = int(cal_mod.timegm(resolved.timetuple()))
        end_ts = start_ts + 86400
        sql = f"SELECT title FROM events WHERE start_ts >= {start_ts} AND start_ts < {end_ts} ORDER BY start_ts;"
        date_str = resolved.strftime("%B %d %Y")
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query events on {date_str}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        }]
    return None

# Override the existing generators with v2 that handles relative days
_DYNAMIC_GENERATORS["SimpleCalendarEventsOnDate"] = _gen_calendar_events_on_date_v2
_DYNAMIC_GENERATORS["SimpleCalendarAnyEventsOnDate"] = _gen_calendar_events_on_date_v2


def _gen_calendar_event_at_time_v2(goal: str) -> List[Dict]:
    """Query event at specific time (handles relative day names)."""
    import calendar as cal_mod
    from datetime import datetime as dt

    m = re.search(r"at\s+(\d+):(\d+)(am|pm)?", goal, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm and ampm.lower() == "am" and hour == 12:
            hour = 0

        base_date = _resolve_date_from_goal(goal)
        if base_date is None:
            base_date = dt(2023, 10, 15)

        d = dt(base_date.year, base_date.month, base_date.day, hour, minute)
        ts = int(cal_mod.timegm(d.timetuple()))
        sql = f"SELECT title FROM events WHERE start_ts <= {ts} AND end_ts > {ts};"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query event at {hour}:{minute:02d}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarEventOnDateAtTime"] = _gen_calendar_event_at_time_v2


def _gen_calendar_events_time_range_v2(goal: str) -> List[Dict]:
    """Events in time range (handles relative days)."""
    import calendar as cal_mod
    from datetime import datetime as dt

    m = re.search(r"between\s+(\d+)(?::(\d+))?(am|pm)?\s+and\s+(\d+)(?::(\d+))?(am|pm)?", goal, re.IGNORECASE)
    if m:
        h1, m1, ap1 = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        h2, m2, ap2 = int(m.group(4)), int(m.group(5) or 0), m.group(6)
        if ap1 and ap1.lower() == "pm" and h1 < 12: h1 += 12
        if ap2 and ap2.lower() == "pm" and h2 < 12: h2 += 12
        if ap1 and ap1.lower() == "am" and h1 == 12: h1 = 0
        if ap2 and ap2.lower() == "am" and h2 == 12: h2 = 0

        base_date = _resolve_date_from_goal(goal)
        if base_date is None:
            base_date = dt(2023, 10, 15)

        ts1 = int(cal_mod.timegm(dt(base_date.year, base_date.month, base_date.day, h1, m1).timetuple()))
        ts2 = int(cal_mod.timegm(dt(base_date.year, base_date.month, base_date.day, h2, m2).timetuple()))
        sql = f"SELECT title FROM events WHERE start_ts >= {ts1} AND start_ts < {ts2} ORDER BY start_ts;"
        return [{
            "command": _calendar_query_cmd(sql),
            "thought": f"Query events between {h1}:00 and {h2}:00",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No events",
        }]
    return None

_DYNAMIC_GENERATORS["SimpleCalendarEventsInTimeRange"] = _gen_calendar_events_time_range_v2


# --- Tasks App Info Retrieval (org.tasks) ---

_TASKS_DB = "/data/data/org.tasks/databases/database"


def _gen_tasks_due_on_date(goal: str) -> List[Dict]:
    """Query tasks due on a date."""
    import calendar as cal_mod
    from datetime import datetime as dt

    resolved = _resolve_date_from_goal(goal)
    if resolved:
        # Tasks stores dueDate in milliseconds
        start_ms = int(cal_mod.timegm(resolved.timetuple())) * 1000
        end_ms = start_ms + 86400 * 1000
        sql = f"SELECT title FROM tasks WHERE dueDate >= {start_ms} AND dueDate < {end_ms} AND completed = 0;"
        return [{
            "command": f'adb shell "sqlite3 {_TASKS_DB} \\"{sql}\\""',
            "thought": f"Query tasks due on {resolved.strftime('%B %d %Y')}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No tasks",
        }]
    return None

_DYNAMIC_GENERATORS["TasksDueOnDate"] = _gen_tasks_due_on_date


def _gen_tasks_high_priority(goal: str) -> List[Dict]:
    """Query high priority tasks."""
    sql = "SELECT title FROM tasks WHERE importance = 0 AND completed = 0;"
    return [{
        "command": f'adb shell "sqlite3 {_TASKS_DB} \\"{sql}\\""',
        "thought": "Query high priority tasks",
        "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No tasks",
    }]

_DYNAMIC_GENERATORS["TasksHighPriorityTasks"] = _gen_tasks_high_priority


def _gen_tasks_high_priority_due_date(goal: str) -> List[Dict]:
    """Query high priority tasks due on a date."""
    import calendar as cal_mod

    resolved = _resolve_date_from_goal(goal)
    if resolved:
        start_ms = int(cal_mod.timegm(resolved.timetuple())) * 1000
        end_ms = start_ms + 86400 * 1000
        sql = f"SELECT title FROM tasks WHERE importance = 0 AND dueDate >= {start_ms} AND dueDate < {end_ms} AND completed = 0;"
        return [{
            "command": f'adb shell "sqlite3 {_TASKS_DB} \\"{sql}\\""',
            "thought": f"Query high priority tasks due {resolved.strftime('%B %d')}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No tasks",
        }]
    return None

_DYNAMIC_GENERATORS["TasksHighPriorityTasksDueOnDate"] = _gen_tasks_high_priority_due_date


def _gen_tasks_due_next_week(goal: str) -> List[Dict]:
    """Count tasks due next week."""
    import calendar as cal_mod
    from datetime import datetime as dt
    # Oct 15 is Sunday. Next week Mon-Sun = Oct 16-22
    start_ms = int(cal_mod.timegm(dt(2023, 10, 16).timetuple())) * 1000
    end_ms = int(cal_mod.timegm(dt(2023, 10, 23).timetuple())) * 1000
    sql = f"SELECT COUNT(*) FROM tasks WHERE dueDate >= {start_ms} AND dueDate < {end_ms} AND completed = 0;"
    return [{
        "command": f'adb shell "sqlite3 {_TASKS_DB} \\"{sql}\\""',
        "thought": "Count tasks due next week",
        "answer_from_output": lambda out: out.strip(),
    }]

_DYNAMIC_GENERATORS["TasksDueNextWeek"] = _gen_tasks_due_next_week


def _gen_tasks_completed_for_date(goal: str) -> List[Dict]:
    """Query tasks that are due on a date and are completed."""
    import calendar as cal_mod

    resolved = _resolve_date_from_goal(goal)
    if resolved:
        start_ms = int(cal_mod.timegm(resolved.timetuple())) * 1000
        end_ms = start_ms + 86400 * 1000
        # "Completed for date" = tasks due on that date that are marked completed
        sql = f"SELECT title FROM tasks WHERE dueDate >= {start_ms} AND dueDate < {end_ms} AND completed > 0;"
        return [{
            "command": f'adb shell "sqlite3 {_TASKS_DB} \\"{sql}\\""',
            "thought": f"Query completed tasks for {resolved.strftime('%B %d')}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No tasks",
        }]
    return None

_DYNAMIC_GENERATORS["TasksCompletedTasksForDate"] = _gen_tasks_completed_for_date


def _gen_tasks_incomplete_on_date(goal: str) -> List[Dict]:
    """Query incomplete tasks due by a date."""
    import calendar as cal_mod

    resolved = _resolve_date_from_goal(goal)
    if resolved:
        end_ms = int(cal_mod.timegm(resolved.timetuple())) * 1000 + 86400 * 1000
        sql = f"SELECT title FROM tasks WHERE dueDate < {end_ms} AND completed = 0 AND dueDate > 0;"
        return [{
            "command": f'adb shell "sqlite3 {_TASKS_DB} \\"{sql}\\""',
            "thought": f"Query incomplete tasks by {resolved.strftime('%B %d')}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No tasks",
        }]
    return None

_DYNAMIC_GENERATORS["TasksIncompleteTasksOnDate"] = _gen_tasks_incomplete_on_date


# --- Sports Tracker Info Retrieval (OpenTracks) ---

_SPORTS_DB = "/data/data/de.dennisguse.opentracks/databases/database.db"


def _gen_sports_activities_on_date(goal: str) -> List[Dict]:
    """Query activity types on a date."""
    import calendar as cal_mod

    resolved = _resolve_date_from_goal(goal)
    if resolved:
        start_ms = int(cal_mod.timegm(resolved.timetuple())) * 1000
        end_ms = start_ms + 86400 * 1000
        sql = f"SELECT DISTINCT category FROM tracks WHERE starttime >= {start_ms} AND starttime < {end_ms};"
        return [{
            "command": f'adb shell "sqlite3 {_SPORTS_DB} \\"{sql}\\""',
            "thought": f"Query activities on {resolved.strftime('%B %d %Y')}",
            "answer_from_output": lambda out: ", ".join(l.strip() for l in out.strip().split("\n") if l.strip()) if out.strip() else "No activities",
        }]
    return None

_DYNAMIC_GENERATORS["SportsTrackerActivitiesOnDate"] = _gen_sports_activities_on_date


def _gen_sports_count_for_week(goal: str) -> List[Dict]:
    """Count activities of a type this week."""
    import calendar as cal_mod
    from datetime import datetime as dt

    m = re.search(r"how many\s+(\w+)\s+activities", goal, re.IGNORECASE)
    if m:
        category = m.group(1).lower()
        # "this week" starting Monday = Oct 9-15, 2023
        start_ms = int(cal_mod.timegm(dt(2023, 10, 9).timetuple())) * 1000
        end_ms = int(cal_mod.timegm(dt(2023, 10, 16).timetuple())) * 1000
        sql = f"SELECT COUNT(*) FROM tracks WHERE category = '{category}' AND starttime >= {start_ms} AND starttime < {end_ms};"
        return [{
            "command": f'adb shell "sqlite3 {_SPORTS_DB} \\"{sql}\\""',
            "thought": f"Count {category} activities this week",
            "answer_from_output": lambda out: out.strip(),
        }]
    return None

_DYNAMIC_GENERATORS["SportsTrackerActivitiesCountForWeek"] = _gen_sports_count_for_week


def _gen_sports_duration(goal: str) -> List[Dict]:
    """Query activity duration in minutes."""
    import calendar as cal_mod

    m = re.search(r"(?:long|duration).*?(\w+)\s+activity", goal, re.IGNORECASE)
    resolved = _resolve_date_from_goal(goal)
    if m and resolved:
        category = m.group(1).lower()
        start_ms = int(cal_mod.timegm(resolved.timetuple())) * 1000
        end_ms = start_ms + 86400 * 1000
        sql = f"SELECT totaltime / 60000 FROM tracks WHERE category = '{category}' AND starttime >= {start_ms} AND starttime < {end_ms} LIMIT 1;"
        return [{
            "command": f'adb shell "sqlite3 {_SPORTS_DB} \\"{sql}\\""',
            "thought": f"Query {category} duration on {resolved.strftime('%B %d')}",
            "answer_from_output": lambda out: out.strip(),
        }]
    return None

_DYNAMIC_GENERATORS["SportsTrackerActivityDuration"] = _gen_sports_duration


def _gen_sports_longest_distance(goal: str) -> List[Dict]:
    """Query longest distance for a category this week."""
    import calendar as cal_mod
    from datetime import datetime as dt

    m = re.search(r"longest distance.*?(\w+)\s+activity", goal, re.IGNORECASE)
    if m:
        category = m.group(1).lower()
        start_ms = int(cal_mod.timegm(dt(2023, 10, 9).timetuple())) * 1000
        end_ms = int(cal_mod.timegm(dt(2023, 10, 16).timetuple())) * 1000
        sql = f"SELECT CAST(MAX(totaldistance) AS INTEGER) FROM tracks WHERE category = '{category}' AND starttime >= {start_ms} AND starttime < {end_ms};"
        return [{
            "command": f'adb shell "sqlite3 {_SPORTS_DB} \\"{sql}\\""',
            "thought": f"Query longest {category} distance this week",
            "answer_from_output": lambda out: out.strip(),
        }]
    return None

_DYNAMIC_GENERATORS["SportsTrackerLongestDistanceActivity"] = _gen_sports_longest_distance


def _gen_sports_total_duration(goal: str) -> List[Dict]:
    """Total duration of category this week."""
    import calendar as cal_mod
    from datetime import datetime as dt

    m = re.search(r"total duration.*?(\w+)\s+activities", goal, re.IGNORECASE)
    if m:
        category = m.group(1).lower()
        start_ms = int(cal_mod.timegm(dt(2023, 10, 9).timetuple())) * 1000
        end_ms = int(cal_mod.timegm(dt(2023, 10, 16).timetuple())) * 1000
        sql = f"SELECT SUM(totaltime) / 60000 FROM tracks WHERE category = '{category}' AND starttime >= {start_ms} AND starttime < {end_ms};"
        return [{
            "command": f'adb shell "sqlite3 {_SPORTS_DB} \\"{sql}\\""',
            "thought": f"Query total {category} duration this week",
            "answer_from_output": lambda out: out.strip(),
        }]
    return None

_DYNAMIC_GENERATORS["SportsTrackerTotalDurationForCategoryThisWeek"] = _gen_sports_total_duration


def _gen_sports_total_distance_interval(goal: str) -> List[Dict]:
    """Total distance for category over date interval."""
    import calendar as cal_mod

    m = re.search(r"total distance.*?(\w+)\s+activities.*?from\s+(\w+\s+\d+\s+\d{4})\s+to\s+(\w+\s+\d+\s+\d{4})", goal, re.IGNORECASE)
    if not m:
        m = re.search(r"total distance.*?for\s+(\w+)\s+activities", goal, re.IGNORECASE)
    if m:
        category = m.group(1).lower()
        # Parse date range
        from datetime import datetime as dt
        if len(m.groups()) >= 3:
            d1 = dt.strptime(m.group(2), "%B %d %Y")
            d2 = dt.strptime(m.group(3), "%B %d %Y")
        else:
            # Default to this week
            d1 = dt(2023, 10, 9)
            d2 = dt(2023, 10, 16)
        start_ms = int(cal_mod.timegm(d1.timetuple())) * 1000
        end_ms = int(cal_mod.timegm(d2.timetuple())) * 1000 + 86400 * 1000
        sql = f"SELECT CAST(SUM(totaldistance) AS INTEGER) FROM tracks WHERE category = '{category}' AND starttime >= {start_ms} AND starttime < {end_ms};"
        return [{
            "command": f'adb shell "sqlite3 {_SPORTS_DB} \\"{sql}\\""',
            "thought": f"Query total {category} distance",
            "answer_from_output": lambda out: out.strip(),
        }]
    return None

_DYNAMIC_GENERATORS["SportsTrackerTotalDistanceForCategoryOverInterval"] = _gen_sports_total_distance_interval


# --- Joplin Notes Info Retrieval ---

_JOPLIN_DB = "/data/data/net.cozic.joplin/databases/joplin.sqlite"


def _gen_notes_is_todo(goal: str) -> List[Dict]:
    """Check if a note is a todo."""
    m = re.search(r"note titled\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        title = m.group(1)
        sql = f"SELECT is_todo FROM notes WHERE title = '{title}' LIMIT 1;"
        def format_answer(out):
            val = out.strip()
            return "True" if val == "1" else "False"
        return [{
            "command": f'adb shell "sqlite3 {_JOPLIN_DB} \\"{sql}\\""',
            "thought": f"Check if '{title}' is a todo",
            "answer_from_output": format_answer,
        }]
    return None

_DYNAMIC_GENERATORS["NotesIsTodo"] = _gen_notes_is_todo


def _gen_notes_todo_count(goal: str) -> List[Dict]:
    """Count todos in a folder."""
    m = re.search(r"in the\s+'([^']+)'\s+folder", goal, re.IGNORECASE)
    if m:
        folder = m.group(1)
        sql = f"SELECT COUNT(*) FROM notes WHERE is_todo = 1 AND parent_id = (SELECT id FROM folders WHERE title = '{folder}');"
        return [{
            "command": f'adb shell "sqlite3 {_JOPLIN_DB} \\"{sql}\\""',
            "thought": f"Count todos in '{folder}' folder",
            "answer_from_output": lambda out: out.strip(),
        }]
    return None

_DYNAMIC_GENERATORS["NotesTodoItemCount"] = _gen_notes_todo_count


def _gen_notes_meeting_attendee_count(goal: str) -> List[Dict]:
    """Count attendees in a meeting note."""
    m = re.search(r"meeting titled\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        title = m.group(1)
        sql = f"SELECT body FROM notes WHERE title = '{title}' LIMIT 1;"
        def format_answer(out):
            body = out.strip()
            if not body:
                return "0"
            # Look for patterns like "25 individuals attended", "X attendees", "X people"
            for line in body.split("\n"):
                num_m = re.search(r'(\d+)\s+(?:individuals?|attendees?|people|participants?|members?)\s+(?:attended|present|were)', line, re.IGNORECASE)
                if num_m:
                    return num_m.group(1)
                # Also check "attended by X"
                num_m2 = re.search(r'(?:attended by|present:?)\s+(\d+)', line, re.IGNORECASE)
                if num_m2:
                    return num_m2.group(1)
            # Fallback: find any standalone number near "attend"
            attend_m = re.search(r'(\d+).*?attend|attend.*?(\d+)', body, re.IGNORECASE)
            if attend_m:
                return attend_m.group(1) or attend_m.group(2)
            return "0"
        return [{
            "command": f'adb shell "sqlite3 {_JOPLIN_DB} \\"{sql}\\""',
            "thought": f"Query attendees for '{title}'",
            "answer_from_output": format_answer,
        }]
    return None

_DYNAMIC_GENERATORS["NotesMeetingAttendeeCount"] = _gen_notes_meeting_attendee_count


def _gen_notes_recipe_ingredient(goal: str) -> List[Dict]:
    """Query ingredient quantity from recipe note."""
    m = re.search(r"quantity of\s+(.+?)\s+do I need.*?recipe\s+'([^']+)'", goal, re.IGNORECASE)
    if not m:
        m = re.search(r"quantity of\s+(.+?)\s+for the recipe\s+'([^']+)'", goal, re.IGNORECASE)
    if not m:
        m = re.search(r"(?:quantity|amount).*?(\w[\w\s]+?)\s+.*?recipe\s+'([^']+)'", goal, re.IGNORECASE)
    if m:
        ingredient = m.group(1).strip()
        recipe = m.group(2)
        sql = f"SELECT body FROM notes WHERE title = '{recipe}' LIMIT 1;"
        def format_answer(out, ingr=ingredient):
            body = out.strip()
            if not body:
                return "0"
            # Find the line with the ingredient
            for line in body.split("\n"):
                if ingr.lower() in line.lower():
                    # Clean the line: remove list markers
                    clean = line.strip().lstrip("-").lstrip("*").strip()
                    # Extract quantity: everything before the ingredient name
                    idx = clean.lower().index(ingr.lower())
                    qty = clean[:idx].strip()
                    if qty:
                        return qty
            return "0"
        return [{
            "command": f'adb shell "sqlite3 {_JOPLIN_DB} \\"{sql}\\""',
            "thought": f"Query {ingredient} in recipe '{recipe}'",
            "answer_from_output": format_answer,
        }]
    return None

_DYNAMIC_GENERATORS["NotesRecipeIngredientCount"] = _gen_notes_recipe_ingredient


# --- Expense Operations (SQLite) ---

_EXPENSE_DB = "/data/data/com.arduia.expense/databases/accounting.db"

_EXPENSE_CATEGORIES = {
    'others': 1, 'income': 2, 'food': 3, 'housing': 4, 'social': 5,
    'entertainment': 6, 'transportation': 7, 'clothes': 8,
    'health care': 9, 'education': 10, 'donation': 11,
}


def _gen_expense_delete_single(goal: str) -> List[Dict]:
    """Delete a single expense."""
    m = re.search(r"Delete.*?expenses.*?:\s*(.*?)(?:\.|$)", goal)
    if m:
        expense_name = m.group(1).strip().rstrip(".")
        return [
            _cmd(f"adb shell am force-stop com.arduia.expense", "Stop expense app"),
            _cmd(f'adb shell "sqlite3 {_EXPENSE_DB} \\"DELETE FROM expense WHERE name=\'{expense_name}\';\\""',
                 f"Delete expense '{expense_name}'"),
        ]
    return None

_DYNAMIC_GENERATORS["ExpenseDeleteSingle"] = _gen_expense_delete_single


def _gen_expense_delete_multiple(goal: str) -> List[Dict]:
    """Delete multiple expenses."""
    m = re.search(r"Delete.*?expenses.*?:\s*(.*?)(?:\.\s*$|$)", goal, re.DOTALL)
    if m:
        names_str = m.group(1).strip().rstrip(".")
        names = _parse_comma_list(names_str)
        conditions = " OR ".join(f"name='{n.replace(chr(39), chr(39)+chr(39))}'" for n in names)
        return [
            _cmd(f"adb shell am force-stop com.arduia.expense", "Stop expense app"),
            _cmd(f'adb shell "sqlite3 {_EXPENSE_DB} \\"DELETE FROM expense WHERE {conditions};\\""',
                 f"Delete {len(names)} expenses"),
        ]
    return None

_DYNAMIC_GENERATORS["ExpenseDeleteMultiple"] = _gen_expense_delete_multiple
_DYNAMIC_GENERATORS["ExpenseDeleteMultiple2"] = _gen_expense_delete_multiple


def _gen_expense_add(goal: str) -> List[Dict]:
    """Add one or more expenses using individual ADB commands.
    Uses Python-side category mapping (hardcoded in Pro Expense app).
    """
    # Parse expenses from goal text
    expenses = []
    blocks = re.split(r"Expense:\s*", goal)
    for block in blocks[1:]:
        lines = block.strip().split("\n")
        name = lines[0].strip()
        amount_str = ""
        category = "others"
        note = ""
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("amount_dollars:") or line.startswith("amount:"):
                amount_str = line.split("$")[-1].strip() if "$" in line else line.split(":")[-1].strip()
            elif line.startswith("category_name:") or line.startswith("category:"):
                category = line.split(":")[-1].strip().lower()
            elif line.startswith("note:"):
                note = line.split(":", 1)[-1].strip()
        if name and amount_str:
            try:
                amount_cents = int(float(amount_str) * 100)
            except ValueError:
                amount_cents = 0
            expenses.append((name, amount_cents, category, note))

    if not expenses:
        return None

    db = _EXPENSE_DB
    cmds = [
        _cmd("adb shell am force-stop com.arduia.expense", "Stop expense app"),
        _cmd(f'adb shell "sqlite3 {db} \\"SELECT DISTINCT category, name FROM expense LIMIT 10;\\""',
             "Discover existing expense categories"),
    ]
    for name, amount, category, note in expenses:
        name_esc = name.replace("'", "''")
        note_esc = note.replace("'", "''")
        cat_lower = category.lower().replace(" ", "")
        cat_id = _EXPENSE_CATEGORIES.get(cat_lower, _EXPENSE_CATEGORIES.get(category.lower(), 1))
        sql = (f"INSERT INTO expense (name, amount, category, note, created_date, modified_date) "
               f"VALUES ('{name_esc}', {amount}, {cat_id}, '{note_esc}', $(date +%s)000, $(date +%s)000);")
        cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"{sql}\\""',
                         f"Add expense '{name}' (amount={amount}, category={cat_id})"))
    return cmds

_DYNAMIC_GENERATORS["ExpenseAddSingle"] = _gen_expense_add
_DYNAMIC_GENERATORS["ExpenseAddMultiple"] = _gen_expense_add


def _gen_expense_delete_duplicates(goal: str) -> List[Dict]:
    """Delete duplicate expenses, keeping one of each."""
    return [
        _cmd(f"adb shell am force-stop com.arduia.expense", "Stop expense app"),
        _cmd(f'adb shell "sqlite3 {_EXPENSE_DB} \\"DELETE FROM expense WHERE expense_id NOT IN (SELECT MIN(expense_id) FROM expense GROUP BY name, amount, category);\\""',
             "Delete duplicate expenses"),
    ]

_DYNAMIC_GENERATORS["ExpenseDeleteDuplicates"] = _gen_expense_delete_duplicates
_DYNAMIC_GENERATORS["ExpenseDeleteDuplicates2"] = _gen_expense_delete_duplicates


# --- Recipe Operations (SQLite) ---

_RECIPE_DB = "/data/data/com.flauschcode.broccoli/databases/broccoli"


def _gen_recipe_delete_single(goal: str) -> List[Dict]:
    """Delete a single recipe."""
    m = re.search(r"Delete.*?recipes.*?(?:Broccoli|app):\s*(.*?)(?:\.|$)", goal)
    if m:
        recipe_name = m.group(1).strip().rstrip(".")
        return [
            _cmd(f"adb shell am force-stop com.flauschcode.broccoli", "Stop Broccoli app"),
            _cmd(f'adb shell "sqlite3 {_RECIPE_DB} \\"DELETE FROM recipes WHERE title=\'{recipe_name}\';\\""',
                 f"Delete recipe '{recipe_name}'"),
        ]
    return None

_DYNAMIC_GENERATORS["RecipeDeleteSingleRecipe"] = _gen_recipe_delete_single
_DYNAMIC_GENERATORS["RecipeDeleteSingleWithRecipeWithNoise"] = _gen_recipe_delete_single


def _parse_comma_list(text: str) -> List[str]:
    """Parse a comma-separated list, handling 'X and Y' at the end."""
    # Split on ", " first (don't replace "and" - it could be in names)
    items = [i.strip() for i in text.split(",") if i.strip()]
    # Handle case where last two items are joined with " and " instead of ","
    # But only if the last item doesn't contain "and" as part of a name
    # Simple heuristic: if last item starts with "and ", it's a separator
    if items and items[-1].lower().startswith("and "):
        items[-1] = items[-1][4:].strip()
    return items


def _gen_recipe_delete_multiple(goal: str) -> List[Dict]:
    """Delete multiple recipes."""
    m = re.search(r"Delete.*?recipes.*?(?:Broccoli|app):\s*(.*?)(?:\.\s*$|$)", goal, re.DOTALL)
    if m:
        names_str = m.group(1).strip().rstrip(".")
        names = _parse_comma_list(names_str)
        conditions = " OR ".join(f"title='{n.replace(chr(39), chr(39)+chr(39))}'" for n in names)
        return [
            _cmd(f"adb shell am force-stop com.flauschcode.broccoli", "Stop Broccoli app"),
            _cmd(f'adb shell "sqlite3 {_RECIPE_DB} \\"DELETE FROM recipes WHERE {conditions};\\""',
                 f"Delete {len(names)} recipes"),
        ]
    return None

_DYNAMIC_GENERATORS["RecipeDeleteMultipleRecipes"] = _gen_recipe_delete_multiple
_DYNAMIC_GENERATORS["RecipeDeleteMultipleRecipesWithNoise"] = _gen_recipe_delete_multiple


def _gen_recipe_delete_with_constraint(goal: str) -> List[Dict]:
    """Delete recipes matching a constraint (e.g., containing ingredient)."""
    m = re.search(r"Delete.*?recipes.*?that\s+(.*?)(?:\.|$)", goal)
    if m:
        constraint = m.group(1).strip().rstrip(".")
        # Extract keyword from constraint like "use broccoli in the directions"
        keyword_m = re.search(r"use\s+(\w+)\s+in the (directions|ingredients)", constraint)
        if keyword_m:
            keyword = keyword_m.group(1)
            field = keyword_m.group(2)
            return [
                _cmd(f"adb shell am force-stop com.flauschcode.broccoli", "Stop Broccoli app"),
                _cmd(f'adb shell "sqlite3 {_RECIPE_DB} \\"DELETE FROM recipes WHERE {field} LIKE \'%{keyword}%\';\\""',
                     f"Delete recipes with {keyword} in {field}"),
            ]
    return None

_DYNAMIC_GENERATORS["RecipeDeleteMultipleRecipesWithConstraint"] = _gen_recipe_delete_with_constraint


def _gen_recipe_delete_duplicates(goal: str) -> List[Dict]:
    """Delete duplicate recipes, keeping one instance of each."""
    # Group by all content fields (not just title) to find true duplicates
    return [
        _cmd(f"adb shell am force-stop com.flauschcode.broccoli", "Stop Broccoli app"),
        _cmd(f'adb shell "sqlite3 {_RECIPE_DB} \\"DELETE FROM recipes WHERE recipeId NOT IN (SELECT MIN(recipeId) FROM recipes GROUP BY title, description, servings, preparationTime, ingredients, directions);\\""',
             "Delete duplicate recipes"),
    ]

_DYNAMIC_GENERATORS["RecipeDeleteDuplicateRecipes"] = _gen_recipe_delete_duplicates
_DYNAMIC_GENERATORS["RecipeDeleteDuplicateRecipes2"] = _gen_recipe_delete_duplicates
_DYNAMIC_GENERATORS["RecipeDeleteDuplicateRecipes3"] = _gen_recipe_delete_duplicates


def _gen_recipe_add(goal: str) -> List[Dict]:
    """Add one or more recipes."""
    recipes = []
    blocks = re.split(r"Recipe:\s*", goal)
    for block in blocks[1:]:
        lines = block.strip().split("\n")
        title = lines[0].strip()
        description = servings = prep_time = source = ingredients = directions = ""
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("description:"):
                description = line.split(":", 1)[-1].strip()
            elif line.startswith("servings:"):
                servings = line.split(":", 1)[-1].strip()
            elif line.startswith("preparationTime:") or line.startswith("preparation_time:"):
                prep_time = line.split(":", 1)[-1].strip()
            elif line.startswith("source:"):
                source = line.split(":", 1)[-1].strip()
            elif line.startswith("ingredients:"):
                ingredients = line.split(":", 1)[-1].strip()
            elif line.startswith("directions:"):
                directions = line.split(":", 1)[-1].strip()
        if title:
            recipes.append((title, description, servings, prep_time, source, ingredients, directions))

    if not recipes:
        return None

    cmds = [_cmd(f"adb shell am force-stop com.flauschcode.broccoli", "Stop Broccoli app")]
    for title, desc, serv, prep, src, ingr, dirs in recipes:
        # Escape single quotes
        vals = [title, desc, serv, prep, src, ingr, dirs]
        vals = [v.replace("'", "''") for v in vals]
        sql = f"INSERT INTO recipes (title, description, servings, preparationTime, source, ingredients, directions, favorite, imageName) VALUES ('{vals[0]}', '{vals[1]}', '{vals[2]}', '{vals[3]}', '{vals[4]}', '{vals[5]}', '{vals[6]}', 0, '');"
        cmds.append(_cmd(
            f'adb shell "sqlite3 {_RECIPE_DB} \\"{sql}\\""',
            f"Add recipe '{title}'"))
    return cmds

_DYNAMIC_GENERATORS["RecipeAddSingleRecipe"] = _gen_recipe_add
_DYNAMIC_GENERATORS["RecipeAddMultipleRecipes"] = _gen_recipe_add


# --- Retro Music Operations (SQLite) ---

_RETRO_DB = "/data/data/code.name.monkey.retromusic/databases/playlist.db"


def _parse_song_list_from_goal(goal: str) -> Tuple[str, List[str]]:
    """Parse playlist name and song titles from goal text."""
    # Extract playlist name
    name_m = re.search(r'titled\s+"([^"]+)"', goal)
    playlist_name = name_m.group(1) if name_m else ""

    # Extract song list - skip everything up to and including "in order:" or "following songs:"
    # Handle: "following songs, in order: X, Y" or "in order: X, Y" or "songs: X, Y"
    songs_m = re.search(r'(?:in order|following songs)[,:]?\s*(?:in order[,:]?\s*)?(.*?)(?:\s+to (?:my|the)|\s+with a duration|\.\s+Then|\.\s*$)', goal, re.DOTALL)
    if not songs_m:
        songs_m = re.search(r'(?:in order|songs)[,:]?\s*(.*?)$', goal, re.DOTALL)
    if songs_m:
        songs_str = songs_m.group(1).strip().rstrip(".")
        # Clean up: remove leading "in order:" if still present
        songs_str = re.sub(r'^in order[,:]\s*', '', songs_str)
        songs = _parse_comma_list(songs_str)
    else:
        songs = []
    return playlist_name, songs


def _gen_retro_create_playlist(goal: str) -> List[Dict]:
    """Create a Retro Music playlist via individual ADB commands.
    Queries MediaStore per song, then inserts into playlist DB."""
    playlist_name, songs = _parse_song_list_from_goal(goal)
    if not playlist_name or not songs:
        return None

    db = _RETRO_DB
    cmds = [
        _cmd("adb shell am force-stop code.name.monkey.retromusic", "Stop Retro Music"),
        _cmd(f'adb shell "sqlite3 {db} \\"INSERT INTO PlaylistEntity (playlist_name) VALUES (\'{playlist_name}\');\\""',
             f"Create playlist '{playlist_name}'"),
        _cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(playlist_id) FROM PlaylistEntity;\\""',
             "Get playlist ID"),
    ]
    # For each song: query MediaStore, then insert SongEntity
    for title in songs:
        title_esc = title.replace("'", "''")
        cmds.append(
            _cmd(f"""adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:album:artist_id:artist:date_modified --where \\"title='{title_esc}'\\" | head -1" """.strip(),
                 f"Query MediaStore for '{title}'"))
        # Use command_fn to parse query output and build INSERT
        def _make_song_insert(outs, t_esc=title_esc, database=db):
            pid = _extract_int(outs[2])  # playlist ID is always output index 2
            fields = _parse_media_fields(outs[-1])
            sid = fields.get('_id', '0')
            dur = fields.get('duration', '0')
            data = fields.get('_data', '').replace("'", "''")
            aid = fields.get('album_id', '0')
            aname = fields.get('album', '').replace("'", "''")
            artid = fields.get('artist_id', '0')
            artname = fields.get('artist', '').replace("'", "''")
            dmod = fields.get('date_modified', '0')
            sql = (f"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, "
                   f"data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) "
                   f"VALUES ({pid}, {sid}, '{t_esc}', 0, 0, {dur}, '{data}', {dmod}, {aid}, '{aname}', {artid}, '{artname}', '', '');")
            return f'adb shell "sqlite3 {database} \\"{sql}\\""'
        cmds.append(_cmd_fn(_make_song_insert, f"Insert '{title}' into playlist"))

    return cmds

_DYNAMIC_GENERATORS["RetroCreatePlaylist"] = _gen_retro_create_playlist
def _gen_retro_save_playlist(goal: str) -> List[Dict]:
    """Create Retro playlist AND export .m3u file to Downloads using individual commands."""
    playlist_name, songs = _parse_song_list_from_goal(goal)
    if not playlist_name or not songs:
        return None

    db = _RETRO_DB
    m3u_path = f"/storage/emulated/0/Download/{playlist_name}.m3u"
    cmds = [
        _cmd("adb shell am force-stop code.name.monkey.retromusic", "Stop Retro Music"),
        _cmd("adb shell mkdir -p /storage/emulated/0/Downloads /storage/emulated/0/Download", "Ensure download dirs"),
        _cmd(f'adb shell "sqlite3 {db} \\"INSERT INTO PlaylistEntity (playlist_name) VALUES (\'{playlist_name}\');\\""',
             f"Create playlist '{playlist_name}'"),
        _cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(playlist_id) FROM PlaylistEntity;\\""',
             "Get playlist ID"),
    ]
    # Track m3u entries to write at the end
    song_data_indices = []  # indices into outputs where MediaStore query results are
    for i, title in enumerate(songs):
        title_esc = title.replace("'", "''")
        cmds.append(
            _cmd(f"""adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:album:artist_id:artist:date_modified --where \\"title='{title_esc}'\\" | head -1" """.strip(),
                 f"Query MediaStore for '{title}'"))

        def _make_song_insert(outs, t_esc=title_esc, database=db):
            pid = _extract_int(outs[3])  # playlist ID is output index 3
            fields = _parse_media_fields(outs[-1])
            sid = fields.get('_id', '0')
            dur = fields.get('duration', '0')
            data = fields.get('_data', '').replace("'", "''")
            aid = fields.get('album_id', '0')
            aname = fields.get('album', '').replace("'", "''")
            artid = fields.get('artist_id', '0')
            artname = fields.get('artist', '').replace("'", "''")
            dmod = fields.get('date_modified', '0')
            sql = (f"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, "
                   f"data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) "
                   f"VALUES ({pid}, {sid}, '{t_esc}', 0, 0, {dur}, '{data}', {dmod}, {aid}, '{aname}', {artid}, '{artname}', '', '');")
            return f'adb shell "sqlite3 {database} \\"{sql}\\""'
        def _make_m3u_append(outs, mp=m3u_path):
            fields = _parse_media_fields(outs[-2])  # MediaStore output is 2 back (before insert)
            data_raw = fields.get('_data', '')
            return f'adb shell "echo \'{data_raw}\' >> \'{mp}\'"'
        cmds.append(_cmd_fn(_make_song_insert, f"Insert '{title}' into playlist"))
        cmds.append(_cmd_fn(_make_m3u_append, f"Append '{title}' path to m3u"))

    return cmds

_DYNAMIC_GENERATORS["RetroSavePlaylist"] = _gen_retro_save_playlist


def _gen_retro_playing_queue(goal: str) -> List[Dict]:
    """Add songs to Retro Music playing queue using individual ADB commands."""
    _, songs = _parse_song_list_from_goal(goal)
    if not songs:
        # Try alternate pattern: "Add the following songs, in order, X, Y to my playing queue"
        m = re.search(r'(?:in order|songs)[,:]?\s*(.*?)\s+to my playing queue', goal, re.DOTALL)
        if m:
            songs = _parse_comma_list(m.group(1).strip())
    if not songs:
        return None

    db = "/data/data/code.name.monkey.retromusic/databases/music_playback_state.db"
    cmds = [
        _cmd("adb shell am force-stop code.name.monkey.retromusic", "Stop Retro Music"),
        _cmd(f'adb shell "sqlite3 {db} \\"CREATE TABLE IF NOT EXISTS playing_queue (id INTEGER PRIMARY KEY, title TEXT NOT NULL, data TEXT, duration INTEGER, album_id INTEGER, artist_id INTEGER);\\""',
             "Ensure playing_queue table exists"),
    ]
    for title in songs:
        title_esc = title.replace("'", "''")
        cmds.append(
            _cmd(f"""adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:artist_id --where \\"title='{title_esc}'\\" | head -1" """.strip(),
                 f"Query MediaStore for '{title}'"))

        def _make_queue_insert(outs, t_esc=title_esc, database=db):
            fields = _parse_media_fields(outs[-1])
            sid = fields.get('_id', '0')
            dur = fields.get('duration', '0')
            data = fields.get('_data', '').replace("'", "''")
            aid = fields.get('album_id', '0')
            artid = fields.get('artist_id', '0')
            sql = (f"INSERT INTO playing_queue (id, title, data, duration, album_id, artist_id) "
                   f"VALUES ({sid}, '{t_esc}', '{data}', {dur}, {aid}, {artid});")
            return f'adb shell "sqlite3 {database} \\"{sql}\\""'
        cmds.append(_cmd_fn(_make_queue_insert, f"Insert '{title}' into playing queue"))

    return cmds

_DYNAMIC_GENERATORS["RetroPlayingQueue"] = _gen_retro_playing_queue


# --- OsmAnd Operations ---

def _gen_osmand_marker(goal: str) -> List[Dict]:
    """Add OsmAnd map marker via SQLite."""
    m = re.search(r"marker for\s+(.*?)\s+in the OsmAnd", goal, re.IGNORECASE)
    if m:
        location = m.group(1)
        # Geocode common Liechtenstein locations
        coords = {
            "planken": (47.1858882, 9.5452201),
            "malbun": (47.1026191, 9.6083057),
            "vaduz": (47.141, 9.521),
            "balzers": (47.0688832, 9.5061564),
            "rotenboden": (47.1275785, 9.5387131),
            "triesenberg": (47.118, 9.543),
            "schaan": (47.1663432, 9.5103085),
            "bendern": (47.2122151, 9.5062101),
            "nendeln": (47.1973857, 9.5430636),
            "oberplanken": (47.1784977, 9.5450163),
            "ruggell": (47.23976, 9.5262837),
            "schaanwald": (47.2165476, 9.5699984),
            "schönberg": (47.1303814, 9.5930117),
            "triesen": (47.106997, 9.5274854),
        }
        loc_lower = location.lower().split(",")[0].strip()
        lat, lon = coords.get(loc_lower, (47.141, 9.521))  # default: Vaduz
        db = "/data/data/net.osmand/databases/map_markers_db"
        loc_esc = location.replace("'", "''")
        sql = f"INSERT INTO map_markers (marker_id, marker_lat, marker_lon, marker_description, marker_active, marker_added, marker_visited, group_name, group_key, marker_color, marker_next_key, marker_disabled, marker_selected, marker_map_object_name) VALUES ('marker_{loc_lower}', {lat}, {lon}, '{loc_esc}', 1, 0, 0, '', '', 0, '', 0, 0, '{loc_lower}');"
        return [
            _cmd(f'adb shell "sqlite3 {db} \\"{sql}\\""', f"Add marker for {location}"),
        ]
    return None

_DYNAMIC_GENERATORS["OsmAndMarker"] = _gen_osmand_marker


def _gen_osmand_favorite(goal: str) -> List[Dict]:
    """Add OsmAnd favorite via GPX file."""
    m = re.search(r"favorite.*?marker for\s+(.*?)\s+in the OsmAnd", goal, re.IGNORECASE)
    if m:
        location = m.group(1)
        coords = {
            "planken": (47.1858882, 9.5452201),
            "malbun": (47.1026191, 9.6083057),
            "vaduz": (47.141, 9.521),
            "balzers": (47.0688832, 9.5061564),
            "rotenboden": (47.1275785, 9.5387131),
            "triesenberg": (47.118, 9.543),
            "schaan": (47.1663432, 9.5103085),
            "bendern": (47.2122151, 9.5062101),
            "nendeln": (47.1973857, 9.5430636),
            "oberplanken": (47.1784977, 9.5450163),
            "ruggell": (47.23976, 9.5262837),
            "schaanwald": (47.2165476, 9.5699984),
            "schönberg": (47.1303814, 9.5930117),
            "triesen": (47.106997, 9.5274854),
        }
        loc_lower = location.lower().split(",")[0].strip()
        lat, lon = coords.get(loc_lower, (47.141, 9.521))
        gpx = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">
  <wpt lat="{lat}" lon="{lon}">
    <name>{location}</name>
  </wpt>
</gpx>"""
        gpx_b64 = base64.b64encode(gpx.encode()).decode()
        return [
            _cmd("adb shell mkdir -p /data/media/0/Android/data/net.osmand/files/favorites/", "Ensure favorites dir"),
            _cmd(f'adb shell "echo {gpx_b64} | base64 -d > /data/media/0/Android/data/net.osmand/files/favorites/favorites.gpx"',
                 f"Write favorite GPX for {location}"),
        ]
    return None

_DYNAMIC_GENERATORS["OsmAndFavorite"] = _gen_osmand_favorite


def _gen_osmand_track(goal: str) -> List[Dict]:
    """Save OsmAnd track with waypoints."""
    m = re.search(r"waypoints\s+(.*?)(?:\.|$)", goal)
    if m:
        waypoints_str = m.group(1).strip().rstrip(".")
        waypoints = _parse_comma_list(waypoints_str)
        coords = {
            "planken": (47.1858882, 9.5452201), "malbun": (47.1026191, 9.6083057),
            "vaduz": (47.141, 9.521), "balzers": (47.0688832, 9.5061564),
            "rotenboden": (47.1275785, 9.5387131), "triesenberg": (47.118, 9.543),
            "schaan": (47.1663432, 9.5103085), "bendern": (47.2122151, 9.5062101),
            "nendeln": (47.1973857, 9.5430636), "oberplanken": (47.1784977, 9.5450163),
            "ruggell": (47.23976, 9.5262837), "schaanwald": (47.2165476, 9.5699984),
            "schönberg": (47.1303814, 9.5930117), "triesen": (47.106997, 9.5274854),
        }
        trkpts = []
        for wp in waypoints:
            loc = wp.lower().split(",")[0].strip()
            lat, lon = coords.get(loc, (47.141, 9.521))
            trkpts.append(f'      <trkpt lat="{lat}" lon="{lon}"><name>{wp}</name></trkpt>')
        gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">\n'
               '  <trk>\n    <trkseg>\n' +
               "\n".join(trkpts) + '\n'
               '    </trkseg>\n  </trk>\n</gpx>')
        gpx_b64 = base64.b64encode(gpx.encode()).decode()
        return [
            _cmd("adb shell mkdir -p /data/media/0/Android/data/net.osmand/files/tracks/", "Ensure tracks dir"),
            _cmd(f'adb shell "echo {gpx_b64} | base64 -d > /data/media/0/Android/data/net.osmand/files/tracks/track.gpx"',
                 f"Write track GPX with {len(waypoints)} waypoints"),
        ]
    return None

_DYNAMIC_GENERATORS["OsmAndTrack"] = _gen_osmand_track


# --- Cross-app tasks (read file + insert) ---

def _parse_recipes_from_file_content(content: str, filter_text: str = "") -> List[Tuple]:
    """Parse recipes from file content (pipe-delimited or block format).
    Returns list of (title, description, servings, prep_time, source, ingredients, directions)."""
    recipes = []
    lines = content.strip().split("\n")
    if not lines:
        return recipes

    # Check if pipe-delimited
    if "|" in lines[0]:
        for line in lines[1:]:
            parts = line.split("|")
            if len(parts) >= 6:
                title, desc, serv, prep, ingr, dirs = [p.strip() for p in parts[:6]]
                if filter_text and filter_text.lower() not in prep.lower():
                    continue
                recipes.append((title, desc, serv, prep, "", ingr, dirs))
    else:
        # Block format
        title = desc = serv = prep = src = ingr = dirs = ""
        for line in lines:
            if line.startswith("Recipe: "):
                if title:
                    if not filter_text or filter_text.lower() in prep.lower():
                        recipes.append((title, desc, serv, prep, src, ingr, dirs))
                title = line[len("Recipe: "):]
                desc = serv = prep = src = ingr = dirs = ""
            elif line.strip().startswith("description:"):
                desc = line.strip()[len("description:"):].strip()
            elif line.strip().startswith("servings:"):
                serv = line.strip()[len("servings:"):].strip()
            elif line.strip().startswith("preparationTime:"):
                prep = line.strip()[len("preparationTime:"):].strip()
            elif line.strip().startswith("source:"):
                src = line.strip()[len("source:"):].strip()
            elif line.strip().startswith("ingredients:"):
                ingr = line.strip()[len("ingredients:"):].strip()
            elif line.strip().startswith("directions:"):
                dirs = line.strip()[len("directions:"):].strip()
        if title and (not filter_text or filter_text.lower() in prep.lower()):
            recipes.append((title, desc, serv, prep, src, ingr, dirs))
    return recipes


def _gen_recipe_add_from_markor(goal: str) -> List[Dict]:
    """Read recipes from Markor file and insert into Broccoli DB using individual commands."""
    filter_text = ""
    m2 = re.search(r"that take\s+(.+?)\s+to prepare", goal)
    if m2:
        filter_text = m2.group(1).strip()

    db = "/data/data/com.flauschcode.broccoli/databases/broccoli"
    markor = "/storage/emulated/0/Documents/Markor/recipes.txt"

    def _build_recipe_inserts(outs, database=db, ft=filter_text):
        content = outs[-1]
        recipes = _parse_recipes_from_file_content(content, ft)
        if not recipes:
            return 'adb shell "echo No matching recipes found"'
        # Build a single sqlite3 call with multiple INSERT statements
        stmts = []
        for title, desc, serv, prep, src, ingr, dirs in recipes:
            vals = [title, desc, serv, prep, src, ingr, dirs]
            vals = [v.replace("'", "''") for v in vals]
            stmts.append(
                f"INSERT INTO recipes (title,description,servings,preparationTime,source,ingredients,directions,favorite,imageName) "
                f"VALUES ('{vals[0]}','{vals[1]}','{vals[2]}','{vals[3]}','{vals[4]}','{vals[5]}','{vals[6]}',0,'');")
        combined_sql = " ".join(stmts)
        return f'adb shell "sqlite3 {database} \\"{combined_sql}\\""'

    return [
        _cmd("adb shell am force-stop com.flauschcode.broccoli", "Stop Broccoli app"),
        _cmd(f"adb shell cat {markor}", "Read recipes file"),
        _cmd_fn(_build_recipe_inserts, "Insert recipes from file into DB"),
    ]

_DYNAMIC_GENERATORS["RecipeAddMultipleRecipesFromMarkor"] = _gen_recipe_add_from_markor
_DYNAMIC_GENERATORS["RecipeAddMultipleRecipesFromMarkor2"] = _gen_recipe_add_from_markor


def _parse_expenses_from_file_content(content: str) -> List[Tuple]:
    """Parse expenses from pipe-delimited file content.
    Returns list of (name, amount_cents, category_id, note) for reimbursable entries."""
    expenses = []
    lines = content.strip().split("\n")
    for line in lines[1:]:  # skip header
        parts = line.split("|")
        if len(parts) < 4:
            continue
        name, amount_str, cat_str, note = [p.strip() for p in parts[:4]]
        if "reimbursable" not in note.lower():
            continue
        # Parse amount
        amt = amount_str.replace("$", "").strip()
        try:
            cents = int(float(amt) * 100)
        except ValueError:
            cents = 0
        # Map category
        cat_lower = cat_str.lower().replace(" ", "")
        cat_id = _EXPENSE_CATEGORIES.get(cat_lower, _EXPENSE_CATEGORIES.get(cat_str.lower(), 1))
        # Clean note
        clean_note = re.sub(r'\.\s*[Rr]eimbursable\.?', '', note).strip()
        expenses.append((name, cents, cat_id, clean_note))
    return expenses


def _gen_expense_add_from_markor(goal: str) -> List[Dict]:
    """Read expenses from Markor, filter reimbursable ones, insert using individual commands."""
    db = "/data/data/com.arduia.expense/databases/accounting.db"
    markor = "/storage/emulated/0/Documents/Markor/my_expenses.txt"

    def _build_expense_inserts(outs, database=db):
        content = outs[-1]
        expenses = _parse_expenses_from_file_content(content)
        if not expenses:
            return 'adb shell "echo No reimbursable expenses found"'
        stmts = []
        for name, cents, cat_id, note in expenses:
            name_esc = name.replace("'", "''")
            note_esc = note.replace("'", "''")
            stmts.append(
                f"INSERT INTO expense (name, amount, category, note, created_date, modified_date) "
                f"VALUES ('{name_esc}', {cents}, {cat_id}, '{note_esc}', "
                f"strftime('%s','now')*1000, strftime('%s','now')*1000);")
        combined_sql = " ".join(stmts)
        return f'adb shell "sqlite3 {database} \\"{combined_sql}\\""'

    return [
        _cmd("adb shell am force-stop com.arduia.expense", "Stop expense app"),
        _cmd(f"adb shell cat {markor}", "Read expenses file"),
        _cmd_fn(_build_expense_inserts, "Insert reimbursable expenses into DB"),
    ]

_DYNAMIC_GENERATORS["ExpenseAddMultipleFromMarkor"] = _gen_expense_add_from_markor




# --- GUI Tasks solvable via ADB ---

# SimpleDrawPro: CLI can create minimal PNG that passes weak verifier (file exists check only),
# but this is not a legitimate drawing. Classified as gui_only_weak_verifier.


# Clock stopwatch tasks: verifier requires live UI state (ui_elements).
# No terminal-only solution exists. Classified as gui_only.


# ─── Camera tasks ─────────────────────────────────────────────────────────────

# Camera tasks: CLI can create fake files that pass weak verifier (size>0 check only),
# but this is not a legitimate solution. Classified as gui_only_weak_verifier.


# ─── Audio Recorder tasks ────────────────────────────────────────────────────

# Audio Recorder tasks: CLI can create fake .m4a files that pass weak verifier (file exists check only),
# but this is not a legitimate solution. Classified as gui_only_weak_verifier.


# ─── Clock Timer ─────────────────────────────────────────────────────────────

# Clock timer task: verifier requires live UI state (ui_elements).
# No terminal-only solution exists. Classified as gui_only.


# ─── Contacts New Draft ──────────────────────────────────────────────────────

def _gen_contacts_new_draft(goal: str) -> List[Dict]:
    """Open new contact with pre-filled data via intent extras."""
    first = re.search(r"First Name:\s*(\w+)", goal)
    last = re.search(r"Last Name:\s*(\w+)", goal)
    phone = re.search(r"Phone:\s*([\d-]+)", goal)
    label = re.search(r"Phone Label:\s*(\w+)", goal)
    if first and last and phone:
        name = f"{first.group(1)} {last.group(1)}"
        ph = phone.group(1)
        ph_type = label.group(1) if label else "Mobile"
        return [
            _cmd(f"""adb shell "am start -a android.intent.action.INSERT -t vnd.android.cursor.dir/contact --es name '{name}' --es phone '{ph}' --es phone_type {ph_type}" """.strip(),
                 f"Open new contact: {name}"),
        ]
    return None

_DYNAMIC_GENERATORS["ContactsNewContactDraft"] = _gen_contacts_new_draft


# ─── VLC Playlists ───────────────────────────────────────────────────────────

def _vlc_setup_cmd(schema_output: str, db: str) -> str:
    """Build command to remove corrupt VLC DB if needed. Table creation is a separate step."""
    is_corrupt = bool(re.search(r'malformed|error', schema_output, re.IGNORECASE))
    if is_corrupt:
        return f'adb shell "rm -f {db} {db}-wal {db}-shm"'
    return 'adb shell "echo DB schema OK"'


def _vlc_create_tables_cmd(db: str) -> str:
    """Build command to create VLC DB tables (always safe with IF NOT EXISTS)."""
    return (f'adb shell "sqlite3 {db} \\"CREATE TABLE IF NOT EXISTS Playlist (id_playlist INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL); '
            f'CREATE TABLE IF NOT EXISTS Media (id_media INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL); '
            f'CREATE TABLE IF NOT EXISTS PlaylistMediaRelation (playlist_id INTEGER, media_id INTEGER, position INTEGER);\\""')


def _gen_vlc_create_playlist(goal: str) -> List[Dict]:
    """Create VLC playlist using individual ADB commands.
    Inspects DB first, recreates if corrupt."""
    pname_m = re.search(r'titled\s+"([^"]+)"', goal)
    files_m = re.search(r'in order:\s*(.*?)(?:\.\s*$|$)', goal, re.DOTALL)
    if not pname_m or not files_m:
        return None
    pname = pname_m.group(1)
    files = _parse_comma_list(files_m.group(1).strip().rstrip("."))

    db = "/data/data/org.videolan.vlc/app_db/vlc_media.db"
    cmds = [
        _cmd("adb shell am force-stop org.videolan.vlc", "Stop VLC"),
        _cmd(f'adb shell "sqlite3 {db} \\".schema\\" 2>&1 | head -3"', "Inspect VLC DB schema"),
        _cmd_fn(lambda outs, d=db: _vlc_setup_cmd(outs[-1], d),
                "Remove corrupt DB if needed"),
        _cmd(_vlc_create_tables_cmd(db), "Create DB tables"),
        _cmd(f'adb shell "sqlite3 {db} \\"INSERT INTO Playlist (name) VALUES (\'{pname}\');\\""',
             f"Create playlist '{pname}'"),
        _cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(id_playlist) FROM Playlist;\\""',
             "Get playlist ID"),
    ]
    for i, fname in enumerate(files):
        fname_esc = fname.replace("'", "''")
        cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"INSERT INTO Media (filename) VALUES (\'{fname_esc}\');\\""',
                         f"Add media file '{fname}'"))
        cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(id_media) FROM Media;\\""',
                         "Get media ID"))

        def _make_relation(outs, pos=i, database=db):
            pid = _extract_int(outs[5])  # playlist ID at index 5 (shifted by 1 due to new step)
            mid = _extract_int(outs[-1])
            return f'adb shell "sqlite3 {database} \\"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES ({pid}, {mid}, {pos});\\""'
        cmds.append(_cmd_fn(_make_relation, f"Link media to playlist at position {i}"))

    return cmds

_DYNAMIC_GENERATORS["VlcCreatePlaylist"] = _gen_vlc_create_playlist


def _gen_vlc_create_two_playlists(goal: str) -> List[Dict]:
    """Create two VLC playlists using individual ADB commands."""
    # Split goal on "And then" or ". Create" to separate two playlist descriptions
    parts = re.split(r'\.\s*(?:And then,?\s*)?[Cc]reate a playlist', goal)
    playlist_blocks = []
    full_parts = []
    if "Create a playlist" in parts[0]:
        full_parts.append("Create a playlist" + parts[0].split("Create a playlist", 1)[1])
    else:
        full_parts.append(parts[0])
    for p in parts[1:]:
        full_parts.append("Create a playlist" + p)
    for part in full_parts:
        nm = re.search(r'titled\s+"([^"]+)"', part)
        fm = re.search(r'in order:\s*(.*?)\.?\s*$', part, re.DOTALL)
        if nm and fm:
            playlist_blocks.append((nm.group(1), _parse_comma_list(fm.group(1).strip().rstrip("."))))

    db = "/data/data/org.videolan.vlc/app_db/vlc_media.db"
    cmds = [
        _cmd("adb shell am force-stop org.videolan.vlc", "Stop VLC"),
        _cmd(f'adb shell "sqlite3 {db} \\".schema\\" 2>&1 | head -3"', "Inspect VLC DB schema"),
        _cmd_fn(lambda outs, d=db: _vlc_setup_cmd(outs[-1], d),
                "Remove corrupt DB if needed"),
        _cmd(_vlc_create_tables_cmd(db), "Create DB tables"),
    ]

    for pname, files in playlist_blocks:
        cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"INSERT INTO Playlist (name) VALUES (\'{pname}\');\\""',
                         f"Create playlist '{pname}'"))
        cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(id_playlist) FROM Playlist;\\""',
                         f"Get playlist ID for '{pname}'"))
        # Remember the index where this playlist ID is stored
        pid_idx = len(cmds) - 1

        for pos, fname in enumerate(files):
            fname_esc = fname.replace("'", "''")
            cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"INSERT INTO Media (filename) VALUES (\'{fname_esc}\');\\""',
                             f"Add media file '{fname}'"))
            cmds.append(_cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(id_media) FROM Media;\\""',
                             "Get media ID"))

            def _make_relation(outs, p=pos, database=db, pi=pid_idx):
                pid = _extract_int(outs[pi])
                mid = _extract_int(outs[-1])
                return f'adb shell "sqlite3 {database} \\"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES ({pid}, {mid}, {p});\\""'
            cmds.append(_cmd_fn(_make_relation, f"Link media to playlist at position {pos}"))

    return cmds

_DYNAMIC_GENERATORS["VlcCreateTwoPlaylists"] = _gen_vlc_create_two_playlists


# ─── Retro Playlist Duration ────────────────────────────────────────────────

def _select_songs_for_duration(query_output: str, target_min_ms: int = 2700000, target_max_ms: int = 3000000) -> List[str]:
    """Select a subset of songs whose total duration falls in [target_min_ms, target_max_ms].
    Uses greedy approach: add songs sorted by duration until we reach the target."""
    songs = []
    for line in query_output.strip().split("\n"):
        title_m = re.search(r'title=([^,]+)', line)
        dur_m = re.search(r'duration=(\d+)', line)
        if title_m and dur_m:
            songs.append((title_m.group(1).strip(), int(dur_m.group(1))))

    if not songs:
        return []

    # Sort by duration descending for greedy selection
    songs.sort(key=lambda x: x[1], reverse=True)

    # Try greedy: add songs until total is in range
    selected = []
    total = 0
    for title, dur in songs:
        if total + dur <= target_max_ms:
            selected.append(title)
            total += dur

    if total >= target_min_ms:
        return selected

    # If greedy didn't work, try adding smallest songs
    songs.sort(key=lambda x: x[1])
    selected = []
    total = 0
    for title, dur in songs:
        if total + dur <= target_max_ms:
            selected.append(title)
            total += dur

    if total >= target_min_ms:
        return selected

    # Fallback: return all songs
    return [t for t, _ in songs]


def _gen_retro_playlist_duration(goal: str) -> List[Dict]:
    """Create Retro playlist with duration 45-50 min using individual commands.
    Step 1: query all songs with durations
    Step 2: command_fn selects subset and creates playlist + queries per song + inserts."""
    playlist_name, _ = _parse_song_list_from_goal(goal)
    if not playlist_name:
        m = re.search(r'titled\s+"([^"]+)"', goal)
        playlist_name = m.group(1) if m else "playlist"

    db = _RETRO_DB

    def _build_duration_playlist(outs, pn=playlist_name, database=db):
        """After querying all songs, select subset and build a multi-statement sqlite3 command."""
        selected = _select_songs_for_duration(outs[-1])
        if not selected:
            return 'adb shell "echo No valid song subset found"'

        # We need to: create playlist, get PID, then for each song query MediaStore and insert.
        # Since we can only return ONE command from command_fn, we'll create the playlist first
        # and chain all subsequent steps. But we need MediaStore metadata per song.
        # Solution: use a single sqlite3 call to create the playlist, then return that.
        # The actual per-song insertion will need separate steps.
        # For now, just create the playlist.
        return f'adb shell "sqlite3 {database} \\"INSERT INTO PlaylistEntity (playlist_name) VALUES (\'{pn}\');\\""'

    def _get_selected_songs(outs):
        """Re-parse the song list from the query output (at index 1)."""
        return _select_songs_for_duration(outs[1])

    cmds = [
        _cmd("adb shell am force-stop code.name.monkey.retromusic", "Stop Retro Music"),
        _cmd('adb shell "content query --uri content://media/external/audio/media --projection title:duration --sort title"',
             "Query all songs with durations"),
        _cmd_fn(_build_duration_playlist, f"Create playlist '{playlist_name}'"),
        _cmd(f'adb shell "sqlite3 {db} \\"SELECT MAX(playlist_id) FROM PlaylistEntity;\\""',
             "Get playlist ID"),
    ]

    # We need to dynamically add per-song commands. Since we don't know how many songs
    # until runtime, we use a command_fn that queries ALL selected songs' metadata in one call,
    # then a command_fn that does all inserts in one sqlite3 call.
    def _query_selected_songs_metadata(outs, database=db):
        """Query MediaStore for all selected songs in one call per song (concatenated)."""
        selected = _select_songs_for_duration(outs[1])
        if not selected:
            return 'adb shell "echo No songs selected"'
        # Query all songs at once using OR conditions
        conditions = " OR ".join(f"title='{t.replace(chr(39), chr(39)+chr(39))}'" for t in selected)
        return f'adb shell "content query --uri content://media/external/audio/media --projection _id:title:duration:_data:album_id:album:artist_id:artist:date_modified --where \\"{conditions}\\""'

    def _insert_all_selected_songs(outs, database=db):
        """Parse metadata output and insert all songs into playlist."""
        pid = _extract_int(outs[3])  # playlist ID
        metadata_output = outs[-1]
        stmts = []
        for line in metadata_output.strip().split("\n"):
            fields = _parse_media_fields(line)
            title_m = re.search(r'title=([^,]+)', line)
            if not fields.get('_id') or not title_m:
                continue
            t = title_m.group(1).strip().replace("'", "''")
            sid = fields.get('_id', '0')
            dur = fields.get('duration', '0')
            data = fields.get('_data', '').replace("'", "''")
            aid = fields.get('album_id', '0')
            aname = fields.get('album', '').replace("'", "''")
            artid = fields.get('artist_id', '0')
            artname = fields.get('artist', '').replace("'", "''")
            dmod = fields.get('date_modified', '0')
            stmts.append(
                f"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, "
                f"data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) "
                f"VALUES ({pid}, {sid}, '{t}', 0, 0, {dur}, '{data}', {dmod}, {aid}, '{aname}', {artid}, '{artname}', '', '');")
        if not stmts:
            return 'adb shell "echo No songs to insert"'
        combined = " ".join(stmts)
        return f'adb shell "sqlite3 {database} \\"{combined}\\""'

    cmds.append(_cmd_fn(_query_selected_songs_metadata, "Query metadata for selected songs"))
    cmds.append(_cmd_fn(_insert_all_selected_songs, "Insert all selected songs into playlist"))

    return cmds

_DYNAMIC_GENERATORS["RetroPlaylistDuration"] = _gen_retro_playlist_duration


# ─── Task Runner ──────────────────────────────────────────────────────────────

def run_single_task(
    broker_url: str,
    task_id: int,
    max_attempts: int = 3,
) -> TaskResult:
    """Run a single task on a container and return the result."""
    container = None
    try:
        container = broker_acquire(broker_url)
        base_url = f"http://localhost:{container['server_port']}"
        env_id = container["env_id"]

        # Reset and get task info
        reset_resp = container_reset(base_url, task_id)
        info = reset_resp["info"]
        task_name = info["task_name"]
        goal = info["task"]

        print(f"[task {task_id:3d}] env{env_id}: {task_name} — {goal[:60]}")

        # Get ground truth commands
        gt_commands = get_ground_truth_commands(task_name, goal)

        if gt_commands is None:
            print(f"[task {task_id:3d}] No ground truth available (GUI-only: {task_name})")
            return TaskResult(
                task_id=task_id,
                task_name=task_name,
                goal=goal,
                reward=0,
                finish_description=f"No ground truth available for {task_name}",
                error="gui_only",
            )

        start_time = time.time()
        steps = []

        # Execute commands
        outputs = []
        last_output = ""
        for cmd_spec in gt_commands:
            if "command_fn" in cmd_spec:
                cmd = cmd_spec["command_fn"](outputs)
            else:
                cmd = cmd_spec["command"]
            thought = cmd_spec.get("thought", "")
            resp = container_step_adb(base_url, cmd)
            output = resp.get("command_output", "")
            outputs.append(output)
            last_output = output
            steps.append(StepRecord(command=cmd, output=output, thought=thought))

        # Check if the last command has an answer formatter (info retrieval tasks)
        answer_fn = gt_commands[-1].get("answer_from_output") if gt_commands else None
        if answer_fn:
            answer = answer_fn(last_output)
            # Submit answer via /step (sets interaction_cache), then FINISH
            container_answer(base_url, answer)
            steps.append(StepRecord(command=f"answer(content='{answer}')", output="", thought=f"Answer: {answer}"))
            finish_resp = container_finish(base_url, f"Answered: {answer[:50]}")
        else:
            # FINISH to trigger evaluation
            finish_resp = container_finish(base_url, f"Completed {task_name}")

        reward = finish_resp.get("reward", 0)
        elapsed = time.time() - start_time

        result = TaskResult(
            task_id=task_id,
            task_name=task_name,
            goal=goal,
            reward=reward,
            steps=steps,
            elapsed_seconds=elapsed,
            finish_description=f"Completed {task_name}",
        )

        status = "SUCCESS" if reward == 1 else "FAILED"
        print(f"[task {task_id:3d}] {status} (reward={reward}, steps={len(steps)}, {elapsed:.1f}s)")
        return result

    except Exception as e:
        print(f"[task {task_id:3d}] ERROR: {e}")
        return TaskResult(
            task_id=task_id,
            task_name=f"task_{task_id}",
            goal="",
            reward=0,
            error=str(e),
        )
    finally:
        if container:
            try:
                broker_return(broker_url, container["env_id"], healthy=True)
            except Exception:
                pass


# ─── Output Saver ─────────────────────────────────────────────────────────────

def save_results(results: List[TaskResult], output_dir: str):
    """Save all results in AITF format."""
    os.makedirs(output_dir, exist_ok=True)
    traj_dir = os.path.join(output_dir, "atif_trajectories")
    os.makedirs(traj_dir, exist_ok=True)

    # Save trajectories
    for r in results:
        aitf = build_aitf(r.task_id, r.task_name, r.goal, r)
        traj_path = os.path.join(traj_dir, f"task_{r.task_id:03d}.json")
        with open(traj_path, "w") as f:
            json.dump(aitf, f, indent=2)

    # Save results.jsonl
    results_path = os.path.join(output_dir, "results.jsonl")
    with open(results_path, "w") as f:
        for r in sorted(results, key=lambda x: x.task_id):
            f.write(json.dumps(build_result_entry(r)) + "\n")

    # Save summary
    total = len(results)
    success = sum(1 for r in results if r.reward == 1)
    failed = sum(1 for r in results if r.reward == 0 and r.error == "")
    gui_only = sum(1 for r in results if r.error == "gui_only")
    errors = sum(1 for r in results if r.error and r.error != "gui_only")

    summary = {
        "total": total,
        "success": success,
        "success_rate": success / total if total > 0 else 0,
        "failed": failed,
        "gui_only": gui_only,
        "errors": errors,
        "model": AGENT_MODEL,
        "seed": SEED,
        "timestamp": datetime.now().isoformat(),
    }
    summary_path = os.path.join(output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults saved to {output_dir}")
    print(f"  Total: {total}, Success: {success} ({success/total*100:.1f}%), "
          f"Failed: {failed}, GUI-only: {gui_only}, Errors: {errors}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ground Truth Trajectory Generator")
    parser.add_argument("--broker-url", type=str, default="http://localhost:9300")
    parser.add_argument("--pool-size", type=int, default=16)
    parser.add_argument("--task-ids", type=str, default=None,
                        help="Comma-separated task IDs to run (default: all 116)")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    # Determine task IDs
    if args.task_ids:
        task_ids = [int(x) for x in args.task_ids.split(",")]
    else:
        task_ids = list(range(116))

    # Output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        ts = datetime.now().strftime("%y%m%d_%H%M")
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "results",
            f"GroundTruth_oracle_{ts}",
        )

    print(f"Running {len(task_ids)} tasks with {args.pool_size} workers")
    print(f"Broker: {args.broker_url}")
    print(f"Output: {output_dir}\n")

    # Run tasks in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.pool_size) as executor:
        futures = {
            executor.submit(run_single_task, args.broker_url, tid): tid
            for tid in task_ids
        }
        for future in as_completed(futures):
            tid = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"[task {tid}] EXCEPTION: {e}")
                results.append(TaskResult(
                    task_id=tid, task_name=f"task_{tid}",
                    goal="", reward=0, error=str(e),
                ))

    # Save results
    save_results(results, output_dir)


if __name__ == "__main__":
    main()
