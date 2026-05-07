"""AndroidWorldEnvironment — adapts AndroidWorld containers to mini-swe-agent.

Implements the ``minisweagent.Environment`` protocol by running bash commands
on the host via subprocess. Commands invoke ``android_env.py`` which HTTP-calls
the container's skyrl_server.

Action space (mirrors ``terminus2/agent.py`` bash-only mode): the model emits
exactly one of ``adb shell <cmd>`` or ``finish --status complete --description
"<answer>"`` per turn. The ``python <script>`` wrapper is attached at
normalization time inside ``execute()`` and is invisible to the model — so
host-side commands like ``python -c ...`` or raw ``sh -c ...`` cannot be
emitted by the model and are rejected with a verb-not-recognized observation.

Usage::

    env = AndroidWorldEnvironment(
        container_url="http://localhost:5800",
        state_file="/tmp/state.json",
        android_env_script="/path/to/android_env.py",
    )
    output = env.execute({"command": "adb shell date"})
    # → wraps to: python /path/to/android_env.py adb 'adb shell date'
    # output = {"output": "Thu Oct 19 ...", "returncode": 0, "exception_info": None}
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field


MAX_OUTPUT_CHARS = 16_000

_ALLOWED_VERBS_BASH_ONLY: tuple[str, ...] = ("adb", "finish")
_ALLOWED_VERBS_BASH_PLUS_TOOLS: tuple[str, ...] = (
    "adb", "finish", "sql", "write-file", "read-file", "find-files",
)
_PASSTHROUGH_VERBS: frozenset[str] = frozenset(
    {"finish", "sql", "write-file", "read-file", "find-files"}
)

# Mirror of the terminus2 deny list — block `adb push|pull|root` regardless of
# how the model wraps it. Anchored on the android_env.py wrapper invocation so
# that strings containing those words inside echoed payloads (e.g. the literal
# token "adb push" appearing inside a SQL VALUES list) don't trigger.
# The inner adb command may be wrapped in single or double quotes depending on
# how the model quotes the argument to `adb`.
_FORBIDDEN_ADB_PATTERN = re.compile(
    r'''android_env\.py\s+adb\s+['"]adb\s+(?:-\S+\s+\S+\s+)*(push|pull|root)\b''',
    re.IGNORECASE,
)

_FORBIDDEN_HINTS = {
    "push": (
        "`adb push` is forbidden — the agent operates on-device only, with "
        "no host→device file transfer. Write content on-device instead via "
        "`write-file` (or `echo \"<base64>\" | base64 -d | adb shell sh -c "
        "'cat > <path>'` for the bash-only template)."
    ),
    "pull": (
        "`adb pull` is forbidden — the agent operates on-device only, with "
        "no device→host file transfer. Read the file on-device with "
        "`read-file <path>` (or `adb shell base64 <path>` for binary, "
        "`adb shell cat <path>` for text), and process the output in your "
        "next turn."
    ),
    "root": (
        "`adb root` is forbidden — privilege elevation is not allowed in "
        "this environment. Use only what the existing shell user can "
        "access; for app-private state, query through content providers, "
        "`cmd <service>`, or `run-as <pkg>`."
    ),
}


def _check_forbidden_adb(command: str) -> str:
    """Return a hint string if the command uses a forbidden adb verb, else ''."""
    m = _FORBIDDEN_ADB_PATTERN.search(command)
    if not m:
        return ""
    verb = m.group(1).lower()
    return _FORBIDDEN_HINTS.get(verb, f"`adb {verb}` is forbidden.")


def _normalize_command(
    raw: str,
    android_env_script: str,
    allowed_verbs: tuple[str, ...] = _ALLOWED_VERBS_BASH_ONLY,
) -> tuple[str | None, str]:
    """Wrap a model-emitted command as a `python <script>` invocation.

    Direct mirror of terminus2's ``_normalize_command`` for one-command-per-turn.
    Two routing modes, both gated by ``allowed_verbs``:

    * ``adb shell <cmd>`` (or any other adb verb) — the entire string IS the
      inner adb command, passed as one shlex-quoted argv to the wrapper's
      ``adb`` subcommand.
    * ``finish``/``sql``/``write-file``/``read-file``/``find-files`` — args
      are already split into shell tokens by the model, so we just prepend
      the script path and let the host shell tokenize. These verbs only
      reach the wrapper when present in ``allowed_verbs`` (the bash-only
      allowlist excludes the four typed-tool verbs, so they get rejected
      with the same "not a recognized verb" hint as any other unknown verb).
    * Anything else (including raw ``python ...``, raw ``sh ...``, etc.) is
      rejected so the model never has a path to arbitrary host execution.

    Returns ``(normalized_command, "")`` on success, or ``(None, error_hint)``
    when the verb is not in ``allowed_verbs``.

    Embedded newlines are rejected. terminus2's parser receives each command
    as a separate item in a JSON ``commands`` array — it never has multi-line
    content within a single command. The mini-swe action_regex captures the
    entire fence body as one string (DOTALL), so a multi-line bash block
    would otherwise pass our first-token check and let the model run a second
    line on the container shell after the wrapper expands. Rejecting newlines
    here makes the per-command boundary identical to terminus2's.
    """
    s = raw.strip()
    if not s:
        return None, "empty command (nothing inside the bash code block)"

    if "\n" in s:
        return None, (
            "ERROR: each turn must contain exactly ONE command (no embedded newlines)."
        )

    first = s.split(None, 1)[0]
    quoted_script = shlex.quote(android_env_script)

    if first == "adb" and "adb" in allowed_verbs:
        return f"python {quoted_script} adb {shlex.quote(s)}", ""
    if first in _PASSTHROUGH_VERBS and first in allowed_verbs:
        return f"python {quoted_script} {s}", ""

    return None, (
        f"ERROR: '{first}' is not a recognized verb. "
    )


@dataclass
class EnvironmentConfig:
    container_url: str = ""
    state_file: str = ""
    android_env_script: str = ""
    timeout: int = 120
    cwd: str = ""
    allowed_verbs: tuple[str, ...] = _ALLOWED_VERBS_BASH_ONLY


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
        """Execute a bash command and return output + returncode.

        Always include ``exception_info`` (None on success) so mini-swe-agent's
        default observation_template — which gates an `<exception>` block on
        ``output.exception_info`` — can render under Jinja2 StrictUndefined.
        """
        command = action.get("command", "")
        if not command:
            return {"output": "(no command provided)", "returncode": 1, "exception_info": None}

        normalized, normalize_err = _normalize_command(
            command,
            self.config.android_env_script,
            allowed_verbs=self.config.allowed_verbs,
        )
        if normalized is None:
            return {"output": normalize_err, "returncode": 1, "exception_info": None}

        forbidden_hint = _check_forbidden_adb(normalized)
        if forbidden_hint:
            return {
                "output": f"ERROR: {forbidden_hint}",
                "returncode": 1,
                "exception_info": None,
            }

        try:
            result = subprocess.run(
                normalized,
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
                "exception_info": None,
            }
        except subprocess.TimeoutExpired:
            return {
                "output": f"Command timed out after {self.config.timeout}s",
                "returncode": -1,
                "exception_info": f"TimeoutExpired after {self.config.timeout}s",
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
