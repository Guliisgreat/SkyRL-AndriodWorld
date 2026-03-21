"""AndroidWorldEnvironment — adapts AndroidWorld containers to mini-swe-agent.

Implements the ``minisweagent.Environment`` protocol by running bash commands
on the host via subprocess. Commands invoke ``android_env.py`` which HTTP-calls
the container's skyrl_server.

Usage::

    env = AndroidWorldEnvironment(
        container_url="http://localhost:5800",
        state_file="/tmp/state.json",
        android_env_script="/path/to/android_env.py",
    )
    output = env.execute({"command": "python android_env.py adb 'adb shell date'"})
    # output = {"output": "Thu Oct 19 ...", "returncode": 0}
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field


MAX_OUTPUT_CHARS = 16_000


@dataclass
class EnvironmentConfig:
    container_url: str = ""
    state_file: str = ""
    android_env_script: str = ""
    timeout: int = 120
    cwd: str = ""


class AndroidWorldEnvironment:
    """Bridges AndroidWorld containers to mini-swe-agent's Environment protocol.

    Each instance is bound to a single container URL and state file.
    ``execute()`` runs bash commands on the host; those commands invoke
    ``android_env.py`` which HTTP-calls the container.
    """

    def __init__(self, **kwargs):
        self.config = EnvironmentConfig(**kwargs)
        self._env: dict[str, str] = {
            **os.environ,
            "ANDROID_SERVER_URL": self.config.container_url,
            "ANDROID_STATE_FILE": self.config.state_file,
            "ANDROID_DISABLE_TREE": "1",  # terminal-only mode
        }

    def execute(self, action: dict, cwd: str = "") -> dict:
        """Execute a bash command and return output + returncode."""
        command = action.get("command", "")
        if not command:
            return {"output": "(no command provided)", "returncode": 1}

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                env=self._env,
                timeout=self.config.timeout,
                cwd=cwd or self.config.cwd or None,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            output = stdout + stderr
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
            return {
                "output": output,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "output": f"Command timed out after {self.config.timeout}s",
                "returncode": -1,
            }

    def get_template_vars(self) -> dict:
        """Provide template variables for Jinja2 rendering."""
        return {
            "android_env_script": self.config.android_env_script,
            "container_url": self.config.container_url,
        }

    def serialize(self) -> dict:
        """Serialize environment info for trajectory saving."""
        return {
            "info": {
                "environment": "androidworld",
                "container_url": self.config.container_url,
            }
        }
