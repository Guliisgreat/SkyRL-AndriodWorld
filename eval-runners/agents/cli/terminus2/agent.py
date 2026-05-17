"""Terminus_2 agent adapted for AndroidWorld — no tmux, direct subprocess.

Uses Harbor's:
- Parsers (JSON / XML) for structured LLM response parsing
- LiteLLM backend for multi-model support
- Chat class for conversation management and token tracking

Replaces tmux send_keys / capture_pane with direct subprocess execution
via ``SkyrlServerEnvironment.exec()``.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import time
from pathlib import Path

from harbor.agents.terminus_2.terminus_json_plain_parser import (
    TerminusJSONPlainParser,
    ParseResult,
    ParsedCommand,
)
from harbor.agents.terminus_2.terminus_xml_plain_parser import (
    TerminusXMLPlainParser,
)
from harbor.llms.chat import Chat
from harbor.llms.lite_llm import LiteLLM

from .environment import ExecResult, SkyrlServerEnvironment
from .prompts import build_instruction

logger = logging.getLogger(__name__)

# Limit how much command output is sent back to the LLM.
MAX_OUTPUT_CHARS = 12_000

# Forbidden ADB subcommands (mobile-agent constraint: no host↔device bridging,
# no privilege elevation). Anchored on the android_env.py wrapper so
# echoed/quoted strings that happen to mention these verbs don't trigger.
# The inner adb command may be wrapped in single or double quotes, depending
# on shlex.quote output (single by default; double if the string has `'`).
_FORBIDDEN_ADB_PATTERN = re.compile(
    r'''android_env\.py\s+adb\s+['"]adb\s+(?:-\S+\s+\S+\s+)*(push|pull|root)\b''',
    re.IGNORECASE,
)

_FORBIDDEN_HINTS = {
    "push": (
        "`adb push` is forbidden — the agent operates on-device only, with "
        "no host→device file transfer. Write content on-device instead: "
        "`echo \"<base64>\" | base64 -d | adb shell sh -c 'cat > <path>'`."
    ),
    "pull": (
        "`adb pull` is forbidden — the agent operates on-device only, with "
        "no device→host file transfer. Read the file on-device with "
        "`adb shell base64 <path>` (binary) or `adb shell cat <path>` "
        "(text), and process the output in your next turn."
    ),
    "root": (
        "`adb root` is forbidden — privilege elevation is not allowed in "
        "this environment. Use only what the existing shell user can "
        "access; for app-private state, query through content providers, "
        "`cmd <service>`, or `run-as <pkg>`."
    ),
}


def _check_forbidden_adb(raw_command: str) -> str:
    """Return a hint string if the command uses a forbidden adb verb, else ''."""
    m = _FORBIDDEN_ADB_PATTERN.search(raw_command)
    if not m:
        return ""
    verb = m.group(1).lower()
    return _FORBIDDEN_HINTS.get(verb, f"`adb {verb}` is forbidden.")


# Verbs whose args are already split into separate shell tokens by the model
# (paths, --flags, quoted SQL/content). For these we just prepend the wrapper
# script path; the host shell tokenizes the rest into argv. The bash-only
# prompt advertises only `adb` and `finish`; the bash-plus-tools prompt also
# advertises the typed I/O verbs. Each mode rejects verbs the prompt didn't
# advertise — so a bash-only model emitting `sql ...` gets a "not recognized"
# error rather than silently working through a verb it was never told about.
_PASSTHROUGH_VERBS_BY_MODE: dict[str, tuple[str, ...]] = {
    "bash-only": ("finish",),
    "bash-plus-tools": ("finish", "sql", "write-file", "read-file", "find-files"),
}

# Human-readable verb lists for the rejection hint sent back to the model.
_VERB_HINT_BY_MODE: dict[str, str] = {
    "bash-only": "adb, finish",
    "bash-plus-tools": "adb, sql, write-file, read-file, find-files, finish",
}

# Sentinel for commands whose verb isn't in the allowlist. Format:
# "__REJECT__:<mode>:<cmd>". _normalize_command tags them so they never reach
# the host shell; _execute_commands strips the tag, looks up the verb hint
# for the mode, and emits a blocked-command stderr.
_REJECT_PREFIX = "__REJECT__:"


def _detect_tool_mode(template_override: str | None) -> str:
    """Pick the verb allowlist mode from the template filename.

    `optimized-vN-bash-plus-tools.txt` → bash-plus-tools (typed I/O verbs OK).
    `optimized-vN-bash-only.txt` → bash-only (only `adb`/`finish`).
    Anything else defaults to bash-only — the safer choice, since over-rejecting
    a verb produces a clear error the model can recover from, while under-
    rejecting silently leaks to the host shell.
    """
    if template_override:
        path = str(template_override)
        if "bash-plus-tools" in path:
            return "bash-plus-tools"
        if "bash-only" in path:
            return "bash-only"
    return "bash-only"


def _normalize_command(s: str, script: str, tool_mode: str = "bash-only") -> str:
    """Wrap a model-emitted command as a `python <script>` invocation.

    The android-json prompt asks the model to emit one of:
        adb shell <cmd>                                 (or any other adb verb)
        sql <db_path> "<SQL>"                           (bash-plus-tools only)
        write-file <device_path> "<content>" [--append] (bash-plus-tools only)
        read-file <device_path>                         (bash-plus-tools only)
        find-files <directory> "<glob>"                 (bash-plus-tools only)
        finish --status complete --description "<answer>"
    The wrapper script path stays out of the prompt; we attach it here.

    For `adb`, the entire string IS the inner adb command, passed as one
    argv entry to the wrapper's `adb` subcommand — so we shell-quote the
    whole thing. For the other verbs, the args are already split into
    shell tokens by the model, so we just prepend the script path.

    `python` is NOT a model-facing verb. Letting model-emitted lines that
    start with `python` pass through to the host shell unchanged would
    let a model run arbitrary host code via `python -c "..."` or
    `python /any/script.py`, defeating the device-only sandbox. So a
    model-emitted `python ...` falls through to the reject branch like
    any other unknown verb. Verbs not in the mode's allowlist are tagged
    with `_REJECT_PREFIX` and handled by `_execute_commands` — they never
    reach the host shell.
    """
    s = s.strip()
    if not s:
        return s
    first = s.split(None, 1)[0]
    if first == "adb":
        return f"python {shlex.quote(script)} adb {shlex.quote(s)}"
    allowed = _PASSTHROUGH_VERBS_BY_MODE.get(tool_mode, ())
    if first in allowed:
        return f"python {shlex.quote(script)} {s}"
    return f"{_REJECT_PREFIX}{tool_mode}:{s}"


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_HARBOR_TEMPLATE_DIR = (
    Path(__import__("harbor").__file__).resolve().parent
    / "agents"
    / "terminus_2"
    / "templates"
)


class AndroidJSONParser:
    """Parser for the simplified android-json format.

    Two equivalent shapes are accepted:
      Singular (preferred, matches Mini-SWE's 1-cmd-per-turn invariant):
        {"analysis": "...", "plan": "...", "command": "<single command>"}
      Array (legacy bash-plus-tools template):
        {"analysis": "...", "plan": "...", "commands": ["<cmd>", ...]}

    The agent.run() loop enforces 1-command-per-turn regardless of shape:
    array-form responses with len > 1 are rejected at the run level.

    Each command is a string starting with `adb` or `finish` (bash-only)
    or one of the typed-tool verbs (bash-plus-tools). The wrapper script
    path is attached at parse time via :func:`_normalize_command`, so the
    prompt never has to mention it.

    Termination is grounded in the action: ``is_task_complete`` is True iff
    one of the emitted commands is a ``finish`` invocation. A separate JSON
    `task_complete` field used to be honored, but it let the agent loop
    short-circuit out before routing through ``cmd_finish``, which dropped
    the answer for IR tasks; the field is now intentionally ignored.
    """

    def __init__(
        self,
        android_env_script: str = "",
        tool_mode: str = "bash-only",
    ):
        self._fallback = TerminusJSONPlainParser()
        self.android_env_script = android_env_script
        self.tool_mode = tool_mode

    def parse_response(self, response: str) -> ParseResult:
        # Strip markdown code fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from mixed text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError as e:
                    return ParseResult(
                        commands=[], is_task_complete=False,
                        error=f"Invalid JSON: {e}", warning="",
                    )
            else:
                return ParseResult(
                    commands=[], is_task_complete=False,
                    error="No JSON found in response", warning="",
                )

        # Accept both schemas. The bash-only template (1 cmd/turn parity
        # with Mini-SWE / Claude CLI) emits a singular `command` string;
        # the bash-plus-tools template still uses a `commands` array.
        # If both keys are present, the singular form wins. A non-list
        # value under `commands` (e.g. model typo'd a string under the
        # plural key) is treated as if it were the singular field, so we
        # don't accidentally iterate over its characters.
        command_singular = data.get("command")
        commands_array = data.get("commands")
        commands_raw: list = []
        if isinstance(command_singular, str) and command_singular.strip():
            commands_raw = [command_singular]
        elif isinstance(commands_array, list):
            commands_raw = commands_array
        elif isinstance(commands_array, str) and commands_array.strip():
            commands_raw = [commands_array]

        commands = []
        is_task_complete = False
        for cmd in commands_raw:
            if isinstance(cmd, str):
                raw_text = cmd.strip()
                commands.append(ParsedCommand(
                    keystrokes=_normalize_command(
                        cmd, self.android_env_script, self.tool_mode,
                    ),
                    duration=0,
                ))
            elif isinstance(cmd, dict):
                # Fallback: Harbor-style {keystrokes, duration}
                raw_text = (cmd.get("keystrokes") or "").strip()
                commands.append(ParsedCommand(
                    keystrokes=_normalize_command(
                        cmd.get("keystrokes", ""),
                        self.android_env_script,
                        self.tool_mode,
                    ),
                    duration=cmd.get("duration", 0),
                ))
            else:
                continue
            # Termination is grounded in the action: a `finish` command
            # routes through cmd_finish (answer + status), the parser-level
            # `task_complete` JSON field is intentionally ignored.
            first = raw_text.split(None, 1)[0] if raw_text else ""
            if first == "finish":
                is_task_complete = True

        return ParseResult(
            commands=commands,
            is_task_complete=is_task_complete,
            error="",
            warning="",
            analysis=data.get("analysis", ""),
            plan=data.get("plan", ""),
        )


def _load_template(template_name: str) -> str:
    """Load a prompt template by name.

    Checks local templates/ first, then falls back to Harbor's templates.
    """
    # Local templates (android-json, etc.)
    local_path = _TEMPLATE_DIR / f"{template_name}.txt"
    if local_path.exists():
        return local_path.read_text()

    # Harbor templates (terminus-json-plain, terminus-xml-plain)
    harbor_path = _HARBOR_TEMPLATE_DIR / f"{template_name}.txt"
    if harbor_path.exists():
        return harbor_path.read_text()

    raise FileNotFoundError(
        f"Template '{template_name}' not found in {_TEMPLATE_DIR} or {_HARBOR_TEMPLATE_DIR}"
    )


# Keep old name as alias for backwards compatibility with terminus2_common.py
def _load_harbor_template(parser_name: str) -> str:
    """Load template for the given parser name (legacy API)."""
    mapping = {
        "json": "terminus-json-plain",
        "xml": "terminus-xml-plain",
        "android-json": "android-json",
    }
    return _load_template(mapping.get(parser_name, "terminus-json-plain"))


def _make_parser(
    parser_name: str,
    android_env_script: str = "",
    tool_mode: str = "bash-only",
):
    if parser_name == "xml":
        return TerminusXMLPlainParser()
    if parser_name == "android-json":
        return AndroidJSONParser(
            android_env_script=android_env_script,
            tool_mode=tool_mode,
        )
    return TerminusJSONPlainParser()


def _limit_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return (
        text[:half]
        + f"\n\n... [{len(text) - max_chars} characters truncated] ...\n\n"
        + text[-half:]
    )


class AndroidTerminus2Agent:
    """Terminus_2-style agent for AndroidWorld tasks.

    Core loop:
      1. Query LLM (via Harbor Chat / LiteLLM)
      2. Parse response (JSON or XML) → extract commands + task_complete
      3. Execute each command via ``SkyrlServerEnvironment.exec()``
      4. Collect stdout, feed back to LLM as next user message
      5. Repeat until task_complete or max_turns
    """

    def __init__(
        self,
        model_name: str,
        android_env_script: str,
        max_turns: int = 30,
        parser_name: str = "json",
        temperature: float = 0.7,
        api_base: str | None = None,
        command_timeout: int = 60,
        reasoning_effort: str | None = None,
        template_override: str | None = None,
        max_tokens: int | None = None,
    ):
        self.model_name = model_name
        self.android_env_script = android_env_script
        self.max_turns = max_turns
        self.parser_name = parser_name
        self.temperature = temperature
        self.api_base = api_base
        self.command_timeout = command_timeout
        self.reasoning_effort = reasoning_effort
        self.template_override = template_override
        self.max_tokens = max_tokens
        self.tool_mode = _detect_tool_mode(template_override)

        self.parser = _make_parser(
            parser_name,
            android_env_script=android_env_script,
            tool_mode=self.tool_mode,
        )
        self.environment: SkyrlServerEnvironment | None = None

        # Built lazily so callers can set api_base after construction.
        self._llm: LiteLLM | None = None
        self._chat: Chat | None = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self, environment: SkyrlServerEnvironment) -> None:
        self.environment = environment
        llm_kwargs: dict = dict(
            model_name=self.model_name,
            temperature=self.temperature,
            api_base=self.api_base,
            reasoning_effort=self.reasoning_effort,
        )
        if self.max_tokens is not None:
            llm_kwargs["max_tokens"] = self.max_tokens
        self._llm = LiteLLM(**llm_kwargs)
        self._chat = Chat(model=self._llm)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, task_text: str) -> dict:
        """Run the full agent loop and return a result dict."""
        assert self.environment is not None, "Call setup() first"
        assert self._chat is not None

        if self.template_override:
            template = Path(self.template_override).read_text()
        else:
            template = _load_harbor_template(self.parser_name)

        if self.parser_name == "android-json":
            # android_env.py template: uses %PLACEHOLDER% syntax.
            initial_prompt = (
                template
                .replace("%ANDROID_ENV_SCRIPT%", self.android_env_script)
                .replace("%INSTRUCTION%", task_text)
                .replace("%COMMAND_OUTPUT%", "(no commands executed yet)")
            )
        else:
            # Legacy Harbor template: uses {instruction}, {terminal_state}
            instruction = build_instruction(task_text, self.android_env_script)
            initial_prompt = (
                template
                .replace("{instruction}", instruction)
                .replace("{terminal_state}", "(no commands executed yet)")
            )

        # Send initial system-like prompt to LLM
        start_time = time.time()
        commands_log: list[dict] = []
        task_complete = False
        turn = 0
        last_error = ""

        for turn in range(1, self.max_turns + 1):
            # ----- 1. Query LLM -----
            if turn == 1:
                prompt_text = initial_prompt
            else:
                # Subsequent turns: feed back command outputs
                prompt_text = terminal_output  # noqa: F821 — set below

            try:
                llm_response = await self._chat.chat(prompt_text)
                response_text = llm_response.content
            except Exception as e:
                logger.error("LLM call failed on turn %d: %s", turn, e)
                last_error = str(e)
                # Document the failed turn so the ATIF converter doesn't
                # silently drop it. assistant_message stays empty since
                # the LLM never produced a response.
                commands_log.append({
                    "command": "<llm-error>",
                    "stdout": "",
                    "stderr": f"LLM call failed: {e}",
                    "return_code": -1,
                    "blocked": True,
                    "assistant_message": "",
                })
                break

            # ----- 2. Parse response -----
            try:
                parsed = self.parser.parse_response(response_text)
            except Exception as e:
                logger.warning("Parse failed on turn %d: %s", turn, e)
                # Feed parse error back so LLM can self-correct
                terminal_output = (
                    f"ERROR: Could not parse your response. {e}\n"
                    "Please respond with valid "
                    f"{'JSON' if self.parser_name == 'json' else 'XML'} "
                    "in the required format."
                )
                # Document the silent failure so the ATIF converter can
                # surface the LLM's natural-language reasoning post-hoc
                # even though no command was emitted.
                commands_log.append({
                    "command": "<parse-error>",
                    "stdout": "",
                    "stderr": terminal_output,
                    "return_code": -1,
                    "blocked": True,
                    "assistant_message": response_text,
                })
                continue

            if parsed.error:
                terminal_output = (
                    f"Parse warning: {parsed.error}\n"
                    "Please fix the format and try again."
                )
                commands_log.append({
                    "command": "<parse-warning>",
                    "stdout": "",
                    "stderr": terminal_output,
                    "return_code": -1,
                    "blocked": True,
                    "assistant_message": response_text,
                })
                continue

            non_empty = [
                c for c in parsed.commands
                if c.keystrokes.rstrip("\n").strip()
            ]

            if not non_empty:
                terminal_output = (
                    "No commands provided. "
                )
                commands_log.append({
                    "command": "<no-command>",
                    "stdout": "",
                    "stderr": terminal_output,
                    "return_code": -1,
                    "blocked": True,
                    "assistant_message": response_text,
                })
                continue

            if len(non_empty) > 1:
                # Reject the whole turn; no command runs, no device step
                # is consumed. The model is told to send the next command
                # in its next response.
                terminal_output = (
                    f"ERROR: Each turn must contain exactly ONE command. "
                )
                commands_log.append({
                    "command": "<multi-command turn rejected>",
                    "stdout": "",
                    "stderr": terminal_output,
                    "return_code": -1,
                    "blocked": True,
                    "assistant_message": response_text,
                })
                continue

            # Exactly one command — execute it.
            terminal_output = await self._execute_commands(
                non_empty, commands_log,
                assistant_message=response_text,
            )

            if parsed.is_task_complete:
                task_complete = True
                break

        elapsed = time.time() - start_time

        return {
            "task_complete": task_complete,
            "turns": turn,
            "commands_log": commands_log,
            "elapsed_seconds": elapsed,
            "input_tokens": self._chat.total_input_tokens,
            "output_tokens": self._chat.total_output_tokens,
            "cost_usd": self._chat.total_cost,
            "last_error": last_error,
        }

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    async def _execute_commands(
        self,
        commands: list,
        commands_log: list[dict],
        *,
        assistant_message: str = "",
    ) -> str:
        """Execute at most one command and return its observation.

        The agent.run() loop now rejects multi-command turns up front to
        match Mini-SWE / Claude CLI semantics (1 LLM round = at most 1
        device API call = at most 1 device step), so this method receives
        a list with 0 or 1 non-empty entry. Rejected/forbidden commands
        emit feedback but do NOT consume a device step — there is no
        synthetic step-burn and no `--no-step` injection.

        ``assistant_message`` is the raw LLM response that produced this
        command. It is attached to every appended log entry so downstream
        ATIF export can recover the agent's natural-language rationale
        (which is otherwise discarded after parsing) and the trajectory
        documents what the LLM emitted on every turn — including blocked
        and forbidden ones.
        """
        non_empty = [c for c in commands
                     if c.keystrokes.rstrip("\n").strip()]
        if not non_empty:
            return ""

        cmd = non_empty[0]
        raw = cmd.keystrokes.rstrip("\n").strip()

        if raw.startswith(_REJECT_PREFIX):
            # Format: "__REJECT__:<mode>:<cmd>"
            rest = raw[len(_REJECT_PREFIX):]
            _mode, _, bad = rest.partition(":")
            first = bad.split(None, 1)[0] if bad else ""
            error_msg = (
                f"ERROR: '{first}' is not a recognized verb. "
                f"If you intended to run a command on the device, wrap it "
                f"with `adb shell` and use proper shell escaping."
            )
            commands_log.append({
                "command": bad,
                "stdout": "",
                "stderr": error_msg,
                "return_code": -1,
                "blocked": True,
                "assistant_message": assistant_message,
            })
            return _limit_output(f"$ {bad}\n{error_msg}")

        forbidden_hint = _check_forbidden_adb(raw)
        if forbidden_hint:
            error_msg = f"ERROR: {forbidden_hint}"
            logger.warning("BLOCKED: %s", raw[:200])
            commands_log.append({
                "command": raw,
                "stdout": "",
                "stderr": error_msg,
                "return_code": -1,
                "blocked": True,
                "assistant_message": assistant_message,
            })
            return _limit_output(f"$ {raw}\n{error_msg}")

        logger.info("EXEC: %s", raw[:200])
        result: ExecResult = await self.environment.exec(
            raw, timeout_sec=self.command_timeout,
        )

        stdout = (result.stdout or "").rstrip()
        stderr = (result.stderr or "").rstrip()
        output = stdout or stderr or "(no output)"
        output = _limit_output(output)

        commands_log.append({
            "command": raw,
            "stdout": stdout[:4000],
            "stderr": stderr[:2000],
            "return_code": result.return_code,
            "assistant_message": assistant_message,
        })

        return f"$ {raw}\n{output}"
