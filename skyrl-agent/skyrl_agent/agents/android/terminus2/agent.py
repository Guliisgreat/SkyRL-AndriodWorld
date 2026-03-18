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

    Commands are plain strings (not {keystrokes, duration} objects).
    Falls back to Harbor's TerminusJSONPlainParser if commands contain objects.
    """

    def __init__(self):
        self._fallback = TerminusJSONPlainParser()

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
                commands.append(ParsedCommand(keystrokes=cmd, duration=0))
            elif isinstance(cmd, dict):
                # Fallback: Harbor-style {keystrokes, duration}
                commands.append(ParsedCommand(
                    keystrokes=cmd.get("keystrokes", ""),
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


def _make_parser(parser_name: str):
    if parser_name == "xml":
        return TerminusXMLPlainParser()
    if parser_name == "android-json":
        return AndroidJSONParser()
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

        self.parser = _make_parser(parser_name)
        self.environment: SkyrlServerEnvironment | None = None

        # Built lazily so callers can set api_base after construction.
        self._llm: LiteLLM | None = None
        self._chat: Chat | None = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self, environment: SkyrlServerEnvironment) -> None:
        self.environment = environment
        self._llm = LiteLLM(
            model_name=self.model_name,
            temperature=self.temperature,
            api_base=self.api_base,
            reasoning_effort=self.reasoning_effort,
        )
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
        a single step from the budget.
        """
        outputs: list[str] = []

        non_empty = [(i, cmd) for i, cmd in enumerate(commands)
                     if cmd.keystrokes.rstrip("\n").strip()]

        for seq, (_, cmd) in enumerate(non_empty):
            raw = cmd.keystrokes.rstrip("\n").strip()
            is_last = (seq == len(non_empty) - 1)

            # Inject --no-step for all but the last ADB command so the
            # entire turn counts as a single step in the budget.
            exec_cmd = raw
            if not is_last and " adb " in raw and "finish" not in raw:
                exec_cmd = raw.replace(" adb ", " adb --no-step ", 1)

            logger.info("EXEC: %s", exec_cmd[:200])
            result: ExecResult = await self.environment.exec(
                exec_cmd, timeout_sec=self.command_timeout,
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
            })

            outputs.append(f"$ {raw}\n{output}")

        combined = "\n\n".join(outputs)
        return _limit_output(combined)
