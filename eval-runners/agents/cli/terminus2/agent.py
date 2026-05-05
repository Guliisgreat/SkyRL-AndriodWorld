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

# Wrapper verbs that consume a step from the budget and accept --no-step.
# `finish` is excluded: it ends the run and the wrapper rejects --no-step on it.
_STEP_CONSUMING_VERBS = ("adb", "sql", "write-file", "read-file", "find-files")

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

    Expects:
      {"analysis": "...", "plan": "...", "commands": ["cmd1", "cmd2"], "task_complete": bool}

    Each command is a string starting with `adb` or `finish`. The wrapper
    script path is attached at parse time via :func:`_normalize_command`,
    so the prompt never has to mention it.
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

        commands_raw = data.get("commands", [])
        commands = []
        for cmd in commands_raw:
            if isinstance(cmd, str):
                commands.append(ParsedCommand(
                    keystrokes=_normalize_command(
                        cmd, self.android_env_script, self.tool_mode,
                    ),
                    duration=0,
                ))
            elif isinstance(cmd, dict):
                # Fallback: Harbor-style {keystrokes, duration}
                commands.append(ParsedCommand(
                    keystrokes=_normalize_command(
                        cmd.get("keystrokes", ""),
                        self.android_env_script,
                        self.tool_mode,
                    ),
                    duration=cmd.get("duration", 0),
                ))

        return ParseResult(
            commands=commands,
            is_task_complete=data.get("task_complete", False),
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
                continue

            if parsed.error:
                terminal_output = (
                    f"Parse warning: {parsed.error}\n"
                    "Please fix the format and try again."
                )
                continue

            if parsed.is_task_complete:
                task_complete = True
                # Execute any remaining commands before breaking
                if parsed.commands:
                    await self._execute_commands(parsed.commands, commands_log)
                break

            if not parsed.commands:
                terminal_output = (
                    "No commands provided. Send at least one command or set "
                    "task_complete to true."
                )
                continue

            # ----- 3. Execute commands -----
            terminal_output = await self._execute_commands(
                parsed.commands, commands_log,
            )

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
    ) -> str:
        """Execute parsed commands sequentially, return combined output.

        Only the last ADB command per turn counts as a step (via --no-step
        flag on earlier commands) so multiple commands in one turn consume
        a single step from the budget. If every command in the turn was
        rejected/forbidden (no real wrapper call happened), we burn one
        step at end-of-turn so the broker's budget still advances by 1 —
        an LLM output round always costs a step, regardless of whether
        the commands were valid.
        """
        outputs: list[str] = []
        real_step_consumed = False

        non_empty = [(i, cmd) for i, cmd in enumerate(commands)
                     if cmd.keystrokes.rstrip("\n").strip()]

        for seq, (_, cmd) in enumerate(non_empty):
            raw = cmd.keystrokes.rstrip("\n").strip()
            is_last = (seq == len(non_empty) - 1)

            if raw.startswith(_REJECT_PREFIX):
                # Format: "__REJECT__:<mode>:<cmd>"
                rest = raw[len(_REJECT_PREFIX):]
                mode, _, bad = rest.partition(":")
                hint = _VERB_HINT_BY_MODE.get(
                    mode, _VERB_HINT_BY_MODE["bash-only"],
                )
                first = bad.split(None, 1)[0] if bad else ""
                error_msg = (
                    f"ERROR: '{first}' is not a recognized verb. "
                )
                commands_log.append({
                    "command": bad,
                    "stdout": "",
                    "stderr": error_msg,
                    "return_code": -1,
                    "blocked": True,
                })
                outputs.append(f"$ {bad}\n{error_msg}")
                continue

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
                })
                outputs.append(f"$ {raw}\n{error_msg}")
                continue

            # Inject --no-step for all but the last step-consuming command
            # so the entire turn counts as a single step in the budget.
            # Normalized form is `python <script> <verb> <args...>`; the
            # wrapper accepts --no-step on adb/sql/write-file/read-file/
            # find-files, but not on finish.
            exec_cmd = raw
            if not is_last:
                parts = raw.split(None, 3)
                if (
                    len(parts) >= 3
                    and parts[0] == "python"
                    and parts[2] in _STEP_CONSUMING_VERBS
                ):
                    rest = parts[3:] if len(parts) > 3 else []
                    exec_cmd = " ".join(parts[:3] + ["--no-step"] + rest)

            logger.info("EXEC: %s", exec_cmd[:200])
            result: ExecResult = await self.environment.exec(
                exec_cmd, timeout_sec=self.command_timeout,
            )
            real_step_consumed = True

            stdout = (result.stdout or "").rstrip()
            stderr = (result.stderr or "").rstrip()
            output = stdout or stderr or "(no output)"
            output = _limit_output(output)

            commands_log.append({
                "command": raw,
                "stdout": stdout[:4000],
                "stderr": stderr[:2000],
                "return_code": result.return_code,
            })

            outputs.append(f"$ {raw}\n{output}")

        # If every command in the turn was rejected/forbidden, no wrapper
        # call happened — the broker's step budget would stall. Burn one
        # step via a no-op `adb shell true` so 1 LLM round = 1 broker step.
        if non_empty and not real_step_consumed:
            burn_cmd = (
                f"python {shlex.quote(self.android_env_script)} "
                f"adb {shlex.quote('adb shell true')}"
            )
            logger.info("STEP BURN (all-blocked turn): %s", burn_cmd[:200])
            try:
                burn_result: ExecResult = await self.environment.exec(
                    burn_cmd, timeout_sec=self.command_timeout,
                )
                burn_rc = burn_result.return_code
                burn_stderr = (burn_result.stderr or "").rstrip()[:400]
            except Exception as e:
                logger.warning("Step-burn call failed: %s", e)
                burn_rc = -1
                burn_stderr = str(e)[:400]
            commands_log.append({
                "command": "<step burn after all-blocked turn>",
                "stdout": "",
                "stderr": burn_stderr,
                "return_code": burn_rc,
                "step_burn": True,
            })

        combined = "\n\n".join(outputs)
        return _limit_output(combined)
