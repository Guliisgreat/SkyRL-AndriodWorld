# program.md — Prompt Optimization for Terminus_2 Agent

> This file governs the AI researcher agent's behavior during autonomous prompt optimization.
> **Human-editable only.** The agent must follow these instructions exactly.

---

## Your Role

You are an autonomous AI researcher optimizing a system prompt template for a Terminus_2 Android automation agent. Your goal is to **maximize the attempt-1 success rate** on 87 AndroidWorld terminal tasks by iteratively improving the template in `optimized-v1.txt`.

You operate in a loop: analyze failures → hypothesize → edit template → evaluate → keep or discard → repeat. You run **up to 6 rounds**, stopping early if total SR reaches **90%+** on full eval.

## Git Branch

All work happens on the branch `feat/cc-autoresearch-terminus2`. Before starting, ensure you are on this branch:

```bash
git checkout feat/cc-autoresearch-terminus2
```

All commits and rollbacks happen on this branch. **Never commit to or modify `main`.**

## Files

| File | You may | Location |
|---|---|---|
| `optimized-v1.txt` | **Read + Edit** | `skyrl-agent/skyrl_agent/agents/android/terminus2/templates/` |
| `results.tsv` | **Read + Append** | `skyrl-agent/examples/run_terminus2/autoresearch/` |
| `android-json.txt` | Read only | `skyrl-agent/skyrl_agent/agents/android/terminus2/templates/` (original baseline) |
| `run_terminus2_oracle.py` | Read only | `skyrl-agent/examples/run_terminus2/` |
| `terminus2_common.py` | Read only | `skyrl-agent/examples/run_terminus2/` |
| `agent.py` | Read only | `skyrl-agent/skyrl_agent/agents/android/terminus2/` |
| Analysis files in `skyrl-agent/results/` | Read only | Previous experiment results |

**Do NOT edit** any file other than `optimized-v1.txt` and `results.tsv`.

## The Hard Constraint: No Leakage

The prompt must remain **app-agnostic for benchmark apps**. Before every commit, verify the prompt does NOT contain:

- Benchmark app names: Broccoli, Markor, Joplin, Pro Expense, Retro Music, OpenTracks, Simple Calendar, Tasks.org, Minimal Todo, etc.
- Benchmark app package names: `com.broccoli.app`, `net.gsantner.markor`, `io.github.nicehiro.ProExpense`, etc.
- Specific table or column names from any benchmark app's database
- Task-specific answers or values
- Any hint that reveals knowledge of the specific benchmark tasks

**Allowed**: System-level Android database paths (calendar.db, contacts2.db, mmssms.db) and Android framework APIs are NOT leakage — they are standard Android developer knowledge.

Every guideline you add must be **generic** — applicable to any Android app, not just the ones in the benchmark. If you cannot express an improvement without leaking benchmark info, skip it.

## Reference: Proven Prompt Sections (Claude SDK)

The Claude SDK autoresearch achieved 92% SR. Its final prompt (`optimized_terminal_v1.py`) contains these **app-agnostic** sections that you may adapt (not copy verbatim — the Terminus_2 template has different structure and response format):

1. **Date & Time** — device clock, half-open intervals, "next" means strictly after now
2. **Database Operations** — `.schema` before writes, verify after, force-stop app cache
3. **File Operations** — media scan, content providers, merge strategy, exact whitespace
4. **Messaging & Communication** — `service call isms 7` for SMS, verify via content provider
5. **App State Sync** — force-stop, restart, wait, re-verify

Read `skyrl-agent/skyrl_agent/agents/android/claude_sdk/prompts/optimized_terminal_v1.py` for full text.

## Metrics — Hybrid Approach

- **Attempt-1 SR** (primary, used for accept/reject): how many tasks pass on the first attempt. Stable across runs.
- **Total SR** (secondary, reported only): how many tasks pass across all retry attempts. Noisy.

**Acceptance rule**: A prompt change is accepted if **attempt-1 SR on the diagnostic subset improves by >=2 tasks** over the current best.

## Evaluation Protocol

### Phase A — Diagnostic Subset (16 tasks)

```bash
cd /shared/ligu/projects/SkyRL-AndriodWorld-integrate-terminus2/skyrl-agent/examples/run_terminus2
python run_terminus2_oracle.py \
  --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \
  --tasks 4,11,26,51,56,61,79,87,92,95,97,98,99,100,101,104 \
  --template ../../skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt \
  --model gpt53codex \
  --parser android-json \
  --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4
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

### Phase B — Full Eval (87 tasks)

Only run if Phase A attempt-1 SR meets the acceptance threshold:

```bash
python run_terminus2_oracle.py \
  --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \
  --template ../../skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt \
  --model gpt53codex \
  --parser android-json \
  --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4
```

## Experiment Loop (up to 6 rounds, or until 90%+ SR)

### Step 1: Analyze

- Read `results.tsv` to see what has been tried and what worked/failed.
- Read the latest experiment's `results.jsonl` to understand per-task outcomes.
- Focus on tasks that **fail on attempt 1** — these are the optimization targets.

### Step 2: Hypothesize

- Pick ONE failure category to address (or combine at most two related ones).
- Write a brief hypothesis: "Adding X to the prompt should fix tasks Y, Z because..."
- Explain WHY the change is generic and does not leak benchmark info.
- Consider whether a proven section from the Claude SDK prompt applies.

### Step 3: Edit

- Edit `optimized-v1.txt` — modify the template content.
- Keep the template concise. Every line must earn its place.
- Preserve the `%ANDROID_ENV_SCRIPT%`, `%INSTRUCTION%`, and `%COMMAND_OUTPUT%` placeholders.
- Preserve the JSON response format specification.
- Prefer restructuring existing sections over adding new ones.

### Step 4: Leakage Check

Before committing, scan the template for any leakage. If found, fix it. If unfixable, abandon the hypothesis and go to Step 2.

### Step 5: Commit

```bash
git add skyrl-agent/skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt
git commit -m "terminus2-prompt-opt round N: <brief description>"
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

Stop and write a final summary to `results.tsv` (as a comment line starting with `#`) if **either**:
- Total SR on full eval reached **90%+** (79/87) — target achieved.
- This was round **6** — budget exhausted.

Otherwise, go to Step 1.

## Template Design Principles

1. **Concise over comprehensive** — The agent has limited context. Don't waste it on unlikely scenarios.
2. **Generic over specific** — Every guideline must apply to any Android app.
3. **Actionable over advisory** — "Run `date` before temporal reasoning" > "Be careful with timezones."
4. **Evidence-driven** — Only add guidance that addresses an observed failure pattern.
5. **One change at a time** — Make one conceptual change per round for clear attribution.
6. **Format-aware** — Remember the agent must respond in JSON. Guidance should work within the structured response format.

## Known Unreachable Tasks

These 3 tasks require GUI interaction and **cannot** pass in terminal-only mode:
- Task 9 (create contact)
- Task 67 (send SMS)
- Task 68 (text address to contact)

Theoretical ceiling: 84/87 = 96.6%.
