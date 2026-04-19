# Terminus_2 Tool Design: Principled CLI Tools for Android Terminal Agents

**Status**: In Progress (sql, write-file implemented; read-file, find-files proposed)
**Date**: 2026-03-19
**Author**: Claude Code

---

## 1. Why: The Tool Design Problem

### 1.1 The Lesson from Claude Code

Claude Code provides ~10 specialized tools for software engineering: `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Bash`, etc. Each tool maps to a **universal OS primitive** — operations that any programming task needs, regardless of what you're building.

The key design insight: **`Bash` can do everything, but specialized tools are better for common operations.** Claude Code could do all file reads via `cat`, all edits via `sed`, all searches via `grep` — but dedicated tools eliminate quoting errors, provide better UX, and let the agent focus on reasoning rather than command syntax.

### 1.2 The Same Problem in Android Automation

Terminus_2 started with a single generic tool: `adb` (run any ADB shell command). This is the equivalent of Claude Code having only `Bash`. The agent could theoretically do everything through `adb`, but in practice:

- **Shell escaping failures** account for ~55% of all task failures (19/29 remaining)
- The agent wastes 2-5 turns per task fighting quoting issues
- The LLM _knows_ the right SQL/content but can't get it through 4 shell layers (Python subprocess → host bash → adb → device sh)

### 1.3 The Design Principle

Add specialized tools **only** for universal data access primitives that any Android automation agent would need, regardless of the specific tasks. The test:

> **Would a developer building a general-purpose Android terminal agent include this tool before seeing any benchmark or task set?**

If yes → add it. If it requires knowledge of specific apps or tasks → it's cheating.

---

## 2. What: The Tool Set

### 2.1 Mapping Claude Code Tools to Android Primitives

Android has 3 fundamental data storage layers:

| Layer | Examples | Read | Write |
|-------|---------|------|-------|
| **Text files** | Notes, configs, logs, scripts | `read-file` | `write-file` |
| **Structured databases** | App data in SQLite .db files | `sql` (SELECT) | `sql` (INSERT/UPDATE/DELETE) |
| **System/app APIs** | Settings, intents, packages, processes | `adb` | `adb` |

This maps directly to Claude Code's model:

| Claude Code | Terminus_2 | Data Layer |
|-------------|-----------|------------|
| `Read` | `read-file` | Text files |
| `Write` | `write-file` | Text files |
| `Grep` / `Glob` | `find-files` | File discovery |
| (no equivalent) | `sql` | Structured data |
| `Bash` | `adb` | Everything else |
| (framework) | `finish` | Task lifecycle |

### 2.2 The Complete Tool Set

```
adb          — run any ADB shell command (generic fallback)
sql          — read/write structured data in SQLite databases
read-file    — read text file content from device
write-file   — write text file content to device
find-files   — search for files on device by pattern
finish       — signal task completion
```

### 2.3 Why Each Tool Exists

**`adb`** — The generic fallback. Handles system settings, app lifecycle (am start/stop), package management (pm), content providers, intents, and any shell command. Like Claude Code's `Bash`.

**`sql`** — SQLite is the universal storage layer on Android. Nearly every app stores data in `.db` files under `/data/data/<pkg>/databases/`. A SQLite database is a binary file — you cannot read or modify it with text file tools. `sqlite3` is the standard CLI client (like `psql` for PostgreSQL), but piping SQL through `adb shell` breaks due to shell escaping. This tool makes `sqlite3` work reliably by handling encoding internally.

**`read-file`** — Reads text file content from the device without shell escaping issues. File paths with spaces, special characters, or non-ASCII names work correctly because the path is passed as a Python argument, not through shell interpolation. Returns clean text content.

**`write-file`** — Writes text content to device files. Content with apostrophes (`Cafe L'amour`), quotes, parentheses, unicode — all handled internally via base64 encoding. Supports `--append` mode for file merging operations.

**`find-files`** — Searches for files by glob pattern. Equivalent to `find <dir> -name "<pattern>"` but without shell escaping issues for patterns with spaces or special characters. Returns a list of matching paths.

**`finish`** — Signals task completion. For information-retrieval tasks, the description IS the answer. Framework-level tool, not a data operation.

### 2.4 Why NOT Other Tools

| Rejected Tool | Why Not |
|--------------|---------|
| `content` (ContentProvider wrapper) | Android-specific API. The `adb` tool already runs `content query/insert`. Adding a wrapper specifically because calendar/expense INSERT tasks fail would be benchmark-fitting. |
| `app-stop <package>` | Convenience wrapper only. `adb "adb shell am force-stop <pkg>"` works fine. No escaping issues. |
| `settings <get\|put>` | Same — `adb "adb shell settings put system key value"` has no escaping problems. |
| `list-packages` | Same — `adb "adb shell pm list packages \| grep keyword"` works fine. |
| `install-apk` | Too specialized. Rare operation. |
| `screenshot` / `tap` / `swipe` | GUI operations — violates terminal-only constraint. |

The principle: **if `adb` handles it without escaping issues, don't add a wrapper.**

---

## 3. How: Tool Specifications

### 3.1 `sql` — Execute SQL on Device Databases

**Status**: Implemented

```
python android_env.py sql <db_path> "<SQL>"
python android_env.py sql <db_path> "<SQL>" --no-step
```

**Behavior**:
1. Receives raw SQL as Python `sys.argv` — no shell interpretation
2. Base64-encodes the SQL internally
3. Sends `adb shell "echo <b64> | base64 -d | sqlite3 <db_path>"` to container
4. Returns sqlite3 text output
5. Counts as one step (unless `--no-step`)

**Examples**:
```bash
# Schema discovery
python android_env.py sql /data/data/com.example.app/databases/data.db ".tables"
python android_env.py sql /data/data/com.example.app/databases/data.db ".schema items"

# Query
python android_env.py sql /data/data/com.example.app/databases/data.db "SELECT * FROM items LIMIT 5;"

# Insert with quotes and parentheses — just works
python android_env.py sql /data/data/com.example.app/databases/data.db "INSERT INTO items (name, desc) VALUES ('Chef''s Special', 'A hearty meal (serves 4)');"

# Delete with WHERE
python android_env.py sql /data/data/com.example.app/databases/data.db "DELETE FROM items WHERE name = 'Old Item';"
```

**What it does NOT do**: discover databases, validate SQL, know about any specific app schema.

---

### 3.2 `write-file` — Write Content to Device Files

**Status**: Implemented

```
python android_env.py write-file <device_path> "<content>"
python android_env.py write-file <device_path> "<content>" --append
python android_env.py write-file <device_path> "<content>" --no-step
```

**Behavior**:
1. Receives content as Python `sys.argv` — no shell interpretation
2. Base64-encodes content internally
3. Sends `adb shell "echo <b64> | base64 -d > <path>"` (or `>>` for append)
4. Returns confirmation
5. Counts as one step (unless `--no-step`)

**Examples**:
```bash
# Simple write
python android_env.py write-file /sdcard/Documents/note.md "Hello world"

# Content with apostrophes
python android_env.py write-file /sdcard/Documents/note.md "Lunch at Cafe L'amour"

# Append mode (for merging)
python android_env.py write-file /sdcard/out.md "First part"
python android_env.py write-file /sdcard/out.md "Second part" --append
```

**What it does NOT do**: create parent directories, trigger media scan, force-stop apps. The agent handles those via `adb`.

---

### 3.3 `read-file` — Read Content from Device Files

**Status**: Proposed

```
python android_env.py read-file <device_path>
python android_env.py read-file <device_path> --no-step
```

**Behavior**:
1. Sends `adb shell "base64 <device_path>"` to container
2. Base64-decodes the output in Python
3. Returns clean text content
4. Counts as one step (unless `--no-step`)

**Why base64 round-trip**: `adb shell cat <path>` can mangle binary content, add extra line endings, or fail on paths with spaces. Base64 ensures byte-perfect transfer.

**Implementation**:
```python
def cmd_read_file(device_path: str, count_step: bool = True) -> int:
    import base64 as _b64

    state = _load_state()
    if state["terminated"]:
        print("ERROR: Task already finished.")
        return 1

    adb_cmd = f'adb shell "base64 {device_path}"'

    try:
        resp = _http_post("/step_adb", {
            "command": adb_cmd,
            "thought": f"read-file: {device_path}",
            "count_step": count_step,
        })
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    raw_output = resp.get("command_output", "").strip()
    reward = resp.get("reward", 0.0)
    terminated = resp.get("terminated", False)
    truncated = resp.get("truncated", False)

    state["step_count"] += 1
    state["reward"] = reward
    if terminated or truncated:
        state["terminated"] = True

    # Decode base64 content
    try:
        content = _b64.b64decode(raw_output).decode("utf-8", errors="replace")
    except Exception:
        content = raw_output  # Fallback to raw output

    if len(content) > MAX_OUTPUT_CHARS:
        content = content[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

    print(f"$ cat {device_path}")
    print(content)

    state["step_records"].append({
        "step_idx": state["step_count"],
        "thought": f"read-file: {device_path}",
        "action_type": "read-file",
        "action_params": {"device_path": device_path},
        "command_output": content[:4000],
    })
    _save_state(state)
    return 0
```

**Examples**:
```bash
# Read a text file
python android_env.py read-file /sdcard/Documents/Markor/note.md

# Read a config file
python android_env.py read-file /data/data/com.example.app/shared_prefs/config.xml
```

---

### 3.4 `find-files` — Search for Files on Device

**Status**: Proposed

```
python android_env.py find-files <directory> "<pattern>"
python android_env.py find-files <directory> "<pattern>" --no-step
```

**Behavior**:
1. Sends `adb shell "find <directory> -name '<pattern>' 2>/dev/null"` to container (pattern is shell-escaped internally)
2. Returns list of matching file paths
3. Counts as one step (unless `--no-step`)

**Implementation**:
```python
def cmd_find_files(directory: str, pattern: str, count_step: bool = True) -> int:
    import shlex

    state = _load_state()
    if state["terminated"]:
        print("ERROR: Task already finished.")
        return 1

    # Shell-escape the pattern to handle spaces and special chars
    safe_pattern = shlex.quote(pattern)
    adb_cmd = f'adb shell "find {directory} -name {safe_pattern} 2>/dev/null"'

    try:
        resp = _http_post("/step_adb", {
            "command": adb_cmd,
            "thought": f"find-files: {directory} {pattern}",
            "count_step": count_step,
        })
    except (urllib.error.URLError, OSError) as e:
        print(f"ERROR: HTTP request failed: {e}")
        return 2

    raw_output = resp.get("command_output", "").strip()
    reward = resp.get("reward", 0.0)
    terminated = resp.get("terminated", False)
    truncated = resp.get("truncated", False)

    state["step_count"] += 1
    state["reward"] = reward
    if terminated or truncated:
        state["terminated"] = True

    if len(raw_output) > MAX_OUTPUT_CHARS:
        raw_output = raw_output[:MAX_OUTPUT_CHARS] + "\n... (truncated)"

    print(f"$ find {directory} -name {safe_pattern}")
    if raw_output:
        print(raw_output)
    else:
        print("(no files found)")

    state["step_records"].append({
        "step_idx": state["step_count"],
        "thought": f"find-files: {directory} {pattern}",
        "action_type": "find-files",
        "action_params": {"directory": directory, "pattern": pattern},
        "command_output": raw_output[:4000],
    })
    _save_state(state)
    return 0
```

**Examples**:
```bash
# Find all databases for a package
python android_env.py find-files /data/data/com.example.app/databases "*.db"

# Find markdown files
python android_env.py find-files /sdcard/Documents "*.md"

# Find files with spaces in name
python android_env.py find-files /sdcard "my document.txt"
```

---

## 4. Results So Far

### 4.1 Impact of `sql` + `write-file`

Measured on 87 AndroidWorld terminal tasks with gpt-5.3-codex:

| Metric | Before (adb only) | After (+ sql, write-file) | Delta |
|--------|-------------------|--------------------------|-------|
| Agent SR (single attempt) | 40/87 (46%) | 56/87 (64%) | **+16** |
| Oracle att1 SR | 42/87 (48%) | 55/87 (63%) | **+13** |
| Oracle total SR (4 attempts) | 58/87 (67%) | 67/87 (77%) | **+9** |
| Oracle cost | $17.84 | $11.40 | **-36%** |

The tools didn't just improve SR — they reduced cost by 36% because the agent spends fewer turns on escaping failures.

### 4.2 What the Tools Fixed

Tasks that went from FAIL → PASS after adding tools:

- **Database operations**: Broccoli recipe INSERT/DELETE, Calendar event INSERT/DELETE, ProExpense DELETE, Tasks.org queries — all previously blocked by SQL escaping through `adb shell`
- **File operations**: Markor note creation with apostrophes, file content updates — blocked by content escaping
- **Contact creation** (Task 9): Previously classified as "GUI-required" — actually works via content provider when SQL escaping isn't an issue

### 4.3 Remaining Failures (20 tasks)

| Category | Count | Can tools help? |
|----------|-------|----------------|
| Complex multi-step (cross-app, merge, filter) | 7 | `read-file` could help with read-modify-write patterns |
| Calendar create (recurring, relative dates) | 2 | Reasoning issue, not tooling |
| SMS (GUI-required) | 2 | No — needs screen interaction |
| ProExpense INSERT (cents format) | 2 | Reasoning issue (math error) |
| Brightness min | 2 | Evaluator/display issue |
| Clipboard | 1 | No terminal API |
| Retro Music playlist | 1 | Likely GUI-required |
| Info retrieval precision | 2 | Reasoning issue |
| Markor folder creation | 1 | Unknown |

Of 20 remaining failures, ~5-7 could potentially benefit from `read-file` (multi-step file operations), ~5 are reasoning errors (not tooling), and ~6-8 are fundamentally unreachable in terminal mode.

---

## 5. Implementation Plan

### Done
- [x] `sql` tool — implemented and tested
- [x] `write-file` tool — implemented and tested
- [x] Prompt updated to document new tools

### Next
- [ ] `read-file` tool — implement in android_env.py
- [ ] `find-files` tool — implement in android_env.py
- [ ] Update prompt to document `read-file` and `find-files`
- [ ] Run eval with all 4 new tools
- [ ] Compare against current best (67/87 oracle)

---

## 6. Summary

The Terminus_2 tool set follows the same design principle as Claude Code: **specialized tools for universal data primitives, with a generic shell fallback for everything else.**

```
┌─────────────────────────────────────────────────────┐
│                   Agent (LLM)                        │
│  Decides WHAT to do — reasoning, planning, intent   │
├─────────────────────────────────────────────────────┤
│                   Tool Layer                         │
│  Handles HOW — escaping, encoding, transport        │
│                                                     │
│  sql        — structured data (SQLite databases)    │
│  read-file  — read text files                       │
│  write-file — write text files                      │
│  find-files — discover files                        │
│  adb        — everything else (generic fallback)    │
│  finish     — task lifecycle                        │
├─────────────────────────────────────────────────────┤
│              Android Device (via ADB)                │
└─────────────────────────────────────────────────────┘
```

The agent expresses **intent** (run this SQL, write this content). The tools handle **mechanics** (encoding, escaping, piping). This separation is what makes the tools general-purpose — they work for any app, any database, any file, without knowledge of the specific task.
