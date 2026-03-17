#!/usr/bin/env python3
"""
CLI wrapper for AndroidWorld containers — "Bash is all you need".

A standalone script that the Claude Agent SDK's built-in Bash tool invokes.
Routes ADB commands through the container's HTTP API, auto-appends the
accessibility tree, and persists state to a JSON file.

Usage::

    # Set env vars (done by trajectory.py before query())
    export ANDROID_SERVER_URL=http://localhost:5001
    export ANDROID_STATE_FILE=/tmp/state.json

    # Execute ADB command (auto-includes accessibility tree)
    python android_env.py adb "adb shell input tap 540 960"

    # Execute ADB command WITHOUT accessibility tree
    python android_env.py adb --no-tree "adb shell input tap 540 960"

    # Get accessibility tree (cached from last adb call, or fresh)
    python android_env.py tree

    # Signal task completion
    python android_env.py finish --status complete --description "Done"
    python android_env.py finish --status infeasible --description "Cannot do X"
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------

SERVER_URL = os.environ.get("ANDROID_SERVER_URL", "")
STATE_FILE = os.environ.get("ANDROID_STATE_FILE", "")
DISABLE_TREE = os.environ.get("ANDROID_DISABLE_TREE", "") == "1"

# Accessibility tree auto-chaining (same as mcp_server.py)
_A11Y_DUMP_SUFFIX = (
    " && adb shell uiautomator dump /sdcard/window_dump.xml"
    " && adb shell cat /sdcard/window_dump.xml"
)

MAX_OUTPUT_CHARS = 16000
MAX_A11Y_CHARS = 32000

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "step_count": 0,
        "terminated": False,
        "reward": 0.0,
        "finish_status": "",
        "finish_description": "",
        "step_records": [],
        "_last_a11y_cache": "",
    }


def _save_state(state: dict) -> None:
    if not STATE_FILE:
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_post(endpoint: str, payload: dict) -> dict:
    """POST JSON to the container and return the parsed response."""
    url = f"{SERVER_URL}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_adb(command: str, no_tree: bool = False, count_step: bool = True) -> int:
    """Execute an ADB command via the container's /step_adb endpoint."""
    state = _load_state()

    if state["terminated"]:
        print("ERROR: Task already finished.")
        return 1

    # ANDROID_DISABLE_TREE=1 forces no-tree mode globally
    if DISABLE_TREE:
        no_tree = True

    combined = command if no_tree else command + _A11Y_DUMP_SUFFIX

    try:
        resp = _http_post("/step_adb", {
            "command": combined,
            "thought": "",
            "count_step": count_step,
        })
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    raw_output = resp.get("command_output", "")
    reward = resp.get("reward", 0.0)
    terminated = resp.get("terminated", False)
    truncated = resp.get("truncated", False)

    state["step_count"] += 1
    state["reward"] = reward
    if terminated or truncated:
        state["terminated"] = True

    # Parse combined output: separate command result from a11y tree
    user_output = raw_output
    a11y_xml = ""

    if not no_tree:
        dump_marker = "UI hierarch"
        xml_marker = "<?xml"

        if dump_marker in raw_output:
            split_idx = raw_output.index(dump_marker)
            user_output = raw_output[:split_idx].rstrip()
            remainder = raw_output[split_idx:]
            if xml_marker in remainder:
                a11y_xml = remainder[remainder.index(xml_marker):]
        elif xml_marker in raw_output:
            split_idx = raw_output.index(xml_marker)
            user_output = raw_output[:split_idx].rstrip()
            a11y_xml = raw_output[split_idx:]

    if len(user_output) > MAX_OUTPUT_CHARS:
        user_output = user_output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

    # Print command output
    print(f"$ {command}")
    if user_output:
        print(user_output)

    # Print a11y tree
    if a11y_xml:
        if len(a11y_xml) > MAX_A11Y_CHARS:
            a11y_xml = a11y_xml[:MAX_A11Y_CHARS] + "\n... (truncated)"
        print(f"\n--- Current Screen (Accessibility Tree) ---")
        print(a11y_xml)
        state["_last_a11y_cache"] = a11y_xml

    if terminated:
        print("\n[Task environment signaled TERMINATED]")

    # Record step
    state["step_records"].append({
        "step_idx": state["step_count"],
        "thought": "",
        "action_type": "adb",
        "action_params": {"command": command},
        "command_output": user_output[:4000],
    })
    _save_state(state)
    return 0


def cmd_tree() -> int:
    """Get the accessibility tree (cached or fresh)."""
    if DISABLE_TREE:
        print("Tree observation is disabled in this mode. Use adb commands directly.")
        return 0

    state = _load_state()

    if state["terminated"]:
        print("ERROR: Task already finished.")
        return 1

    # Return cached tree if available
    cached = state.get("_last_a11y_cache", "")
    if cached:
        print(cached)
        return 0

    # No cache — make a fresh call (initial observation)
    try:
        resp = _http_post("/step_adb", {
            "command": (
                "adb shell uiautomator dump /sdcard/window_dump.xml"
                " && adb shell cat /sdcard/window_dump.xml"
            ),
            "thought": "initial accessibility tree observation",
        })
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    cmd_output = resp.get("command_output", "")
    if "<?xml" in cmd_output:
        cmd_output = cmd_output[cmd_output.index("<?xml"):]
    if len(cmd_output) > MAX_A11Y_CHARS:
        cmd_output = cmd_output[:MAX_A11Y_CHARS] + "\n... (truncated)"

    state["_last_a11y_cache"] = cmd_output
    _save_state(state)

    print(cmd_output)
    return 0


def cmd_finish(status: str, description: str) -> int:
    """Signal task completion via the container's /step endpoint.

    For information-retrieval tasks the evaluator reads ``interaction_cache``
    which is ONLY populated when the environment receives an action with
    ``action_type == "answer"``.  We therefore always send an ``answer``
    action first (with the description as the answer text), then a ``status``
    action to terminate the episode.  This is harmless for non-IR tasks
    (interaction_cache is simply ignored).
    """
    state = _load_state()

    if state["terminated"]:
        print("Task was already finished.")
        return 1

    goal_status = (
        "complete"
        if status.lower() in ("complete", "success", "done")
        else "infeasible"
    )

    try:
        # Step 1: Set interaction_cache via "answer" action (needed for
        # information-retrieval evaluation; no-op for other task types).
        if goal_status == "complete" and description:
            _http_post("/step", {
                "action": {"action_type": "answer", "text": description},
                "thought": description,
            })

        # Step 2: Terminate the episode.
        action_dict = {
            "action_type": "status",
            "goal_status": goal_status,
            "text": description,
        }
        resp = _http_post("/step", {"action": action_dict, "thought": description})
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    reward = resp.get("reward", 0.0)

    state["terminated"] = True
    state["reward"] = reward
    state["finish_status"] = goal_status
    state["finish_description"] = description
    _save_state(state)

    print(f"Task marked as '{goal_status}'. Reward: {reward}.")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AndroidWorld CLI wrapper — Bash is all you need",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # adb subcommand
    adb_p = sub.add_parser("adb", help="Execute ADB command")
    adb_p.add_argument("command", help="ADB command (e.g. 'adb shell input tap 540 960')")
    adb_p.add_argument("--no-tree", action="store_true",
                        help="Skip auto-appending accessibility tree")
    adb_p.add_argument("--no-step", action="store_true",
                        help="Don't count this command as a step")

    # tree subcommand
    sub.add_parser("tree", help="Get accessibility tree (cached or fresh)")

    # finish subcommand
    fin_p = sub.add_parser("finish", help="Signal task completion")
    fin_p.add_argument("--status", required=True, help="'complete' or 'infeasible'")
    fin_p.add_argument("--description", default="", help="Outcome description")

    args = parser.parse_args()

    if not SERVER_URL:
        print("ERROR: ANDROID_SERVER_URL environment variable not set")
        return 1
    if not STATE_FILE:
        print("ERROR: ANDROID_STATE_FILE environment variable not set")
        return 1

    if args.subcommand == "adb":
        return cmd_adb(args.command, no_tree=args.no_tree,
                        count_step=not args.no_step)
    elif args.subcommand == "tree":
        return cmd_tree()
    elif args.subcommand == "finish":
        return cmd_finish(args.status, args.description)
    return 1


if __name__ == "__main__":
    sys.exit(main())
