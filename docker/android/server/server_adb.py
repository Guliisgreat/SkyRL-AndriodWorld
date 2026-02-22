"""
ADB server - extends the default server with POST /step_adb for raw ADB command execution.

Use this app when running the ADB agent against Docker containers.
Does not modify server.py; imports the existing app and adds one route.

Compatible with the server.py baked into androidworld:v8 (which has no
container_state or extra imports). We import only what the old server exports
(app, get_app_env, prepare_observation_for_transfer) and define everything
else locally.
"""

import os
import re
import subprocess
import logging
from typing import Annotated, Optional

from pydantic import BaseModel
from fastapi import Depends, HTTPException

# Import ONLY symbols that exist in the old (v8) server.py
from .server import (
    app,
    get_app_env,
    prepare_observation_for_transfer,
)
from .env import AndroidWorldEnv

Env = Annotated[AndroidWorldEnv, Depends(get_app_env)]

# Local logger (old server.py exports 'logger' but we don't depend on it)
logger = logging.getLogger("server_adb")

# Lightweight container_state - optional, for tracking success/failure.
# The old server.py in the image does NOT have this; we define our own.
class _ContainerState:
    def __init__(self):
        self.consecutive_failures = 0
    def mark_success(self):
        self.consecutive_failures = 0
    def mark_failure(self):
        self.consecutive_failures += 1

_container_state = _ContainerState()


# --- Task control parsing (mirrors adb_agent.parse_task_control) ---
def _parse_task_control(command: str) -> dict:
    if command.startswith("FINISH"):
        m = re.search(r"content=['\"]?(.*?)['\"]?\)", command)
        return {"action_type": "status", "goal_status": "complete", "text": m.group(1) if m else ""}
    if command.startswith("INFEASIBLE"):
        m = re.search(r"content=['\"]?(.*?)['\"]?\)", command)
        return {"action_type": "status", "goal_status": "infeasible", "text": m.group(1) if m else ""}
    raise ValueError(f"Not a task control command: {command}")


# --- ADB command validation (mirrors adb_agent whitelist/blocklist) ---
ALLOWED_PREFIXES = [
    "adb shell input tap", "adb shell input swipe", "adb shell input text", "adb shell input keyevent",
    "adb shell am start", "adb shell am force-stop", "adb shell am broadcast",
    "adb shell pm list packages", "adb shell pm list features", "adb shell monkey",
    "adb shell dumpsys", "adb shell settings get", "adb shell settings put",
    "adb shell content query", "adb shell content insert", "adb shell content delete",
    "adb shell getprop", "adb shell ls", "adb shell cat", "adb shell uiautomator dump",
    "adb shell wm size", "adb shell wm density", "adb shell date", "adb shell whoami",
]
BLOCKED_PATTERNS = [
    r"\brm\s", r"\brm$", r"\brmdir\b", r"\breboot\b", r"\bshutdown\b",
    r"\bformat\b", r"\bmkfs\b", r"\bdd\b", r"\bwipe\b",
    r";\s*rm", r"&&\s*rm", r"\|\s*rm",
]

def _validate_adb_command(command: str) -> None:
    if not any(command.startswith(p) for p in ALLOWED_PREFIXES):
        raise ValueError(f"Command not in whitelist: {command}")
    for pat in BLOCKED_PATTERNS:
        if re.search(pat, command):
            raise ValueError(f"Blocked dangerous pattern in command: {command}")


class StepAdbInput(BaseModel):
    command: str
    thought: Optional[str] = "Not provided"


@app.post("/step_adb")
async def step_adb(env: Env, data: StepAdbInput):
    """Execute a raw ADB command in the container and return observation + command output."""
    command = data.command.strip()
    thought = data.thought or "Not provided"

    logger.info(f"step_adb: command={command[:80]}..., thought={thought[:50]}.")

    try:
        # Task control: FINISH / INFEASIBLE -> existing env.step()
        if command.startswith("FINISH") or command.startswith("INFEASIBLE"):
            action = _parse_task_control(command)
            observation, reward, terminated, truncated, info = env.step(action=action, thought=thought)
            _container_state.mark_success()
            return {
                "status": "success",
                "observation": prepare_observation_for_transfer(observation),
                "command_output": "",
                "reward": reward,
                "terminated": terminated,
                "truncated": truncated,
                "info": info,
            }

        # Validate and run ADB command
        _validate_adb_command(command)
        args = command.split()
        if args and args[0] == "adb":
            args = args[1:]
        full_cmd = [env.adb_path, "-s", f"emulator-{env.console_port}"] + args
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        command_output = (result.stdout or "") + (result.stderr or "")

        # Update env state and get observation (same as step() after perform_action)
        env.steps += 1
        observation, info = env.get_raw_observation()
        env.current_observation = {"image": observation, "task": info.get("task", "")}
        env.truncated = env.steps > env.max_steps
        reward = env.evaluation()

        _container_state.mark_success()
        return {
            "status": "success",
            "observation": prepare_observation_for_transfer(env.current_observation),
            "command_output": command_output,
            "reward": reward,
            "terminated": env.terminated,
            "truncated": env.truncated,
            "info": info,
        }
    except subprocess.TimeoutExpired:
        _container_state.mark_failure()
        raise HTTPException(status_code=500, detail="ADB command timed out")
    except ValueError as e:
        _container_state.mark_failure()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _container_state.mark_failure()
        logger.error(f"step_adb failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    server_port = os.getenv("SERVER_PORT", 5000)
    uvicorn.run(app, host="0.0.0.0", port=int(server_port))
