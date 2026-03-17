# Claude Code CLI as AndroidWorld Agent

**Date:** 2026-03-09
**Branch:** `feat/cc-tune-claude-agent-sdk`
**Status:** Proposed
**Supersedes:** rule-based plan, SDK-based plan

## 1. Core Idea

Use `claude` CLI directly. The orchestrator script:
1. Resets a container for a task
2. Runs `claude -p "<task description>"` with env vars pointing to the container
3. Claude Code uses its built-in Bash tool to call `android_env.py`
4. Claude explores, reasons, executes, self-verifies, finishes — all autonomously
5. Orchestrator reads the state file for reward + recorded commands

No SDK. No MCP server. No Python agent loop. Just `claude` CLI + Bash.

## 2. Architecture

```
orchestrator.py                claude CLI                    container
     │                             │                            │
     │  1. POST /reset             │                            │
     │─────────────────────────────┼───────────────────────────>│
     │                             │                            │
     │  2. claude -p "task..."     │                            │
     │────────────────────────────>│                            │
     │                             │                            │
     │                             │  Bash: python android_env.py adb "..."
     │                             │───────────────────────────>│
     │                             │<───────────── output + a11y tree
     │                             │                            │
     │                             │  Bash: python android_env.py adb "..."
     │                             │───────────────────────────>│
     │                             │<───────────── output + a11y tree
     │                             │                            │
     │                             │  ... (Claude reasons & acts)
     │                             │                            │
     │                             │  Bash: python android_env.py finish ...
     │                             │───────────────────────────>│
     │                             │<───────────── reward
     │                             │                            │
     │<────────────── exit         │                            │
     │                             │                            │
     │  3. Read state.json         │                            │
     │  4. Record result           │                            │
```

## 3. How It Works

### Single task, manual:

```bash
# 1. Reset the container
curl -X POST http://localhost:5200/reset \
  -H 'Content-Type: application/json' \
  -d '{"seed": 7, "options": {"task_id": 3, "go_home_on_reset": true}}'

# 2. Set env vars
export ANDROID_SERVER_URL=http://localhost:5200
export ANDROID_STATE_FILE=/tmp/task3_state.json

# 3. Run Claude Code with the task description
claude -p "You are an Android automation agent. Use python android_env.py to control the device.

Task: Delete the following recipes from Broccoli app: Butternut Squash Soup, BBQ Chicken Quesadillas, Avocado Toast with Egg.

Complete this task, then call finish." \
  --allowedTools "Bash(command:*)"
```

Claude Code takes it from there — it has Bash, it sees the system prompt, it
calls `android_env.py` to explore and act.

### Batch, automated:

```bash
python orchestrator.py \
  --data val_data_seed7_no_gui.jsonl \
  --pool-size 4 \
  --model claude-opus-4-6 \
  --output results.jsonl
```

## 4. Orchestrator Script

`run_claude_cli.py` (~150 lines):

```python
#!/usr/bin/env python3
"""
Run Claude Code CLI on AndroidWorld tasks.

For each task:
  1. Reset container
  2. Run: claude -p "<system_prompt + task>" --allowedTools "Bash"
  3. Read state file → reward + step records
  4. Save to JSONL
"""

import argparse, json, os, subprocess, tempfile, time

ANDROID_ENV_SCRIPT = os.path.join(os.path.dirname(__file__), "android_env.py")

SYSTEM_INSTRUCTIONS = f"""You are an Android automation agent. You control an \
Android device via ADB commands through a CLI wrapper.

## CLI Wrapper

Use Bash to call the wrapper:

```bash
python {ANDROID_ENV_SCRIPT} adb "adb shell <command>"          # run ADB command (returns output + screen state)
python {ANDROID_ENV_SCRIPT} adb --no-tree "adb shell <cmd>"    # run without screen state (for parsing output)
python {ANDROID_ENV_SCRIPT} tree                                # get initial screen state
python {ANDROID_ENV_SCRIPT} finish --status complete --description "Done"
```

## Strategy

PREFER programmatic approaches over GUI interaction:
1. SQLite: adb shell sqlite3 <db_path> "<SQL>"
2. File ops: adb shell cat/rm/mv/cp/mkdir
3. Intents: adb shell am start ...
4. GUI (last resort): tap/swipe via adb shell input

## Discovery

Explore the device to find what you need:
- Find app databases: adb shell find /data/data/<package> -name "*.db"
- Inspect schema: adb shell sqlite3 <db> ".tables" / ".schema <table>"
- List files: adb shell ls <path>
- List packages: adb shell pm list packages | grep <keyword>
- Get date: adb shell date

## Self-Verification

ALWAYS verify your work before finishing:
- After delete: query DB/filesystem to confirm it's gone
- After insert: query to confirm the row/file exists
- After modify: read back to confirm the change
- For questions: double-check your answer

## Key Rules

1. Call `tree` once at start to see the screen.
2. Each `adb` call auto-returns the screen state.
3. Use base64 for SQL with special characters:
   echo <b64_sql> | base64 -d | sqlite3 <db>
4. ALWAYS call `finish` when done.
5. Copy text EXACTLY from the task — do not paraphrase.
"""


def reset_container(base_url, task_id, seed):
    """POST /reset to the container."""
    import urllib.request
    data = json.dumps({
        "seed": seed,
        "options": {"task_id": task_id, "go_home_on_reset": True}
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/reset", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    urllib.request.urlopen(req, timeout=300)


def run_claude_cli(task_text, server_url, state_file, model="claude-opus-4-6", max_turns=30):
    """Run claude CLI with the task prompt."""
    prompt = f"{SYSTEM_INSTRUCTIONS}\n\n## Task\n\n{task_text}\n\nComplete this task on the Android device."

    env = os.environ.copy()
    env["ANDROID_SERVER_URL"] = server_url
    env["ANDROID_STATE_FILE"] = state_file

    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--max-turns", str(max_turns),
        "--allowedTools", "Bash(command:*)",
    ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    return result.stdout, result.stderr, result.returncode


def run_one_task(task_def, container_url, model, max_turns):
    """Reset, run Claude, read state, return result."""
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    # Create state file
    state_fd, state_file = tempfile.mkstemp(suffix=".json", prefix=f"task{task_id}_")
    os.close(state_fd)
    with open(state_file, "w") as f:
        json.dump({"step_count": 0, "terminated": False, "reward": 0.0,
                    "finish_status": "", "finish_description": "",
                    "step_records": [], "_last_a11y_cache": ""}, f)

    # Reset
    reset_container(container_url, task_id, seed)
    time.sleep(10)  # wait for a11y tree stabilization

    # Run Claude
    stdout, stderr, rc = run_claude_cli(task_text, container_url, state_file, model, max_turns)

    # Read state
    state = {}
    try:
        with open(state_file) as f:
            state = json.load(f)
    except: pass
    finally:
        os.unlink(state_file)

    return {
        "task_id": task_id,
        "seed": seed,
        "task": task_text,
        "reward": state.get("reward", 0.0),
        "step_count": state.get("step_count", 0),
        "finished": state.get("terminated", False),
        "commands": state.get("step_records", []),
        "claude_stdout": stdout[-2000:] if stdout else "",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--tasks", type=str, default=None)
    parser.add_argument("--container-url", default="http://localhost:5200")
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--output", default="claude_cli_results.jsonl")
    args = parser.parse_args()

    # Load tasks
    with open(args.data) as f:
        tasks = [json.loads(l) for l in f if l.strip()]
    if args.tasks:
        ids = set(int(x) for x in args.tasks.split(","))
        tasks = [t for t in tasks if t["task_id"] in ids]

    # Run
    with open(args.output, "w") as out:
        for task_def in tasks:
            print(f"Task {task_def['task_id']}: {task_def['task'][:60]}...")
            result = run_one_task(task_def, args.container_url, args.model, args.max_turns)
            print(f"  reward={result['reward']}, steps={result['step_count']}")
            out.write(json.dumps(result) + "\n")
            out.flush()

if __name__ == "__main__":
    main()
```

That's the entire orchestrator. ~150 lines. Everything else is Claude's job.

## 5. What Claude Code Does (examples)

### Example 1: Delete recipes from Broccoli

Claude receives:
> Task: Delete the following recipes from Broccoli app: Butternut Squash Soup,
> BBQ Chicken Quesadillas, Avocado Toast with Egg.

Claude's Bash calls:
```bash
# Explore
python android_env.py adb --no-tree "adb shell sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli 'SELECT title FROM recipes'"

# Act
python android_env.py adb --no-tree "adb shell sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE title='Butternut Squash Soup'\""
python android_env.py adb --no-tree "adb shell sqlite3 ... \"DELETE FROM recipes WHERE title='BBQ Chicken Quesadillas'\""
python android_env.py adb --no-tree "adb shell sqlite3 ... \"DELETE FROM recipes WHERE title='Avocado Toast with Egg'\""

# Verify
python android_env.py adb --no-tree "adb shell sqlite3 ... 'SELECT title FROM recipes'"

# Done
python android_env.py finish --status complete --description "Deleted 3 recipes"
```

### Example 2: IR query — "What is the next calendar event?"

```bash
# Get device time
python android_env.py adb --no-tree "adb shell date +%s"

# Query calendar
python android_env.py adb --no-tree "adb shell sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts > 1698200000 ORDER BY start_ts LIMIT 1\""

# Answer (description IS the answer for IR tasks)
python android_env.py finish --status complete --description "Morning Yoga"
```

### Example 3: Create note + send SMS

```bash
# Create file
python android_env.py adb --no-tree "adb shell mkdir -p /storage/emulated/0/Documents/markor/"
python android_env.py adb --no-tree "adb shell \"echo 'Hello world' > /storage/emulated/0/Documents/markor/note.md\""

# Verify
python android_env.py adb --no-tree "adb shell cat /storage/emulated/0/Documents/markor/note.md"

# Open SMS compose
python android_env.py adb "adb shell am start -a android.intent.action.SENDTO -d sms:+1234567890 com.simplemobiletools.smsmessenger"

# (Claude reads a11y tree, finds input field, types message, taps send)
python android_env.py adb "adb shell input tap 540 811"
python android_env.py adb "adb shell input text 'Hello%sworld'"
python android_env.py adb "adb shell input tap 1006 1454"

python android_env.py finish --status complete --description "Created note and sent SMS"
```

## 6. System Prompt Tuning

The system prompt is the **only** thing we control. Everything else is Claude's
autonomous reasoning. Key tuning areas:

| Area | What to include | Why |
|------|----------------|-----|
| **Strategy** | "Prefer SQLite over GUI" | Cuts steps from 15+ to 3-5 |
| **DB locations** | Known app DB paths | Saves 2-3 exploration steps per task |
| **Discovery** | `find`, `.tables`, `.schema` | Claude can figure out unknowns |
| **Self-verification** | "Verify before finishing" | Catches mistakes before FINISH |
| **Base64 hint** | Shell escaping via base64 | Avoids `L'amour` type crashes |
| **Gotchas** | ??? | TBD based on failure analysis |

### What NOT to include:
- Per-task logic (that's Claude's job)
- Regex patterns for parsing task text
- Hardcoded category mappings (Claude can query `.schema` and figure it out)
- Step-by-step instructions for each task type

### Iterative tuning process:
1. Run 10 tasks with minimal prompt → inspect failures
2. Add targeted hints for common failure patterns
3. Run all 71 → compare with baseline
4. Repeat

## 7. Comparison with Alternatives

| Approach | Lines of code | Brain | Generalization | Cost/task |
|----------|--------------|-------|----------------|-----------|
| Rule-based script | ~1700 | Python if/else | None (71 tasks only) | $0 |
| Claude Agent SDK | ~200 orchestrator + SDK | Claude API | Any task | ~$0.05-0.50 |
| **Claude Code CLI** | **~150 orchestrator** | **Claude Code** | **Any task** | **~$0.05-0.50** |

The CLI approach is the simplest. No SDK dependency, no MCP server, no
subprocess management. Just `claude -p "..."`.

## 8. Implementation Plan

### Step 1: Prep (~30 min)
- Ensure `android_env.py` works standalone (already verified)
- Pick a healthy container for testing

### Step 2: Manual test (~1 hour)
- Run 3-5 tasks manually via `claude -p "..."` in the terminal
- Observe how Claude reasons and what it gets wrong
- Iterate on system prompt

### Step 3: Orchestrator script (~1 hour)
- Write `run_claude_cli.py` (shown above)
- Add container pool support (multiple containers in parallel)
- Add JSONL output

### Step 4: Full run + analysis (~2 hours)
- Run all 71 tasks
- Compare with rule-based baseline (70/71)
- Analyze failures → refine system prompt
- Run again

## 9. Decisions

1. **`--max-turns`: 30.** Covers all task complexities with headroom.
   Simple tasks finish in ~5 turns, complex ones in ~20.

2. **Model: Claude Opus 4.6** (`claude-opus-4-6`). Best reasoning for
   timestamp math, schema discovery, and multi-step tasks. Cost is acceptable
   for evaluation.

3. **Execution: Sequential first.** Run tasks one at a time to verify
   correct implementation and debug issues. Parallel execution later once
   the pipeline is proven.

4. **Cost: Acceptable.** ~71 tasks × ~$0.10-0.50/task = ~$7-35 per full run.
   Worth it for evaluation and prompt tuning.

## 10. Files

| File | Role |
|------|------|
| `run_claude_cli.py` | **New** — orchestrator that runs `claude` CLI per task |
| `android_env.py` | **Existing** — Bash CLI wrapper (adb, tree, finish) |
| `val_data_seed7_no_gui.jsonl` | Task definitions |
| `verify_all_71_tasks.py` | Rule-based baseline for comparison |
