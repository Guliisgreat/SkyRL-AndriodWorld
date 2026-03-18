# Beyond Prompt Optimization: Terminus_2 Agent Improvements

**Status**: Proposed
**Date**: 2026-03-18
**Author**: Claude Code
**Context**: Autoresearch prompt optimization reached 58/87 (67%) oracle SR, 40/87 (46%) agent SR. Prompt-only changes have plateaued. This doc proposes code-level and architectural improvements to push toward 90%+.

---

## 1. Current State

### Results (R6 — best prompt)

| Mode | SR | Cost |
|------|-----|------|
| Agent (single attempt) | 40/87 (46%) | $7.80 |
| Oracle att1 | 42/87 (48%) | — |
| Oracle total (4 attempts) | 58/87 (67%) | $17.84 |

### Failure Breakdown (29 remaining failures, oracle mode)

| Category | Count | Root Cause | Prompt-fixable? |
|----------|-------|------------|-----------------|
| Broccoli recipe DB ops | 7 | Shell escaping for INSERT/DELETE with text | No — agent can't reliably base64-encode |
| Calendar event creation | 5 | Shell escaping for INSERT + timestamp format | No — same escaping issue |
| Markor file ops | 4 | Apostrophes/quotes in file content | No — same escaping issue |
| ProExpense DB ops | 3 | Shell escaping + cents format errors | Partially |
| SMS/Contact | 3 | Requires GUI (Simple SMS Messenger) | No — architectural |
| Retro Music | 2 | Requires GUI (playlist creation) | No — architectural |
| Settings (brightness) | 2 | Evaluator checks display, not setting | Unknown |
| Clipboard | 1 | No terminal API for clipboard | No — architectural |
| Cross-app pipeline | 1 | Multi-step complexity | Partially |
| Info retrieval | 1 | Timestamp/query precision | Yes |

**Key insight**: ~16 of 29 failures stem from a single root cause — the LLM cannot reliably generate correctly-escaped shell commands for complex SQL or text with special characters. The LLM _knows_ the right SQL but can't get it through `adb shell`'s quoting layers.

---

## 2. Proposed Changes (Priority Order)

### 2.1 `sql` Helper Command — Eliminate Shell Escaping for DB Operations

**Impact**: Could fix ~16 tasks (Broccoli, Calendar, ProExpense, some Markor)
**Effort**: Small (1 file, ~50 lines)

#### Problem

The agent must currently construct commands like:
```
python android_env.py adb "adb shell \"echo 'INSERT INTO recipes (title,servings) VALUES (''Pasta'',4);' | sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli\""
```

This goes through 4 shell layers: Python subprocess → host bash → adb → device sh. Quotes, parentheses, and apostrophes break at every layer. The prompt teaches base64 encoding as a workaround, but the LLM generates correct base64 only ~30% of the time.

#### Solution

Add a new `sql` subcommand to `android_env.py` (or a new `sql_helper.py`) that accepts raw SQL and a DB path, handles all encoding internally:

```
python android_env.py sql <db_path> "<raw SQL>"
```

Implementation in `environment.py`:
```python
async def exec_sql(self, db_path: str, sql: str) -> ExecResult:
    """Execute SQL on the device, handling all shell escaping internally."""
    import base64
    encoded = base64.b64encode(sql.encode()).decode()
    cmd = f'echo "{encoded}" | base64 -d | sqlite3 {db_path}'
    return await self._run_on_device(cmd)
```

The agent's command becomes:
```
python android_env.py sql /data/data/com.flauschcode.broccoli/databases/broccoli "INSERT INTO recipes (title,servings) VALUES ('Pasta',4);"
```

No escaping needed — the wrapper handles it.

#### Prompt Update

Replace the base64 section with:
```
### For database queries and writes:
python android_env.py sql <db_path> "<SQL statement>"

This handles all shell escaping automatically. Use it for ALL sqlite3 operations:
- python android_env.py sql /data/data/<pkg>/databases/<db> ".tables"
- python android_env.py sql /data/data/<pkg>/databases/<db> "SELECT * FROM t LIMIT 5;"
- python android_env.py sql /data/data/<pkg>/databases/<db> "INSERT INTO t (a,b) VALUES ('text',42);"
- python android_env.py sql /data/data/<pkg>/databases/<db> "DELETE FROM t WHERE title='Chicken Wrap';"
```

#### Files to Modify

1. **`skyrl-agent/skyrl_agent/agents/android/claude_sdk/android_env.py`** — Add `sql` subcommand handler
2. **`skyrl-agent/skyrl_agent/agents/android/terminus2/environment.py`** — Add `exec_sql()` method (optional, for direct API use)
3. **`skyrl-agent/skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt`** — Update prompt to use `sql` command
4. **`skyrl-agent/skyrl_agent/agents/android/terminus2/agent.py`** — No changes needed (commands are opaque strings)

#### Risk

- Low risk — additive change, doesn't break existing `adb` subcommand
- The `sql` command still goes through `android_env.py` so step counting and state tracking work normally

---

### 2.2 `write-file` Helper Command — Eliminate Escaping for File Content

**Impact**: Could fix ~5 tasks (Markor note creation, merge, update with special chars)
**Effort**: Small (1 file, ~30 lines)

#### Problem

Writing file content with apostrophes (e.g., "Cafe L'amour") through `adb shell` fails:
```
adb shell "echo 'Lunch meeting at Cafe L'amour' > /sdcard/file.md"  # breaks
```

#### Solution

Add a `write-file` subcommand:
```
python android_env.py write-file <device_path> "<content>"
```

Implementation: base64-encode the content, push via `echo <b64> | base64 -d > <path>` on device.

#### Files to Modify

1. **`android_env.py`** — Add `write-file` subcommand

---

### 2.3 Temperature Tuning

**Impact**: Could improve att1 SR by 5-10% (fewer random errors)
**Effort**: Trivial (CLI flag)

#### Problem

At `temperature=0.7`, the model sometimes:
- Uses wrong column names it saw in schema (e.g., `title` instead of `name`)
- Miscalculates timestamps (off by timezone offset)
- Generates invalid base64 strings
- Picks suboptimal approaches on first attempt

#### Solution

Test `temperature=0.3` on the 87-task eval. Lower temperature → more deterministic → fewer random errors. The agent's task is execution, not creative writing.

#### Execution

```bash
python run_terminus2_oracle.py \
  --data val_data_seed7_terminal.jsonl \
  --template optimized-v1.txt \
  --model gpt-5.3-codex --parser android-json \
  --temperature 0.3 \
  --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4
```

No code changes needed — just a CLI flag.

---

### 2.4 Shell Error Auto-Recovery in Agent Loop

**Impact**: Could improve oracle total SR by 5-10%
**Effort**: Medium (~30 lines in agent.py)

#### Problem

When a command fails with "syntax error" or "no closing quote", the agent burns a turn asking the LLM to fix it. The LLM often makes the same mistake again. This wastes 2-3 turns per failed command.

#### Solution

In `agent.py`'s `_execute_commands()`, detect shell escaping errors and automatically retry with base64:

```python
async def _execute_commands(self, commands, commands_log):
    for cmd in commands:
        result = await self.environment.exec(cmd)
        if self._is_shell_escape_error(result):
            # Auto-retry with base64 encoding
            fixed_cmd = self._base64_wrap(cmd)
            result = await self.environment.exec(fixed_cmd)
    ...

def _is_shell_escape_error(self, result):
    stderr = (result.stderr or "").lower()
    return any(x in stderr for x in [
        "no closing quote", "syntax error", "unexpected '('"
    ])
```

#### Risk

- Medium — auto-fixing might mask real errors
- Should log when auto-recovery triggers for debugging

---

### 2.5 Increase max_turns to 40

**Impact**: Small improvement for complex multi-step tasks
**Effort**: Trivial (CLI flag)

Some tasks (cross-app pipelines, multi-recipe operations) exhaust the 30-turn budget while still making progress. Bumping to 40 gives the agent more room to recover from errors.

---

### 2.6 Few-Shot Examples in Prompt

**Impact**: Medium — teaches correct patterns by example
**Effort**: Medium (prompt engineering)

#### Problem

The agent improvises command syntax each time. Even with base64 guidance in the prompt, it often ignores it and tries echo-pipe first.

#### Solution

Add 1-2 condensed successful trajectories to the prompt showing the exact pattern for:
1. A DB delete operation (e.g., delete a record by name using base64)
2. A file creation with special characters

#### Risk

- Increases prompt length (~20-30 lines)
- May cause the model to over-fit to the example patterns
- Need to ensure examples are app-agnostic (no leakage)

#### Example (app-agnostic)

```
### Worked Example: Delete a record by name

Turn 1 — explore:
  adb shell pm list packages | grep -i myapp
  adb shell "echo '.tables' | sqlite3 /data/data/com.example.myapp/databases/app.db"
  adb shell "echo '.schema items' | sqlite3 /data/data/com.example.myapp/databases/app.db"

Turn 2 — inspect:
  adb shell "echo 'SELECT id,name FROM items;' | sqlite3 /data/data/com.example.myapp/databases/app.db"

Turn 3 — delete (use base64 because SQL has quotes):
  echo -n "DELETE FROM items WHERE name='Target Item';" | base64
  echo "REVMRVRFIEZST00gaXRlbXMgV0hFUkUgbmFtZT0nVGFyZ2V0IEl0ZW0nOw==" | base64 -d | adb shell sqlite3 /data/data/com.example.myapp/databases/app.db

Turn 4 — verify + finish:
  adb shell "echo 'SELECT count(*) FROM items;' | sqlite3 /data/data/com.example.myapp/databases/app.db"
  python android_env.py finish --status complete --description "Deleted Target Item"
```

---

### 2.7 Command Pre-Processing in agent.py

**Impact**: Small-medium — catches and fixes common mistakes
**Effort**: Medium (~40 lines)

#### Problem

The agent often generates the broken pattern `adb shell sqlite3 <db> "SQL"` despite the prompt saying "NEVER". It also sometimes forgets to wrap the CLI command with `python android_env.py adb "..."`.

#### Solution

In `agent.py`, before executing each command, apply pattern-based fixes:

```python
def _preprocess_command(self, cmd: str) -> str:
    # Fix: adb shell sqlite3 <db> "SQL" → echo-pipe version
    match = re.match(r'adb shell sqlite3 (\S+) "(.*)"', cmd)
    if match:
        db, sql = match.groups()
        encoded = base64.b64encode(sql.encode()).decode()
        return f'echo "{encoded}" | base64 -d | adb shell sqlite3 {db}'
    return cmd
```

#### Risk

- Low — only fixes known-broken patterns
- Should log rewrites for debugging

---

## 3. Implementation Plan

### Phase 1: Quick Wins (1-2 hours)

1. **Temperature test** — run eval at temp=0.3 (no code changes)
2. **max_turns=40** — run eval with more turns (no code changes)

### Phase 2: sql Helper (2-3 hours)

1. Add `sql` subcommand to `android_env.py`
2. Update prompt to use `sql` command
3. Run eval on diagnostic subset
4. If improved, run full 87-task eval

### Phase 3: write-file Helper (1 hour)

1. Add `write-file` subcommand
2. Update prompt
3. Eval

### Phase 4: Agent Loop Improvements (2-3 hours)

1. Shell error auto-recovery
2. Command pre-processing
3. Eval

### Phase 5: Few-Shot Examples (1-2 hours)

1. Craft 2 app-agnostic worked examples
2. Add to prompt
3. Eval

---

## 4. Expected Impact

| Change | Est. Tasks Fixed | New Total SR |
|--------|-----------------|--------------|
| Current best (R6 prompt) | — | 58/87 (67%) |
| + sql helper | +10-15 | 68-73/87 (78-84%) |
| + write-file helper | +3-5 | 71-78/87 (82-90%) |
| + temperature 0.3 | +2-4 | 73-82/87 (84-94%) |
| + auto-recovery | +1-3 | 74-85/87 (85-98%) |
| + few-shot examples | +1-2 | 75-87/87 (86-100%) |
| **Theoretical ceiling** | | **84/87 (96.6%)** |

The theoretical ceiling is 84/87 because 3 tasks (9, 67, 68) require GUI interaction (contact creation, SMS via Simple SMS Messenger).

## 5. Decision Log

| Question | Decision |
|----------|----------|
| Implement sql helper in android_env.py or separate file? | In android_env.py — keeps single entry point |
| Should sql helper also handle .tables/.schema? | Yes — unified interface, agent doesn't need to pick patterns |
| Should auto-recovery be opt-in or default? | Default with logging — transparent to the agent |
| Temperature: test 0.3 or 0.5? | Test both, compare on diagnostic subset |
| Few-shot examples: how many? | 2 max — one DB op, one file op. Keep prompt under 200 lines total |
