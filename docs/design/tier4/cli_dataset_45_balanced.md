# 5-Category 45-Task Balanced Subset for the CLI-Advantage Benchmark

A realism-vetted, soft-balanced subset of tier4 tasks for evaluating CLI agents
against GUI agents on Android. This document records the selection process,
the category schema, the resulting per-category task lists, and the known
drawbacks of the current dataset.

The full 77-task source pool lives at
`eval-runners/data/tier4/all_tasks_seed7.jsonl` (built by integrating the
original 50 tier4 tasks with the 27 tier4-extra tasks per commit `84fe2e7`).

---

## 1. Goal

Construct a dataset that supports two specific claims for a CLI-vs-GUI
comparison paper:

1. **There exist tasks no GUI agent can solve but a CLI agent can.**
2. **On tasks both modalities can solve, CLI is more step-efficient.**

The dataset must be defensible against the standard reviewer objection that
benchmark tasks were cherry-picked to favor the proposed method. We achieve
this through:

- **Realism filter**: drop tasks no real Android user would phrase that way.
- **Category-first framing**: define user-need categories *before* selecting
  tasks within them, so the categorization is not a post-hoc justification.
- **Soft balance**: enforce 8–12 tasks per category so headline averages are
  not dominated by any single capability.

---

## 2. Selection process

### 2.1 Source pool: 77 tasks

The starting pool is all 77 tier4 tasks already implemented in
`docker/android/skyrl_server/tier4/`:

- 50 original tier4 tasks (commit `acc6548`)
- 27 tier4-extra tasks (integrated in commit `84fe2e7`)

### 2.2 Realism filter (drops 12 contrived tasks)

Each task was rated on a 3-level rubric — **highly realistic / stretched but
plausible / contrived**. Contrived tasks were dropped outright. A task is
"contrived" when it satisfies any of:

- No real Android user would phrase a request this way (e.g. "list `.log`
  files modified in the last 60 minutes" — that is a sysadmin filter).
- The criteria are obscure or designed-for-CLI (e.g. "average character
  length of all SMS messages").
- The task is a synthetic cross-app workflow that doesn't map to a real
  user goal (e.g. "find the longest activity in OpenTracks and create a
  task in the Tasks app with the activity name and distance").

The 12 dropped contrived task IDs:

```
7, 13, 15, 30, 34, 45, 55, 59, 61, 72, 73, 76
```

| ID | Task | Why contrived |
|---:|---|---|
| 7 | `.log/.txt` files modified in last 60 minutes | Sysadmin filter, not user need |
| 13 | Contacts with email but no SMS in 6 months | CRM-analyst flavor |
| 15 | Longest contact name | Pure trivia |
| 30 | Longest OpenTracks activity → create task | Bizarre cross-app dance |
| 34 | Files in Downloads created during calendar event windows | Random correlation |
| 45 | No-reminder + >2h + "meeting" 3-condition filter | Researcher-flavored |
| 55 | Average character length of all SMS messages | Trivia |
| 59 | Counts of `.txt/.log/.bin/.dat` extensions | Hardcoded niche extension list |
| 61 | Flatten subdirectories in Downloads | Unusual unix-folklore op |
| 72 | SMS received during active calendar events | Contrived correlation |
| 73 | Each calendar event ↔ same-day expenses | Same flavor |
| 76 | Joplin TODO notes → calendar event tomorrow at 9 AM | Highly specific workflow |

### 2.3 Category assignment

Each remaining task is assigned to exactly one of 5 categories defined in
section 3 below. Categories are user-need-grounded (what the user wants to
achieve), not agent-capability-grounded (what query language the agent uses).

This step yielded the following raw counts:

| Category | Raw count |
|---|---:|
| A. Compute across items | 27 |
| B. Bulk operations | 12 |
| C. Multi-condition filters | 8 |
| D. Cross-app correlation | 8 |
| E. Hidden device state | 10 |

### 2.4 Soft-balance pruning

Categories were trimmed to the 8–12 range:

- **A** (27 → 12): kept the most universal and least overlapping. Dropped 15
  tasks that overlap with kept ones (e.g. dropped `37` "5 largest files"
  because `36` already covers "total Downloads + top 3 largest"), are app-
  niche (Markor, Joplin, Retro Music), or are merely curiosity (`48`
  "earliest event by date").
- **B** (12 → 9): dropped 3 tasks with arbitrary specifics (`8` Markor footer
  append, `18` Food→Entertainment, `24` Low→Medium priority).
- **C** (8 → 8): kept all candidates (already at the floor).
- **D** (8 → 8): kept all candidates (already at the floor).
- **E** (10 → 8): dropped 2 sysadmin-flavored (`2` app versions, `52` uptime).

Result: 45 tasks, all in the 8–12 range.

---

## 3. The 5 categories

Each category has a one-sentence user intent and a one-line structural
explanation for why CLI dominates. Categories map to the 5 patterns
identified in the published [25-task subset doc](../docs/design/tier4_20task_final_subset.md).

### A. Compute across items (12 tasks)

> **User intent:** "Tell me a number, a ranking, or a yes/no, computed
> across many items."
>
> **Why CLI wins:** SQL `SUM/AVG/COUNT/ORDER BY ... LIMIT` and shell `wc/du`
> produce the answer directly. Apps display individual items, not aggregates.

Sub-patterns inside this category:

- **Single-number aggregate** (4): `3, 28, 46, 62` (wait — 62 is dropped; see final list)
- **Top-K ranking** (4): `12, 22, 36, 64`
- **Group-by aggregate** (2): `16, 20`
- **Coverage check** (2): `49, 65` plus `25` (3 actually)

Final list:

| ID | Task |
|---:|---|
| 3 | How many unread SMS messages do you have? |
| 12 | Top 3 phone numbers by SMS message count |
| 16 | Groups of contacts sharing the same phone number |
| 20 | Top 3 expense categories by total amount this month |
| 22 | Top 5 highest-amount expenses |
| 25 | Confirm all overdue tasks in Tasks app are completed |
| 28 | Total OpenTracks distance this week + longest activity |
| 36 | Total Downloads size + 3 largest files |
| 46 | Total minutes of all calendar events this month |
| 49 | Confirm all events this month have a reminder |
| 64 | 3 days this month with the highest spending |
| 65 | Verify all expenses have a valid category |

### B. Bulk operations (9 tasks)

> **User intent:** "Apply the same change (delete, rename, modify) to many
> items at once."
>
> **Why CLI wins:** a single `find ... -exec`, `for` loop, or SQL `UPDATE`
> handles all items with O(1) cognitive cost. GUI requires N tap sequences.

| ID | Task |
|---:|---|
| 0 | Delete all .tmp files in Downloads |
| 5 | Rename Screenshot_* by mtime to YYYYMMDD_HHMMSS.png |
| 6 | Move files >50MB in Downloads to Archive folder |
| 11 | Delete old SMS not in contacts containing keyword |
| 17 | Merge contacts sharing the same phone (alphabetical-first) |
| 43 | Delete calendar events whose title contains 'test' |
| 47 | Delete duplicate calendar events |
| 66 | Delete Pro Expense entries under $1.00 |
| 70 | Add a 15-minute reminder to events without one |

### C. Multi-condition filters (8 tasks)

> **User intent:** "Find items matching A AND B AND NOT C."
>
> **Why CLI wins:** SQL `WHERE` chains arbitrary conditions. Apps offer one
> filter at a time, forcing manual intersection across separate views.

| ID | Task |
|---:|---|
| 14 | Contacts with a birthday set but no phone number |
| 19 | Pro Expense >$50, category 'Transportation', last month |
| 26 | Joplin notes containing X but NOT Y |
| 31 | Songs by artist X longer than 4 minutes |
| 56 | SMS messages containing a URL |
| 60 | Zero-byte files in Downloads |
| 63 | Pro Expense entries above the overall average |
| 68 | Calendar events on Saturday/Sunday |

### D. Cross-app correlation (8 tasks)

> **User intent:** "Compare or join data across two apps."
>
> **Why CLI wins:** a shell session has access to all app databases at once.
> GUI loses context when switching between apps.

| ID | Task |
|---:|---|
| 4 | SMS senders in last 7 days NOT in contacts |
| 23 | Total monthly expenses → Markor note + Calendar event |
| 33 | Broccoli recipes → Markor index note |
| 35 | Phones in Markor notes NOT in contacts |
| 44 | Calendar events containing keyword → Markor note |
| 71 | Export contacts to a Markor note (Name: phone) |
| 74 | SMS containing 'urgent' → create a task per one |
| 75 | OpenTracks weekly summary → Markor note |

### E. Hidden device state (8 tasks)

> **User intent:** "What is the device's current state — permissions,
> resource usage, connectivity?"
>
> **Why CLI wins:** `dumpsys`, `pm`, `settings get/list` expose state that
> is buried deep in OS menus or not surfaced at all.

| ID | Task |
|---:|---|
| 39 | Apps with location permission |
| 40 | Audio routing device + media volume |
| 41 | Apps with camera permission |
| 42 | WiFi state + SSID |
| 50 | Free storage space remaining (GB) |
| 51 | 3 most recently installed apps |
| 53 | App that drained most battery since last full charge |
| 54 | App that used the most mobile data |

---

## 4. The 45 task IDs (comma-separated, ready for the runner)

```
0,3,4,5,6,11,12,14,16,17,19,20,22,23,25,26,28,31,33,35,36,39,40,41,42,43,44,46,47,49,50,51,53,54,56,60,63,64,65,66,68,70,71,74,75
```

Sorted by category:

```
A: 3,12,16,20,22,25,28,36,46,49,64,65
B: 0,5,6,11,17,43,47,66,70
C: 14,19,26,31,56,60,63,68
D: 4,23,33,35,44,71,74,75
E: 39,40,41,42,50,51,53,54
```

---

## 5. Drawbacks of the current dataset

These are the gaps a reviewer will likely flag. We document them rather than
hide them; some can be closed before publication, others are inherent
limitations.

### 5.1 Category D (Cross-app) is mostly "export workflows", not joins

Of the 8 cross-app tasks, only 2 (`4` SMS-not-in-contacts, `35` Markor-phones-
not-in-contacts) are genuine cross-app *correlation* (set intersection across
two apps' data). The other 6 (`23, 33, 44, 71, 74, 75`) are "compute X in
app A, write the result into app B" — these show off CLI's batch+write
capability but are not the canonical "join data from two apps" pattern that
the published 25-subset paper highlights as one of CLI's structural
strengths.

**Mitigation**: author 4–5 new pure-correlation cross-app tasks before
publication. Drafts:

- Calendar attendees not in my contacts
- Songs in Retro Music whose titles appear in any Markor note
- Apps in "recently installed" that have sent me push notifications
- Contacts I have texted but never called
- Files I downloaded the day before each scheduled meeting

If these are added, drop the weakest 4 export-workflow tasks (`23, 33, 44,
71, 75`) so D stays at 8 with stronger composition.

### 5.2 Category C (Multi-condition) has 5 of 8 tasks rated "stretched"

`14`, `26`, `31`, `60`, `63` are realistic in motivation but use arbitrary
thresholds, dev-flavored phrasing, or statistical framing that real users
do not naturally produce.

**Mitigation**: author 2–3 universal-feeling multi-condition tasks. Drafts:

- Unread SMS from numbers I haven't replied to in the last 7 days
- Calendar events in the next 7 days that overlap each other
- Contacts with no email, no recent calls, AND no SMS in 30 days
- Tasks completed yesterday with priority high

Drop the weakest 2–3 of the existing C tasks if added.

### 5.3 No GUI-favorable control categories

Every category in this dataset is structurally CLI-favorable by construction.
A reviewer will say: *"You only included tasks where CLI wins. Did you
exclude tasks where GUI wins?"*

The answer is yes — we focused on data-task categories where the published
paper argues CLI is structurally advantaged. To strengthen credibility, the
paper should either:

- (a) Be explicit about scope: this is a *data-task* benchmark, not a
  general mobile-agent benchmark; CLI is not claimed to dominate visual
  or spatial tasks.
- (b) Add 2–3 control categories where GUI is competitive (e.g. visual
  recognition, form completion, in-app navigation), report results on
  them, and show CLI does *not* win there. This strengthens the modality
  argument.

Path (b) is the more rigorous option but requires implementing 15–25 new
GUI-favorable tasks, which is out of scope for this dataset.

### 5.4 Single-seed selection

The category assignment and the soft-balance pruning were both performed
based on a single-seed (seed=7) run of three agents. Multi-seed validation
on the previous 40-task subset showed bucket assignments are stable to
±1–2 tasks per bucket across seeds — but the *selection* itself was still
made on a single seed.

**Mitigation**: re-run the 3 agents on this 45-task subset across 3 seeds
(7, 30, 1234) and confirm no task systematically migrates between buckets.
Multi-seed JSONLs are already at:
- `eval-runners/data/tier4/all_tasks_seed7.jsonl`
- `eval-runners/data/tier4/all_tasks_seed30.jsonl`
- `eval-runners/data/tier4/all_tasks_seed1234.jsonl`

### 5.5 Model-size confound in the CLI vs GUI comparison

The CLI agent is **Opus 4.7** (frontier model, hundreds of billions of
params, hosted API). The GUI agents are **MAI-UI-8B** (8B local) and
**Qwen3-VL-32B** (32B). A reviewer will reasonably ask: *"How much of the
+58pp gap is from the modality, and how much is from the model strength?"*

This is the single biggest threat to the paper's headline claim.

**Mitigation**: at least one of:
- Run a smaller-model CLI agent (e.g. Sonnet 4 or Haiku 4.5) on the same
  benchmark. If CLI still beats GUI by ≥40pp, the modality argument
  survives.
- Run a frontier-model GUI agent (Claude 4.7 with vision tools, GPT-4o
  with vision) on the same benchmark. If GUI catches up substantially,
  the gap was largely model-strength; if not, it really is modality.

Without one of these, the headline should be phrased as *"Opus 4.7 with
shell access vs 8B/32B with vision access"* rather than *"CLI vs GUI."*

### 5.6 Tier4-extra tasks (50–76) have lower published baseline

15 of the 45 tasks in this subset are tier4-extras, which were never run by
the GUI baseline agents in the published 25-subset paper. Our own runs
showed these extras are roughly 5–10pp harder for GUI than the original 50,
likely because they tend toward system-introspection and cross-app patterns.
This isn't a methodological flaw, but worth disclosing: the dataset
includes newer, less-validated tasks.

### 5.7 No fairness check across the contrived-drop boundary

We dropped 12 contrived tasks. We did not measure whether those 12 were
disproportionately CLI-favorable in the actual runs (i.e. whether keeping
them would have shifted the headline). A skeptic could argue we dropped
"contrived" tasks that happened to make GUI look good. We should report
the headline computed on the contrived 12 separately as a sanity check —
if GUI agents fail on them anyway, the drop is harmless.

---

## 6. What's not in this dataset (and where to find it)

- **Contrived tasks excluded** (12 IDs): listed in section 2.2.
- **Stretched-but-realistic tasks excluded for balance** (20 IDs): the 15
  dropped from category A and the 3 from B and 2 from E. These are not in
  the dataset but remain in the source JSONL.
- **The 32 unused tier4 tasks** (12 contrived + 20 over-balance) remain
  available in `eval-runners/data/tier4/all_tasks_seed7.jsonl` for anyone
  who wants to run them separately.

---

## 7. Reproduction

```bash
TASKS_45="0,3,4,5,6,11,12,14,16,17,19,20,22,23,25,26,28,31,33,35,36,39,40,41,42,43,44,46,47,49,50,51,53,54,56,60,63,64,65,66,68,70,71,74,75"

# CLI agent
python eval-runners/benchmarks/androidworld/run_claude_cli.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_45" \
    --broker-url http://localhost:9200 --pool-size 8 \
    --model claude-opus-4-7 --max-turns 50 \
    --prompt clean_optimized_v10 --effort max

# GUI agent (MAI-UI-8B, local vLLM)
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_mai.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_45" \
    --model /shared/models/MAI-UI-8B \
    --api-url http://localhost:8401/v1 --api-key dummy \
    --broker-url http://localhost:9200 --pool-size 8 \
    --max-steps 50

# GUI agent (Qwen3-VL-32B, OpenRouter)
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_qwen3vl.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_45" \
    --model qwen/qwen3-vl-32b-instruct \
    --api-url https://openrouter.ai/api/v1 \
    --api-key "$OPENROUTER_API_KEY" \
    --broker-url http://localhost:9200 --pool-size 8 \
    --max-steps 50
```

For multi-seed runs, swap `seed7` → `seed30` or `seed1234` in `--data`.
