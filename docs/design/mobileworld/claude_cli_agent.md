# Design: Claude Code CLI Agent for MobileWorld

**Status**: Draft v2  
**Date**: 2026-04-09  
**Branch**: `refactor/eval-runner`

## 1. Goal

Use Claude Code CLI as an agent to complete MobileWorld tasks via terminal-only
interaction (no screenshots, no accessibility tree, no GUI taps/swipes). Two
optimization axes over the AndroidWorld baseline:

1. **System prompt** — Android domain knowledge from a senior developer who
   controls devices via terminal
2. **Tool script** — Pre-built composable tools that handle escaping, encoding,
   and multi-layer command nesting so Claude generates high-level commands
   instead of fragile raw bash

**Hard constraint**: No benchmark-specific, app-specific, or task-specific
leakage. Every tool and prompt element must be general Android/container
knowledge portable to AndroidWorld, AndroidLab, or any other Android benchmark.

## 1.1 Leakage Analysis: Docker/PostgreSQL Backend Knowledge

### The tension

MobileWorld's hardest tasks (~60 of 208) involve backend services running as
Docker-in-Docker containers with PostgreSQL databases. Providing tools and
prompt knowledge about Docker + PostgreSQL makes these tasks dramatically
easier. But does this constitute benchmark-specific leakage?

### Our position: No — Docker/PG is general infrastructure knowledge

**Argument 1: The inertness test.** If you give the same tools and prompt to an
agent on AndroidWorld (which has no Docker backends):
- `service-status` returns "no containers running" — agent moves on
- `pg` has nothing to discover — agent never calls it
- The prompt section "Container Environment" says "the container *may* host
  Docker services" — conditional language, not an assertion

The tools are inert when irrelevant. They don't help on non-Docker benchmarks,
so they provide zero unfair advantage.

**Argument 2: The senior-developer test.** A real Android developer given SSH
access to an unfamiliar container would:
1. Run `docker ps` to see what's running
2. Notice PostgreSQL containers and query them
3. This is standard practice, not benchmark-specific insight

Our tools automate this natural workflow. The prompt doesn't say "there IS a
Mastodon instance" — it says "there MAY be Docker services; here's how to
discover them."

**Argument 3: The escaping problem.** Even if an agent independently discovers
Docker+PG backends, it still fails >80% of the time because
`docker exec <container> psql -U user -d db -c "SELECT ..."` requires
triple-nested escaping. The `pg` tool solves a mechanical escaping problem,
not an information asymmetry problem.

**Argument 4: Granularity of knowledge.** The tools and prompt contain:
- General: "Docker containers may be running" ✓
- General: "PostgreSQL can be queried via `psql`" ✓
- NOT present: container names, database names, table schemas, port mappings ✗
- NOT present: app names (Mastodon, Mattermost) ✗
- NOT present: any task goals or expected outcomes ✗

The agent must still discover all specifics from the live environment.

### Where we draw the line

| Knowledge level | Leakage? | In our design? |
|----------------|----------|---------------|
| "Docker exists as a technology" | No | Yes (tools) |
| "PostgreSQL exists, queryable via psql" | No | Yes (tools) |
| "The container may host Docker services" | No | Yes (prompt) |
| "There IS a service called Mastodon on port 3000" | **Yes** | **No** |
| "The Mastodon DB has a table called `accounts`" | **Yes** | **No** |
| "To post a toot, use `tootctl`" | **Yes** | **No** |
| "Email state is at `/sdcard/.../state.json`" | **Yes** | **No** |

## 2. Architecture

```
Claude Code CLI
    │
    ├─ System prompt (mw_terminal_expert.py)
    │     Android domain knowledge + tool documentation
    │
    ├─ Allowed tools: Bash(command:*), Read, Write
    │
    └─ Bash calls ──► mw_tools.py <subcommand> [args]
                          │
                          ├─ adb          → POST /exec  (ADB commands)
                          ├─ exec         → POST /exec  (container shell)
                          ├─ sql          → POST /exec  (device SQLite via adb shell)
                          ├─ pg           → POST /exec  (PostgreSQL via docker exec psql)
                          ├─ read-file    → POST /exec  (cat/base64, PDF text extraction)
                          ├─ write-file   → POST /exec  (base64 encode → write)
                          ├─ find-files   → POST /exec  (find with glob)
                          ├─ json-read    → POST /exec  + local JSON parse
                          ├─ json-write   → POST /exec  (structured JSON → file)
                          ├─ content      → POST /exec  (content provider query/insert/update/delete)
                          ├─ intent       → POST /exec  (am start/broadcast with proper escaping)
                          ├─ http         → direct HTTP from host (curl-like)
                          ├─ service-status → POST /exec (docker ps + health check)
                          └─ finish       → POST /step  (answer action) + stdout signal
```

**Key decisions:**

- **Separate script** (`mw_tools.py`), not an extension of `android_env.py`.
  The AndroidWorld env script is coupled to its `/step_adb` protocol. MobileWorld
  uses `/exec` (general shell) and has different lifecycle endpoints.
- **All tools route through `/exec`** on the MobileWorld container. This is the
  SkyRL adapter endpoint that runs any command inside the container (ADB
  commands get device-serial rewriting automatically).
- **Allow `Read` and `Write`** as Claude Code tools. `Read` lets Claude inspect
  files it pulls to `/tmp`. `Write` lets Claude create helper scripts on the fly
  (e.g., a Python script for complex JSON manipulation).
- **`finish` writes to stdout** (not HTTP) so the runner script (`mw_cli_common.py`)
  captures the answer and calls `/task/eval` itself — matching the existing
  MobileWorld lifecycle.

## 3. Tool Script Design (`mw_tools.py`)

Location: `eval-runners/benchmarks/mobileworld/mw_tools.py`

### 3.1 Existing Tools (carried from mw_env.py, improved)

| Tool | Syntax | What it does | Improvement over raw bash |
|------|--------|-------------|--------------------------|
| `adb` | `mw adb "adb shell <cmd>"` | Run ADB command on device | Serial rewriting, output truncation |
| `exec` | `mw exec "<shell cmd>"` | Run any command in container | Timeout handling, error formatting |
| `sql` | `mw sql <db_path> "<SQL>"` | SQLite on device | Auto `su root`, retry with different quoting strategies, column-aligned output |
| `read-file` | `mw read-file <path>` | Read file from device or container | Auto-detect device vs host path; **PDF text extraction** via `pdftotext` or Python fallback; base64 round-trip for binary safety |
| `write-file` | `mw write-file <path> '<content>'` | Write file to device or container | Base64 encoding to avoid all escaping issues; `--append` flag; auto `mkdir -p` |
| `find-files` | `mw find-files <dir> "<pattern>"` | Search files | `shlex.quote` for safety, `-maxdepth` default to avoid hanging |
| `http` | `mw http <METHOD> "<url>" [--data '...']` | HTTP request | SSL handling, timeout, response truncation |
| `finish` | `mw finish --status complete --description "<answer>"` | Signal task completion | Calls `/step` with answer action |

### 3.2 New Tools

#### `pg` — PostgreSQL query via Docker

**Why**: Android automation environments may host backend services in Docker
containers with PostgreSQL databases. Querying them via raw bash requires
triple-nested escaping (`docker exec <container> psql -U user -d db -c "SQL"`)
that agents consistently fail to get right. This tool eliminates the escaping
problem entirely by piping SQL via stdin.

```bash
mw pg <container_pattern> <database> "<SQL>" [--user <user>]
```

- `container_pattern`: grep pattern to find the Docker container (e.g., `"db-1"`,
  `"postgres"`)  — **not** a hardcoded container name
- Auto-discovers the running container name via `docker ps --format '{{.Names}}' | grep <pattern>`
- Pipes SQL via stdin to avoid all quoting issues:
  `echo "<SQL>" | docker exec -i <container> psql -U <user> -d <db> -t`
- Default user: `postgres`
- `-t` flag for tuple-only output (no headers/footers)
- Truncates output to 4000 chars
- If no matching container is found, prints clear error: `ERROR: no running container matching '<pattern>'`

**Example:**
```bash
mw pg "db-1" mydb "SELECT username FROM users LIMIT 5"
mw pg "postgres" appdb "SELECT id,name FROM items" --user appuser
```

**Why this is general**: Any Docker-in-Docker setup with PostgreSQL benefits.
No app names, table names, or schemas are baked in. On environments without
Docker, this tool simply reports no containers found.

#### `json-read` — Parse and query JSON files

**Why**: Many Android apps store state as JSON files (email state, app configs,
callback data). Reading raw JSON with `cat` then asking Claude to parse it
wastes tokens and is error-prone. A tool that extracts specific fields is
more reliable.

```bash
mw json-read <path> [<jq_expression>]
```

- Reads file (device or host), parses JSON
- Optional jq-like expression for field extraction: `.key`, `.[0]`, `.key[0].subkey`
- Without expression: pretty-prints the full JSON (truncated to 4000 chars)
- Implemented in Python (no `jq` dependency) using a simple path evaluator

**Example:**
```bash
mw json-read /sdcard/Android/data/com.example/files/state.json
mw json-read /sdcard/Android/data/com.example/files/state.json ".emails[0].subject"
```

#### `json-write` — Write structured JSON to file

**Why**: Writing JSON via `echo '{"key": "value"}' > file` in a nested
shell context is a quoting disaster. A dedicated tool accepts key-value pairs
or a JSON string and writes it atomically.

```bash
mw json-write <path> '<json_string>'
mw json-write <path> --merge '<json_string>'   # merge into existing file
```

- Base64-encodes the JSON to avoid all shell escaping
- `--merge` reads existing file, deep-merges the new data, writes back
- Validates JSON before writing (fails fast on malformed input)

#### `content` — Android content provider operations

**Why**: Content providers are Android's standard data API (contacts, SMS,
calendar, media). The `content` CLI tool requires precise URI formatting and
column specifications. Agents frequently get the syntax wrong.

```bash
mw content query <uri> [--projection <cols>] [--where "<clause>"] [--sort "<order>"]
mw content insert <uri> [--bind <type>:<col>:<value> ...]
mw content update <uri> --where "<clause>" [--bind <type>:<col>:<value> ...]
mw content delete <uri> --where "<clause>"]
```

- Builds the full `adb shell content query/insert/update/delete` command with
  proper escaping
- `--bind` uses Android's type notation: `s:name:John` (string), `i:age:30` (int),
  `l:date:1234567890` (long)
- `--projection` accepts comma-separated column names
- Auto-escapes values containing spaces and special characters

**Example:**
```bash
mw content query content://sms/sent --projection "address:body:date" --sort "date DESC"
mw content insert content://sms --bind s:address:+15551234 --bind s:body:"Hello" --bind i:type:2
```

#### `intent` — Fire Android intents

**Why**: `am start` and `am broadcast` with extras require precise flag syntax
(`--es`, `--ei`, `--ez`, `--el`, etc.) that agents frequently botch. A
structured tool maps named parameters to the right flags.

```bash
mw intent start <component_or_action> [--extra <type>:<key>:<value> ...]  [--data <uri>] [--flags <int>]
mw intent broadcast <action> [--extra <type>:<key>:<value> ...] [--data <uri>]
```

- `--extra` types: `s` (string/--es), `i` (int/--ei), `z` (bool/--ez),
  `l` (long/--el), `f` (float/--ef)
- Component format: `com.package/.Activity` or `-a android.intent.action.X`
- Auto-adds `-n` for component, `-a` for action

**Example:**
```bash
mw intent start -a android.intent.action.SET_ALARM --extra i:android.intent.extra.alarm.HOUR:14 --extra i:android.intent.extra.alarm.MINUTES:30 --extra z:android.intent.extra.alarm.SKIP_UI:true
mw intent broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE --data "file:///sdcard/Download/photo.jpg"
```

#### `service-status` — Check Docker service health

**Why**: Before querying a backend, the agent needs to know if it's running.
Discovering and starting Docker services via raw `docker ps` + `docker compose up`
is multi-step and error-prone.

```bash
mw service-status [<name_pattern>]
mw service-status --start <compose_dir>
mw service-status --stop <compose_dir>
```

- Without args: lists all running Docker containers with health status
- With pattern: filters by container name
- `--start`: runs `docker compose up -d` in the given directory
- `--stop`: runs `docker compose down` in the given directory
- Returns structured output: container name, status, ports, health

### 3.3 Tool Design Principles

1. **Escaping is the tool's job** — The agent passes logical values; the tool
   handles all shell/SQL/JSON escaping via base64 or stdin piping.
2. **Discovery over assumption** — Tools like `pg` auto-discover container names
   via `docker ps | grep`. No hardcoded names.
3. **Truncation** — All output capped at 4000 chars with a `[truncated]` marker.
   Prevents context window blowup on large DB dumps.
4. **Error clarity** — On failure, tools print `ERROR: <specific message>` so
   the agent can diagnose and retry.
5. **No app knowledge** — Tools know about Android platform concepts (content
   providers, intents, SQLite, ADB) and container concepts (Docker, PostgreSQL)
   but nothing about specific apps, schemas, or file locations.

## 4. System Prompt Design (`mw_terminal_expert.py`)

Location: `eval-runners/agents/cli/claude_sdk/prompts/mw_terminal_expert.py`

The prompt has four sections: Role, Tools, Android Knowledge, Strategy.

### 4.1 Role (~50 tokens)

```
You are a senior Android developer who automates devices via terminal commands.
You control an Android device and its host container through a CLI tool suite.
You cannot see the screen — no screenshots, no UI hierarchy, no tap/swipe.
All interaction is through shell commands, databases, files, APIs, and intents.
```

### 4.2 Tools (~300 tokens)

Document each tool with one-line syntax + one-line description. Reference the
tool table from Section 3. Format:

```
## Tools

python {script} adb "adb shell <command>"                    # Any ADB command
python {script} exec "<command>"                              # Any shell command in container
python {script} sql <db_path> "<SQL>"                         # SQLite query on device (auto root)
python {script} pg <container_grep> <db> "<SQL>" [--user u]   # PostgreSQL via Docker
python {script} read-file <path>                              # Read file (device or host, PDF-aware)
python {script} write-file <path> '<content>' [--append]      # Write file (base64-safe)
python {script} find-files <dir> "<pattern>"                  # Search files by glob
python {script} json-read <path> [jq_expr]                    # Read + parse JSON
python {script} json-write <path> '<json>'  [--merge]         # Write structured JSON
python {script} content query|insert|update|delete <uri> ...  # Android content providers
python {script} intent start|broadcast <target> [--extra ...] # Fire intents
python {script} service-status [pattern|--start|--stop dir]   # Docker service management
python {script} http <METHOD> "<url>" [--data '...']          # HTTP requests
python {script} finish --status complete --description "<answer>"
```

### 4.3 Android Domain Knowledge (~600 tokens)

This is the senior-developer knowledge that's general to any Android automation.
NOT a discovery guide (the agent should still discover specifics from the device),
but structural knowledge that saves exploration turns.

```
## Android Platform Knowledge

### File System Layout
- /sdcard/ — user-accessible storage (Download/, Documents/, DCIM/, Android/data/<pkg>/)
- /data/data/<package>/ — app private data (databases/, shared_prefs/, files/)
- /data/user_de/0/<package>/ — device-encrypted app data
- /system/ — read-only system files

### App Discovery
- List packages: `pm list packages | grep <keyword>`
- Find app data: `find-files /data/data/<pkg> "*.db"` for databases
- Find app files: `find-files /sdcard/Android/data/<pkg> "*"`
- Get package path: `pm path <package>`

### Database Patterns
- Most apps store data in SQLite databases under /data/data/<pkg>/databases/
- Always discover schema first: `sql <db> ".tables"`, then `sql <db> ".schema <table>"`
- After modifying a database, force-stop the app: `am force-stop <package>`
  so it re-reads from disk on next launch.
- Timestamp conventions vary: ~10 digits = Unix seconds, ~13 digits = milliseconds.
  Check existing rows to determine the convention before inserting.

### Content Providers
- Standard URIs: content://sms, content://contacts, content://call_log,
  content://media/external, content://calendar
- Use `content query` to read, `content insert` to create records.
- Content providers handle app notification automatically (no force-stop needed).

### Intents
- Launch activity: `am start -n <package>/<activity>` or `am start -a <action>`
- Common actions: SET_ALARM, SEND (SMS), VIEW, MEDIA_SCANNER_SCAN_FILE
- Broadcast: `am broadcast -a <action>` — e.g., media scanner, airplane mode toggle
- Alarm extras: HOUR (24h int), MINUTES (int), SKIP_UI (bool)

### File Operations
- After creating files under /sdcard/, trigger media scan:
  `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://<path>`
- Use `read-file` for reliable reading (handles encoding, PDFs).
- Use `write-file` for reliable writing (handles escaping via base64).

### System Settings
- Read: `settings get <namespace> <key>` (namespaces: system, secure, global)
- Write: `settings put <namespace> <key> <value>`
- Some settings need a broadcast to take effect (e.g., airplane_mode).
- Display: `wm size`, `wm density`

### Container Environment
- The device runs inside a host container. The host may also run additional
  services (e.g., web apps, databases) in Docker containers alongside the emulator.
- ALWAYS run `service-status` early to discover what services are available.
  If no Docker containers are running, skip backend-related tools.
- If you discover PostgreSQL containers, use `pg` to query them — it handles
  escaping automatically. Discover databases with `pg <container> postgres "\\l"`
  and tables with `pg <container> <db> "\\dt"`.
- Use `exec` for arbitrary container commands (curl, docker, ls, etc.).
- Backend services may need to be started before use. Look for docker-compose
  files: `find-files /app "*compose*"` or `find-files / "docker-compose.yml"`.

### Date & Time
- Get device time: `adb "adb shell date"` — ALWAYS do this before temporal reasoning.
- Convert relative dates ("today", "next Monday") using the device clock.
- Unix timestamps in DBs may be UTC — compare in the same timezone.
- For range queries, use >= start AND < end (half-open), not BETWEEN.
```

### 4.4 Strategy (~200 tokens)

```
## Strategy

Before each action, reason about what you know vs. what you're assuming.

1. **Discover** — Find the relevant app, its data files, database schemas,
   running services. Use `find-files`, `sql ... ".tables"`, `service-status`.
2. **Inspect** — Read existing data before modifying. Understand formats,
   ID mappings, timestamp units. Match observed patterns exactly.
3. **Act** — Use the right tool: `sql` for databases, `content` for providers,
   `json-write` for JSON files, `intent` for system actions, `pg` for Docker
   databases.
4. **Verify** — Query back to confirm changes persisted. Re-read files, re-query
   databases.
5. **Sync** — Force-stop apps after DB changes. Trigger media scan after file
   changes.

## Rules

1. For information-retrieval tasks, `--description` in `finish` IS your answer.
   Give ONLY what was asked — no extra commentary.
2. ALWAYS call `finish` when done.
3. Copy text and values EXACTLY from the task — do not paraphrase.
4. Read the FULL task description — most tasks require multiple steps.
5. When a task involves time, ALWAYS check device date/timezone first.
```

### 4.5 Total Prompt Size

| Section | Tokens (est.) |
|---------|--------------|
| Role | 50 |
| Tools | 300 |
| Android Knowledge | 600 |
| Strategy + Rules | 200 |
| **Total** | **~1150** |

This is deliberately compact. The oracle prompt is ~800 tokens but contains
app-specific data locations. Our prompt trades those specifics for general
platform knowledge that helps the agent discover on its own.

## 5. Runner Script

Location: `eval-runners/benchmarks/mobileworld/run_claude_cli.py`

Reuses the existing `mw_cli_common.py` infrastructure:

```python
# Pseudo-code
parser = build_common_parser()
args = parser.parse_args()

system_prompt = load_system_prompt(args.prompt)  # loads mw_terminal_expert
allowed_tools = get_allowed_tools(args.prompt)   # "Bash(command:*),Read,Write"

# Register new prompt in PROMPT_MODULES:
#   "mw_terminal_expert": "agents.cli.claude_sdk.prompts.mw_terminal_expert"

# Point MW_ENV_SCRIPT to mw_tools.py instead of mw_env.py
# (or add a separate config in the prompt module)

task_runner = partial(run_one_task, ...)
results = run_parallel(tasks, ...) or run_sequential(tasks, ...)
finalize_results(results, ...)
```

Changes to `mw_cli_common.py`:
- Add `MW_TOOLS_SCRIPT` path pointing to `mw_tools.py`
- Allow prompt modules to specify which env script to use via
  `ENV_SCRIPT` attribute (default: `mw_env.py`, new prompt uses `mw_tools.py`)
- Register `"mw_terminal_expert"` in `PROMPT_MODULES`

## 6. File Layout

```
eval-runners/
├── benchmarks/mobileworld/
│   ├── mw_tools.py              # NEW — tool script
│   ├── run_claude_cli.py        # NEW — runner (thin wrapper over mw_cli_common)
│   └── mw_cli_common.py         # MODIFY — add mw_terminal_expert prompt, MW_TOOLS_SCRIPT
│
└── agents/cli/claude_sdk/prompts/
    └── mw_terminal_expert.py    # NEW — system prompt module
```

## 7. Implementation Plan

Build order: tools first (foundation), then prompt (depends on final tool
signatures), then runner (wires them together), then validate.

### Phase 1: Core Tools — baseline parity with `mw_env.py`

**Step 1** — Create `mw_tools.py` scaffold with shared infrastructure:
- `_exec(command)` — POST to `/exec` endpoint
- `_step(payload)` — POST to `/step` endpoint
- `_truncate(text, limit=4000)` — consistent output capping
- argparse with subcommands
- Environment variables: `MW_SERVER_URL`, `MW_DEVICE_ID`, `MW_STATE_FILE`

**Step 2** — Port and improve 8 existing tools from `mw_env.py`:
- `adb`: add output truncation, cleaner error messages
- `exec`: add configurable timeout, error formatting
- `sql`: **major improvement** — use stdin piping as primary strategy
  (`echo "SQL" | adb shell su 0 sqlite3 <db>`) instead of nested quoting;
  keep current quoting strategies as fallbacks
- `read-file`: add PDF text extraction fallback chain
  (`pdftotext` → `python3 fitz` → `strings` → file metadata)
- `write-file`: keep base64 approach, add `--append` flag, auto `mkdir -p`
- `find-files`: add `-maxdepth 5` default, `shlex.quote` for pattern
- `http`: keep as-is, add response truncation
- `finish`: keep as-is (calls `/step` with answer action)

**Deliverable**: `mw_tools.py` that can replace `mw_env.py` 1:1 on existing
tasks. Validate by running 3-5 tasks that currently work with `mw_env.py`.

### Phase 2: Backend & Docker Tools — unlock hardest task category

**Step 3** — Add `pg` tool:
- Auto-discover container via `docker ps --format '{{.Names}}' | grep <pattern>`
- Pipe SQL via stdin: `echo "<SQL>" | docker exec -i <container> psql -U <user> -d <db> -t`
- Handle: no matching container, connection refused, query errors
- Test: run `pg "db" postgres "\\l"` and `pg "db" postgres "SELECT 1"` against
  a live container

**Step 4** — Add `service-status` tool:
- No args: `docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'`
- With pattern: pipe through `grep`
- `--start <dir>`: `cd <dir> && docker compose up -d` (detect compose file variant)
- `--stop <dir>`: `cd <dir> && docker compose down`
- Handle: Docker not installed, no compose file in dir, compose up failures

**Deliverable**: Agent can discover and query any Docker+PG backend without
manual escaping. Test on backend-dependent tasks.

### Phase 3: Structured Data Tools — reduce token waste & parsing errors

**Step 5** — Add `json-read` tool:
- Fetch file content via `_exec("adb shell cat <path>")` or `_exec("cat <path>")`
- Parse JSON in Python (not on device)
- Simple path evaluator: `.key`, `.[0]`, `.key[0].subkey`, `.key[*].subkey`
- Pretty-print with truncation

**Step 6** — Add `json-write` tool:
- Validate JSON input in Python
- Base64-encode and write via `_exec`
- `--merge`: read existing → deep merge → write back
- Verify write by reading back

**Deliverable**: Agent can read/write structured JSON without shell escaping.
Test with nested JSON containing special characters.

### Phase 4: Android Platform Tools — correct intent & content provider syntax

**Step 7** — Add `content` tool:
- Build `adb shell content query/insert/update/delete` commands
- `--bind` parser: `s:col:val` → `--bind s:col:val` in ADB content syntax
- `--projection`, `--where`, `--sort` with proper escaping
- Handle: invalid URI, permission denied, empty results

**Step 8** — Add `intent` tool:
- Build `am start` / `am broadcast` commands
- `--extra` parser: `s:key:val` → `--es key val`, `i:key:val` → `--ei key val`, etc.
- `--data` for URI data, `--flags` for intent flags
- Auto-detect action vs component (starts with `android.` → `-a`, contains `/` → `-n`)

**Deliverable**: Agent can fire intents and query content providers with
correct syntax on first try. Test with SET_ALARM, MEDIA_SCANNER, SMS content
provider.

### Phase 5: System Prompt

**Step 9** — Write `mw_terminal_expert.py`:
- `build_system_prompt(script_path)` — format tool docs with actual script path
- `REQUIRED_TOOLS = "Bash(command:*),Read,Write"`
- `ENV_SCRIPT = "mw_tools"` — tells runner which env script to use
- Four sections: Role, Tools, Android Knowledge, Strategy (see Section 4)
- Validate token count stays under ~1200

### Phase 6: Runner Integration

**Step 10** — Update `mw_cli_common.py`:
- Add `MW_TOOLS_SCRIPT` path constant pointing to `benchmarks/mobileworld/mw_tools.py`
- Register `"mw_terminal_expert"` in `PROMPT_MODULES` dict
- In `load_system_prompt()`: check for `ENV_SCRIPT` attribute on module;
  if present and `== "mw_tools"`, format prompt with `MW_TOOLS_SCRIPT` instead
  of `MW_ENV_SCRIPT`

**Step 11** — Create `run_claude_cli.py`:
- Thin wrapper: parse args, load prompt, build task runner, run parallel/sequential
- Same structure as AndroidWorld's `run_claude_cli.py`

### Phase 7: Validation

**Step 12** — Smoke test (single container, 5 tasks):
- Pick 1 task per category: settings, SMS, email/file, backend (PG), information-retrieval
- Run with `mw_terminal_expert` prompt
- Verify all tools are called correctly, no crashes

**Step 13** — Comparison test (single container, 20 tasks):
- Run same 20 tasks with: (a) `mw_adb_oracle`, (b) `mw_terminal_expert`
- Measure: success rate, avg steps, avg cost, common failure modes
- Goal: within 15% of oracle on non-backend tasks, within 30% on backend tasks

**Step 14** — Full eval (broker, all 208 tasks):
- Run with broker and pool of containers
- Compare against oracle ceiling and any prior baselines

## 8. Portability Check

Every tool and prompt element is general:

| Component | Android-general? | Container-general? | Benchmark-neutral? |
|-----------|:-:|:-:|:-:|
| `adb`, `sql`, `read-file`, `write-file`, `find-files` | Yes | Yes | Yes |
| `pg` | N/A | Yes (any Docker+PG) | Yes |
| `content`, `intent` | Yes (Android API) | N/A | Yes |
| `json-read`, `json-write` | Yes | Yes | Yes |
| `service-status` | N/A | Yes (any Docker) | Yes |
| `http` | Yes | Yes | Yes |
| System prompt: file layout | Yes (AOSP standard) | N/A | Yes |
| System prompt: content providers | Yes (Android API) | N/A | Yes |
| System prompt: intent system | Yes (Android API) | N/A | Yes |
| System prompt: DB patterns | Yes | N/A | Yes |

**Porting to AndroidWorld / AndroidLab:**

- Use `mw_tools.py` directly — it's compatible since these containers also
  have `/exec` (or can be trivially adapted to `/step_adb`).
- `pg` and `service-status` become no-ops: `service-status` returns empty,
  `pg` finds no containers. They add ~20 tokens to the prompt but cause no harm.
- Alternatively, strip Docker tools from the prompt for a leaner version.
  The prompt module can expose a `VARIANT = "full"` / `"android-only"` flag.
- The system prompt needs zero content changes — all Android knowledge
  (file layout, content providers, intents, etc.) applies identically.

## 9. Risk & Mitigations

| Risk | Mitigation |
|------|-----------|
| Docker/PG tools signal "there are backends" | See Section 1.1. Tools are inert on non-Docker environments. Prompt uses conditional language ("may host"). Agent must still discover all specifics. |
| `pg` tool leaks that backends use PostgreSQL | `pg` is documented generically. No container names, DB names, table schemas, or port mappings are provided. Agent discovers via `service-status` + `pg ... ".tables"`. |
| Agent over-relies on Docker tools on simple tasks | Strategy section says "Discover first". On tasks without Docker services, `service-status` returns empty and agent falls back to ADB/SQLite tools. |
| `service-status --start` lets agent start arbitrary services | This is intentional — some tasks require backends that may not auto-start. The agent doesn't know *which* services to start without discovery. Restricted to `docker compose` in known directories. |
| PDF extraction unreliable | Three fallback chain: `pdftotext` → `python3 -c "import fitz; ..."` → `strings`. If all fail, return file metadata only. |
| Tool overhead adds latency | Each tool call is one HTTP POST (~50ms). Negligible vs. LLM inference time. |
| Claude ignores tools and writes raw bash | Prompt explicitly says "Use the right tool" and tools are documented first. The allowed-tools list includes Read/Write for fallback. |
| Content provider URIs vary across Android versions | Prompt says "discover first". Tools don't hardcode URIs. |
| Docker compose directory paths are environment-specific | `service-status --start` requires the agent to discover compose dirs via `find-files / "docker-compose.yml"` or `find-files /app "*compose*"`. No paths are hardcoded. |
