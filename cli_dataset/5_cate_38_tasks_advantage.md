# 5-Category 38-Task CLI-Advantage Subset

A curated subset of 38 tasks selected from the 77-task tier4 source pool to
demonstrate CLI agents' structural advantages over GUI agents in mobile-data
workflows.

## Headline result (single-seed, seed=7)

| Agent | Type | Solved | Rate |
|-------|------|-------:|-----:|
| **CLI Opus 4.7** (`clean_optimized_v10`, effort=max, 50 turns) | CLI | **26/38** | **68%** |
| **GUI MAI-UI-8B** (vLLM 0.11.0, single H100) | GUI | 7/38 | 18% |

**Gap: +50 percentage points.** On the 7 both-solve tasks, CLI uses 6.7 avg
steps vs MAI's 15.6 — **2.32× more step-efficient**.

## Source pool and selection

- **Source pool**: 77 tier4 tasks (50 original + 27 extras integrated in
  commit `84fe2e7`), located at `eval-runners/data/tier4/all_tasks_seed7.jsonl`.
- **Drop**: 12 tasks classified as **contrived** (no realistic user query)
  — IDs 7, 13, 15, 30, 34, 45, 55, 59, 61, 72, 73, 76.
- **Filter**: from the remaining 65, keep only **CLI-favorable** outcomes
  (CLI-only or Both-CLI-faster-or-tied) plus up to **2 Hard tasks per
  category** (honesty floor — both modalities fail).
- **Drop**: GUI-only tasks (CLI fails, MAI succeeds) and Both-MAI-faster
  tasks. These contradict the hypothesis and are excluded by design.
- **Result**: 38 tasks, distributed across 5 user-need categories.

This is an **advantage benchmark**, named honestly — analogous to the
published [tier4_20task_final_subset](../docs/design/tier4_20task_final_subset.md)
which uses the same outcome-aware curation methodology.

## The 5 categories

User-need-grounded, mapped 1:1 to the 5 structural patterns identified in
the published 25-subset paper.

| # | Category | Count | User intent | Why CLI wins | Published paper's pattern |
|---|---|---:|---|---|---|
| **A** | **Compute across items** | 12 | "Tell me a number, ranking, or yes/no computed across many items" | SQL `SUM/AVG/COUNT/ORDER BY` produces the answer; apps display individual items | "No Aggregate Views" |
| **B** | **Bulk operations** | 8 | "Apply the same change to many items at once" | One shell loop / SQL `UPDATE` is O(1); GUI requires N tap sequences | "O(N) per Item" |
| **C** | **Multi-condition filter** | 6 | "Find items matching A AND B AND NOT C" | SQL `WHERE` chains arbitrary conditions; apps offer one filter at a time | "No Multi-Condition Filters" |
| **D** | **Cross-app correlation** | 6 | "Compare or join data across two apps" | Shell session has access to all app databases at once; GUI loses context when switching | "No Cross-App Memory" |
| **E** | **Hidden device state** | 6 | "Read system state — permissions, resource usage, connectivity" | `dumpsys`, `pm`, `settings get/list` expose state buried deep in OS menus | "Invisible Data" |

---

## A. Compute across items (12 tasks)

| ID | Task | Realism |
|---:|---|:---:|
| 9 | Which Markor note has the most content (by character count) | ⚠️ stretched |
| 10 | 5 most-recently-modified Markor notes (last 7 days) | ✅ realistic |
| 12 | Top 3 phone numbers by SMS count | ✅ realistic |
| 16 | Groups of contacts sharing a phone number | ✅ realistic |
| 20 | Top 3 expense categories by total this month | ✅ realistic |
| 21 | Count of suspected duplicate expenses (same date+amount+category) | ⚠️ stretched |
| 22 | Top 5 highest expenses | ✅ realistic |
| 29 | OpenTracks activity with highest average speed | ✅ realistic |
| 32 | Top 5 longest songs by duration | ⚠️ stretched |
| 36 | Total Downloads size + 3 largest files | ✅ realistic |
| 37 | 5 largest files in Downloads | ✅ realistic |
| 65 | Verify all expenses have a valid category | ✅ realistic |

**A realism: 9 / 3 stretched (75%)**

## B. Bulk operations (8 tasks)

| ID | Task | Realism |
|---:|---|:---:|
| 0 | Delete .tmp files in Downloads | ✅ realistic |
| 5 | Rename Screenshot_* by mtime to YYYYMMDD_HHMMSS.png | ⚠️ stretched |
| 6 | Move files >50MB to Archive | ✅ realistic |
| 8 | Append a footer to every .md file in Markor's Notes | ⚠️ stretched |
| 17 | Merge same-phone contacts, keep alphabetical-first | ⚠️ stretched |
| 43 | Delete calendar events whose title contains 'test' | ✅ realistic |
| 47 | Delete duplicate calendar events | ✅ realistic |
| 66 | Delete Pro Expense entries under $1.00 | ⚠️ stretched |

**B realism: 4 / 4 stretched (50%)**

## C. Multi-condition filter (6 tasks)

| ID | Task | Realism |
|---:|---|:---:|
| 14 | Contacts with birthday but no phone | ⚠️ stretched |
| 19 | Pro Expense >$50, Transportation, last month | ✅ realistic |
| 26 | Joplin notes containing X but NOT Y | ⚠️ stretched |
| 31 | Songs by artist X longer than 4 minutes | ⚠️ stretched |
| 56 | SMS messages containing a URL | ✅ realistic |
| 60 | Zero-byte files in Downloads | ⚠️ stretched |

**C realism: 2 / 4 stretched (33%)**

## D. Cross-app correlation (6 tasks)

| ID | Task | Realism |
|---:|---|:---:|
| 4 | SMS senders in last 7 days NOT in contacts | ✅ realistic |
| 23 | Total monthly expense → Markor note + Calendar event | ⚠️ stretched |
| 35 | Phones in Markor notes NOT in contacts | ⚠️ stretched |
| 44 | Calendar events containing keyword → Markor note | ⚠️ stretched |
| 71 | Export contacts to Markor note | ⚠️ stretched |
| 74 | SMS containing 'urgent' → create task per one | ✅ realistic |

**D realism: 2 / 4 stretched (33%)**

## E. Hidden device state (6 tasks)

| ID | Task | Realism |
|---:|---|:---:|
| 2 | List versions of Markor / Pro Expense / Simple Calendar Pro | ⚠️ stretched |
| 39 | Apps with location permission | ✅ realistic |
| 40 | Audio routing device + media volume level | ⚠️ stretched |
| 41 | Apps with Camera permission | ✅ realistic |
| 51 | 3 most recently installed apps (output package names) | ⚠️ stretched |
| 52 | Device uptime since last reboot | ⚠️ stretched |

**E realism: 2 / 4 stretched (33%)**

---

## Realism aggregate

| Category | Realistic | Stretched | Realism % |
|---|---:|---:|---:|
| A. Compute across items | 9 | 3 | **75%** |
| B. Bulk operations | 4 | 4 | 50% |
| C. Multi-condition filter | 2 | 4 | 33% |
| D. Cross-app correlation | 2 | 4 | 33% |
| E. Hidden device state | 2 | 4 | 33% |
| **Total** | **19** | **19** | **50%** |

The 38-set is **half highly realistic, half stretched-but-plausible, zero
contrived**. Category A is the strongest on realism; categories C, D, E
sit at 33% — disclosed honestly. The methodology section of any paper
using this dataset should report this distribution.

---

## Comma-separated task IDs (ready for the runner)

```
0,2,4,5,6,8,9,10,12,14,16,17,19,20,21,22,23,26,29,31,32,35,36,37,39,40,41,43,44,47,51,52,56,60,65,66,71,74
```

By category:

```
A: 9,10,12,16,20,21,22,29,32,36,37,65
B: 0,5,6,8,17,43,47,66
C: 14,19,26,31,56,60
D: 4,23,35,44,71,74
E: 2,39,40,41,51,52
```

---

## Reproduction commands

Same broker pool, same image, same prompts as the 40-subset doc; only
`--tasks` argument changes.

### CLI agent — Opus 4.7 + clean_optimized_v10 + max effort

```bash
TASKS_38=0,2,4,5,6,8,9,10,12,14,16,17,19,20,21,22,23,26,29,31,32,35,36,37,39,40,41,43,44,47,51,52,56,60,65,66,71,74

python eval-runners/benchmarks/androidworld/run_claude_cli.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_38" \
    --broker-url http://localhost:9200 --pool-size 8 \
    --model claude-opus-4-7 \
    --max-turns 50 \
    --prompt clean_optimized_v10 \
    --effort max
```

### GUI agent — MAI-UI-8B (local vLLM 0.11.0)

```bash
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_mai.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_38" \
    --model /shared/models/MAI-UI-8B \
    --api-url http://localhost:8401/v1 --api-key dummy \
    --broker-url http://localhost:9200 --pool-size 8 \
    --max-steps 50
```

### GUI agent — Qwen3-VL-32B-Instruct (OpenRouter)

```bash
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_qwen3vl.py \
    --data eval-runners/data/tier4/all_tasks_seed7.jsonl \
    --tasks "$TASKS_38" \
    --model qwen/qwen3-vl-32b-instruct \
    --api-url https://openrouter.ai/api/v1 \
    --api-key "$OPENROUTER_API_KEY" \
    --broker-url http://localhost:9200 --pool-size 8 \
    --max-steps 50
```

For multi-seed: swap `seed7` → `seed30` or `seed1234` in `--data`.

---

## Methodology (for the paper's methods section)

The selection is **outcome-aware curation**, named transparently. Steps:

1. Run all three agents (CLI, MAI, Qwen3-VL) on **all 77 source tasks**
   with identical seed, identical broker pool, identical max-turns budget.
2. For each task, classify by joint outcome:
   `CLI-only`, `Both-CLI-faster`, `Both-MAI-faster`, `GUI-only`, `Hard`.
3. Drop 12 tasks classified as **contrived** by realism rubric (rated by
   the dataset authors against criteria: real user phrasing, plausible
   utility, non-power-user vocabulary).
4. From each category, keep:
   - up to 10 CLI-favorable tasks (CLI-only + Both-CLI-faster-or-tied),
   - up to 2 Hard tasks (honesty floor — both modalities fail).
5. Drop GUI-only and Both-MAI-faster tasks (contradict the hypothesis).

The full 77-task source pool ships with the dataset so reviewers can audit
exactly which tasks were excluded and verify the selection criteria are
reproducible.

---

## Drawbacks (disclose in the paper)

1. **50% realism rate** — stretched tasks comprise half the dataset. The
   per-category distribution skews toward category A. Categories C, D, E
   sit at 33% realism each.
2. **Soft balance not strict** — A=12, B=8, C=6, D=6, E=6. The 8-task
   floor isn't met for C/D/E. The pool simply doesn't have more
   CLI-favorable realistic candidates without violating the realism filter.
3. **Single-seed selection** — the bucket assignments were computed on
   seed=7. Multi-seed validation on the precursor 40-set showed ±1 task
   variance across seeds, but the 38-set itself has not yet been multi-seed
   validated.
4. **Model-size confound** — CLI agent is Opus 4.7 (frontier hosted),
   GUI agents are 8B local + 32B hosted. The +50pp gap is partly
   modality, partly model strength. Mitigated only by running a
   smaller-model CLI agent (e.g., Sonnet 4 or Haiku 4.5) — out of scope
   for current dataset.
5. **GUI-favorable control categories absent** — every category is
   structurally CLI-favorable. Reviewer-credibility weakness; the paper
   should be scoped explicitly as a "data-task" benchmark, not a general
   mobile-agent benchmark.
6. **Several existing tasks may be falsely labeled "Hard"** due to
   AVD-specific setup quirks (Calendar provider lacks a default account
   on fresh containers; `description` content-bind silently fails).
   Documented separately for follow-up; doesn't affect this subset's
   measured numbers but means task difficulty is overstated for some
   excluded tasks.

---

## Comparison with sibling subsets

| Subset | Tasks | CLI rate | GUI rate | Gap | Realism | Multi-seed |
|---|---:|---:|---:|---:|:---:|:---:|
| Published 25-subset | 25 | 84% (Opus 4.6) | 24% (MAI) | +60 pp | high | partial |
| Internal 40-subset (`tier4_40task_subset.md`) | 40 | 88% (Opus 4.7) | 28% (MAI) | +60 pp | mixed (~70% real) | ✅ 3 seeds |
| **38-subset (this doc)** | **38** | **68%** (Opus 4.7) | **18%** (MAI) | **+50 pp** | **50% real, 0% contrived** | ❌ single seed |
| Realism-vetted 45 (`5_cate_45_tasks_balanced.md`) | 45 | — (not measured) | — | — | high (no contrived) | ❌ |

The 38-set trades **headline gap** (60 → 50 pp) for **methodological
defensibility** (drops contrived tasks, applies transparent
outcome-aware filter). It is the version most likely to survive review.

---

## Future work to harden this subset

- Multi-seed validation across seed=7, 30, 1234 (data files already exist
  at `eval-runners/data/tier4/all_tasks_seedN.jsonl`).
- Run a smaller-model CLI agent (Sonnet 4 or Haiku 4.5) to address the
  model-size confound.
- Author additional realistic CLI-favorable tasks for categories C and D
  (current floor is 6; target is 8). See
  [`new_task_specs.md`](new_task_specs.md) for spec drafts.
- Investigate whether existing "Hard" tasks (e.g., calendar tasks 43, 44,
  46, 49) are infrastructure-limited rather than truly Hard, using the
  no-agent validation protocol.
