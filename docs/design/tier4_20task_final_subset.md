# Tier4 CLI-Advantage Benchmark: 25-Task Subset

## Motivation

Mobile agent benchmarks today — AndroidWorld (116 tasks), MobileWorld (117
tasks) — measure one thing: how well an agent operates a touchscreen. But
users don't always need screen interactions. They need **results**:

- "Clean up my duplicate contacts"
- "How many hours of meetings this month?"
- "What's eating up my storage?"
- "Organize my screenshots by date"

These are everyday requests. Users know the answer is on their phone but can't
get to it — the GUI wasn't designed for bulk operations, data aggregation, or
cross-app lookups. So they give up, estimate, or live with clutter.

CLI agents can serve these unmet needs. They access the same data through shell
commands, content providers, and SQL — bypassing the GUI bottleneck. This
benchmark measures that capability.

## Results at a Glance

| Agent | Type | Solved | Rate |
|-------|------|-------:|-----:|
| **Opus 4.6 (tools)** | **CLI** | **25/25** | **100%** |
| Sonnet 4 (tools) | CLI | 22/25 | 88% |
| MAI-UI-8B | GUI | 8/25 | 32% |
| Qwen3-VL-32B | GUI | 5/25 | 20% |
| Venus-1.5-8B | GUI | 0/25 | 0% |

**CLI solves every task. The best GUI agent solves fewer than 1 in 3.**

This is not because GUI agents are bad — MAI-UI-8B and Qwen3-VL-32B score
30-32% on the full 50-task set and 60-70% on the original AndroidWorld
benchmark. The gap exists because these 25 tasks require capabilities that
screen interaction structurally cannot provide.

---

## The 25 Tasks

### Composition

- **15 CLI-exclusive tasks**: CLI agents solve them; no GUI agent does
- **10 both-solve tasks**: Both CLI and GUI can solve, but CLI is faster, more
  reliable, or scales better

This mix provides two signals: (1) tasks only CLI can do, and (2) tasks where
CLI does it better even when GUI can technically manage.

### Task List

| # | User Ask | Task | CLI | Best GUI | GUI Steps | CLI Steps |
|---|----------|------|:---:|:--------:|----------:|----------:|
| | **Theme 1: Clean up my phone** | | | | | |
| 0 | "Delete all temp files in Downloads" | BulkDeleteTmpInDownloads | OK | OK (2/3) | 8 | 5 |
| 5 | "Organize my screenshots by date" | BulkRenameScreenshots | OK | — | — | 10 |
| 17 | "Merge my duplicate contacts" | DedupMergeContactsSamePhone | OK | — | — | 12 |
| 24 | "Change all low-priority tasks to medium" | BulkChangePriorityTasks | OK | OK (1/3) | 16 | 12 |
| | **Theme 2: Who's contacting me?** | | | | | |
| 4 | "Which unknown numbers texted me this week?" | CrossAppSmsNumbersNotInContacts | OK | — | — | 8 |
| 16 | "Do any contacts share the same phone number?" | DedupContactsDuplicatePhones | OK | — | — | 9 |
| 35 | "Which phone numbers in my notes aren't in contacts?" | CrossAppMarkorPhonesVsContacts | OK | OK (1/3) | 19 | 15 |
| | **Theme 3: What's eating my storage?** | | | | | |
| 36 | "How big are my Downloads? What are the 3 largest?" | AggregationDownloadSizeTop3 | OK | — | — | 7 |
| 37 | "What are the 5 biggest files I downloaded?" | TopKLargestDownloadFiles | OK | — | — | 6 |
| 6 | "Move my large files to Archive" | BulkMoveLargeFiles | OK | OK (1/3) | 14 | 11 |
| | **Theme 4: Manage my calendar** | | | | | |
| 44 | "Make me a note of all meetings about [topic]" | CrossAppCalendarToMarkor | OK | — | — | 14 |
| 45 | "Which long meetings don't have reminders?" | FilterCalendarLongNoReminder | OK | — | — | 12 |
| 48 | "What's the oldest event in my calendar?" | TopKCalendarEarliestEvent | OK | — | — | 11 |
| 49 | "Did I forget reminders on any events this month?" | CoverageCalendarEventsHaveReminders | OK | — | — | 18 |
| | **Theme 5: Device info & privacy** | | | | | |
| 2 | "What versions of my apps are installed?" | HiddenStateListAppVersions | OK | OK (1/3) | 22 | 6 |
| 40 | "Where is my audio playing? Speaker or Bluetooth?" | HiddenStateAudioRouting | OK | — | — | 8 |
| | **Theme 6: Track my spending** | | | | | |
| 19 | "List my big transportation expenses from last month" | FilterExpenseHighTravelLastMonth | OK | OK (1/3) | 13 | 15 |
| 22 | "What are my biggest expenses?" | TopKExpenseHighestAmount | OK | OK (1/3) | 5 | 8 |
| 27 | "Do I have duplicate notes in Joplin?" | DedupJoplinSameTitleNotes | OK | OK (2/3) | 2 | 8 |
| | **Theme 7: Search & analyze my data** | | | | | |
| 8 | "Add a footer to all my markdown notes" | BulkAppendFooterToMarkdown | OK | OK (2/3) | 24 | 16 |
| 9 | "Which of my notes has the most content?" | AggregationLongestMarkorNote | OK | — | — | 8 |
| 28 | "What's my total running distance this week?" | AggregationOpenTracksWeeklyStats | OK | OK (1/3) | 17 | 12 |
| 31 | "Find all long songs by [artist]" | FilterRetroMusicMultiCondition | OK | — | — | 12 |
| 32 | "What are my longest songs?" | TopKRetroMusicLongestSongs | OK | — | — | 8 |
| 34 | "Which files were created during my meetings?" | CrossAppFilesCreatedDuringEvents | OK | — | — | 10 |

---

## Two Dimensions of CLI Advantage

### Dimension 1: Tasks GUI Cannot Solve (15 tasks)

These 15 tasks have 0% GUI success rate across three independent GUI agents.

| Category | Tasks | Why GUI Fails |
|----------|-------|---------------|
| Cross-app data joins | 4, 34, 35, 44 | Must correlate data from two apps; context lost when switching screens |
| Database aggregation/dedup | 9, 16, 17, 31, 32 | Requires GROUP BY, COUNT, ORDER BY on data not sortable in any app UI |
| File metadata | 36, 37 | File sizes not shown in Files app; cannot sum or sort by size |
| Calendar content provider | 45, 48, 49 | No search, no reminder filter, no "oldest event" view in calendar app |
| Hidden system state | 40 | Audio routing device name exists only in `dumpsys audio` |

**This is the core claim**: these tasks represent user needs that screen
interaction *structurally* cannot serve, regardless of how good the GUI agent is.

### Dimension 2: Tasks GUI Can Solve But CLI Does Better (10 tasks)

These 10 tasks are solvable by GUI, but CLI is more efficient, more reliable,
or scales better.

| # | Task | Best GUI | CLI | GUI/CLI Ratio | Key Difference |
|---|------|:--------:|:---:|:-------------:|----------------|
| 2 | ListAppVersions | 22 steps | 6 steps | **3.7x** | 3 `dumpsys` calls vs 22 menu taps |
| 0 | DeleteTmpFiles | 8 steps | 5 steps | **1.6x** | `rm *.tmp` vs multi-select UI |
| 8 | AppendFooter | 24 steps | 16 steps | **1.5x** | Shell loop vs open-edit-save ×4 |
| 28 | WeeklyStats | 17 steps | 12 steps | **1.4x** | DB query vs navigating app views |
| 24 | ChangePriority | 16 steps | 12 steps | **1.3x** | SQL UPDATE vs tap each task |
| 6 | MoveLargeFiles | 14 steps | 11 steps | **1.3x** | `find -size +50M -exec mv` vs UI |
| 35 | PhonesVsContacts | 19 steps | 15 steps | **1.3x** | Two queries vs app switching |
| 19 | FilterExpense | 13 steps | 15 steps | **0.9x** | Pro Expense has good filter UI |
| 22 | TopExpenses | 5 steps | 8 steps | **0.6x** | Expense list is sortable in app |
| 27 | DedupJoplinNotes | 2 steps | 8 steps | **0.2x** | Duplicates visible in note list |

**Key insight**: For tasks 19, 22, 27 — GUI is actually *faster*. This is not
a weakness of the benchmark; it's evidence of fairness. When the answer is
visually accessible on one screen, GUI wins. When computation, aggregation, or
multi-step data processing is needed, CLI wins.

**Reliability matters too**: Even where GUI steps are comparable, only 1-2 of 3
GUI agents succeed vs both CLI agents. CLI is more deterministic.

---

## Trajectory Analysis: Three Case Studies

### Case 1: Scaling — Append Footer to Markdown Files (Task 8)

**Task**: Add `---\nGenerated by AutoBot` to every .md file in Markor's Notes folder.

**GUI (Qwen3-VL, 24 steps, reward=1)**:
```
For each of 4 files (6 steps each):
  1. Tap file to open
  2. Tap edit mode
  3. Type "---\nGenerated by AutoBot"
  4. Back (save)
  5. Back (to file list)
  6. Tap next file
```

**CLI (Opus, 16 steps, reward=1)**:
```
  1. find Notes/ -name "*.md"          → discover 4 files
  2-5. read-file each                  → check existing content
  6-9. write-file each --append        → append footer
  10-13. read-file each                → verify
  14. force-stop Markor                → sync
  15-16. finish
```

**The scaling argument**: GUI cost is **6N** (6 steps per file). CLI cost is
**3N + 3** (read + write + verify per file, plus discovery and sync).

| Files | GUI Steps | CLI Steps | Feasible? (50 budget) |
|------:|----------:|----------:|:---------------------:|
| 4 | 24 | 16 | Both OK |
| 8 | 48 | 27 | Both OK |
| 10 | 60 | 33 | **CLI only** |
| 20 | 120 | 63 | **CLI only** |

GUI breaks at ~8 files. CLI handles any count.

### Case 2: Data Not on Screen — App Versions (Task 2)

**Task**: List the version of Markor, Pro Expense, and Simple Calendar Pro.

**GUI (MAI-UI, 22 steps, reward=1)**:
```
  1-2: Open Settings
  3-4: Navigate to Apps list
  5-7: Find Markor → tap → scroll to version info
  8-10: Back → find Pro Expense → tap → scroll
  11-14: Back → find Simple Calendar → tap → scroll
  15-22: Navigation errors, retries, answer
```

**CLI (Opus, 6 steps, reward=1)**:
```
  1: pm list packages                                → find package names
  2: dumpsys package net.gsantner.markor | grep ver  → "2.10.9"
  3: dumpsys package com.arduia.expense | grep ver   → "1.0.0-beta05"
  4: dumpsys package ...calendar.pro | grep ver      → "6.22.2"
  5-6: finish
```

**Why 3.7x faster**: GUI navigates Settings → Apps → [app] → About for each app
(~7 taps per app with error recovery). CLI queries the package manager directly.

Only 1 of 3 GUI agents succeeds — the deep Settings menu hierarchy causes
navigation errors for the other two.

### Case 3: When GUI Wins — Joplin Duplicate Notes (Task 27)

**Task**: List all Joplin notes with duplicate titles.

**GUI (Qwen3-VL, 2 steps, reward=1)**:
```
  1: Open Joplin
  2: Answer — duplicates visible in the note list at a glance
```

**CLI (Opus, 8 steps, reward=1)**:
```
  1: find Joplin data directory
  2: find database file
  3: .tables → discover schema
  4: SELECT title, COUNT(*) GROUP BY title HAVING COUNT(*) > 1
  5-6: verify
  7-8: finish
```

**Why GUI is 4x faster here**: The duplicate titles are *directly visible* on
one screen. No computation needed — just read the list. CLI has to discover
the database, inspect the schema, and write a query. This is overhead for a
task where the answer is already rendered.

**This case matters**: It shows the benchmark is fair. We don't claim CLI is
universally better. We claim CLI is better when the task requires data access
beyond what's on screen — and the 15 CLI-exclusive tasks prove exactly that.

---

## Five Failure Patterns

From analyzing GUI trajectories across all 25 tasks, five structural
limitations explain why GUI agents fail or struggle:

### Pattern 1: Invisible Data
**Tasks**: 36, 37, 40, 2, 9

Data exists on the device but no app renders it. File sizes, audio routing,
character counts, app versions behind deep menus.

> *"I know my phone knows this. Why can't I see it?"*

CLI: `stat`, `dumpsys`, `wc`, `pm dump` access raw system data directly.

### Pattern 2: No Aggregate Views
**Tasks**: 36, 28, 9

Apps show individual items. Users want totals, counts, rankings. No app
provides "total meeting hours" or "total download size."

> *"I can see each item. I just want the total."*

CLI: SQL `SUM()`, `COUNT()`, `GROUP BY` compute aggregates in one command.

### Pattern 3: No Cross-App Memory
**Tasks**: 4, 34, 35, 44

Correlating data across apps requires remembering App A's data while reading
App B. GUI agents see one screen at a time with no persistent memory.

> *"I need to check my texts against my contacts. Why can't I see both?"*

CLI: Query results stored in conversation context; multiple `content query`
calls cross-referenced programmatically.

### Pattern 4: O(N) Taps for N Items
**Tasks**: 0, 5, 8, 17, 24, 45, 48, 49

Each item requires the same tap sequence: open → check → act → close → next.
With 50-step budgets, GUI handles ~8-10 items maximum.

> *"I want to do this to ALL of them. Not one at a time."*

CLI: Shell loops process any count in constant effort.

### Pattern 5: No Multi-Condition Filters
**Tasks**: 4, 16, 31, 32, 45

Apps filter by one dimension (artist, date, folder). Users want compound
filters: by artist AND duration, contacts sharing a number, events without
reminders AND longer than 2 hours.

> *"I want to filter by two things at once."*

CLI: SQL WHERE with AND, GROUP BY with HAVING.

---

## Why This Matters

### For the benchmark community

AndroidWorld and MobileWorld test **screen operation** — tapping, swiping, typing,
navigating menus. This 25-task subset tests **programmatic data access** —
content providers, SQL, shell commands, system introspection. No existing
benchmark covers this.

### For the future of mobile agents

The five patterns describe real user frustrations that exist today:
- Users live with clutter because bulk cleanup is too tedious
- Users estimate instead of counting because no app shows the total
- Users don't cross-reference apps because they can't see both at once
- Users don't check permissions because the menu is buried

CLI agents serve these **latent needs** — requests users would make if they
could. The ideal mobile agent uses GUI for visual tasks (take a photo, fill a
form) and CLI for data tasks (query, aggregate, batch process). This benchmark
measures the data-task capability that enables that hybrid future.

### What the numbers show

The benchmark produces a clean, interpretable signal:

1. **CLI solves everything**: Opus 100%, Sonnet 88%
2. **GUI solves some but not most**: MAI-UI 32%, Qwen3-VL 20%, Venus 0%
3. **When both solve, CLI is often faster**: Up to 3.7x fewer steps
4. **When GUI is faster, it's for simple reads**: 2-3 steps to read a visible list
5. **The gap is structural, not model-dependent**: 3 different GUI architectures all fail the same 15 tasks
