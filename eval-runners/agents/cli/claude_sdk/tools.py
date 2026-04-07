"""
MCP tool factory for Claude Agent SDK ↔ AndroidWorld bridge.

Pure-text ADB agent: observations are accessibility trees (uiautomator dump),
not screenshots.  Creates in-process MCP tools bound to a specific
RuntimeClient via closures.  Uses the SDK's ``@tool`` decorator and
``create_sdk_mcp_server()`` so the tools run in-process (no subprocess).

Usage (from trajectory)::

    from skyrl_agent.agents.android.claude_sdk.tools import make_android_tools

    tools, state = make_android_tools(runtime_client)
    server = create_sdk_mcp_server("android", tools=tools)
    # pass server to ClaudeAgentOptions(mcp_servers={"android": server})
"""

from typing import Any, Dict, List, Tuple

from claude_agent_sdk import tool


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

BLOCKED_PATTERNS_RAW = [
    "rmdir", "reboot", "shutdown", "format", "mkfs", "dd", "wipe",
]

MAX_OUTPUT_CHARS = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_command_allowed(command: str) -> bool:
    """Check command against the allowlist and blocklist."""
    cmd = command.strip()
    if not any(cmd.startswith(p) for p in ALLOWED_PREFIXES):
        return False
    cmd_lower = cmd.lower()
    return not any(blocked in cmd_lower for blocked in BLOCKED_PATTERNS_RAW)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_android_tools(
    runtime_client,
) -> Tuple[List, Dict[str, Any]]:
    """
    Create MCP tools bound to a specific RuntimeClient.

    Each tool is a closure over ``runtime_client`` and a shared mutable
    ``state`` dict.  After the SDK ``query()`` completes, the caller reads
    ``state`` to build the trajectory result.

    Args:
        runtime_client: A ``RuntimeClient`` instance connected to one
            Android container.

    Returns:
        (tools_list, state) — list of tool objects (from ``@tool``
        decorator) and the shared state dict.
    """
    state: Dict[str, Any] = {
        "step_count": 0,
        "terminated": False,
        "reward": 0.0,
        "finish_status": "",
        "finish_description": "",
        "step_records": [],       # Per-step records for trajectory saving
    }

    # -- run_adb_command ------------------------------------------------

    @tool(
        "run_adb_command",
        "Execute an ADB shell command on the Android device. "
        "Returns the command output as text. The command must start with "
        "'adb shell'.",
        {"command": str, "thought": str},
    )
    async def run_adb_command(args: Dict[str, Any]) -> Dict[str, Any]:
        command: str = args.get("command", "")
        thought: str = args.get("thought", "")

        if state["terminated"]:
            return {"content": [{"type": "text", "text": "ERROR: Task already finished."}]}

        if not _is_command_allowed(command):
            return {"content": [{
                "type": "text",
                "text": (
                    f"ERROR: Command not allowed: {command}\n"
                    "Commands must start with an allowed ADB prefix "
                    "(adb shell input, adb shell am, adb shell dumpsys, etc.)."
                ),
            }]}

        payload = {"command": command, "thought": thought}
        observation, cmd_output, reward, terminated, truncated, info = (
            await runtime_client.step_adb(payload)
        )

        state["step_count"] += 1
        state["reward"] = reward
        if terminated or truncated:
            state["terminated"] = True

        # Truncate long output
        if len(cmd_output) > MAX_OUTPUT_CHARS:
            cmd_output = cmd_output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

        result_text = f"$ {command}\n{cmd_output}"
        if terminated:
            result_text += "\n[Task environment signaled TERMINATED]"

        # Record step
        state["step_records"].append({
            "step_idx": state["step_count"],
            "thought": thought,
            "action_type": "adb",
            "action_params": {"command": command},
            "command_output": cmd_output,
        })

        return {"content": [{"type": "text", "text": result_text}]}

    # -- get_accessibility_tree -----------------------------------------

    @tool(
        "get_accessibility_tree",
        "Dump the current screen's UI hierarchy (accessibility tree) as XML "
        "text. Use this to observe what is on screen — element types, text, "
        "content descriptions, bounds, and clickable/focusable state. "
        "Call this after UI interactions (tap, swipe, text input) to verify "
        "the result, or any time you need to inspect the screen.",
        {},
    )
    async def get_accessibility_tree(args: Dict[str, Any]) -> Dict[str, Any]:
        if state["terminated"]:
            return {"content": [{"type": "text", "text": "ERROR: Task already finished."}]}

        payload = {
            "command": "adb shell uiautomator dump /dev/tty",
            "thought": "dumping accessibility tree",
        }
        observation, cmd_output, reward, terminated, truncated, info = (
            await runtime_client.step_adb(payload)
        )

        if len(cmd_output) > MAX_OUTPUT_CHARS:
            cmd_output = cmd_output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

        return {"content": [{"type": "text", "text": cmd_output}]}

    # -- finish_task ----------------------------------------------------

    @tool(
        "finish_task",
        "Signal that the task is complete or infeasible. Call this when you "
        "have completed the task or determined it cannot be done.",
        {"status": str, "description": str},
    )
    async def finish_task(args: Dict[str, Any]) -> Dict[str, Any]:
        status_val: str = args.get("status", "complete")
        description: str = args.get("description", "")

        if state["terminated"]:
            return {"content": [{"type": "text", "text": "Task was already finished."}]}

        goal_status = (
            "complete"
            if status_val.lower() in ("complete", "success", "done")
            else "infeasible"
        )
        action_dict = {
            "action_type": "status",
            "goal_status": goal_status,
            "text": description,
        }
        payload = {"action": action_dict, "thought": description}

        observation, reward, terminated, truncated, info = (
            await runtime_client.step(payload)
        )

        state["terminated"] = True
        state["reward"] = reward
        state["finish_status"] = goal_status
        state["finish_description"] = description

        return {"content": [{
            "type": "text",
            "text": f"Task marked as '{goal_status}'. Reward: {reward}.",
        }]}

    return [run_adb_command, get_accessibility_tree, finish_task], state
