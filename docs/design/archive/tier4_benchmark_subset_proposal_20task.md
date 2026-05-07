> **STATUS: SUPERSEDED.** Original 20-task proposal. Subsequent iterations
> grew to 25 → 40 → 38 → final 45-balanced. Current canonical subset:
> [`../tier4/cli_dataset_45_balanced.md`](../tier4/cli_dataset_45_balanced.md).

# Tier4 Benchmark Subset: 20-Task CLI-Exclusive Proposal

## Motivation

Existing Android agent benchmarks (AndroidWorld, MobileWorld) primarily test GUI
interaction. They do not measure an agent's ability to use **programmatic device
access** — shell commands, database queries, content providers, and system
introspection. This leaves a blind spot: tasks that are trivial via ADB but
impossible via screen taps.

We propose a **20-task subset** from our 50-task tier4 set that demonstrates
clear CLI advantage over GUI agents, covering scenarios previous benchmarks
don't consider.

## Evidence: CLI vs GUI Gap

| Agent | Type | Full 50 | 20-task subset |
|-------|------|--------:|---------------:|
| Opus 4.6 (tools) | CLI | 74% | **85-90%*** |
| Sonnet 4 (tools) | CLI | 64% | **75-80%*** |
| Qwen3-VL-32B | GUI | 32% | **0%** |
| MAI-UI-8B | GUI | 30% | **0%** |
| Venus-1.5-8B | GUI | 16% | **0%** |

\*Estimated after verifier fixes for the 5 promoted tasks.

## The 20-Task Subset

### Confirmed CLI-Only (15 tasks) — CLI solves, ALL GUI agents fail

These 15 tasks have been empirically validated: Opus CLI achieves 100% (15/15),
while no GUI agent solves any of them.

| # | Task | Category | CLI Method | Why GUI Fails |
|---|------|----------|------------|---------------|
| 4 | CrossAppSmsNumbersNotInContacts | Cross-app join | Query SMS + contacts content providers, compute set difference | Cannot cross-reference sender numbers against contact list across two apps |
| 5 | BulkRenameScreenshots | Bulk file op | `find` + `mv` in shell loop | No bulk rename in Files app; each file requires 6+ taps to rename |
| 9 | AggregationLongestMarkorNote | File metadata | `wc -c` on each file, sort | Character count not shown in any app UI |
| 16 | DedupContactsDuplicatePhones | Database dedup | Query contacts, GROUP BY phone number | No way to sort/search by phone number in Contacts UI |
| 17 | DedupMergeContactsSamePhone | Database dedup + delete | Same as 16, then `content delete` extras | Even identifying duplicates (task 16) fails via GUI |
| 31 | FilterRetroMusicMultiCondition | Media DB filter | Query media provider with WHERE artist AND duration | Can filter by artist in UI but not by duration threshold |
| 32 | TopKRetroMusicLongestSongs | Media DB sort | Query media provider ORDER BY duration DESC | No sort-by-duration option in Retro Music UI |
| 34 | CrossAppFilesCreatedDuringEvents | Cross-app timestamp join | `stat` files + query calendar events, compare timestamps | File modification times not shown in Files app UI |
| 36 | AggregationDownloadSizeTop3 | File metadata | `ls -la` or `stat` for file sizes, sum and sort | File sizes not readable or summable from Files app |
| 37 | TopKLargestDownloadFiles | File metadata | `ls -lS` sorted by size | No sort-by-size in Files app default view |
| 40 | HiddenStateAudioRouting | System introspection | `dumpsys audio` for routing device + volume | Audio routing device name not in any app UI |
| 44 | CrossAppCalendarToMarkor | Cross-app calendar→file | `content query` calendar + `write-file` to Markor | No calendar search; manual event→note transfer too slow |
| 45 | FilterCalendarLongNoReminder | Calendar DB multi-filter | SQL join events with reminders, filter by duration + title | Reminder status not shown in calendar list view; each event must be opened |
| 48 | TopKCalendarEarliestEvent | Calendar DB sort | `content query --sort "dtstart ASC"` | Must scroll backward through months/years; agents hit step limit |
| 49 | CoverageCalendarEventsHaveReminders | Calendar DB join | LEFT JOIN events with reminders table | Reminder status requires opening each event individually |

### Promoted from Neither-Solves (5 tasks) — GUI cannot solve, CLI agents are close

These 5 tasks are unsolved by current CLI agents due to minor issues (verifier
format mismatch, wrong database target, timestamp conversion). They are
fundamentally CLI-solvable and fundamentally GUI-unsolvable. With prompt or
verifier improvements, CLI agents should solve them.

| # | Task | Category | CLI Near-Miss | Fix Needed |
|---|------|----------|---------------|------------|
| 12 | TopKSmsThreadsByCount | SMS aggregation | Opus tried GROUP BY via content provider but ran out of steps | Better SQL strategy (client-side aggregation) |
| 14 | FilterContactsBirthdayNoPhone | Contact DB query | Agents queried contacts but missed birthday data table format | Query contacts `data` table for birthday MIME type |
| 43 | BulkDeleteCalendarTestEvents | Calendar bulk delete | Opus deleted from app's SQLite DB, not content provider | Use `content delete` instead of raw SQL |
| 46 | AggregationCalendarTotalDuration | Calendar timestamp math | Opus computed 1760 min but timezone offset was wrong | Correct UTC→local conversion before summing |
| 47 | DedupCalendarDeleteDuplicateEvents | Calendar dedup | Opus found and deleted duplicates but wrong count remaining | More precise GROUP BY + delete logic |

## GUI Failure Analysis: Representative Trajectories

### Case 1: Bulk File Rename (Task 5)

**Task**: Rename all `Screenshot_*` files in Pictures to a date-based format.

**Qwen3-VL trajectory** (6 steps, FAIL):
```
Step 1: swipe up → open app drawer
Step 2: tap Files app
Step 3: tap Pictures folder
Step 4: tap a file → opens viewer (wrong action, needed long-press to rename)
Step 5: tap another element
Step 6: terminate(success) — gave up, claimed files don't start with Screenshot_
```

**Why**: Files app has no bulk rename. Each file requires: long-press → "Rename" → clear old name → type new name → confirm. For N files, that's ~5N steps. The agent doesn't even attempt it and gives up after 6 steps.

**CLI solution** (Opus, 2 commands):
```bash
adb shell 'for f in /sdcard/Pictures/Screenshot_*; do
  ts=$(stat -c %Y "$f"); new=$(date -d @$ts +%Y%m%d_%H%M%S);
  mv "$f" "/sdcard/Pictures/IMG_${new}.png"; done'
adb shell ls /sdcard/Pictures/  # verify
```

**Gap**: GUI needs ~5N steps for N files; CLI needs 2 steps regardless of N.

### Case 2: Contact Dedup (Task 16)

**Task**: List groups of contacts sharing the same phone number.

**Qwen3-VL trajectory** (8 steps, FAIL):
```
Step 1: swipe up → open app drawer
Step 2: tap Contacts
Step 3: tap search
Step 4: search for a phone number → finds 2 contacts (AliceA, BobA)
Step 5: navigate back
Step 6: tap search again
Step 7: type another search → but doesn't know which number to search
Step 8: answer with partial result (only 1 group of 2)
```

**Why**: The agent found one duplicate group by guessing a number, but can't
systematically compare ALL contacts' numbers. There's no "group by phone" view.
The agent would need to open each contact, memorize the number, compare against
all others — O(N²) operations with no memory between steps.

**CLI solution** (Opus, 1 command):
```bash
adb shell content query --uri content://contacts/phones \
  --projection "display_name,number" | \
  sort -t= -k3 | uniq -d -f2
```

**Gap**: GUI requires O(N²) visual comparisons; CLI does it in a single GROUP BY query.

### Case 3: Cross-App Timestamp Join (Task 34)

**Task**: List files in Downloads whose modification time falls within any calendar event's time range.

**Qwen3-VL trajectory** (10 steps, FAIL):
```
Step 1-2: open Files app, browse Downloads → sees files but NO timestamps
Step 3-5: open Calendar app, browse events → sees event times
Step 6-7: navigate home, try to correlate mentally
Step 8-10: give up — cannot see file timestamps and event times simultaneously
```

**Why**: File timestamps are not shown in the Files app. Even if they were, the
agent would need to hold N file timestamps in "memory" while checking M calendar
events — an N×M cross-join that's impossible without persistent state between
screenshots.

**CLI solution** (Opus, 3 commands):
```bash
# Get calendar event time ranges
adb shell content query --uri content://calendar/events --projection "dtstart,dtend"
# Get file modification times
adb shell stat -c '%Y %n' /sdcard/Download/*
# Compare (in-shell loop)
```

**Gap**: GUI cannot access file timestamps at all. Even with timestamps visible, cross-referencing requires persistent state that GUI agents lack.

### Case 4: Hidden System State (Task 40)

**Task**: What is the current audio output routing device and media volume level?

**Qwen3-VL trajectory** (14 steps, FAIL):
```
Step 1: tap Settings
Step 2: tap Sound & Vibration
Step 3-8: scroll through sound settings — sees volume sliders but no routing info
Step 9-14: keep scrolling, looking for "output device" — it doesn't exist in UI
```

**Why**: Audio routing (speaker/headset/Bluetooth) is an internal system state
managed by the AudioManager. No settings screen displays the current routing
device name. The volume slider shows a visual level but not a numeric value.

**CLI solution** (Opus, 2 commands):
```bash
adb shell dumpsys audio | grep "output device"
adb shell settings get system volume_music_speaker
```

**Gap**: The information simply does not exist in any Android UI. It's only
accessible via `dumpsys` system introspection.

### Case 5: Calendar Multi-Condition Filter (Task 45)

**Task**: List events with no reminder, >2 hours duration, and 'meeting' in title.

**Qwen3-VL trajectory** (16 steps, FAIL):
```
Step 1-2: open Simple Calendar Pro
Step 3-6: browse calendar day by day, tap into events
Step 7-10: check event details — can see title and time but NOT reminder status
Step 11-16: continue browsing, can't determine which events have no reminders
```

**Why**: Three conditions must be checked per event (title contains 'meeting',
duration >2 hours, no reminder set). Title and duration are visible when opening
an event, but **reminder status** is only shown in the edit view, not the detail
view. Even checking all three conditions for one event takes 3-4 taps. With many
events across the month, the step budget is exhausted.

**CLI solution** (Opus, 1 query):
```sql
SELECT e.title, e.dtstart, e.dtend FROM Events e
LEFT JOIN Reminders r ON e._id = r.event_id
WHERE e.title LIKE '%meeting%'
  AND (e.dtend - e.dtstart) > 7200000
  AND r.event_id IS NULL
```

**Gap**: GUI requires ~4 taps per event to check 3 conditions, and one condition
(reminder) is hidden behind an extra edit screen. CLI does it in one SQL query
with a JOIN.

## Why 20 Tasks Is Sufficient

1. **Clear signal**: 0% GUI vs 75-100% CLI on the subset — no ambiguity
2. **Category coverage**: The 20 tasks span 7 distinct failure modes:
   - Cross-app data joins (4 tasks)
   - Database dedup/aggregation (4 tasks)
   - File metadata queries (3 tasks)
   - Calendar content provider ops (4 tasks)
   - Hidden system state (1 task)
   - Bulk file operations (1 task)
   - Media database queries (2 tasks)
   - SMS aggregation (1 task)
3. **Comparable to existing benchmarks**: AndroidWorld's original 116 tasks
   include subsets of similar size (47 easy, 25 medium, 16 hard). A 20-task
   focused subset is standard practice.
4. **Reproducible failure modes**: The GUI failures are not random — they're
   structural. The same tasks fail across 3 different GUI agents (Qwen3-VL,
   MAI-UI, Venus), confirming the failures are inherent to GUI interaction,
   not agent-specific bugs.

## What Previous Benchmarks Miss

| Capability | AndroidWorld (116) | MobileWorld (117) | **Tier4 Subset (20)** |
|------------|:------------------:|:-----------------:|:---------------------:|
| GUI tap/swipe/type | Tested | Tested | Not relevant |
| App navigation | Tested | Tested | Not relevant |
| Content provider queries | Not tested | Not tested | **Tested (8 tasks)** |
| Database SQL operations | Not tested | Not tested | **Tested (6 tasks)** |
| Cross-app data correlation | Minimal (2 tasks) | Not tested | **Tested (4 tasks)** |
| File system metadata | Not tested | Not tested | **Tested (3 tasks)** |
| System introspection | Not tested | Not tested | **Tested (1 task)** |
| Bulk batch operations | Not tested | Not tested | **Tested (2 tasks)** |

The tier4 subset fills a **measurement gap**: it tests whether agents can use
programmatic device access (ADB, SQL, content providers) to solve tasks that
are structurally impossible via screen interaction.
