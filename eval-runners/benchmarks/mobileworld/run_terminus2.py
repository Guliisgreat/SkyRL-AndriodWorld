#!/usr/bin/env python3
"""Run the Terminus_2 agent on MobileWorld with a Tier 1a-pure-style prompt.

Usage:
    python run_terminus2.py --data gui_only_tasks.jsonl \\
        --broker-url http://localhost:9400 --pool-size 16 \\
        --model openrouter/minimax/minimax-m2.7 \\
        --max-turns 50

The agent uses `mw_env.py` (the minimal MobileWorld bridge) and is given only
three documented bridge commands — adb, exec, finish — plus the three Tier 1a
discipline rules. Mirrors `mw_terminal_expert_tier1a_pure.py` for Claude CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util as _ilu
import json
import os
import sys
import tempfile
import time
import types as _types
from functools import partial

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from mw_cli_common import (
    MW_ENV_SCRIPT,
    MW_TOOLS_SCRIPT,
    build_common_parser,
    check_health,
    eval_task,
    finalize_results,
    get_task_goal,
    init_task,
    load_tasks,
    parse_containers,
    resolve_output_path,
    run_broker,
    run_parallel,
    run_sequential,
    teardown_task,
    _extract_answer,
    _http_post_quiet,
)


# ---------------------------------------------------------------------------
# Import terminus2 agent + environment via file loader (same trick used by
# androidworld/terminus2_common.py — avoids skyrl_agent.__init__ pulling
# in torch/transformers).
# ---------------------------------------------------------------------------

_EVAL_RUNNERS_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir, os.pardir))
_T2_PKG = os.path.join(_EVAL_RUNNERS_ROOT, "agents", "cli", "terminus2")


def _ensure_stub_package(dotted_name: str, path: str | None = None):
    if dotted_name not in sys.modules:
        mod = _types.ModuleType(dotted_name)
        mod.__path__ = [path] if path else []
        mod.__package__ = dotted_name
        sys.modules[dotted_name] = mod


def _import_t2_module(module_name: str, file_name: str):
    _ensure_stub_package("skyrl_agent", os.path.join(_EVAL_RUNNERS_ROOT, "agents"))
    _ensure_stub_package("skyrl_agent.agents", os.path.join(_EVAL_RUNNERS_ROOT, "agents"))
    _ensure_stub_package("skyrl_agent.agents.android", os.path.join(_EVAL_RUNNERS_ROOT, "agents", "cli"))
    _ensure_stub_package("skyrl_agent.agents.android.terminus2", _T2_PKG)
    fqn = f"skyrl_agent.agents.android.terminus2.{module_name}"
    file_path = os.path.join(_T2_PKG, file_name)
    spec = _ilu.spec_from_file_location(fqn, file_path, submodule_search_locations=[])
    mod = _ilu.module_from_spec(spec)
    mod.__package__ = "skyrl_agent.agents.android.terminus2"
    sys.modules[fqn] = mod
    spec.loader.exec_module(mod)
    return mod


_env_mod = _import_t2_module("environment", "environment.py")
SkyrlServerEnvironment = _env_mod.SkyrlServerEnvironment

_prompts_mod = _import_t2_module("prompts", "prompts.py")
_agent_mod = _import_t2_module("agent", "agent.py")
AndroidTerminus2Agent = _agent_mod.AndroidTerminus2Agent


# ---------------------------------------------------------------------------
# Tier 1a-pure instruction for MobileWorld (mirrors
# `mw_terminal_expert_tier1a_pure.py` for the Claude CLI runner).
# Monkey-patched into terminus2's agent module so the agent uses it
# instead of the default AndroidWorld instruction.
# ---------------------------------------------------------------------------

def build_mw_tier1a_pure_instruction(task_text: str, mw_env_script: str) -> str:
    return f"""\
You are an Android automation agent. You control an Android device by writing \
shell commands that interact with the device through a thin CLI bridge.

## Bridge

```bash
python {mw_env_script} adb "adb shell <command>"            # Run on device
python {mw_env_script} exec "<command>"                      # Run on container host
python {mw_env_script} finish --status complete --description "<answer>"
```

These are your ONLY pre-defined commands. Compose everything else from raw \
shell. Examples (you must figure out the right command for each task):

- SQLite on device: `adb "adb shell sqlite3 <db> '<SQL>'"`
- Read a file on device: `adb "adb shell cat <path>"`
- Find files on device: `adb "adb shell find <dir> -name '<pattern>'"`
- HTTP from container: `exec "curl -sS <url>"`
- Postgres in a Docker container: `exec "docker exec <container> psql -U <user> -d <db> -c '<SQL>'"`
  (you must discover containers via `exec "docker ps"`)
- Android content providers: `adb "adb shell content query --uri <uri>"`
- Android intents: `adb "adb shell am start -a <action> ..."` or `am broadcast`

## Constraint

Do NOT observe or manipulate the screen — no screenshots, no UI hierarchy \
dumps, no tap/swipe/keyevent input, no screen coordinates. All other ADB \
shell capabilities remain available.

## Approach

Before each action, reason about:
- What has been observed on the device so far?
- What is still an assumption that hasn't been verified?
- What is the most likely failure mode of the next command?

Then follow this cycle:

1. **Decompose** — On your first turn, restate every numbered subtask from \
the user request as a checklist. Track which are done as you work.
2. **Discover** — find the relevant app, its data files, database schemas, \
and any backend services. Use raw `adb shell pm list packages | grep ...`, \
`adb shell find /data/data/<pkg> ...`, `exec "docker ps"`.
3. **Inspect** — read existing data before modifying. Understand formats, \
ID mappings, timestamp units, and conventions. Match observed patterns \
exactly when creating new entries.
4. **Act** — write to the persistent store the receiving app actually reads \
from (database table, content provider, or proper send intent / API).
5. **Verify** — see Verification below. Mandatory.
6. **Sync** — force-stop the app so it re-reads from disk on next launch.

## Verification (MANDATORY before finish)

Every send / post / create / delete action MUST be followed by a query against \
the same store the receiving app reads from. Quote the verifying row in your \
reasoning. If the verification returns nothing, the action did NOT happen — \
retry with a different mechanism. Do not call `finish` until every numbered \
subtask in the user request has a passing verification.

For multi-step requests, the second-app action (e.g. send-after-analyze) is \
the most common point of failure — budget extra effort for it.

## Forbidden Shortcuts

The evaluator checks the runtime delivery channel, not your local edits. \
Do NOT write to UI-cache, session-state, or render-cache files (any file the \
app uses to memoize what is currently *displayed* rather than what was *sent / \
received*) as a substitute for the real send mechanism. If the file's contents \
look like "the list of items currently shown on screen," it is a cache, not a \
delivery channel — find the actual persistent store the recipient reads from \
and use that instead.

## Principles

1. **Never assume** — discover paths, package names, schemas, column values, \
and content provider URIs from the device.
2. **Ground in reality** — base decisions on observed device state. Before any \
temporal reasoning, get the current date / time / timezone from the device.
3. **Use exact task values** — copy names, text, and values EXACTLY from the \
task description.

## Shell Escaping

When a command contains quotes, parentheses, or special characters, pipe it \
through stdin to avoid double-escaping issues with ADB:
```bash
echo "SELECT * FROM events;" | python {mw_env_script} adb "adb shell sqlite3 <db_path>"
```

## Android-Specific Patterns

These behaviors are non-obvious:
- **Media scanner**: after writing files to shared storage, broadcast \
`android.intent.action.MEDIA_SCANNER_SCAN_FILE`.
- **Corrupt databases**: if sqlite3 reports corruption, remove the DB and its \
WAL/SHM files and recreate the required tables.
- **Integer ID mappings**: when databases use integer IDs for categories, \
types, or priorities, query existing rows to discover the mapping.

## Rules

1. For information-retrieval tasks, `--description` in `finish` IS your answer. \
Give ONLY what was asked — no extra commentary.
2. You MUST call `finish` to complete a task.
3. Do not call `finish` until every numbered subtask has a passing verification.

## Task

{task_text}
"""


# ---------------------------------------------------------------------------
# Tier 1a instruction (with mw_tools 14 helpers + Android encyclopedia).
# Mirrors `mw_terminal_expert_tier1a.py` for the Claude CLI runner.
# Use with --instruction tier1a (and bridge=mw_tools.py).
# ---------------------------------------------------------------------------

def build_mw_tier1a_instruction(task_text: str, mw_tools_script: str) -> str:
    return f"""\
You are a senior Android developer who automates devices via terminal commands.
You control an Android device and its host container through a CLI tool suite.
You cannot see the screen — no screenshots, no UI hierarchy, no tap/swipe.
All interaction is through shell commands, databases, files, APIs, and intents.

## Tools

```bash
python {mw_tools_script} adb "adb shell <command>"                         # Any ADB command
python {mw_tools_script} exec "<command>"                                   # Shell command in container
python {mw_tools_script} sql <db_path> "<SQL>"                              # SQLite on device (auto root)
python {mw_tools_script} pg <container_grep> <db> "<SQL>" [--user u]        # PostgreSQL via Docker
python {mw_tools_script} read-file <path>                                   # Read file (device or host, PDF-aware)
python {mw_tools_script} write-file <path> '<content>' [--append]           # Write file (base64-safe)
python {mw_tools_script} find-files <dir> "<pattern>" [--maxdepth N]        # Search files by glob
python {mw_tools_script} json-read <path> [jq_expr]                         # Read + parse JSON file
python {mw_tools_script} json-write <path> '<json>' [--merge]               # Write structured JSON
python {mw_tools_script} content query|insert|update|delete <uri> [opts]    # Android content providers
python {mw_tools_script} intent start|broadcast <target> [--extra t:k:v]    # Fire intents
python {mw_tools_script} service-status [pattern|--start dir|--stop dir]    # Docker service management
python {mw_tools_script} http <METHOD> "<url>" [--data '...']               # HTTP requests
python {mw_tools_script} finish --status complete --description "<answer>"
```

Tool notes:
- `sql` pipes SQL via stdin — pass raw SQL directly, special characters are safe.
- `pg` auto-discovers Docker containers by name pattern. Use `pg <pattern> <db> "\\dt"` to list tables.
- `content` binds use type:column:value — e.g., `--bind s:name:John --bind i:age:30`.
- `intent` extras use type:key:value — e.g., `--extra i:android.intent.extra.alarm.HOUR:14`. \
Types: s=string, i=int, z=bool, l=long, f=float.
- `json-read` supports path expressions: `.key`, `.[0]`, `.key[0].subkey`.

## Android Platform Knowledge

### File System Layout
- /sdcard/ — user storage (Download/, Documents/, DCIM/, Android/data/<pkg>/)
- /data/data/<package>/ — app private data (databases/, shared_prefs/, files/)
- /data/user_de/0/<package>/ — device-encrypted app data

### App Discovery
- List packages: `pm list packages | grep <keyword>`
- Find databases: `find-files /data/data/<pkg> "*.db"`
- Find app files: `find-files /sdcard/Android/data/<pkg> "*"`

### Database Patterns
- Most apps use SQLite under /data/data/<pkg>/databases/
- Discover schema first: `sql <db> ".tables"`, then `sql <db> ".schema <table>"`
- After modifying a database, force-stop the app: `am force-stop <package>`
- Timestamp conventions: ~10 digits = Unix seconds, ~13 digits = milliseconds.

### Content Providers
- Standard URIs: content://sms, content://contacts, content://call_log, \
content://media/external, content://calendar
- Content providers handle app notification automatically (no force-stop needed).

### Intents
- Launch: `intent start -a android.intent.action.VIEW --data "http://..."`
- Common actions: SET_ALARM, SEND, VIEW, MEDIA_SCANNER_SCAN_FILE
- Alarm extras: HOUR (24h int), MINUTES (int), SKIP_UI (bool)

### File Operations
- After creating files under /sdcard/, trigger media scan: \
`intent broadcast android.intent.action.MEDIA_SCANNER_SCAN_FILE --data "file://<path>"`
- After creating/deleting files in app directories, force-stop the app.

### Container Environment
- ALWAYS run `service-status` early to discover what services are available.
- If you discover PostgreSQL containers, use `pg` to query them. Discover \
databases: `pg <container> postgres "\\l"`, tables: `pg <container> <db> "\\dt"`.

### Date & Time
- Get device time: `adb "adb shell date"` — ALWAYS do this before temporal reasoning.
- Unix timestamps in DBs may be UTC — compare in same timezone.

## Strategy

1. **Decompose** — On your FIRST turn, restate every numbered subtask from the \
user request as a checklist.
2. **Discover** — Find the relevant app, its data files, schemas, services. \
Use `find-files`, `sql ... ".tables"`, `service-status`.
3. **Inspect** — Read existing data before modifying. Match observed patterns exactly.
4. **Act** — `sql` for device DBs, `pg` for Docker DBs, `content` for providers, \
`intent` for system actions.
5. **Verify** — See "Verification" below. Mandatory.
6. **Sync** — Force-stop apps after DB changes. Trigger media scan after file changes.

## Verification (MANDATORY before finish)

Every send/post/create/delete action MUST be followed by a verification query \
against the same destination the evaluator will check. Quote the verifying row \
in your reasoning. If the verification returns nothing, retry. Do not call \
`finish` until every numbered subtask has a passing verification.

For multi-step requests, the second-app action (send-after-analyze) is the \
most common point of failure — budget extra effort.

## Forbidden Shortcuts

The evaluator checks the runtime delivery channel, not your local edits. Do \
NOT write to UI-cache, session-state, or render-cache files (any file the app \
uses to memoize what is currently displayed) as a substitute for the real send \
mechanism. Find the actual persistent store the recipient app reads from and \
use that mechanism instead.

## Rules

1. For information-retrieval tasks, `--description` in `finish` IS your answer. \
Give ONLY what was asked.
2. You MUST call `finish` to complete a task.
3. Do not call `finish` until every numbered subtask has a passing verification.
4. Copy text and values EXACTLY from the task — do not paraphrase.
5. Read the FULL task description — most tasks require multiple steps.

## Task

{task_text}
"""


# ---------------------------------------------------------------------------
# Tier 1b instruction — 14 helpers documented but NO encyclopedia.
# Mirrors `mw_terminal_expert_tier1b.py` for Claude CLI. Use with
# --instruction tier1b (and bridge=mw_tools.py).
# ---------------------------------------------------------------------------

def build_mw_tier1b_instruction(task_text: str, mw_tools_script: str) -> str:
    return f"""\
You are an Android automation agent. You control an Android device by writing \
shell scripts that interact with ADB and a small CLI tool suite.

## CLI Wrapper

```bash
python {mw_tools_script} adb "adb shell <command>"            # ADB shell
python {mw_tools_script} exec "<command>"                      # Container shell
python {mw_tools_script} sql <db_path> "<SQL>"                 # SQLite on device
python {mw_tools_script} pg <container_grep> <db> "<SQL>"      # PostgreSQL via Docker
python {mw_tools_script} read-file <path>                      # Read file
python {mw_tools_script} write-file <path> '<content>'         # Write file
python {mw_tools_script} find-files <dir> "<pattern>"          # Glob search
python {mw_tools_script} json-read <path> [jq_expr]            # Read JSON
python {mw_tools_script} json-write <path> '<json>'            # Write JSON
python {mw_tools_script} content query|insert|update|delete <uri>  # Content providers
python {mw_tools_script} intent start|broadcast <target>       # Fire intents
python {mw_tools_script} service-status [pattern]              # Docker services
python {mw_tools_script} http <METHOD> "<url>"                 # HTTP requests
python {mw_tools_script} finish --status complete --description "<answer>"
```

Use `<tool> --help` to discover flags. Run `service-status` early to see what \
backend services exist in this container.

## Constraint

Do NOT observe or manipulate the screen — no screenshots, no UI hierarchy \
dumps, no tap/swipe/keyevent input, no screen coordinates.

## Approach

Before each action, reason about:
- What has been observed on the device so far?
- What is still an assumption that hasn't been verified?
- What is the most likely failure mode of the next command?

Then follow this cycle:

1. **Decompose** — On your first turn, restate every numbered subtask from \
the user request as a checklist. Track which are done as you work.
2. **Discover** — find the relevant app, its data files, database schemas, \
content providers, and any backend services.
3. **Inspect** — read existing data before modifying. Match observed patterns \
exactly when creating new entries.
4. **Act** — prefer content providers when available; fall back to direct \
database writes or file operations.
5. **Verify** — see Verification below. Mandatory.
6. **Sync** — force-stop the app so it re-reads from disk on next launch.

## Verification (MANDATORY before finish)

Every send / post / create / delete action MUST be followed by a query against \
the same store the receiving app reads from. Quote the verifying row in your \
reasoning. If the verification returns nothing, retry. Do not call `finish` \
until every numbered subtask has a passing verification.

For multi-step requests, the second-app action (send-after-analyze) is the \
most common point of failure — budget extra effort.

## Forbidden Shortcuts

The evaluator checks the runtime delivery channel, not your local edits. Do \
NOT write to UI-cache, session-state, or render-cache files (any file the app \
uses to memoize what is currently displayed) as a substitute for the real send \
mechanism. Find the actual persistent store the recipient app reads from.

## Principles

1. **Never assume** — discover paths, package names, schemas, column values, \
content provider URIs from the device.
2. **Ground in reality** — base decisions on observed device state. Get the \
device's date / time / timezone before any temporal reasoning.
3. **Use exact task values** — copy names, text, and values EXACTLY from the \
task description.

## Shell Escaping

When a command contains quotes, parentheses, or special characters, pipe via \
stdin to avoid double-escaping:
```bash
echo "SELECT * FROM events;" | python {mw_tools_script} adb "adb shell sqlite3 <db>"
```

## Android-Specific Patterns

These behaviors are non-obvious:
- **Media scanner**: after writing files to shared storage, broadcast \
`android.intent.action.MEDIA_SCANNER_SCAN_FILE`.
- **Corrupt databases**: if sqlite3 reports corruption, remove the DB and its \
WAL/SHM files and recreate the required tables.
- **Integer ID mappings**: when databases use integer IDs for categories or \
priorities, query existing rows to discover the mapping.

## Rules

1. For information-retrieval tasks, `--description` in `finish` IS your answer. \
Give ONLY what was asked.
2. You MUST call `finish` to complete a task.
3. Do not call `finish` until every numbered subtask has a passing verification.

## Task

{task_text}
"""


# Default monkey-patch (overridden by main() based on --instruction flag).
_agent_mod.build_instruction = build_mw_tier1a_pure_instruction


# ---------------------------------------------------------------------------
# Per-task runner — adapted from mw_cli_common.run_one_task but invokes the
# Terminus_2 agent instead of the Claude CLI subprocess.
# ---------------------------------------------------------------------------

async def _run_terminus2_task_async(
    task_def: dict,
    container_url: str,
    *,
    model: str,
    max_turns: int,
    parser_name: str,
    temperature: float,
    api_base: str | None,
    command_timeout: int,
    task_timeout: int,
    reasoning_effort: str | None,
    max_tokens: int | None,
    bridge_script: str = MW_ENV_SCRIPT,
    adb_serial: str = "localhost:5556",
    device_id: str = "emulator-5554",
) -> dict:
    task_name = task_def["task_name"]
    trial = task_def.get("trial", 1)

    print(f"\n{'='*70}")
    print(f"TASK {task_name} (trial={trial})")
    print(f"{'='*70}")
    sys.stdout.flush()

    state_fd, state_file = tempfile.mkstemp(
        suffix=".json", prefix=f"mw_t2_{task_name[:30]}_",
    )
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({
            "step_count": 0, "terminated": False,
            "finish_status": "", "finish_description": "",
            "step_records": [], "_last_a11y_cache": "",
        }, f)

    try:
        teardown_task(container_url, task_name, device_id)
    except Exception:
        pass

    try:
        init_task(container_url, task_name, device_id)
        print("  Task init OK.")
    except Exception as e:
        print(f"  Task init FAILED: {e}")
        os.unlink(state_file)
        return {"task_name": task_name, "trial": trial,
                "task": "", "reward": 0.0, "error": f"init: {e}"}

    await asyncio.sleep(5)  # let emulator settle

    try:
        goal = get_task_goal(container_url, task_name)
        if isinstance(goal, dict):
            goal = str(goal)
        print(f"  Goal: {str(goal)[:100]}")
    except Exception as e:
        print(f"  Failed to get goal: {e}")
        goal = task_def.get("task", task_name)

    env = SkyrlServerEnvironment(
        container_url=container_url,
        state_file=state_file,
        android_env_script=bridge_script,
        env_vars={
            # mw_env.py / mw_tools.py both read these
            "MW_SERVER_URL": container_url,
            "MW_ADB_SERIAL": adb_serial,
            "MW_DEVICE_ID": device_id,
            "MW_STATE_FILE": state_file,
            "MW_DISABLE_TREE": "1",
        },
    )

    agent = AndroidTerminus2Agent(
        model_name=model,
        android_env_script=bridge_script,
        max_turns=max_turns,
        parser_name=parser_name,
        temperature=temperature,
        api_base=api_base,
        command_timeout=command_timeout,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )
    agent.setup(env)

    print(f"  Running Terminus_2 (model={model}, max_turns={max_turns}, "
          f"parser={parser_name})...")
    sys.stdout.flush()

    start_time = time.time()
    try:
        agent_result = await asyncio.wait_for(
            agent.run(str(goal)),
            timeout=task_timeout,
        )
        elapsed = time.time() - start_time
        print(f"  Agent finished in {elapsed:.0f}s "
              f"(turns={agent_result['turns']}, "
              f"complete={agent_result['task_complete']})")
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"  TIMEOUT after {elapsed:.0f}s")
        agent_result = {
            "task_complete": False, "turns": 0,
            "commands_log": [], "elapsed_seconds": elapsed,
            "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "last_error": "timeout",
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ERROR: {e}")
        agent_result = {
            "task_complete": False, "turns": 0,
            "commands_log": [], "elapsed_seconds": elapsed,
            "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "last_error": str(e),
        }

    state = {}
    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception:
        pass
    finally:
        try:
            os.unlink(state_file)
        except OSError:
            pass

    step_count = state.get("step_count", 0)
    finished = state.get("terminated", False)
    finish_description = state.get("finish_description", "")

    # Auto-finish: if agent didn't call finish, try to extract an answer
    # from its last assistant message (mirrors mw_cli_common behavior).
    if not finished:
        last_text = ""
        for entry in reversed(agent_result.get("commands_log", []) or []):
            if isinstance(entry, dict) and entry.get("stdout"):
                last_text = entry["stdout"]
                break
        if last_text:
            answer = _extract_answer(last_text)
            if answer:
                print(f"  Auto-finish: submitting extracted answer ({len(answer)} chars)")
                try:
                    _http_post_quiet(
                        f"{container_url}/step",
                        {"device": device_id,
                         "action": {"action_type": "answer", "text": answer}},
                    )
                    finish_description = answer
                except Exception:
                    pass

    score, eval_reason = 0.0, ""
    try:
        score, eval_reason = eval_task(container_url, task_name, device_id)
        print(f"  Eval score: {score} ({eval_reason})")
    except Exception as e:
        print(f"  Eval FAILED: {e}")

    try:
        teardown_task(container_url, task_name, device_id)
    except Exception:
        pass

    status = "OK" if score > 0 else "FAIL"
    print(f"  >>> REWARD: {score} ({status}), steps={step_count}, "
          f"finished={finished}, agent_turns={agent_result['turns']}")
    print(f"      tokens: in={agent_result['input_tokens']}, "
          f"out={agent_result['output_tokens']}, "
          f"cost=${agent_result['cost_usd']:.4f}")
    sys.stdout.flush()

    return {
        "task_name": task_name,
        "task_id": task_def.get("task_id", 0),
        "trial": trial,
        "task": str(goal),
        "reward": score,
        "eval_reason": eval_reason,
        "step_count": step_count,
        "finished": finished,
        "finish_description": finish_description,
        "commands": state.get("step_records", []),
        "elapsed_seconds": elapsed,
        "input_tokens": agent_result["input_tokens"],
        "output_tokens": agent_result["output_tokens"],
        "cost_usd": agent_result["cost_usd"],
        "num_turns": agent_result["turns"],
        "claude_output": "",  # not applicable
        "agent_commands_log": agent_result.get("commands_log", []),
    }


def run_terminus2_task_sync(task_def: dict, container_url: str, **kwargs) -> dict:
    """Sync wrapper — safe to call from thread-pool workers."""
    return asyncio.run(_run_terminus2_task_async(task_def, container_url, **kwargs))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser():
    parser = build_common_parser(description="Terminus_2 agent on MobileWorld")
    # Override --prompt help (it isn't used here; we always use the inline
    # Tier 1a-pure instruction). Keep the flag for output-name compatibility.
    parser.set_defaults(prompt="terminus2_mw_tier1a_pure")
    parser.add_argument("--instruction", default="tier1a_pure",
                        choices=["tier1a_pure", "tier1a", "tier1b"],
                        help="Instruction style. tier1a_pure = bash only "
                             "(adb/exec/finish), no encyclopedia. "
                             "tier1a = full mw_tools 14 helpers + Android encyclopedia. "
                             "tier1b = full mw_tools 14 helpers but NO encyclopedia.")
    parser.add_argument("--parser", default="json",
                        choices=["json", "xml", "android-json"],
                        help="Response parser format (default: json)")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="LLM temperature (default: 0.7)")
    parser.add_argument("--api-base", default=None,
                        help="LiteLLM api_base override (e.g., for local vLLM)")
    parser.add_argument("--command-timeout", type=int, default=60)
    parser.add_argument("--task-timeout", type=int, default=900)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Pick instruction + bridge based on flag
    if args.instruction == "tier1a_pure":
        bridge_script = MW_ENV_SCRIPT
        _agent_mod.build_instruction = build_mw_tier1a_pure_instruction
        args.prompt = "terminus2_mw_tier1a_pure"
    elif args.instruction == "tier1b":
        bridge_script = MW_TOOLS_SCRIPT
        _agent_mod.build_instruction = build_mw_tier1b_instruction
        args.prompt = "terminus2_mw_tier1b"
    else:  # tier1a
        bridge_script = MW_TOOLS_SCRIPT
        _agent_mod.build_instruction = build_mw_tier1a_instruction
        args.prompt = "terminus2_mw_tier1a"

    if not os.path.exists(bridge_script):
        print(f"ERROR: bridge script not found at {bridge_script}")
        return 1

    tasks = load_tasks(args.data, args.tasks)
    if not tasks:
        print("No tasks to run.")
        return 0

    output_path = resolve_output_path(args)

    task_runner = partial(
        run_terminus2_task_sync,
        model=args.model,
        max_turns=args.max_turns,
        parser_name=args.parser,
        temperature=args.temperature,
        api_base=args.api_base,
        command_timeout=args.command_timeout,
        task_timeout=args.task_timeout,
        reasoning_effort=args.reasoning_effort,
        max_tokens=args.max_tokens,
        bridge_script=bridge_script,
        adb_serial=args.adb_serial,
        device_id=args.device_id,
    )

    if args.broker_url:
        mode = "broker"
        if not check_health(args.broker_url):
            print(f"ERROR: Broker at {args.broker_url} is not healthy")
            return 1
        print(f"Broker {args.broker_url} is healthy. Pool size: {args.pool_size}")
    elif args.containers:
        mode = "parallel"
    else:
        mode = "sequential"

    print(f"Mode: {mode} (Terminus_2)")
    print(f"Tasks: {len(tasks)}, model={args.model}, max_turns={args.max_turns}")
    print(f"Instruction: {args.instruction}")
    print(f"Parser: {args.parser}, temperature: {args.temperature}")
    print(f"Bridge: {os.path.basename(bridge_script)} at {bridge_script}")
    print(f"Output: {output_path}")

    if mode == "broker":
        results = run_broker(tasks, args.broker_url, args.pool_size,
                             output_path, task_runner)
    elif mode == "parallel":
        containers = parse_containers(args.containers)
        results = run_parallel(tasks, containers, output_path, task_runner)
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container at {args.container_url} is not healthy")
            return 1
        print(f"Container {args.container_url} is healthy.")
        results = run_sequential(tasks, args.container_url, output_path, task_runner)

    system_prompt = (
        f"[Terminus_2 + MobileWorld, model={args.model}, parser={args.parser}, "
        f"temp={args.temperature}, prompt=tier1a_pure]"
    )
    finalize_results(results, output_path, args.model, system_prompt, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
