# Tier4 Final 20-Task Subset: CLI-Exclusive Benchmark

## Design Philosophy

We select 20 tasks that represent **latent user needs** — things users genuinely
want to do on their phones but give up on because the GUI makes it too tedious.
CLI agents unlock these needs by providing programmatic access.

The selection criteria:
1. **Realistic**: "Would a real person ask this?" — not "Did we design this to
   break GUI agents?"
2. **CLI-exclusive**: No GUI agent (Qwen3-VL-32B, MAI-UI-8B, Venus-1.5-8B)
   solves it across 3 independent runs
3. **CLI-solvable**: At least one CLI agent (Opus or Sonnet) solves it
4. **Pattern-representative**: Tasks cover distinct user pain points, not
   repetitions of the same pattern

## The User Story

Every task maps to a real frustration:

> "I know my phone has this information, but I can't get to it."
> "I want to do this to 50 files, but I'd have to tap each one."
> "I need to check something across two apps, but I can't see them at the same time."
> "I know this setting exists somewhere, but I can't find it in the menus."

CLI agents solve these by accessing the same data through ADB shell, content
providers, and SQL — bypassing the GUI bottleneck entirely.

---

## The 20 Tasks

### Theme 1: "Clean up my phone" — Bulk Maintenance (4 tasks)

Users accumulate clutter but phones provide no bulk operations.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 0 | "Delete all the temp files in my Downloads" | BulkDeleteTmpInDownloads | Opus/Sonnet | Qwen/MAI |
| 5 | "Organize my screenshots by date" | BulkRenameScreenshots | Opus/Sonnet | — |
| 17 | "Clean up my duplicate contacts" | DedupMergeContactsSamePhone | Opus/Sonnet | — |
| 47 | "Remove duplicate calendar events from sync issues" | DedupCalendarDeleteDuplicateEvents | — | — |

**Why task 0 is included despite being GUI-solvable**: It's the simplest version
of bulk file management. GUI agents can do it for 4 files (9 steps), but CLI
does it in 1 command regardless of count. It anchors the "easy baseline" and
shows the efficiency gap grows with scale.

**Pattern**: GUI handles small counts (~4 files) but fails at scale. CLI scales
to any count with the same effort.

### Theme 2: "Who's contacting me?" — Communication Insights (3 tasks)

Users want to understand their communication patterns but messaging apps only
show individual conversations.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 4 | "Which unknown numbers texted me this week?" | CrossAppSmsNumbersNotInContacts | Opus/Sonnet | — |
| 12 | "Who do I text the most?" | TopKSmsThreadsByCount | — | — |
| 16 | "Do I have contacts with the same phone number?" | DedupContactsDuplicatePhones | Opus/Sonnet | — |

**Pattern**: Answering "across all my X" questions requires aggregating data
that's spread across many screens. GUI agents can read one conversation at a
time but can't compute over all of them.

### Theme 3: "How much space am I using?" — Storage Management (3 tasks)

Users run out of storage but can't easily find what's taking space.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 36 | "How big are my Downloads? What's taking the most space?" | AggregationDownloadSizeTop3 | Opus/Sonnet | — |
| 37 | "What are the biggest files I've downloaded?" | TopKLargestDownloadFiles | Opus/Sonnet | — |
| 6 | "Move my large files to the Archive folder" | BulkMoveLargeFiles | Opus/Sonnet | MAI |

**Why task 6 is included despite MAI solving it**: Only 1 of 3 GUI agents
succeeds, taking 50 steps. CLI does it in 2. It shows GUI can theoretically
do it but the effort is disproportionate.

**Pattern**: File metadata (sizes) is not shown in standard file managers.
Even when shown, sorting/summing requires computation GUI agents can't do.

### Theme 4: "Manage my calendar" — Schedule Management (4 tasks)

Calendar apps show one day/week at a time. Users can't answer questions about
their schedule without scrolling through every day.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 46 | "How many hours of meetings do I have this month?" | AggregationCalendarTotalDuration | — | — |
| 48 | "What's the oldest event still in my calendar?" | TopKCalendarEarliestEvent | Opus/Sonnet | — |
| 49 | "Did I forget to set reminders on any events?" | CoverageCalendarEventsHaveReminders | Opus | — |
| 45 | "Which long meetings don't have reminders?" | FilterCalendarLongNoReminder | Opus/Sonnet | — |

**Pattern**: Calendar queries spanning time ranges or checking properties across
many events require content provider access. The calendar UI shows events
day-by-day but provides no aggregate views, no search, no property filters.

### Theme 5: "What apps have access to my data?" — Privacy & Settings (2 tasks)

Users worry about privacy but permission screens are buried in Settings.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 40 | "Where is my audio playing right now?" | HiddenStateAudioRouting | Opus/Sonnet | — |
| 2 | "What versions of my apps are installed?" | HiddenStateListAppVersions | Opus/Sonnet | MAI |

**Why task 2 is included despite MAI solving it**: Only 1 of 3 GUI agents
succeeds. The task requires checking 3 app versions, each requiring navigating
to Settings → Apps → [app] → About. CLI does it with 3 `dumpsys` calls.

**Pattern**: System state (audio routing, app versions, permissions) is
scattered across deep Settings menus. CLI accesses it directly via `dumpsys`
and `pm`.

### Theme 6: "Track my spending" — Expense Analysis (2 tasks)

Users want insights from their expense data but the app only shows individual
entries.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 21 | "Do I have duplicate expense entries?" | DedupExpenseSuspectedDuplicates | Opus/Sonnet | Qwen/Venus |
| 22 | "What are my biggest expenses?" | TopKExpenseHighestAmount | Opus/Sonnet | Qwen |

**Why included despite some GUI solves**: These represent the common pattern of
"query my financial data." The GUI agents that solve them take 5 steps of
reading a list — they work only because Pro Expense has a good list view. The
pattern breaks for more complex queries (task 23, cross-app expense summary,
fails for all).

### Theme 7: "Search across my apps" — Cross-App Insights (2 tasks)

Users want to correlate information across apps but can't copy-paste between them
efficiently.

| # | User Ask | Task | CLI | GUI |
|---|----------|------|:---:|:---:|
| 44 | "Make me a note of all meetings about [topic]" | CrossAppCalendarToMarkor | Opus | — |
| 32 | "What are my longest songs?" | TopKRetroMusicLongestSongs | Opus/Sonnet | — |

**Pattern**: Cross-app tasks require reading from one data source and writing to
another. GUI agents lose context when switching apps. CLI agents can query
both databases in sequence.

---

## Results on the 20-Task Subset

| Agent | Type | Solved | Rate |
|-------|------|-------:|-----:|
| **Opus 4.6 (tools)** | CLI | **17/20** | **85%** |
| Opus 4.6 | CLI | 16/20 | 80% |
| Sonnet 4 (tools) | CLI | 14/20 | 70% |
| Sonnet 4 | CLI | 13/20 | 65% |
| Qwen3-VL-32B | GUI | 3/20 | 15% |
| MAI-UI-8B | GUI | 3/20 | 15% |
| Venus-1.5-8B | GUI | 1/20 | 5% |

**CLI/GUI gap: 5.7x** (85% vs 15%)

The 3 tasks GUI agents solve (tasks 0, 6, 21/22) are the simplest versions of
their themes — small file counts, list browsing. They anchor the baseline and
show the gap widens with task complexity.

## Five Failure Patterns

From analyzing GUI agent trajectories across these 20 tasks, we identify five
structural patterns that explain why GUI agents fail. These are not agent bugs —
they are fundamental limitations of screen-based interaction.

### Pattern 1: Invisible Data

**Tasks**: 36, 37, 40, 2 (partially)

Data exists on the device but is not rendered in any app UI. File sizes are not
shown in the Files app list view. Audio routing device names are not in Settings.
App version numbers require navigating to Settings → Apps → [each app] → About.

> **User frustration**: "I know my phone knows this, but there's no screen that
> shows it."

**CLI advantage**: `dumpsys`, `stat`, `pm dump` access all device state directly,
whether or not any app UI surfaces it.

### Pattern 2: No Aggregate Views

**Tasks**: 12, 46, 36, 21

Users want totals, counts, rankings — but apps show individual items only. "How
many hours of meetings?" requires summing every event. "Who texts me most?"
requires counting every conversation. No app provides these aggregate views.

> **User frustration**: "I can see each item, but I can't get the summary."

**CLI advantage**: SQL queries with SUM, COUNT, GROUP BY, ORDER BY compute
aggregates in a single command. Content providers expose the raw data.

### Pattern 3: No Cross-App Memory

**Tasks**: 4, 44, 34 (excluded but illustrative)

Comparing data across two apps requires the agent to remember information from
App A while looking at App B. GUI agents see one screen at a time and have no
persistent memory. When switching apps, the previous screen's data is gone.

> **User frustration**: "I need to check my texts against my contacts, but I
> can't look at both at once."

**CLI advantage**: Shell scripts can store query results in variables and cross-
reference them. Multiple `content query` calls return structured data that can
be compared programmatically.

### Pattern 4: O(N) Taps for N Items

**Tasks**: 5, 17, 47, 45, 48, 49

Bulk operations and per-item checks require touching every item individually.
Renaming N files = ~5N taps. Checking reminders on N events = ~4N taps. Merging
N duplicate contacts = ~6N taps. With budgets of 50 steps, anything over ~10
items is infeasible.

> **User frustration**: "I want to do this to all of them, not one at a time."

**CLI advantage**: Shell loops, `find -exec`, `content delete --where` process
any number of items in constant effort. Scaling is O(1) not O(N).

### Pattern 5: Multi-Condition Filters Don't Exist

**Tasks**: 45, 16, 4, 32

Apps provide simple views (all contacts, all events, all songs) but no way to
filter by multiple conditions simultaneously. "Songs by artist X longer than
4 minutes" requires a WHERE clause with two conditions. "Contacts sharing the
same number" requires a GROUP BY. These are trivial in SQL but have no UI
equivalent.

> **User frustration**: "I want to filter by X AND Y, but the app only lets me
> filter by X."

**CLI advantage**: SQL WHERE clauses, content provider selection args, and shell
pipelines with `grep | sort | uniq` handle arbitrary filter combinations.

---

## Why This Subset Matters

### For the benchmark community

Previous mobile agent benchmarks (AndroidWorld 116 tasks, MobileWorld 117 tasks)
test GUI interaction: tapping, swiping, typing, navigating menus. They measure
how well an agent can **operate the screen**.

This 20-task subset tests a different capability: can an agent **access and
process device data programmatically**? This is not tested by any existing
benchmark.

### For the future of mobile agents

The five patterns above describe real user frustrations. Today, users work
around these limitations by:
- Not doing bulk operations (living with clutter)
- Not asking aggregate questions (estimating instead of counting)
- Not cross-referencing apps (keeping a mental model instead)
- Not checking system state (ignoring privacy concerns)

CLI agents don't need users to change their behavior. The agent receives a
natural language request ("clean up my duplicate contacts") and uses
programmatic access to fulfill it — regardless of whether the GUI supports it.

This represents a **capability expansion**: not replacing GUI agents, but
complementing them with tasks that GUI interaction fundamentally cannot serve.
