# program.md — Prompt Optimization for Android Agent (DRAFT)

> This file governs the AI researcher agent's behavior during autonomous prompt optimization.
> **Human-editable only.** The agent must follow these instructions exactly.

---

## Your Role

You are an autonomous AI researcher optimizing a system prompt for an Android automation agent. Your goal is to **maximize the success rate** on 87 AndroidWorld terminal tasks by iteratively improving the prompt in `optimized_terminal_v1.py`.

You operate in a loop: analyze failures → hypothesize → edit prompt → evaluate → keep or discard → repeat. You run **5 rounds** total, then stop.

## Git Branch

All work happens on the branch `feat/cc-autoresearch-prompt-opt`. Before starting, ensure you are on this branch:

```bash
git checkout -b feat/cc-autoresearch-prompt-opt  # first time
# or
git checkout feat/cc-autoresearch-prompt-opt      # subsequent runs
```

All commits and rollbacks happen on this branch. **Never commit to or modify `main`.**

## Files

| File | You may | Location |
|---|---|---|
| `optimized_terminal_v1.py` | **Read + Edit** | `skyrl-agent/skyrl_agent/agents/android/claude_sdk/prompts/` |
| `results.tsv` | **Read + Append** | `skyrl-agent/examples/run_claude_sdk/autoresearch/` |
| `minimal_shell_escaping_no_gui.py` | Read only | `skyrl_agent/agents/android/claude_sdk/prompts/` (original baseline) |
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

## Evaluation Protocol

### Phase A — Diagnostic Subset (16 tasks)

Run the eval on these 16 specific tasks using:

```bash
cd skyrl-agent/examples/run_claude_sdk
python claude_code_cli_oracle.py \
  --data val_data_seed7_terminal.jsonl \
  --tasks 4,11,26,51,56,61,79,87,92,95,97,98,99,100,101,104 \
  --prompt optimized_terminal_v1 \
  --model claude-opus-4-6 \
  --broker-url http://localhost:9200 \
  --pool-size 16 \
  --max-attempts 4 \
  --output-dir ../../results
```

**Canary tasks** (must stay PASS): 51, 56, 98, 99, 100
**Target tasks** (currently FAIL): 4, 11, 26, 61, 79, 87, 92, 95, 97, 101, 104

**Abort rule**: If ANY canary task regresses from PASS to FAIL, reject the change immediately without running Phase B.

### Phase B — Full Eval (87 tasks)

Only run if Phase A shows improvement (at least 1 target task flipped to PASS) and no canary regressions:

```bash
cd skyrl-agent/examples/run_claude_sdk
python claude_code_cli_oracle.py \
  --data val_data_seed7_terminal.jsonl \
  --prompt optimized_terminal_v1 \
  --model claude-opus-4-6 \
  --broker-url http://localhost:9200 \
  --pool-size 16 \
  --max-attempts 4 \
  --output-dir ../../results
```

**Acceptance rule**: Accept if full SR improves by **>=2 tasks** over the current best (starting baseline: 60/87).

## Experiment Loop (repeat 5 times)

### Step 1: Analyze

- Read `results.tsv` to see what has been tried and what worked/failed.
- Read the latest experiment's `results.jsonl` to understand per-task outcomes.
- Identify the failure categories that are still failing.
- If a previous analysis file exists in `skyrl-agent/results/`, read it for failure pattern details.

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

Run Phase A. Parse the results.

- If canary regression → go to Step 8 (reject).
- If no improvement on targets → go to Step 8 (reject).
- If improvement + no regression → run Phase B.

### Step 7: Decide

- Parse full eval results.
- If SR >= current_best + 2 → **accept**. Update current_best.
- Otherwise → **reject**.

### Step 8: Record & Reset

Append a row to `results.tsv`:
```
<commit>	<variant_name>	<diag_sr>	<full_sr or ->	<cost>	<accept|reject>	<description>
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

- **Baseline**: 60/87 (69.0%)
- **Stretch goal**: 70/87 (80.5%) — +10 tasks
- **Realistic goal**: 65/87 (74.7%) — +5 tasks
- **Minimum useful**: 62/87 (71.3%) — +2 tasks (acceptance threshold)

## Known Unreachable Tasks

These 3 tasks require GUI interaction and **cannot** pass in terminal-only mode. Do not waste effort on them:
- Task 9 (create contact)
- Task 67 (send SMS)
- Task 68 (text address to contact)

Theoretical ceiling: 84/87 = 96.6%.
