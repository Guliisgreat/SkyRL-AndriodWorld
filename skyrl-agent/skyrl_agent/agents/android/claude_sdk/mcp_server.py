#!/usr/bin/env python3
"""
Standalone stdio MCP server for the Claude Agent SDK ↔ AndroidWorld bridge.

Runs as a subprocess spawned by the Claude CLI.  Communicates over stdin/stdout
using the MCP protocol.  Talks to a single Android container via HTTP.

Usage (by the SDK, not manually)::

    python claude_sdk_mcp_server.py --server-url http://localhost:5001 \
                                     --state-file /tmp/state_xyz.json

The ``--state-file`` is a JSON file that this process writes after every tool
call so the parent trajectory can read accumulated state (step count, reward,
finished status, etc.) after the SDK ``query()`` completes.
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import aiohttp
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


# ---------------------------------------------------------------------------
# ADB command safety (mirrors android_api_screen_adb_agent.py)
# ---------------------------------------------------------------------------

ALLOWED_PREFIXES = [
    "adb shell input tap",
    "adb shell input swipe",
    "adb shell input text",
    "adb shell input keyevent",
    "adb shell am start",
    "adb shell am force-stop",
    "adb shell am broadcast",
    "adb shell pm list packages",
    "adb shell pm list features",
    "adb shell monkey",
    "adb shell dumpsys",
    "adb shell settings get",
    "adb shell settings put",
    "adb shell content query",
    "adb shell content insert",
    "adb shell content delete",
    "adb shell getprop",
    "adb shell ls",
    "adb shell cat",
    "adb shell uiautomator dump",
    "adb shell wm size",
    "adb shell wm density",
    "adb shell date",
    "adb shell whoami",
    "adb shell mkdir",
    "adb shell rm",
    "adb shell mv",
    "adb shell cp",
    "adb shell find",
    "adb shell echo",
    "adb shell printf",
    "adb shell touch",
    "adb shell sleep",
    "adb shell svc",
    "adb shell sh",
    "adb shell cmd",
    "adb shell pm grant",
    "adb shell pm clear",
    "adb shell sed",
]

BLOCKED_PATTERNS = ["rmdir", "reboot", "shutdown", "format", "mkfs", "dd", "wipe"]

MAX_OUTPUT_CHARS = 16000
MAX_A11Y_CHARS = 32000  # Larger limit for accessibility tree

# Accessibility tree auto-appended to every run_adb_command response.
# Cached so standalone get_accessibility_tree calls don't consume a step.
_A11Y_DUMP_SUFFIX = (
    " && adb shell uiautomator dump /sdcard/window_dump.xml"
    " && adb shell cat /sdcard/window_dump.xml"
)
_last_a11y_cache: str = ""


def _is_command_allowed(command: str) -> bool:
    cmd = command.strip()
    if not any(cmd.startswith(p) for p in ALLOWED_PREFIXES):
        return False
    cmd_lower = cmd.lower()
    return not any(b in cmd_lower for b in BLOCKED_PATTERNS)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {
    "step_count": 0,
    "terminated": False,
    "reward": 0.0,
    "finish_status": "",
    "finish_description": "",
    "step_records": [],
}

_state_file: str = ""


def _flush_state() -> None:
    """Write current state to the state file (atomic via tmp + rename)."""
    if not _state_file:
        return
    tmp = _state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_state, f)
    os.replace(tmp, _state_file)


# ---------------------------------------------------------------------------
# HTTP helpers (talk to the container's RuntimeServer)
# ---------------------------------------------------------------------------

_session: aiohttp.ClientSession | None = None
_server_url: str = ""


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120),
        )
    return _session


async def _http_step_adb(command: str, thought: str) -> dict:
    """POST /step_adb and return the JSON response."""
    session = await _get_session()
    payload = {"command": command, "thought": thought}
    async with session.post(f"{_server_url}/step_adb", json=payload) as resp:
        return await resp.json()


async def _http_step(action: dict, thought: str) -> dict:
    """POST /step and return the JSON response."""
    session = await _get_session()
    payload = {"action": action, "thought": thought}
    async with session.post(f"{_server_url}/step", json=payload) as resp:
        return await resp.json()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def build_server() -> Server:
    server = Server("android", version="1.0.0")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="run_adb_command",
                description=(
                    "Execute an ADB shell command on the Android device. "
                    "Returns the command output as text. "
                    "The command must start with 'adb shell'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The ADB command to execute",
                        },
                        "thought": {
                            "type": "string",
                            "description": "Your reasoning for this action",
                        },
                    },
                    "required": ["command", "thought"],
                },
            ),
            Tool(
                name="get_accessibility_tree",
                description=(
                    "Dump the current screen's UI hierarchy (accessibility "
                    "tree) as XML text. Use this for the INITIAL observation "
                    "only. After that, run_adb_command automatically includes "
                    "the accessibility tree in its response."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="finish_task",
                description=(
                    "Signal that the task is complete or infeasible. "
                    "Call this when you have completed the task or "
                    "determined it cannot be done."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "'complete' or 'infeasible'",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the outcome",
                        },
                    },
                    "required": ["status", "description"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "run_adb_command":
            return await _handle_run_adb(arguments)
        elif name == "get_accessibility_tree":
            return await _handle_get_a11y(arguments)
        elif name == "finish_task":
            return await _handle_finish(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _handle_run_adb(args: dict) -> list[TextContent]:
    global _last_a11y_cache
    command: str = args.get("command", "")
    thought: str = args.get("thought", "")

    if _state["terminated"]:
        return [TextContent(type="text", text="ERROR: Task already finished.")]

    if not _is_command_allowed(command):
        return [TextContent(
            type="text",
            text=(
                f"ERROR: Command not allowed: {command}\n"
                "Commands must start with an allowed ADB prefix "
                "(adb shell input, adb shell am, adb shell dumpsys, etc.)."
            ),
        )]

    # Chain accessibility tree dump with the user's command so both execute
    # in a single /step_adb call (1 container step instead of 2).
    # The container's _split_chained_commands() handles && splitting.
    combined = command + _A11Y_DUMP_SUFFIX

    try:
        resp = await _http_step_adb(combined, thought)
    except Exception as e:
        return [TextContent(type="text", text=f"ERROR: HTTP request failed: {e}")]

    raw_output = resp.get("command_output", "")
    reward = resp.get("reward", 0.0)
    terminated = resp.get("terminated", False)
    truncated = resp.get("truncated", False)

    _state["step_count"] += 1
    _state["reward"] = reward
    if terminated or truncated:
        _state["terminated"] = True

    # Parse combined output: separate command result from accessibility tree
    user_output = raw_output
    a11y_xml = ""
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

    # Build response: command output + accessibility tree
    result_text = f"$ {command}\n{user_output}"

    if a11y_xml:
        if len(a11y_xml) > MAX_A11Y_CHARS:
            a11y_xml = a11y_xml[:MAX_A11Y_CHARS] + "\n... (truncated)"
        result_text += f"\n\n--- Current Screen (Accessibility Tree) ---\n{a11y_xml}"
        _last_a11y_cache = a11y_xml

    if terminated:
        result_text += "\n[Task environment signaled TERMINATED]"

    _state["step_records"].append({
        "step_idx": _state["step_count"],
        "thought": thought,
        "action_type": "adb",
        "action_params": {"command": command},
        "command_output": user_output,
    })
    _flush_state()

    return [TextContent(type="text", text=result_text)]


async def _handle_get_a11y(args: dict) -> list[TextContent]:
    global _last_a11y_cache

    if _state["terminated"]:
        return [TextContent(type="text", text="ERROR: Task already finished.")]

    # Return cached tree if available (from the last run_adb_command).
    # This avoids consuming a container step for redundant observations.
    if _last_a11y_cache:
        return [TextContent(type="text", text=_last_a11y_cache)]

    # No cache — make a fresh call (typically the initial observation).
    # This costs 1 container step.
    try:
        resp = await _http_step_adb(
            "adb shell uiautomator dump /sdcard/window_dump.xml && "
            "adb shell cat /sdcard/window_dump.xml",
            "initial accessibility tree observation",
        )
    except Exception as e:
        return [TextContent(type="text", text=f"ERROR: HTTP request failed: {e}")]

    cmd_output = resp.get("command_output", "")
    # Strip the "UI hierchary dumped to: ..." prefix line
    if "<?xml" in cmd_output:
        cmd_output = cmd_output[cmd_output.index("<?xml"):]
    if len(cmd_output) > MAX_A11Y_CHARS:
        cmd_output = cmd_output[:MAX_A11Y_CHARS] + "\n... (truncated)"

    _last_a11y_cache = cmd_output
    _flush_state()
    return [TextContent(type="text", text=cmd_output)]


async def _handle_finish(args: dict) -> list[TextContent]:
    status_val: str = args.get("status", "complete")
    description: str = args.get("description", "")

    if _state["terminated"]:
        return [TextContent(type="text", text="Task was already finished.")]

    goal_status = (
        "complete"
        if status_val.lower() in ("complete", "success", "done")
        else "infeasible"
    )
    try:
        # Set interaction_cache via "answer" action (needed for
        # information-retrieval evaluation; no-op for other task types).
        if goal_status == "complete" and description:
            await _http_step(
                {"action_type": "answer", "text": description}, description
            )

        # Terminate the episode.
        action_dict = {
            "action_type": "status",
            "goal_status": goal_status,
            "text": description,
        }
        resp = await _http_step(action_dict, description)
    except Exception as e:
        return [TextContent(type="text", text=f"ERROR: HTTP request failed: {e}")]

    reward = resp.get("reward", 0.0)

    _state["terminated"] = True
    _state["reward"] = reward
    _state["finish_status"] = goal_status
    _state["finish_description"] = description
    _flush_state()

    return [TextContent(
        type="text",
        text=f"Task marked as '{goal_status}'. Reward: {reward}.",
    )]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    global _server_url, _state_file

    parser = argparse.ArgumentParser(description="Android MCP server for Claude SDK")
    parser.add_argument("--server-url", required=True, help="Container HTTP URL")
    parser.add_argument("--state-file", required=True, help="Path to state JSON file")
    args = parser.parse_args()

    _server_url = args.server_url
    _state_file = args.state_file

    # Write initial state
    _flush_state()

    server = build_server()
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)

    # Cleanup
    if _session and not _session.closed:
        await _session.close()


if __name__ == "__main__":
    asyncio.run(main())
