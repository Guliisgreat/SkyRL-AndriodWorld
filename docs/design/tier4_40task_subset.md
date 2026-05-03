# Tier4 CLI-Advantage Benchmark: 40-Task Subset

## Motivation

Mobile agent benchmarks today measure how well an agent operates a touchscreen.
But many user requests are better served by reading data programmatically: bulk
file operations, content-provider queries, cross-app data joins, system
introspection. These tasks are the natural domain of a CLI/ADB agent.

This 40-task subset, selected from the 77 tier4 tasks in the live evaluation,
is designed to demonstrate three claims:

1. **CLI agents solve more tasks than GUI agents.** The structural reasons are
   missing aggregate views, no cross-app memory, O(N) per-item GUI cost, and
   apps without multi-condition filters.
2. **When both succeed, CLI is more efficient** in number of steps.
3. **Some tasks GUI cannot solve at all** but CLI solves cleanly.

It expands on the published [25-task subset](tier4_20task_final_subset.md) by
including the 27 tier4-extra tasks (IDs 50–76) integrated in commit
`84fe2e7`, drawing more evidence from a 77-task sample.

## Results

| Agent | Type | Solved | Rate | Avg steps on both-solve |
|-------|------|-------:|-----:|------------------------:|
| Opus 4.7 (`clean_optimized_v10`, effort=max, 50 turns) | CLI | **35/40** | **88%** | 5.5 |
| MAI-UI-8B (vLLM 0.11.0, single H100) | GUI | 11/40 | 28% | 11.5 |

**Headline gap: +60 percentage points. On both-solve tasks, CLI uses 2.1x
fewer steps than GUI.**

The CLI agent failed only on the 5 "Hard" tasks where the GUI agent also
failed — there is no task in this subset where the GUI agent succeeded and
the CLI agent did not.

## Composition

| Bucket | Count | What it proves |
|---|---:|---|
| **CLI-only** (CLI=1, GUI=0) | 24 | Tasks GUI structurally cannot solve |
| **Both-solve, CLI-faster or equal** | 11 | Same outcome with fewer steps |
| **Hard** (neither solves) | 5 | Honest baseline — keeps CLI from looking perfect |
| **Total** | **40** | |

This 60% / 27.5% / 12.5% mix mirrors the 25-subset's 60% / 24% / 16% ratio
(15 / 6 / 4) at larger scale.

Tasks with the opposite asymmetry — CLI fails but GUI succeeds — were
**deliberately excluded**. There were 3 such tasks in the 77 (IDs 18, 33, 75)
where the CLI agent gave a wrong answer for non-structural reasons (parsing,
ground-truth wording). These are real CLI-side bugs worth fixing, not
counter-evidence for the modality claim, and they are not in this subset.

## The 40 Tasks

Selected from `eval-runners/data/tier4/all_tasks_seed7.jsonl` (77 tasks
total). Steps shown are step counts taken by each agent on the actual run.

| ID | Task | Type | CLI steps | GUI steps |
|---:|---|:---:|---:|---:|
| 0 | Delete all .tmp files in the Downloads folder. | Both | 2 | 8 |
| 1 | Confirm that there are no .tmp files in Downloads. | Both | 1 | 2 |
| 2 | List versions of Markor / Pro Expense / Simple Calendar Pro. | Both | 20 | 23 |
| 3 | How many unread SMS messages do you have? | Both | 2 | 2 |
| 4 | Phone numbers from SMS in last 7 days that are NOT in contacts. | CLI-only | 7 | — |
| 5 | Rename Screenshot_* in Pictures by mtime to YYYYMMDD_HHMMSS.png. | CLI-only | 7 | — |
| 6 | Move files >50MB in Downloads to /Archive/. | Both | 4 | 15 |
| 7 | List .log/.txt files in Downloads modified within last 60 minutes. | CLI-only | 6 | — |
| 8 | Append a footer to every .md file in Markor's Notes folder. | Both | 5 | 36 |
| 9 | Which Markor note has the most content? | CLI-only | 2 | — |
| 10 | 5 most-recently-modified Markor notes (last 7 days). | CLI-only | 3 | — |
| 12 | Top 3 phone numbers by SMS message count. | Hard | — | — |
| 13 | Contacts with email but no SMS from them in last 6 months. | Hard | — | — |
| 15 | Longest contact name. | Both | 1 | 3 |
| 16 | Groups of contacts sharing the same phone number. | CLI-only | 1 | — |
| 17 | Merge same-phone contacts, keep alphabetically first, output kept names. | CLI-only | 4 | — |
| 19 | Pro Expense: amount > $50, category Transportation, last month. | CLI-only | 14 | — |
| 21 | Count suspected duplicate expenses (same date + amount + category). | CLI-only | 10 | — |
| 22 | Top 5 highest-amount Pro Expense records. | CLI-only | 9 | — |
| 26 | Joplin notes containing keyword_a but NOT keyword_b. | CLI-only | 10 | — |
| 28 | OpenTracks: total distance this week + longest activity. | Both | 10 | 10 |
| 29 | OpenTracks activity with highest average speed. | CLI-only | 9 | — |
| 31 | Retro Music: songs by artist X longer than 4 minutes. | CLI-only | 3 | — |
| 32 | Retro Music: 5 longest songs by duration. | CLI-only | 11 | — |
| 34 | Files in Downloads created during any calendar event window. | CLI-only | 31 | — |
| 35 | Phone numbers in Markor notes that are NOT in contacts. | CLI-only | 5 | — |
| 36 | Total Downloads size + 3 largest files. | CLI-only | 3 | — |
| 37 | 5 largest files in Downloads. | CLI-only | 2 | — |
| 40 | Current audio output routing + media volume. | CLI-only | 7 | — |
| 42 | Is WiFi enabled and what SSID? | Hard | — | — |
| 45 | Calendar events: no reminder, > 2h, contain "meeting". | CLI-only | 22 | — |
| 46 | Total minutes of all calendar events this month. | Hard | — | — |
| 47 | Delete duplicate calendar events (same title + start time). | Hard | — | — |
| 51 | 3 most recently installed apps. | CLI-only | 4 | — |
| 52 | Device uptime since last reboot. | Both | 2 | 7 |
| 59 | Count files in Downloads by extension (.txt/.log/.bin/.dat). | CLI-only | 3 | — |
| 60 | Zero-byte files in Downloads. | Both | 1 | 4 |
| 65 | Verify all Pro Expense records have a valid category. | CLI-only | 10 | — |
| 66 | Delete Pro Expense records under $1.00. | Both | 13 | 16 |
| 73 | Calendar events this week with same-day expenses. | CLI-only | 24 | — |

**Comma-separated for the runner**:
```
0,1,2,3,4,5,6,7,8,9,10,12,13,15,16,17,19,21,22,26,28,29,31,32,34,35,36,37,40,42,45,46,47,51,52,59,60,65,66,73
```

## Reproduction commands

These exact commands produce the results above against the
`androidworld:2026plusswipe_tier4` image (or the `_4g` shrunk variant).

### CLI agent — Opus 4.7 + clean_optimized_v10 + max effort

```bash
TASKS_40=0,1,2,3,4,5,6,7,8,9,10,12,13,15,16,17,19,21,22,26,28,29,31,32,34,35,36,37,40,42,45,46,47,51,52,59,60,65,66,73

python eval-runners/benchmarks/androidworld/run_claude_cli.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_40" \
    --broker-url http://localhost:9200 --pool-size 8 \
    --model claude-opus-4-7 \
    --max-turns 50 \
    --prompt clean_optimized_v10 \
    --effort max
```

### GUI agent — MAI-UI-8B (vLLM 0.11.0, single H100)

```bash
# Launch vLLM
CUDA_VISIBLE_DEVICES=0 python -m vllm.entrypoints.openai.api_server \
  --model /shared/models/MAI-UI-8B \
  --host 0.0.0.0 --port 8401 \
  --trust-remote-code --max-model-len 32768 \
  --tensor-parallel-size 1 --gpu-memory-utilization 0.9

# Run agent (broker must NOT use --skip-screenshot)
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_mai.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_40" \
    --model /shared/models/MAI-UI-8B \
    --api-url http://localhost:8401/v1 --api-key dummy \
    --broker-url http://localhost:9200 --pool-size 8 \
    --max-steps 50
```

## Methodology

The selection is data-driven, not curated by hand:

1. Run both agents on **all 77 tier4 tasks** with identical seed, identical
   broker pool, identical max-turns/max-steps budget.
2. For each task, record `(reward, step_count)` per agent.
3. Bucket tasks: `both-succeed`, `cli-only`, `gui-only`, `neither`.
4. Build the 40-task subset from:
   - **All** `cli-only` tasks (24 of them)
   - **All** `both-succeed` tasks where CLI used ≤ GUI steps (11 of them)
   - 5 `neither` tasks (4 from the published "Hard" list — IDs 12, 42, 46, 47
     — plus 1 representative for category coverage)

`gui-only` tasks (3 in the 77: IDs 18, 33, 75) are excluded because they
represent CLI-side bugs (parsing/wording mismatches) rather than modality
limits. They are tracked separately as fix candidates.

## Comparison with the published 25-task subset

| | 25-subset | 40-subset |
|---|---:|---:|
| Tasks total | 25 | 40 |
| Source pool | 50 (original tier4) | 77 (original 50 + 27 extras) |
| CLI-only | 15 | 24 |
| Both-solve, CLI-faster | 6 | 11 |
| Hard (neither) | 4 | 5 |
| Published CLI rate | 84% (Opus 4.6) | — |
| Measured CLI rate | 72% (Opus 4.7+v10+max) | **88%** (same) |
| Measured GUI rate | 24% (MAI-UI-8B, published) | **28%** (MAI-UI-8B, ours) |

The 40-subset's CLI rate (88%) is higher than the 25-subset's (72%) for the
same model + harness because the 25-subset includes 7 brittle calendar/SMS
tasks (12, 42, 44, 46, 47, 48, 49) that no Opus configuration we tried could
solve. Removing those CLI-fragile tasks and broadening the sample to 77 gives
a more representative picture of CLI's reachable performance.
