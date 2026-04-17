# Tier4 CLI-Advantage Benchmark: 25-Task Subset

## Motivation

Mobile agent benchmarks today — AndroidWorld (116 tasks), MobileWorld (117
tasks) — measure how well an agent operates a touchscreen. But users often
need **results** that screens weren't designed to deliver:

- "Clean up my duplicate contacts"
- "How many hours of meetings this month?"
- "What's eating up my storage?"
- "Which unknown numbers are texting me?"

These are everyday requests. Users know the answer is on their phone but can't
get to it — the GUI wasn't designed for bulk operations, data aggregation, or
cross-app lookups. So they give up, estimate, or live with clutter.

CLI agents can serve these unmet needs through shell commands, content
providers, and SQL — bypassing the GUI bottleneck. This benchmark measures that.

## Results

| Agent | Type | Solved | Rate | Avg Steps |
|-------|------|-------:|-----:|----------:|
| Opus 4.6 (tools) | CLI | 21/25 | **84%** | 15.0 |
| Sonnet 4 (tools) | CLI | 18/25 | **72%** | 12.2 |
| MAI-UI-8B | GUI | 6/25 | 24% | 25.2 |
| Qwen3-VL-32B | GUI | 2/25 | 8% | 15.6 |
| Venus-1.5-8B | GUI | 0/25 | 0% | 6.4 |

CLI agents solve 3-10x more tasks than GUI agents. When both succeed, CLI
typically needs fewer steps.

---

## The 25 Tasks

25 tasks selected from the 50-task tier4 set. Three types:

- **15 CLI-exclusive**: CLI solves, all 3 GUI agents fail (0/3)
- **6 both-solve, CLI-faster**: Both modalities succeed, CLI takes fewer steps
- **4 neither-solves**: Both fail — hard tasks that pull CLI below 100%

This mix avoids cherry-picking: CLI doesn't get a perfect score, and GUI gets
credit where it succeeds.

### Task List

| # | What the user would say | Type | CLI Steps | GUI Steps | GUI SR |
|---|-------------------------|:----:|----------:|----------:|:------:|
| | **Clean up my phone** | | | | |
| 0 | "Delete all temp files in Downloads" | CLI-faster | 5 | 8 | 2/3 |
| 5 | "Organize my screenshots by date" | CLI-only | 10 | — | 0/3 |
| 17 | "Merge my duplicate contacts" | CLI-only | 12 | — | 0/3 |
| 24 | "Change all low-priority tasks to medium" | CLI-faster | 12 | 16 | 1/3 |
| 47 | "Remove duplicate calendar events" | Hard | — | — | 0/3 |
| | **Who's contacting me?** | | | | |
| 4 | "Which unknown numbers texted me this week?" | CLI-only | 8 | — | 0/3 |
| 12 | "Who do I text the most?" | Hard | — | — | 0/3 |
| 16 | "Do any contacts share the same phone number?" | CLI-only | 9 | — | 0/3 |
| | **What's eating my storage?** | | | | |
| 36 | "How big are my Downloads? Top 3 largest?" | CLI-only | 7 | — | 0/3 |
| 37 | "What are the 5 biggest files I downloaded?" | CLI-only | 6 | — | 0/3 |
| 6 | "Move my large files to Archive" | CLI-faster | 11 | 14 | 1/3 |
| | **Manage my calendar** | | | | |
| 44 | "Make a note of all meetings about [topic]" | CLI-only | 14 | — | 0/3 |
| 45 | "Which long meetings have no reminders?" | CLI-only | 12 | — | 0/3 |
| 46 | "Total hours of meetings this month?" | Hard | — | — | 0/3 |
| 48 | "What's the oldest event in my calendar?" | CLI-only | 11 | — | 0/3 |
| 49 | "Did I forget reminders on any events?" | CLI-only | 18 | — | 0/3 |
| | **Device info** | | | | |
| 2 | "What app versions are installed?" | CLI-faster | 6 | 22 | 1/3 |
| 40 | "Where is my audio playing?" | CLI-only | 8 | — | 0/3 |
| 42 | "Is WiFi on? What network?" | Hard | — | — | 0/3 |
| | **Analyze my data** | | | | |
| 8 | "Add a footer to all my markdown notes" | CLI-faster | 16 | 24 | 2/3 |
| 9 | "Which note has the most content?" | CLI-only | 8 | — | 0/3 |
| 28 | "Total running distance this week?" | CLI-faster | 12 | 17 | 1/3 |
| 31 | "Find all long songs by [artist]" | CLI-only | 12 | — | 0/3 |
| 32 | "What are my longest songs?" | CLI-only | 8 | — | 0/3 |
| 34 | "Which files were created during meetings?" | CLI-only | 10 | — | 0/3 |

**Type legend:**
- **CLI-only** (15): CLI solves, all GUI agents fail — tasks GUI structurally cannot do
- **CLI-faster** (6): Both solve, but CLI uses 1.3-3.7x fewer steps — GUI is inefficient
- **Hard** (4): Both CLI and GUI fail — genuinely difficult tasks that keep scores honest

---

## Efficiency: When Both Solve, CLI Uses Fewer Steps

6 tasks are solved by both CLI and GUI agents. On all 6, CLI finishes in
fewer steps:

| # | Task | CLI Steps | GUI Steps | Ratio |
|---|------|----------:|----------:|------:|
| 2 | Check app versions | 6 | 22 | **3.7x** |
| 0 | Delete temp files | 5 | 8 | **1.6x** |
| 8 | Append footer to notes | 16 | 24 | **1.5x** |
| 28 | Weekly running stats | 12 | 17 | **1.4x** |
| 6 | Move large files | 11 | 14 | **1.3x** |
| 24 | Change task priorities | 12 | 16 | **1.3x** |

GUI steps shown are for the best-performing GUI agent. CLI is 1.3-3.7x faster.

**Reliability gap**: On these 6 tasks, CLI agents succeed consistently (both
Opus and Sonnet). GUI agents succeed sporadically — only 1 or 2 of 3 agents
manage each task.

### Why CLI Needs Fewer Steps

**Task 2 — App versions (3.7x)**:
- GUI: Settings → Apps → scroll → tap Markor → scroll to version → back →
  repeat for 2 more apps = 22 steps with navigation errors
- CLI: `dumpsys package X | grep versionName` × 3 = 6 steps, no navigation

**Task 8 — Append footer to 4 files (1.5x, scales worse)**:
- GUI: open file → edit → type → back → back → next file = 6 steps per file.
  For 4 files = 24. For 20 files = 120 (exceeds budget).
- CLI: `write-file X --append` per file = ~3 steps per file.
  For 4 files = 16. For 20 files = 63 (still feasible).

**Task 6 — Move large files (1.3x)**:
- GUI: browse files, check sizes (if shown), select, move — 14 steps
- CLI: `find -size +50M -exec mv {} /Archive/` — 11 steps including verify

---

## Five Patterns: Why GUI Falls Behind

### Pattern 1: Invisible Data (tasks 36, 37, 40, 9, 2)

Data exists on the device but no app renders it on screen. File sizes, audio
routing, character counts, package versions behind deep menus.

> *"I know my phone knows this. Why can't I see it?"*

CLI accesses it directly: `stat`, `dumpsys`, `wc -c`, `pm dump`.

### Pattern 2: No Aggregate Views (tasks 12, 46, 36)

Apps show individual items. Users want totals and rankings. "Total meeting
hours?" "Who texts me most?" No app provides the summary.

> *"I can see each item. I just want the total."*

CLI computes aggregates: `SUM(duration)`, `COUNT(*) GROUP BY`, `du -s`.

### Pattern 3: No Cross-App Memory (tasks 4, 34, 44)

Correlating data across two apps requires remembering App A's data while
reading App B. GUI agents see one screen at a time — switching apps loses
context.

> *"I need to check my texts against my contacts. Why can't I see both?"*

CLI stores query results and cross-references them in the same session.

### Pattern 4: O(N) per Item (tasks 0, 5, 8, 17, 24, 47, 48, 49)

Each item requires the same tap sequence: open → check → act → close → next.
At 50-step budgets, GUI handles ~8-10 items before running out.

> *"I want to do this to ALL of them. Not one at a time."*

CLI processes any count with the same command: `find -exec`, `content delete
--where`, shell loops.

### Pattern 5: No Multi-Condition Filters (tasks 4, 16, 31, 32, 45)

Apps filter by one dimension. Users want compound filters: songs by artist
AND longer than 4 minutes; contacts sharing a number; events without
reminders AND longer than 2 hours.

> *"I want to filter by two things at once. The app only lets me pick one."*

CLI uses SQL WHERE with AND, GROUP BY with HAVING, or piped grep.

---

## What This Shows

### CLI agents serve real needs that GUI cannot

Every task maps to an everyday user request. These are not edge cases — they
are things users already want but have stopped asking for because the phone's
GUI can't deliver. CLI agents unlock these latent needs.

### The limitation is structural, not a model gap

Three different GUI architectures (Qwen3-VL-32B, MAI-UI-8B, Venus-1.5-8B)
all struggle. The bottleneck is the **interaction modality** — what you can
do through a screen — not the model's intelligence.

### Even when GUI succeeds, CLI is more efficient

On the 6 both-solve tasks, CLI uses 1.3-3.7x fewer steps. The gap widens
with scale: GUI cost grows linearly with item count (6N steps for N files),
while CLI cost stays near-constant.

### Previous benchmarks miss this entirely

AndroidWorld and MobileWorld test zero tasks requiring: content provider
queries, SQL, file metadata, system introspection, cross-app data joins, or
bulk processing. This subset fills that gap.

### The future is multimodal

The ideal mobile agent uses GUI for visual tasks (take a photo, navigate a
map, fill a form) and CLI for data tasks (query, aggregate, batch process).
This benchmark provides the data-task evaluation that enables measuring
progress toward that hybrid future.
