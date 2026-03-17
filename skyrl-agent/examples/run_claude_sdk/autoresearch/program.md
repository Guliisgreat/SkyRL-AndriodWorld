# program.md — Prompt Optimization for Android Agent

> This file governs the AI researcher agent's behavior during autonomous prompt optimization.
> **Human-editable only.** The agent must follow these instructions exactly.

---

## Your Role

You are an autonomous AI researcher optimizing a system prompt for an Android automation agent. Your goal is to **maximize the attempt-1 success rate** on 87 AndroidWorld terminal tasks by iteratively improving the prompt in `optimized_terminal_v1.py`.

You operate in a loop: analyze failures → hypothesize → edit prompt → evaluate → keep or discard → repeat. You run **5 rounds** total, then stop.

## Git Branch

All work happens on the branch `feat/cc-autoresearch-prompt-opt`. Before starting, ensure you are on this branch:

```bash
git checkout feat/cc-autoresearch-prompt-opt
```

All commits and rollbacks happen on this branch. **Never commit to or modify `main`.**

## Files

| File | You may | Location |
|---|---|---|
| `optimized_terminal_v1.py` | **Read + Edit** | `skyrl-agent/skyrl_agent/agents/android/claude_sdk/prompts/` |
| `results.tsv` | **Read + Append** | `skyrl-agent/examples/run_claude_sdk/autoresearch/` |
| `minimal_shell_escaping_no_gui.py` | Read only | `skyrl-agent/skyrl_agent/agents/android/claude_sdk/prompts/` (original baseline) |
| `claude_code_cli_oracle.py` | Read only | `skyrl-agent/examples/run_claude_sdk/` |
| `claude_cli_common.py` | Read only | `skyrl-agent/examples/run_claude_sdk/` |
| Analysis files in `skyrl-agent/results/` | Read only | Previous experiment results and failure analyses |

**Do NOT edit** any file other than `optimized_terminal_v1.py` and `results.tsv`.

## The Hard Constraint: No Leakage

The prompt must remain **completely app-agnostic**. Before every commit, verify the prompt does NOT contain:

- App names: Broccoli, Markor, Joplin, Pro Expense, Retro Music, OpenTracks, Simple Calendar, Tasks.org, or any other app name from the benchmark
- Package names: `com.xxx.yyy`
- Database paths: `/data/data/...`
- Specific table or column names from any app
- Task-specific answers or values
- Any hint that reveals knowledge of the specific benchmark tasks

Every guideline you add must be **generic** — applicable to any Android app, not just the ones in the benchmark. If you cannot express an improvement without leaking benchmark info, skip it.

## Metrics — Hybrid Approach

Agent behavior is stochastic: tasks that need multiple retry attempts to pass are noisy and flip randomly between runs. To get a reliable signal, we track **two metrics** but only gate on the stable one:

- **Attempt-1 SR** (primary, used for accept/reject): how many tasks pass on the first attempt. This is stable across runs and reflects genuine prompt quality.
- **Total SR** (secondary, reported only): how many tasks pass across all retry attempts. Reported for context but NOT used for gating decisions.

**Acceptance rule**: A prompt change is accepted if **attempt-1 SR on the diagnostic subset improves by >=2 tasks** over the current best.

## Evaluation Protocol

### Phase A — Diagnostic Subset (16 tasks)

Run the eval on these 16 specific tasks:

```bash
cd /shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent/examples/run_claude_sdk
python claude_code_cli_oracle.py \
  --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \
  --tasks 4,11,26,51,56,61,79,87,92,95,97,98,99,100,101,104 \
  --prompt optimized_terminal_v1 \
  --model claude-opus-4-6 \
  --broker-url http://localhost:9200 \
  --pool-size 16 \
  --max-attempts 4
```

### Parsing Results

After the eval completes, parse the results JSONL to extract attempt-1 SR:

```python
import json
with open("<results_dir>/results.jsonl") as f:
    results = [json.loads(l) for l in f if l.strip()]
for r in results:
    all_att = r.get("all_attempts", [])
    att1_reward = all_att[0]["reward"] if all_att else r.get("reward", 0)
    # att1_reward > 0 means attempt-1 pass
```

**Baseline attempt-1 SR on diagnostic subset: 4/16** (tasks 51, 98, 100, 104)

**Accept rule**: attempt-1 SR >= 6/16 (baseline 4 + 2).

### Phase B — Full Eval (87 tasks)

Only run if Phase A attempt-1 SR meets the acceptance threshold:

```bash
cd /shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent/examples/run_claude_sdk
python claude_code_cli_oracle.py \
  --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \
  --prompt optimized_terminal_v1 \
  --model claude-opus-4-6 \
  --broker-url http://localhost:9200 \
  --pool-size 16 \
  --max-attempts 4
```

## Experiment Loop (repeat 5 times)

### Step 1: Analyze

- Read `results.tsv` to see what has been tried and what worked/failed.
- Read the latest experiment's `results.jsonl` to understand per-task outcomes.
- Focus on tasks that **fail on attempt 1** — these are the optimization targets.
- Read failure analysis files in `skyrl-agent/results/` for pattern details.

### Step 2: Hypothesize

- Pick ONE failure category to address (or combine at most two related ones).
- Write a brief hypothesis: "Adding X to the prompt should fix tasks Y, Z because..."
- Explain WHY the change is generic and does not leak benchmark info.

### Step 3: Edit

- Edit `optimized_terminal_v1.py` — modify the `build_system_prompt()` function.
- Keep the prompt concise. Every line must earn its place. Remove guidance that doesn't help.
- Prefer restructuring existing sections over adding new ones.

### Step 4: Leakage Check

Before committing, scan the prompt for any leakage. If found, fix it. If unfixable, abandon the hypothesis and go to Step 2 with a different idea.

### Step 5: Commit

```bash
git add skyrl-agent/skyrl_agent/agents/android/claude_sdk/prompts/optimized_terminal_v1.py
git commit -m "prompt-opt round N: <brief description>"
```

### Step 6: Evaluate

Run Phase A. Parse attempt-1 results.

- If attempt-1 SR < baseline + 2 → go to Step 8 (reject).
- If attempt-1 SR >= baseline + 2 → run Phase B.

### Step 7: Decide

- Parse full eval attempt-1 results.
- Record both attempt-1 SR and total SR.
- If attempt-1 SR improved → **accept**. Update current_best.
- Otherwise → **reject**.

### Step 8: Record & Reset

Append a row to `results.tsv`:
```
<commit>	<variant_name>	<att1_sr_diag>	<total_sr_diag>	<att1_sr_full or ->	<total_sr_full or ->	<cost>	<accept|reject>	<description>
```

If rejected: `git reset --hard <last accepted commit>`

### Step 9: Loop or Stop

If this was round 5, stop and write a final summary to `results.tsv` as a comment line starting with `#`.

Otherwise, go to Step 1.

## Prompt Design Principles

1. **Concise over comprehensive** — A short, precise prompt beats a long, vague one. The agent has limited context; don't waste it on unlikely scenarios.
2. **Generic over specific** — Every guideline must apply to any Android app. "Always check the database schema before writing" is good. "Broccoli stores recipes in a SQLite table" is leakage.
3. **Actionable over advisory** — "Run `date +%Z` to get timezone before any date computation" is better than "Be careful with timezones."
4. **Evidence-driven** — Only add guidance that addresses an observed failure pattern. Don't add speculative advice.
5. **One change at a time** — Make one conceptual change per round so you can attribute results. Don't change 5 things at once.

## What Success Looks Like

Diagnostic subset (16 tasks):
- **Baseline attempt-1 SR**: 4/16 (25.0%)
- **Stretch goal**: 10/16 (62.5%)
- **Realistic goal**: 7/16 (43.8%) — +3 tasks
- **Minimum useful**: 6/16 (37.5%) — +2 tasks (acceptance threshold)

## Known Unreachable Tasks

These 3 tasks require GUI interaction and **cannot** pass in terminal-only mode. Do not waste effort on them:
- Task 9 (create contact)
- Task 67 (send SMS)
- Task 68 (text address to contact)

Theoretical ceiling: 84/87 = 96.6%.

## Baseline Reference

Phase 0 baseline (diagnostic subset, `ClaudeCodeCLI_claudeopus46_260317_1729`):

| Task | Attempt-1 | Total | Category |
|---|---|---|---|
| 51 | PASS | PASS | Markor note update |
| 98 | PASS | PASS | Calendar query |
| 100 | PASS | PASS | Tasks query |
| 104 | PASS | PASS | Completed tasks query |
| 26 | fail | PASS (att 2) | Brightness min |
| 97 | fail | PASS (att 2) | Next week events |
| 4 | fail | FAIL | Broccoli delete |
| 11 | fail | FAIL | Pro Expense delete |
| 56 | fail | FAIL | Broccoli recipe add |
| 61 | fail | FAIL | Calendar deletion |
| 79 | fail | FAIL | Create note with text |
| 87 | fail | FAIL | Merge notes |
| 92 | fail | FAIL | Next upcoming event |
| 95 | fail | FAIL | Next meeting query |
| 99 | fail | FAIL | Events between times |
| 101 | fail | FAIL | High priority tasks |
