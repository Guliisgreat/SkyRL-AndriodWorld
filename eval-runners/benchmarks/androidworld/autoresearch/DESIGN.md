# Autoresearch-Style Prompt Optimization for Android Agent

**Status**: Approved — decisions finalized
**Date**: 2026-03-17
**Author**: Claude Code

---

## 1. Context & Goal

We want to maximize the **oracle upper-bound success rate** of the Claude Code CLI agent on AndroidWorld terminal tasks. The current best result is **69.0% (60/87)** using the `minimal_shell_escaping_no_gui` prompt with oracle feedback (Mode 2, max 4 attempts).

The lever we're optimizing is the **system prompt** — the only thing the AI agent (acting as researcher) is allowed to modify. The constraint is that the prompt must remain **app-agnostic**: no app names, DB schemas, or task-specific hints that would constitute benchmark leakage.

## 2. Analogy: Autoresearch → Prompt Optimization

| Autoresearch (Karpathy) | Our Setup |
|---|---|
| `train.py` — model architecture & hyperparams | `minimal_shell_escaping_no_gui.py` — system prompt |
| `prepare.py` — fixed data/eval infrastructure | `claude_code_cli_oracle.py` + `claude_cli_common.py` — fixed eval runner |
| `program.md` — instructions for the AI researcher | `program.md` (new) — instructions for the prompt optimizer agent |
| `val_bpb` — evaluation metric (lower is better) | **success rate** — % of 87 tasks passing (higher is better) |
| `results.tsv` — experiment log | `results.tsv` (new) — prompt variant log with SR, cost, delta |
| `train.py` modification → 5-min train → check bpb | prompt edit → run eval subset → check SR |
| git commit + rollback on failure | git commit + rollback on failure |
| VRAM constraint (soft) | **No app-specific leakage** constraint (hard) |

### Key Differences

1. **Cost per experiment**: Autoresearch runs a 5-min GPU training. Our eval runs 87 tasks at ~$70/run (full) or ~$8-15/run on a diagnostic subset. We need a cheaper inner loop.
2. **Metric noise**: BPB is deterministic given the same code. Our SR has stochastic variance (agent behavior varies across runs). We need repeated runs or statistical tests.
3. **Search space**: Autoresearch modifies Python code (architecture, math). We modify natural language (prompt phrasing, structure, heuristics). The search space is less structured.
4. **Hard constraint**: No app-specific info allowed in the prompt. Autoresearch has no equivalent hard constraint beyond "it must run."

## 3. Current Failure Analysis (27 failing tasks)

From the Mode 2 analysis (`ClaudeCodeCLI_claudeopus46_260312_0144`):

| Failure Category | Tasks | Count | Prompt-Addressable? |
|---|---|---|---|
| **Temporal reasoning** (wrong date/time logic) | 92,95,97,101-105,107 | 9 | Yes — add temporal reasoning guidelines |
| **Complex file ops** (multi-step exact-match) | 79,86,87 | 3 | Yes — add precision/verification strategies |
| **DB schema mismatch** (wrong columns/values) | 11,21 | 2 | Partially — add generic DB discovery heuristics |
| **Brightness min** (`settings put` not accepted) | 26,44 | 2 | Partially — add alternative approach hints |
| **App-specific DB ops** (Broccoli delete logic) | 4,14 | 2 | Partially — add generic dedup strategies |
| **Requires GUI** (SMS, contacts) | 9,67,68 | 3 | No — hard constraint of no-GUI mode |
| **Playlist DB** (Retro Music internals) | 58 | 1 | Unlikely without app-specific hints |
| **Markor edge cases** (create folder, edit, delete) | 13,22,24 | 3 | Partially — better file-op verification |
| **Calendar deletion** (event matching) | 61 | 1 | Partially — temporal + verification |
| **Oct 20 query** (specific date parsing) | 94 | 1 | Yes — temporal reasoning |

**Prompt-addressable tasks**: ~15-20 of the 27 failures could potentially be fixed via better prompt guidance, giving a theoretical ceiling of ~85-92% SR.

**Hard floor** (GUI-required): 3 tasks (9, 67, 68) cannot pass without GUI — sets a ceiling of 84/87 = **96.6%** for terminal-only mode.

## 4. Proposed System

### 4.1 File Roles

| File | Who Edits | Role |
|---|---|---|
| `optimized_terminal_v*.py` (new) | AI researcher agent | The system prompt — our search variable |
| `minimal_shell_escaping_no_gui.py` | Nobody | Original baseline prompt (preserved) |
| `claude_code_cli_oracle.py` + `claude_cli_common.py` | Nobody | Fixed eval infrastructure |
| `program.md` (new) | Human | Instructions governing the AI researcher's behavior |
| `results.tsv` (new) | AI researcher agent | Experiment log (append-only) |
| `val_data_seed7_terminal.jsonl` | Nobody | Fixed eval dataset (87 tasks) |

> **Decision**: We create a new prompt file `optimized_terminal_v1.py` (copying from `minimal_shell_escaping_no_gui.py`) so the original baseline is preserved untouched. The researcher agent edits only the new file.

### 4.2 The Experiment Loop

```
┌─────────────────────────────────────────────────┐
│  AI Researcher Agent (Claude Code)              │
│                                                 │
│  1. Read results.tsv — what's been tried        │
│  2. Read failure analysis from last run         │
│  3. Hypothesize a prompt change                 │
│  4. Edit optimized_terminal_v1.py                │
│  5. Leakage check — no app names/DB paths       │
│  6. Git commit the change                       │
│  7. Run Phase A — 16-task diagnostic subset     │
│  8. If canary regressions → reject, git reset   │
│  9. If improvement → run Phase B (full 87)      │
│  10. Accept if full SR >= best + 2 tasks        │
│      Reject otherwise → git reset               │
│  11. Log result to results.tsv                  │
│  12. Analyze new failures → loop to step 1      │
└─────────────────────────────────────────────────┘
```

### 4.3 Two-Phase Evaluation (Cost Control)

Since full eval costs ~$70, we use a two-phase approach:

**Phase A — Diagnostic subset (16 tasks, ~$14)**
A mix of 5 passing tasks (regression canaries) and 11 failing tasks (improvement targets). If regressions appear on the passing tasks, abort early.

**Diagnostic subset (16 tasks):**

| Task | Baseline | Category | Role |
|---|---|---|---|
| 51 | PASS (attempt 2) | Markor note update | Canary — fragile pass |
| 56 | PASS (attempt 3) | Broccoli recipe add | Canary — fragile pass |
| 98 | PASS (attempt 3) | Calendar query | Canary — fragile pass |
| 99 | PASS (attempt 3) | Calendar query | Canary — fragile pass |
| 100 | PASS (attempt 4) | Tasks query | Canary — fragile pass |
| 92 | FAIL | Temporal — next upcoming event | Target |
| 95 | FAIL | Temporal — next meeting | Target |
| 97 | FAIL | Temporal — next week events | Target |
| 101 | FAIL | Temporal — high priority tasks | Target |
| 104 | FAIL | Temporal — completed tasks for date | Target |
| 79 | FAIL | Complex file — create note with text | Target |
| 87 | FAIL | Complex file — merge notes | Target |
| 11 | FAIL | DB schema — delete expense | Target |
| 4 | FAIL | Broccoli delete logic | Target |
| 26 | FAIL | Brightness min | Target |
| 61 | FAIL | Calendar deletion | Target |

**Phase B — Full eval (87 tasks, ~$70)**
Only triggered if Phase A shows improvement and no regressions on canary tasks. This is the authoritative metric.

### 4.4 results.tsv Schema

```
commit	prompt_variant	sr_diag	sr_full	cost_usd	status	description
abc1234	baseline_v0	-	60/87	71.47	baseline	Original minimal_shell_escaping_no_gui
def5678	temporal_v1	12/15	-	12.30	reject	Added temporal reasoning section, regressed on task 52
ghi9012	temporal_v2	14/15	63/87	82.10	accept	Refined temporal guidance, +3 full tasks
```

Columns:
- `commit` — git short hash
- `prompt_variant` — human-readable name for the change
- `sr_diag` — success rate on diagnostic subset (Phase A)
- `sr_full` — success rate on full 87 tasks (Phase B), `-` if not run
- `cost_usd` — total eval cost
- `status` — `baseline`, `accept`, `reject`, `crash`
- `description` — what was changed and why

### 4.5 Leakage Guard

Every prompt edit must pass this check before committing:

> The prompt must not contain any of: app names (Broccoli, Markor, Joplin, Pro Expense, Retro Music, OpenTracks, Simple Calendar, etc.), database paths, package names (`com.xxx`), specific column names, or task-specific answers.

The `program.md` will instruct the researcher agent to self-check this constraint and explain why each change is generic.

## 5. Hypothesized Prompt Improvements (Ordered by Expected Impact)

Based on failure analysis, these are the prompt modifications to try — each is app-agnostic:

### H1: Temporal Reasoning Guidelines (targets 9+ tasks)
Add a section on date/time handling:
- Always query the device's current date/time/timezone before temporal reasoning
- "Next week" = Monday through Sunday of the following week
- "Due Friday" = the nearest upcoming Friday
- When querying by date range, use `>=` and `<` rather than `BETWEEN` to avoid off-by-one

### H2: Database Discovery Protocol (targets 5+ tasks)
Add generic DB interaction heuristics:
- Always `.schema` before any write/delete operation
- Check column types and constraints before inserting
- Verify row counts before and after mutations
- For delete operations: SELECT first, confirm match count, then DELETE

### H3: Exact-Match Verification (targets 3+ tasks)
Strengthen the "verify after acting" principle:
- After writes, re-read the data and diff against the expected state
- For info-retrieval, double-check the answer format matches what was asked
- For file operations, `cat` the file after writing to confirm content

### H4: Alternative Approach Escalation (targets 2+ tasks)
Add a meta-strategy:
- If `settings put` commands don't produce the expected result, try alternative system APIs
- If direct DB manipulation fails, check if the app has a CLI or intent-based interface
- Try `am start`, `am broadcast`, or `content://` providers as alternatives

### H5: Multi-Step Planning (targets 3+ tasks)
For complex tasks requiring multiple coordinated operations:
- Break the task into numbered sub-steps before executing
- Verify each sub-step succeeded before proceeding
- If any sub-step fails, re-evaluate the entire plan

## 6. Implementation Plan

### Phase 0: Setup (human + agent)
- [ ] Create git branch `feat/cc-autoresearch-prompt-opt` from `main`
- [ ] Create `program.md` in the autoresearch directory with researcher instructions
- [ ] Create `optimized_terminal_v1.py` as a copy of `minimal_shell_escaping_no_gui.py`
- [ ] Initialize `results.tsv` with header row
- [ ] Run baseline eval on the 16-task diagnostic subset to establish current numbers

> All commits and rollbacks happen on `feat/cc-autoresearch-prompt-opt`. The `main` branch is never modified.

### Phase 1–5: Five Rounds of Autonomous Optimization
The AI researcher agent runs **5 rounds**, each round being one full cycle:
1. Analyze failures from the previous round
2. Hypothesize and implement a prompt change in `optimized_terminal_v1.py`
3. Git commit the change
4. Run Phase A (16-task diagnostic) — abort if canary regressions
5. If Phase A improves: run Phase B (full 87-task eval)
6. Accept (keep commit) if full SR improves by **>=2 tasks** over current best
7. Reject (git reset) otherwise
8. Log result to `results.tsv`

**Budget**: 5 rounds × (Phase A ~$14 + Phase B ~$70) = ~$420 max. Phase B is skipped on diagnostic regressions, so actual cost will be lower.

**Model**: claude-opus-4-6 only — optimizing for maximum SR on a single model.

**Automation**: Fully autonomous. The researcher agent runs the entire loop without human intervention, following `program.md`.

### Phase 6: Final Report
- [ ] Document all experiments and outcomes
- [ ] Report final SR vs baseline (69.0%)
- [ ] Analyze which failure categories were resolved

## 7. Decisions (Resolved)

| Question | Decision |
|---|---|
| Diagnostic subset | 16 tasks: 5 canary passes (30%) + 11 failure targets (70%) |
| Acceptance threshold | >=2 task improvement on full eval to accept |
| Budget | 5 rounds of iteration |
| Model | claude-opus-4-6 only |
| Automation | Fully autonomous (like autoresearch) |
| Prompt file | New file `optimized_terminal_v1.py`, original preserved |
