"""SkyrlServerEnvironment — runs commands on the host via subprocess.

Commands are android_env.py invocations that HTTP-call the container's
skyrl_server.  No tmux, no interactive terminal — just run-and-return.
"""

import asyncio
import os
import subprocess
from dataclasses import dataclass


@dataclass
class ExecResult:
    """Minimal replica of harbor.environments.base.ExecResult."""
    stdout: str | None = None
    stderr: str | None = None
    return_code: int = 0


class SkyrlServerEnvironment:
    """Host-side execution environment backed by a skyrl_server container.

    Each instance is bound to a single container URL and state file.
    ``exec()`` runs shell commands on the host; those commands invoke
    ``android_env.py`` which HTTP-calls the container.
    """

    def __init__(
        self,
        container_url: str,
        state_file: str,
        android_env_script: str,
        env_vars: dict[str, str] | None = None,
    ):
        self.container_url = container_url
        self.state_file = state_file
        self.android_env_script = android_env_script
        self._env: dict[str, str] = {
            **os.environ,
            "ANDROID_SERVER_URL": container_url,
            "ANDROID_STATE_FILE": state_file,
            **(env_vars or {}),
        }

    async def exec(
        self,
        command: str,
        timeout_sec: int = 120,
    ) -> ExecResult:
        """Run *command* on the host and return captured output."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                text=True,
                env=self._env,
                timeout=timeout_sec,
            )
            return ExecResult(
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                stdout="",
                stderr=f"Command timed out after {timeout_sec}s",
                return_code=-1,
            )
