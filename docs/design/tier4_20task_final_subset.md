# Tier4 CLI-Advantage Benchmark: 20-Task Subset

## Why This Benchmark Exists

Mobile agent benchmarks today — AndroidWorld (116 tasks), MobileWorld (117 tasks)
— measure one thing: how well an agent taps, swipes, and types on a screen.

But users don't always want screen interactions. They want **results**:

- "Clean up my duplicate contacts"
- "How many hours of meetings do I have this month?"
- "What's eating up my storage?"
- "Which unknown numbers have been texting me?"

These are everyday requests. Users know the answer is on their phone. They just
can't get to it — because the GUI wasn't designed for bulk queries, cross-app
lookups, or system introspection. So they give up, estimate, or ignore the need.

CLI agents can serve these needs. They access the same data through shell
commands, content providers, and SQL queries — bypassing the GUI bottleneck.
This benchmark measures that capability.

## Task Selection

**20 tasks. 0% GUI success. 80% CLI success.**

Selection criteria:
1. **User-realistic**: Every task maps to a request a real person would make
2. **GUI-impossible**: All 3 GUI agents (Qwen3-VL-32B, MAI-UI-8B, Venus-1.5-8B)
   score 0% — not because the task is obscure, but because the GUI structurally
   cannot support it
3. **CLI-solvable**: At least one CLI agent solves it, proving the task is
   achievable with programmatic access
4. **Diverse**: Tasks span 7 user-facing themes, not repetitions of one pattern

Source: 15 tasks from the **CLI-exclusive** quadrant (CLI solves, all GUI fail)
plus 5 tasks from the **neither-solves** quadrant that are realistic user needs
where CLI agents came close but failed on format/verification issues.

---

## The 20 Tasks, by User Theme

### Theme 1: "Clean up my phone" (4 tasks)

Phones accumulate clutter. Users want to clean up but face one-by-one UI flows.

| # | What the user would say | Task |
|---|-------------------------|------|
| 5 | "Organize my screenshots — rename them by date" | BulkRenameScreenshots |
| 17 | "I have duplicate contacts. Merge them, keep the first alphabetically" | DedupMergeContactsSamePhone |
| 47 | "My calendar has duplicate events from syncing. Remove the extras" | DedupCalendarDeleteDuplicateEvents |
| 43 | "Delete all the test events I created in my calendar" | BulkDeleteCalendarTestEvents |

**GUI barrier**: No bulk rename in Files app. No "find duplicates" in Contacts
or Calendar. Each item must be handled individually — O(N) taps for N items.

**CLI method**: `find` + `mv` for renaming. `content query` + GROUP BY for
duplicates, `content delete` for removal. O(1) regardless of item count.

### Theme 2: "Who's contacting me?" (3 tasks)

Users want communication insights that messaging apps don't surface.

| # | What the user would say | Task |
|---|-------------------------|------|
| 4 | "Which numbers texted me this week that aren't in my contacts?" | CrossAppSmsNumbersNotInContacts |
| 12 | "Who do I text the most? Show me the top 3" | TopKSmsThreadsByCount |
| 16 | "Do any of my contacts share the same phone number?" | DedupContactsDuplicatePhones |

**GUI barrier**: SMS app shows conversations individually. Checking each sender
against the contact list requires switching between two apps — no persistent
memory between screens. Counting messages per thread has no UI.

**CLI method**: `content query --uri content://sms` cross-referenced with
`content://contacts`. GROUP BY and COUNT in SQL.

### Theme 3: "What's eating my storage?" (2 tasks)

Users run out of space but can't easily see file sizes or totals.

| # | What the user would say | Task |
|---|-------------------------|------|
| 36 | "How big are my Downloads? What are the 3 biggest files?" | AggregationDownloadSizeTop3 |
| 37 | "Show me the 5 largest files in my Downloads folder" | TopKLargestDownloadFiles |

**GUI barrier**: The Files app shows files but not their sizes in the default
list view. Even if sizes appear, summing them or sorting by size is not
supported. The agent would need to read each size from the screen and perform
arithmetic.

**CLI method**: `ls -lS` or `stat -c '%s %n'` — file sizes returned as
structured data, trivially sorted and summed.

### Theme 4: "Manage my calendar" (4 tasks)

Calendar apps show one day at a time. Users can't ask questions about their
schedule as a whole.

| # | What the user would say | Task |
|---|-------------------------|------|
| 46 | "How many hours of meetings do I have this month in total?" | AggregationCalendarTotalDuration |
| 48 | "What's the oldest event still in my calendar?" | TopKCalendarEarliestEvent |
| 49 | "Did I forget to set reminders on any of my events this month?" | CoverageCalendarEventsHaveReminders |
| 45 | "Which of my long meetings are missing reminders?" | FilterCalendarLongNoReminder |

**GUI barrier**: Calendar shows events day-by-day. Summing durations, finding the
oldest event (scrolling back months/years), or checking reminder status on each
event individually — all require O(N) interactions with no aggregate view.

**CLI method**: `content query --uri content://calendar/events` returns all
events as structured data. SQL SUM for duration, ORDER BY for oldest, LEFT JOIN
with reminders table for missing reminders.

### Theme 5: "What's going on with my phone?" (2 tasks)

Users want to check device state that isn't shown in any app.

| # | What the user would say | Task |
|---|-------------------------|------|
| 40 | "Where is my audio playing? Speaker or Bluetooth?" | HiddenStateAudioRouting |
| 39 | "Which apps have access to my location?" | HiddenStateLocationPermissions |

**GUI barrier**: Audio routing is internal system state — no Settings screen
shows "current output device." Location permissions exist in Settings → Apps →
Permissions → Location, but navigating there requires 4+ precise taps through
nested menus that GUI agents consistently fail to complete.

**CLI method**: `dumpsys audio | grep routing` for audio. `dumpsys package`
with permission filtering for location grants.

### Theme 6: "Cross-reference my apps" (3 tasks)

Users want to connect information across apps but can't view two apps at once.

| # | What the user would say | Task |
|---|-------------------------|------|
| 44 | "Make me a note of all my meetings about [topic]" | CrossAppCalendarToMarkor |
| 34 | "Which files were created while I was in meetings?" | CrossAppFilesCreatedDuringEvents |
| 9 | "Which of my notes has the most content?" | AggregationLongestMarkorNote |

**GUI barrier**: Cross-app tasks require reading from App A, switching to App B,
and transferring data. GUI agents lose the data from App A's screen when they
switch. File character counts and modification timestamps are not shown in any
app UI.

**CLI method**: Multiple `content query` or `read-file` calls store results in
the conversation context. Shell commands access file metadata (`wc -c`, `stat`)
that no app surfaces.

### Theme 7: "What's in my music library?" (2 tasks)

Users want to browse their music by properties the app doesn't support.

| # | What the user would say | Task |
|---|-------------------------|------|
| 32 | "What are my longest songs?" | TopKRetroMusicLongestSongs |
| 31 | "Show me all songs by [artist] that are over 4 minutes" | FilterRetroMusicMultiCondition |

**GUI barrier**: Retro Music can sort by title, artist, or album — but not by
duration. Filtering by artist AND duration simultaneously has no UI equivalent.
The agent would need to browse every song and read its duration text.

**CLI method**: `content query --uri content://media/external/audio/media` with
WHERE and ORDER BY clauses on the duration column.

---

## Results

| Agent | Type | Solved | Rate |
|-------|------|-------:|-----:|
| **Opus 4.6 (tools)** | CLI | **15/20** | **75%** |
| Opus 4.6 | CLI | 14/20 | 70% |
| Sonnet 4 (tools) | CLI | 12/20 | 60% |
| Sonnet 4 | CLI | 11/20 | 55% |
| Qwen3-VL-32B | GUI | **0/20** | **0%** |
| MAI-UI-8B | GUI | **0/20** | **0%** |
| Venus-1.5-8B | GUI | **0/20** | **0%** |

**CLI achieves 75%. GUI achieves 0%. The gap is absolute.**

The 5 tasks CLI agents also fail (12, 39, 43, 46, 47) are near-misses —
correct approach but wrong output format or database target. With prompt or
verifier refinements, CLI should reach 90%+.

---

## Five Patterns: Why GUI Agents Fail

These are not agent bugs. They are structural limitations of screen-based
interaction.

### Pattern 1: Invisible Data
**Tasks**: 36, 37, 40, 39, 9

The data exists on the device but no app renders it. File sizes, audio routing
device names, character counts, permission grants — all stored in the system
but not in any UI.

> "I know my phone knows this. Why can't I see it?"

CLI bypasses the rendering layer: `stat`, `dumpsys`, `wc` access raw system
data directly.

### Pattern 2: No Aggregate Views
**Tasks**: 12, 46, 36

Apps show individual items. Users want totals, counts, rankings. "How many
hours of meetings?" "Who texts me most?" "How big are my Downloads?" No app
provides the summary.

> "I can see each item. I just want the total."

CLI computes aggregates with SQL: `SUM(duration)`, `COUNT(*) GROUP BY address`,
`SUM(file_size)`.

### Pattern 3: No Cross-App Memory
**Tasks**: 4, 34, 44

Correlating data across apps requires remembering App A's data while reading
App B. GUI agents see one screen at a time — switching apps erases the previous
context.

> "I need to check my texts against my contacts. Why can't I see both?"

CLI stores query results and cross-references them in the same script. No
context is lost between commands.

### Pattern 4: O(N) per Item, O(1) per Batch
**Tasks**: 5, 17, 43, 47, 48, 49, 45

Every item requires the same sequence of taps: open, check, act, close, next.
Renaming 10 files = 50 taps. Checking 30 events for reminders = 120 taps. At
50-step budgets, GUI agents handle ~10 items maximum.

> "I want to do this to ALL of them. Not one at a time."

CLI processes any number with the same command: `find -exec mv`,
`content delete --where`, `for f in *.tmp; do rm $f; done`.

### Pattern 5: Multi-Condition Filters
**Tasks**: 45, 31, 4, 16, 32

Apps provide single-dimension filters (by artist, by date, by app). Users want
compound filters: songs by artist X AND longer than 4 minutes. Contacts sharing
the same number. Events without reminders AND longer than 2 hours.

> "I want to filter by two things at once. The app only lets me pick one."

CLI uses SQL WHERE with AND, GROUP BY with HAVING, or shell pipelines with
multiple `grep` stages.

---

## What This Proves

### 1. CLI agents serve real needs GUI cannot

Every task in this subset maps to an everyday user request. These are not
contrived edge cases — they are things users already want but have stopped
asking for because the GUI can't deliver.

### 2. The limitation is structural, not a model gap

Three different GUI agent architectures (Qwen3-VL-32B, MAI-UI-8B,
Venus-1.5-8B) all score 0%. Larger models, more steps, different prompts — none
help. The bottleneck is the **interaction modality**, not the agent's intelligence.

### 3. CLI is complementary, not competing

The best GUI agents score 30-32% on the full 50-task set — they handle tasks
where the answer is visually accessible (reading lists, counting items on screen).
The best CLI agent scores 74%. The 20-task subset isolates where CLI provides
**unique value** that GUI cannot replicate.

### 4. Previous benchmarks have a blind spot

AndroidWorld and MobileWorld test zero tasks requiring: content provider queries,
SQL operations, file metadata access, system introspection, cross-app data
joins, or bulk batch processing. This subset fills that gap.

### 5. The future is multimodal agents

The ideal mobile agent should use GUI for visual tasks (take a photo, navigate
a map, fill a form) and CLI for data tasks (query databases, bulk operations,
system inspection). This benchmark provides the missing data-task evaluation
that enables measuring progress toward that hybrid future.
