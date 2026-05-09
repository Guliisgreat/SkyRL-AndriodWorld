"""Shared building blocks for ATIF-v1.6 trajectory export.

Single source of truth for:
  * the schema constants and Bash tool definition every harness uses;
  * step-builder helpers that always emit the four required agent-step
    fields (``message``, ``model_name``, ``tool_calls``, ``observation``);
  * the trajectory envelope wrapper;
  * a generic ``save_atif_trajectories`` driver parameterized by an
    agent-specific ``result_to_atif_fn`` callable.

Per-harness converters live next to their runner glue and call into
these helpers — see:

  * ``claude_cli_common.result_to_atif``  — ClaudeCodeCLI
  * ``mini_swe_common.result_to_atif``    — MiniSweAgent
  * ``terminus2_common.result_to_atif``   — Terminus_2

The converters' job is to translate harness-specific result shapes into
a uniform ATIF trajectory: same step-id sequence, same agent-step
shape, same tool-call shape, same observation shape. The CONTENT of the
fields will still differ across harnesses (because each harness emits
LLM responses in a different format and uses a different system
template) — but the SHAPE is identical. That makes downstream tooling
(viewers, validators, RL pipelines, parity checks) format-agnostic.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import uuid
from typing import Any, Callable, Dict, List, Optional


ATIF_SCHEMA_VERSION = "ATIF-v1.6"
BENCHMARK_NAME = "AndroidWorld"

# A single Bash tool definition shared by all three harnesses, since they
# all surface their device action as a single ``Bash`` call carrying a
# command string. This keeps ``agent.tool_definitions`` byte-identical
# across harnesses.
BASH_TOOL_DEFINITION: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "Bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute",
                },
            },
            "required": ["command"],
        },
    },
}

# Cap observation text per agent step. Same value across all three
# harnesses so identical device output produces identical step content.
OBS_MAX_CHARS = 8000


def make_session_id(task_id: int) -> str:
    return f"androidworld-task{task_id}-{uuid.uuid4().hex[:8]}"


def truncate_observation(text: str | None) -> str:
    """Apply the shared observation cap with a uniform truncation marker."""
    if not text:
        return ""
    if len(text) <= OBS_MAX_CHARS:
        return text
    return text[:OBS_MAX_CHARS] + "\n... (truncated)"


# ---------------------------------------------------------------------------
# Command-shape normalization
# ---------------------------------------------------------------------------
#
# Each harness wraps the model-emitted verb differently before running it
# on the host. terminus2 and claude_cli store the wrapped form in their
# logs (e.g. ``python /abs/android_env.py adb 'adb shell date'``); mini-swe
# stores the bare form. ATIF should record the bare verb the model
# actually emitted, so the tool_calls.arguments.command field is uniform
# across harnesses.

_WRAPPER_RE = re.compile(
    r"""^\s*python\s+
        (?:'[^']*'|"[^"]*"|\S+)\s+   # the wrapper script path (quoted or bare)
        (?P<verb>adb|finish|sql|write-file|read-file|find-files|tree)
        (?P<rest>(?:\s.*)?)$
    """,
    re.VERBOSE | re.DOTALL,
)


def unwrap_command(raw: str) -> str:
    """Return the bare verb form of a possibly wrapper-wrapped command.

    Examples::

        unwrap_command("python /abs/android_env.py adb 'adb shell date'")
            -> 'adb shell date'
        unwrap_command('python android_env.py adb "adb shell pm list"')
            -> 'adb shell pm list'
        unwrap_command('python android_env.py finish --status complete --description "ok"')
            -> 'finish --status complete --description "ok"'
        unwrap_command('adb shell date')   # already bare
            -> 'adb shell date'

    Falls back to returning ``raw`` unchanged when the input doesn't
    match the wrapper pattern (so harnesses that already store the bare
    form pass through cleanly).
    """
    if not raw:
        return raw
    m = _WRAPPER_RE.match(raw)
    if not m:
        return raw.strip()

    verb = m.group("verb")
    rest = (m.group("rest") or "").strip()

    if verb == "adb":
        # adb's argument is one shell-quoted argv entry — peel the quotes.
        try:
            inner = shlex.split(rest)
        except ValueError:
            return f"{verb} {rest}".strip()
        if len(inner) == 1:
            return inner[0].strip()
        # Multiple tokens after `adb` is unusual but preserve them.
        return f"{verb} {rest}".strip()

    # finish / sql / write-file / read-file / find-files / tree:
    # arguments are already shell tokens — just glue verb + rest.
    return f"{verb} {rest}".strip() if rest else verb


# ---------------------------------------------------------------------------
# Step builders — every agent step emits the four required fields.
# ---------------------------------------------------------------------------

def make_system_step(step_id: int, message: str) -> Dict[str, Any]:
    return {"step_id": step_id, "source": "system", "message": message}


def make_user_step(step_id: int, message: str) -> Dict[str, Any]:
    return {"step_id": step_id, "source": "user", "message": message}


def make_agent_step(
    step_id: int,
    *,
    message: str,
    command: str,
    observation: str,
    model_name: str,
    function_name: str = "Bash",
    tool_call_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an ATIF agent step with the four required fields.

    Always emits, in order:
      * ``message`` — what the agent emitted (LLM natural-language response,
        verbatim when available, falling back to a placeholder when not).
      * ``model_name`` — provenance (the LLM that produced this turn).
      * ``tool_calls`` — single Bash call with ``arguments.command`` set
        to the BARE verb form (un-wrapped, see ``unwrap_command``).
      * ``observation`` — single result whose ``source_call_id`` matches
        the tool call's id, ``content`` is the device's reply (or the
        framework's rejection note when no device call landed).

    For agent turns where the framework rejected the response (parse
    error, no command, multi-command, blocked verb, etc.) callers should
    pass ``command=""`` and put the rejection text in ``observation`` —
    the four fields stay populated so the trajectory is structurally
    uniform regardless of whether a device call actually occurred.
    """
    call_id = tool_call_id or f"call_{step_id}"
    step: Dict[str, Any] = {
        "step_id": step_id,
        "source": "agent",
        "message": message or "",
        "model_name": model_name or "",
        "tool_calls": [{
            "tool_call_id": call_id,
            "function_name": function_name,
            "arguments": {"command": command or ""},
        }],
        "observation": {
            "results": [{
                "source_call_id": call_id,
                "content": truncate_observation(observation),
            }],
        },
    }
    if extra:
        step["extra"] = extra
    return step


def make_system_note_step(
    step_id: int, message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A standalone ``source=system`` step for env errors / annotations."""
    step = {"step_id": step_id, "source": "system", "message": message}
    if extra:
        step["extra"] = extra
    return step


# ---------------------------------------------------------------------------
# Trajectory envelope
# ---------------------------------------------------------------------------

def wrap_trajectory(
    *,
    agent_name: str,
    model: str,
    result: Dict[str, Any],
    steps: List[Dict[str, Any]],
    extra_final_metrics: Optional[Dict[str, Any]] = None,
    extra_root: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the final ATIF trajectory dict from already-built steps.

    The two leading steps (system header + user task) must be supplied
    by the caller as the first two entries of ``steps``.
    """
    task_id = result.get("task_id", 0)

    final_metrics_extra: Dict[str, Any] = {
        "task_id": task_id,
        "seed": result.get("seed", 0),
        "reward": result.get("reward", 0.0),
        "finished": result.get("finished", False),
        "elapsed_seconds": result.get("elapsed_seconds", 0),
        "finish_description": result.get("finish_description", ""),
        "num_turns": result.get("num_turns", 0),
    }
    if extra_final_metrics:
        final_metrics_extra.update(extra_final_metrics)

    root_extra: Dict[str, Any] = {
        "benchmark": BENCHMARK_NAME,
        "task_text": result.get("task", ""),
    }
    if extra_root:
        root_extra.update(extra_root)

    return {
        "schema_version": ATIF_SCHEMA_VERSION,
        "session_id": make_session_id(task_id),
        "agent": {
            "name": agent_name,
            "version": "1.0",
            "model_name": model,
            "tool_definitions": [BASH_TOOL_DEFINITION],
        },
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": result.get("input_tokens", 0),
            "total_completion_tokens": result.get("output_tokens", 0),
            "total_cost_usd": result.get("cost_usd", 0.0),
            "total_steps": result.get("step_count", 0),
            "extra": final_metrics_extra,
        },
        "extra": root_extra,
    }


# ---------------------------------------------------------------------------
# Save driver
# ---------------------------------------------------------------------------

def save_atif_trajectories(
    results: List[Dict[str, Any]],
    output_dir: str,
    model: str,
    system_prompt: str,
    *,
    result_to_atif_fn: Callable[..., Dict[str, Any]],
) -> None:
    """Write one ATIF JSON per task into ``output_dir/atif_trajectories/``.

    ``result_to_atif_fn`` must accept ``(result, model, system_prompt)``
    and may also accept ``output_dir`` as a kwarg (used by MiniSweAgent's
    converter to locate the native ``trajectories/task_NNN.json`` it
    needs to read).
    """
    atif_dir = os.path.join(output_dir, "atif_trajectories")
    os.makedirs(atif_dir, exist_ok=True)

    for result in results:
        task_id = result.get("task_id", 0)
        traj = result_to_atif_fn(
            result, model, system_prompt, output_dir=output_dir,
        )
        path = os.path.join(atif_dir, f"task_{task_id:03d}.json")
        with open(path, "w") as f:
            json.dump(traj, f, indent=2, default=str)

    print(f"ATIF trajectories saved to {atif_dir}/ ({len(results)} files)")
