# Beyond Prompt Optimization: Terminus_2 Agent Improvements

**Status**: Proposed
**Date**: 2026-03-19
**Author**: Claude Code
**Context**: Autoresearch prompt optimization reached 58/87 (67%) oracle SR, 40/87 (46%) agent SR. Prompt-only changes have plateaued. This doc proposes code-level improvements to push toward 90%+.

---

## 1. Current State

### Results (R6 — best prompt)

| Mode | SR | Cost |
|------|-----|------|
| Agent (single attempt) | 40/87 (46%) | $7.80 |
| Oracle att1 | 42/87 (48%) | — |
| Oracle total (4 attempts) | 58/87 (67%) | $17.84 |

### Failure Breakdown (29 remaining oracle failures)

| Category | Count | Root Cause |
|----------|-------|------------|
| App DB ops (Broccoli, Calendar, ProExpense) | 15 | Shell escaping for SQL with text/parens |
| File ops with special chars (Markor) | 4 | Shell escaping for apostrophes/quotes |
| GUI-required (SMS, Contact, Retro Music, Clipboard) | 6 | No terminal API |
| Settings (brightness min) | 2 | Evaluator/display issue |
| Cross-app pipeline | 1 | Multi-step complexity |
| Info retrieval | 1 | Timestamp precision |

**Key insight**: 19 of 29 failures stem from shell escaping. The LLM _knows_ the right SQL/content but can't get it through `adb shell`'s 4 quoting layers (Python subprocess → host bash → adb → device sh). The fix is to eliminate those layers for DB and file operations.

### Why Prompt Optimization Hit a Wall

We tried 9 rounds of prompt changes to teach the agent to use base64 encoding as a workaround. Results:
- The agent uses base64 only ~30% of the time when it should
- When it does use base64, it often generates incorrect encoded strings (LLMs are bad at encoding)
- Even correct base64 piping has subtle syntax issues (`adb shell sqlite3` doesn't accept stdin the same way across devices)

The problem is fundamental: **asking an LLM to do mechanical encoding is the wrong abstraction**. The agent should express _intent_ (run this SQL, write this content) and let tooling handle the _mechanics_ (escaping, encoding, piping).

---

## 2. Design Philosophy: Generic Tools, Not Task-Specific Helpers

### The Terminal Agent Contract

Our claim: the agent operates through **terminal commands only** — no screenshots, no GUI, no accessibility trees. This means:
- Agent issues text commands → receives text output
- All reasoning happens in the agent; tools are dumb executors
- Tools must be **app-agnostic** — they work for any app, any database, any file

### What's Allowed vs. Not Allowed

| Allowed (generic tools) | Not Allowed (leakage/cheating) |
|------------------------|-------------------------------|
| `sql <db_path> "<any SQL>"` | `delete-broccoli-recipe <name>` |
| `write-file <path> "<any content>"` | `create-markor-note <title> <text>` |
| `read-file <path>` | `add-calendar-event <title> <time>` |
| `content-query <uri> [args]` | `solve-task <task_id>` |

The tools are equivalent to having better CLI utilities on PATH — like `psql` vs raw `echo | postgres`, or `jq` vs manual JSON parsing with `grep`/`sed`.

### TerminalBench Analogy

In TerminalBench, agents have access to standard CLI tools (`grep`, `awk`, `curl`, `psql`, `sqlite3`, `python`). Nobody considers `psql "SELECT * FROM users"` to be "not terminal." Our `sql` helper is the same thing — a proper CLI client for sqlite3 that handles quoting correctly, rather than forcing the agent to manually pipe through 4 shell layers.

---

## 3. Tool Specifications

### 3.1 `sql` — Execute SQL on Any Device Database

#### Interface

```
python android_env.py sql <db_path> "<SQL statement>"
python android_env.py sql <db_path> "<SQL statement>" --no-step
```

#### Behavior

1. Receives `db_path` (absolute path on device) and `sql` (raw SQL string) as Python `sys.argv` — **no shell interpretation** of the SQL content
2. Base64-encodes the SQL string in Python
3. Constructs the ADB command: `adb shell "echo '<base64>' | base64 -d | sqlite3 <db_path>"`
4. Sends to container via `/step_adb` endpoint (same as `cmd_adb`)
5. Returns the sqlite3 output as text
6. Counts as one step (unless `--no-step`)

#### Implementation

```python
def cmd_sql(db_path: str, sql: str, count_step: bool = True) -> int:
    """Execute a SQL statement on a device database.

    Handles all shell escaping internally via base64 encoding.
    The agent passes raw SQL — no quoting gymnastics needed.
    """
    import base64

    state = _load_state()
    if state["terminated"]:
        print("ERROR: Task already finished.")
        return 1

    # Base64-encode the SQL to bypass all shell escaping layers
    encoded = base64.b64encode(sql.encode("utf-8")).decode("ascii")

    # Construct the ADB command that decodes and pipes to sqlite3
    adb_cmd = (
        f'adb shell "echo {encoded} | base64 -d | sqlite3 {db_path}"'
    )

    try:
        resp = _http_post("/step_adb", {
            "command": adb_cmd,
            "thought": f"sql: {sql[:200]}",
            "count_step": count_step,
        })
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    raw_output = resp.get("command_output", "")
    reward = resp.get("reward", 0.0)
    terminated = resp.get("terminated", False)
    truncated = resp.get("truncated", False)

    state["step_count"] += 1
    state["reward"] = reward
    if terminated or truncated:
        state["terminated"] = True

    # Truncate large outputs
    if len(raw_output) > MAX_OUTPUT_CHARS:
        raw_output = raw_output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

    # Print output (same format as cmd_adb for consistency)
    print(f"$ sqlite3 {db_path}")
    print(f"  SQL: {sql}")
    if raw_output.strip():
        print(raw_output)
    else:
        print("(no output)")

    # Record step
    state["step_records"].append({
        "step_idx": state["step_count"],
        "thought": f"sql: {sql[:200]}",
        "action_type": "sql",
        "action_params": {"db_path": db_path, "sql": sql},
        "command_output": raw_output[:4000],
    })
    _save_state(state)
    return 0
```

#### CLI Parser Addition

```python
# In main(), add to subparsers:
sql_p = sub.add_parser("sql", help="Execute SQL on a device database")
sql_p.add_argument("db_path", help="Absolute path to database on device")
sql_p.add_argument("sql", help="SQL statement to execute")
sql_p.add_argument("--no-step", action="store_true",
                    help="Don't count as a step")
```

#### Examples (All App-Agnostic)

```bash
# Schema exploration — works for ANY app
python android_env.py sql /data/data/com.example.app/databases/main.db ".tables"
python android_env.py sql /data/data/com.example.app/databases/main.db ".schema items"

# Read data
python android_env.py sql /data/data/com.example.app/databases/main.db "SELECT * FROM items LIMIT 10;"

# Insert with quotes and parentheses — just works
python android_env.py sql /data/data/com.example.app/databases/main.db "INSERT INTO items (name, description, count) VALUES ('Chef''s Special', 'A hearty meal (serves 4)', 42);"

# Delete with WHERE IN
python android_env.py sql /data/data/com.example.app/databases/main.db "DELETE FROM items WHERE name IN ('Item A', 'Item B', 'Item C');"

# Update
python android_env.py sql /data/data/com.example.app/databases/main.db "UPDATE items SET count = 0 WHERE name = 'Old Item';"

# Multi-statement (semicolon-separated)
python android_env.py sql /data/data/com.example.app/databases/main.db "DELETE FROM items WHERE id = 5; UPDATE metadata SET count = count - 1;"
```

#### What the Tool Does NOT Do

- Does NOT know about any specific app, table, or schema
- Does NOT validate SQL syntax — passes it raw to sqlite3
- Does NOT auto-discover database paths — agent must find them via `pm list packages` + `find`
- Does NOT handle content providers — that's still via `adb shell content ...`

---

### 3.2 `write-file` — Write Content to Any Device File

#### Interface

```
python android_env.py write-file <device_path> "<content>"
python android_env.py write-file <device_path> "<content>" --append
python android_env.py write-file <device_path> "<content>" --no-step
```

#### Behavior

1. Receives `device_path` and `content` as Python `sys.argv` — no shell interpretation
2. Base64-encodes the content in Python
3. Constructs: `adb shell "echo '<base64>' | base64 -d > <device_path>"` (or `>>` for append)
4. Sends to container via `/step_adb`
5. Returns confirmation or error
6. Counts as one step (unless `--no-step`)

#### Implementation

```python
def cmd_write_file(device_path: str, content: str,
                   append: bool = False, count_step: bool = True) -> int:
    """Write content to a file on the device.

    Handles all shell escaping internally via base64 encoding.
    Supports any content: apostrophes, quotes, unicode, binary.
    """
    import base64

    state = _load_state()
    if state["terminated"]:
        print("ERROR: Task already finished.")
        return 1

    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    redirect = ">>" if append else ">"

    adb_cmd = (
        f'adb shell "echo {encoded} | base64 -d {redirect} {device_path}"'
    )

    try:
        resp = _http_post("/step_adb", {
            "command": adb_cmd,
            "thought": f"write-file: {device_path}",
            "count_step": count_step,
        })
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    raw_output = resp.get("command_output", "")
    reward = resp.get("reward", 0.0)
    terminated = resp.get("terminated", False)
    truncated = resp.get("truncated", False)

    state["step_count"] += 1
    state["reward"] = reward
    if terminated or truncated:
        state["terminated"] = True

    mode = "appended to" if append else "wrote to"
    print(f"$ {mode} {device_path} ({len(content)} bytes)")
    if raw_output.strip():
        print(raw_output)

    state["step_records"].append({
        "step_idx": state["step_count"],
        "thought": f"write-file: {device_path}",
        "action_type": "write-file",
        "action_params": {
            "device_path": device_path,
            "content_length": len(content),
            "append": append,
        },
        "command_output": raw_output[:4000],
    })
    _save_state(state)
    return 0
```

#### CLI Parser Addition

```python
wf_p = sub.add_parser("write-file", help="Write content to a device file")
wf_p.add_argument("device_path", help="Absolute path on device")
wf_p.add_argument("content", help="Content to write")
wf_p.add_argument("--append", action="store_true",
                   help="Append instead of overwrite")
wf_p.add_argument("--no-step", action="store_true",
                   help="Don't count as a step")
```

#### Examples (All App-Agnostic)

```bash
# Simple text file
python android_env.py write-file /sdcard/Documents/note.md "Hello world"

# Content with apostrophes — just works
python android_env.py write-file /sdcard/Documents/note.md "Lunch at Cafe L'amour, 1 PM"

# Content with quotes and special chars
python android_env.py write-file /sdcard/Documents/note.md "She said \"hello\" & waved (goodbye)"

# Multi-line content
python android_env.py write-file /sdcard/Documents/note.md "Line 1
Line 2
Line 3"

# Append mode (for merging files)
python android_env.py write-file /sdcard/Documents/merged.md "First file content"
python android_env.py write-file /sdcard/Documents/merged.md "Second file content" --append
```

#### What the Tool Does NOT Do

- Does NOT know about Markor, Joplin, or any specific app
- Does NOT create parent directories — agent must `adb shell mkdir -p` first if needed
- Does NOT trigger media scan — agent must do that separately
- Does NOT force-stop apps — agent must do that separately

---

## 4. Other Improvements (No New Tools)

### 4.1 Temperature Tuning

Test `temperature=0.3` and `temperature=0.5`. No code changes — CLI flag only.

```bash
python run_terminus2_oracle.py ... --temperature 0.3
```

### 4.2 Increase max_turns to 40

More recovery room for complex multi-step tasks. CLI flag only.

```bash
python run_terminus2_oracle.py ... --max-turns 40
```

### 4.3 Prompt Update for New Tools

Once `sql` and `write-file` are implemented, update `optimized-v1.txt`:

- Replace the entire "CRITICAL: Shell Escaping" section with simple tool documentation
- Remove base64 encoding instructions (the agent no longer needs to know about encoding)
- Remove "NEVER use" warnings (the broken patterns no longer exist if the agent uses the new tools)
- This should significantly shorten the prompt (~50 lines instead of ~50 lines of escaping guidance)

New prompt section would look like:

```
## Tools

### Run ADB commands:
python %ANDROID_ENV_SCRIPT% adb "adb shell <cmd>"

### Execute SQL on device databases:
python %ANDROID_ENV_SCRIPT% sql <db_path> "<SQL>"

Handles all escaping automatically. Use for ALL database operations:
  python %ANDROID_ENV_SCRIPT% sql /data/data/<pkg>/databases/<db> ".tables"
  python %ANDROID_ENV_SCRIPT% sql /data/data/<pkg>/databases/<db> "SELECT * FROM t LIMIT 5;"
  python %ANDROID_ENV_SCRIPT% sql /data/data/<pkg>/databases/<db> "INSERT INTO t (a,b) VALUES ('text',42);"
  python %ANDROID_ENV_SCRIPT% sql /data/data/<pkg>/databases/<db> "DELETE FROM t WHERE name='Item';"

### Write files on device:
python %ANDROID_ENV_SCRIPT% write-file <device_path> "<content>"
python %ANDROID_ENV_SCRIPT% write-file <device_path> "<content>" --append

Handles apostrophes, quotes, and special characters automatically.

### Signal task completion:
python %ANDROID_ENV_SCRIPT% finish --status complete --description "<answer>"
```

---

## 5. Implementation Plan

### Phase 1: Implement Tools

1. Add `cmd_sql()` to `android_env.py` (~40 lines)
2. Add `cmd_write_file()` to `android_env.py` (~35 lines)
3. Wire up CLI parsers in `main()` (~15 lines)
4. Unit test: verify base64 round-trip on a test container

### Phase 2: Update Prompt

1. Rewrite shell escaping section → tool documentation
2. Simplify DB write and file operations sections
3. Remove base64 instructions and NEVER warnings

### Phase 3: Evaluate

1. Run diagnostic 16-task subset with new tools
2. If improved, run full 87-task eval
3. Test at temperature 0.3 and 0.5
4. Test at max_turns 40

### Phase 4: Compare

1. Compare against R6 baseline (58/87 oracle, 40/87 agent)
2. Report per-task changes (which tasks were fixed by tools vs temperature)

---

## 6. Expected Impact

| Change | Est. Tasks Fixed | New Total SR (oracle) |
|--------|-----------------|----------------------|
| Current best (R6) | — | 58/87 (67%) |
| + sql helper | +10-15 | 68-73/87 (78-84%) |
| + write-file helper | +3-5 | 71-78/87 (82-90%) |
| + temperature tuning | +2-4 | 73-82/87 (84-94%) |
| + max_turns 40 | +1-2 | 74-84/87 (85-97%) |
| **Theoretical ceiling** | | **84/87 (96.6%)** |

Ceiling: 3 tasks (9, 67, 68) require GUI interaction and are unreachable in terminal mode.

## 7. Decision Log

| Question | Decision | Rationale |
|----------|----------|-----------|
| Tools in android_env.py or separate files? | android_env.py | Single entry point, consistent step counting and state tracking |
| App-agnostic enforcement? | Tools take raw paths + raw SQL/content only | No app names, schemas, or task-specific logic in the tool code |
| Should sql handle multi-statement SQL? | Yes — sqlite3 handles `;`-separated statements natively | Enables atomic multi-step DB operations |
| Should write-file support binary? | Not initially — text/UTF-8 only | Binary files (images, APKs) can still use `adb push` |
| Step counting for new tools? | Yes by default, `--no-step` opt-out | Consistent with existing `adb` subcommand behavior |
| Should tools auto-force-stop apps? | No | Tool is generic; only the agent knows which app to restart |
| Should tools auto-trigger media scan? | No | Same reason — tool doesn't know the app context |
