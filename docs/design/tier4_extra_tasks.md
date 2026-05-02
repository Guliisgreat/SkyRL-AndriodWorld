# Tier4 Extra Tasks — 27 New GUI-Exclusive Benchmarks

Added to expand the tier4 benchmark from 50 → 77 tasks. All classes are
prefixed `Tier4Extra*` and marked with `# ── tier4_extra ──` comments in source.
No existing task logic was modified.

## Eval Patterns

Two evaluation patterns are used across all tasks:

- **Output-check**: The agent reports an answer via `FINISH(content='...')`.
  The evaluator reads `env.interaction_cache` and compares against
  `_ground_truth`. Numeric answers allow a tolerance (±1–2).
- **State-check**: The agent modifies device state (creates files, deletes
  rows, inserts reminders, etc.). The evaluator queries the device via ADB
  content providers, SQLite, or filesystem commands to verify the change.

## Why GUI-Exclusive

Each task satisfies at least one of:

| Condition | Meaning |
|-----------|---------|
| A — Hidden state | Value never rendered on any app screen (dumpsys, /proc, pm) |
| B — Cross-app join | Requires correlating data from 2+ apps |
| C — Aggregation | Answer is a computed value (AVG, SUM, COUNT, ratio) no app displays |
| D — Completeness | Proving "all X satisfy Y" requires exhaustive enumeration |

---

## 1. System (5 tasks) — `system.py`

All use hidden system data that no GUI app exposes.

### 1.1 Tier4ExtraHiddenStateRemainingStorage

| Field | Value |
|-------|-------|
| App | settings |
| Complexity | 1.2 |
| Eval | output-check |
| GUI-exclusive | A — `df /data` free-space value never shown in Settings UI |
| Template | How much free storage space is remaining on the device (internal storage)? Output the amount in GB (rounded to 1 decimal place). |

**Eval logic**: Runs `df /data`, parses Available column (1K-blocks), converts to GB. Checks `interaction_cache` for a number within ±0.5 GB tolerance.

### 1.2 Tier4ExtraHiddenStateRecentInstalls

| Field | Value |
|-------|-------|
| App | settings |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | A — `dumpsys package` firstInstallTime not shown in Settings |
| Template | What are the 3 most recently installed apps on the device? Output their package names. |

**Eval logic**: Parses `firstInstallTime` from `dumpsys package packages`, sorts descending, stores top 3. Checks all 3 package names appear in cache.

### 1.3 Tier4ExtraHiddenStateUptime

| Field | Value |
|-------|-------|
| App | settings |
| Complexity | 1.0 |
| Eval | output-check |
| GUI-exclusive | A — `/proc/uptime` not accessible via GUI |
| Template | How long has the device been running since last reboot? Output the uptime in hours and minutes. |

**Eval logic**: Reads `/proc/uptime`, converts to hours+minutes. Checks both values in cache with ±2 min tolerance.

### 1.4 Tier4ExtraHiddenStateBatteryDrain

| Field | Value |
|-------|-------|
| App | settings |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | A — `dumpsys batterystats` per-app drain not shown in Settings |
| Template | Which app has consumed the most battery since last full charge? Output the app package name and its estimated battery usage percentage. |

**Eval logic**: Parses `dumpsys batterystats` "Estimated power use" section for per-UID usage. Finds top consumer, checks package name (or last segment) in cache. Percentage within ±2% tolerance earns 1.0; package-only earns 0.5.

### 1.5 Tier4ExtraHiddenStateMobileDataUsage

| Field | Value |
|-------|-------|
| App | settings |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | A — `dumpsys netstats detail` per-app mobile data not shown in Settings |
| Template | Which app has used the most mobile data (cellular data) on the device? Output the app package name and approximate data usage in MB. |

**Eval logic**: Parses `dumpsys netstats detail` for mobile interface (rmnet) sections, sums rxBytes+txBytes per UID. Maps top UID to package via `pm list packages --uid`. Checks package name in cache; MB within ±5 MB earns 1.0; package-only earns 0.5.

---

## 2. SMS (4 tasks) — `sms.py`

Use `content://sms/inbox` content provider for data setup and evaluation.

### 2.1 Tier4ExtraAggregationSmsAvgLength

| Field | Value |
|-------|-------|
| App | simple sms messenger |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | C — Average character length is a computed value not shown in any SMS app |
| Template | What is the average character length of all SMS messages in your inbox? Output the number (rounded to nearest integer). |

**Eval logic**: Seeds 5 SMS with known body lengths. Stores `round(total_chars / count)`. Checks cache for matching number ±2.

### 2.2 Tier4ExtraFilterSmsContainingUrl

| Field | Value |
|-------|-------|
| App | simple sms messenger |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | C — SMS app has no URL filter; requires regex scan over all messages |
| Template | List all SMS messages in the inbox that contain a URL (http:// or https://). Output the sender phone numbers. |

**Eval logic**: Seeds 2 SMS with URLs + 3 without. Stores sender numbers of URL-containing messages. Checks all appear in cache (normalized).

### 2.3 Tier4ExtraTopKSmsOldestMessages

| Field | Value |
|-------|-------|
| App | simple sms messenger |
| Complexity | 1.2 |
| Eval | output-check |
| GUI-exclusive | C — SMS app shows newest first; reliably identifying 3 oldest across 7 requires sorting by date field |
| Template | What are the 3 oldest SMS messages in your inbox? List the sender phone numbers. |

**Eval logic**: Seeds 7 SMS with varying date offsets (0–90 days). Sorts by date ascending, stores 3 oldest sender numbers. Checks all in cache.

### 2.4 Tier4ExtraCoverageSmsAllFromKnownContacts

| Field | Value |
|-------|-------|
| App | simple sms messenger, contacts |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | B+D — Cross-app join (SMS × Contacts) + completeness proof |
| Template | Are all SMS messages in the inbox from phone numbers that are in your contacts? If yes, output 'all known'. If not, output how many are from unknown numbers. |

**Eval logic**: Two variants (`all_known` / `has_unknown`). Seeds 3 contact SMS ± 2 unknown SMS. Checks for "all known" or count in cache. Parameterized via `variant`.

---

## 3. Files (3 tasks) — `files.py`

Filesystem operations on `/storage/emulated/0/Download/`.

### 3.1 Tier4ExtraAggregationFileCountByExtension

| Field | Value |
|-------|-------|
| App | files |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | C — Files app shows files but not per-extension counts |
| Template | Count how many files of each extension type (.txt, .log, .bin, .dat) are in the Downloads folder. Output the counts per extension. |

**Eval logic**: Creates files with known extension distribution (3 txt, 2 log, 4 bin, 1 dat). Checks all counts appear in cache.

### 3.2 Tier4ExtraFilterEmptyFilesInDownloads

| Field | Value |
|-------|-------|
| App | files |
| Complexity | 1.2 |
| Eval | output-check |
| GUI-exclusive | C — Files app doesn't filter by size=0; needs `find -empty` or `stat` |
| Template | List all zero-byte (empty) files in the Downloads folder. Output the filenames. |

**Eval logic**: Creates 3 empty files (via `touch`) + 2 non-empty. Checks all 3 empty filenames in cache.

### 3.3 Tier4ExtraBulkFlattenSubdirectories

| Field | Value |
|-------|-------|
| App | files |
| Complexity | 1.5 |
| Eval | state-check |
| GUI-exclusive | D — Files app can move one-by-one; bulk flatten + rmdir requires shell |
| Template | Move all files from any subdirectories within Downloads into the Downloads root folder, then remove the empty subdirectories. |

**Eval logic**: Creates 2 subdirectories with 2 files each. Verifies: (1) all 4 files exist at Downloads root (`find -maxdepth 1`), (2) subdirectories no longer exist (`test -d`).

---

## 4. Calendar (4 tasks) — `calendar.py`

Use `content://com.android.calendar/events` and `content://com.android.calendar/reminders`.
All events use cleanup prefix `tier4cal_`.

### 4.1 Tier4ExtraAggregationCalendarEventsPerDay

| Field | Value |
|-------|-------|
| App | simple calendar pro |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | C — Calendar shows daily view but doesn't compute "busiest day" |
| Template | Which day this month has the most calendar events in Simple Calendar Pro? Output the date and the number of events. |

**Eval logic**: Distributes events across 4 days (4, 3, 2, 1 events). Checks that count "4" and day "5" appear in cache.

### 4.2 Tier4ExtraFilterCalendarWeekendEvents

| Field | Value |
|-------|-------|
| App | simple calendar pro |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | C — Calendar app doesn't have a "weekend only" filter |
| Template | List all calendar events in Simple Calendar Pro that start on a Saturday or Sunday. Output the event titles. |

**Eval logic**: Creates 14 events (one per day for 2 weeks). Computes which fall on Saturday/Sunday via `weekday()`. Checks all weekend event titles in cache.

### 4.3 Tier4ExtraTopKCalendarLongestEvents

| Field | Value |
|-------|-------|
| App | simple calendar pro |
| Complexity | 1.2 |
| Eval | output-check |
| GUI-exclusive | C — Calendar doesn't sort by duration; requires computing dtend-dtstart |
| Template | What are the 3 longest calendar events by duration in Simple Calendar Pro? Output the event titles. |

**Eval logic**: Creates 7 events with durations 30–240 min (shuffled). Sorts by duration, stores top 3 titles. Checks all in cache.

### 4.4 Tier4ExtraBulkAddReminderToAllEvents

| Field | Value |
|-------|-------|
| App | simple calendar pro |
| Complexity | 2.0 |
| Eval | state-check |
| GUI-exclusive | D — Adding reminders one-by-one via GUI is possible but identifying which lack reminders requires cross-querying events × reminders tables |
| Template | Add a 15-minute reminder to all calendar events in Simple Calendar Pro that do not already have a reminder set. |

**Eval logic**: Creates 3 events without reminders + 2 with. Queries `content://com.android.calendar/reminders` for each event that needed one. Returns 0.0 if "No result found" for any.

---

## 5. Expense (5 tasks) — `expense.py`

Use SQLite DB at `/data/data/com.arduia.expense/databases/accounting.db`, table `expense`.

### 5.1 Tier4ExtraAggregationExpenseAvgPerCategory

| Field | Value |
|-------|-------|
| App | pro expense |
| Complexity | 2.0 |
| Eval | output-check |
| GUI-exclusive | C — App shows individual expenses, not per-category averages |
| Template | What is the average expense amount (in dollars) per category this month in Pro Expense? Output each category and its average. |

**Eval logic**: Seeds 3 categories with known amounts (Food avg=$6.67, Housing avg=$25.00, Entertainment avg=$4.00). Checks "housing" and "food" appear in cache.

### 5.2 Tier4ExtraFilterExpenseAboveAverage

| Field | Value |
|-------|-------|
| App | pro expense |
| Complexity | 1.5 |
| Eval | output-check |
| GUI-exclusive | C — "Above average" requires computing the mean first; app has no such filter |
| Template | List all expenses in Pro Expense whose amount is above the overall average. Output the expense names. |

**Eval logic**: Seeds 5 expenses [100, 200, 500, 1000, 3000], avg=960. Two above average (1000, 3000). Checks their names in cache.

### 5.3 Tier4ExtraTopKExpenseDaysMostSpent

| Field | Value |
|-------|-------|
| App | pro expense |
| Complexity | 2.0 |
| Eval | output-check |
| GUI-exclusive | C — App doesn't aggregate spending per day |
| Template | What are the 3 days this month with the highest total spending in Pro Expense? Output the dates. |

**Eval logic**: Seeds expenses across 5 days with known totals (day 1: 10000, day 7: 8000, day 3: 5000, day 12: 3000, day 9: 2000). Top 3 = days 1, 7, 3. Checks dates or day numbers in cache.

### 5.4 Tier4ExtraCoverageExpenseAllCategorized

| Field | Value |
|-------|-------|
| App | pro expense |
| Complexity | 1.2 |
| Eval | output-check |
| GUI-exclusive | D — Completeness proof; app doesn't flag uncategorized entries |
| Template | Verify that all expenses in Pro Expense have a valid category assigned. If any are uncategorized (category 0 or missing), output their names. If all are categorized, output 'all categorized'. |

**Eval logic**: Two variants (`all_valid` / `has_uncategorized`). Seeds 3 valid + optionally 2 with category=0. Checks "all categorized" or uncategorized names in cache. Parameterized via `variant`.

### 5.5 Tier4ExtraBulkDeleteSmallExpenses

| Field | Value |
|-------|-------|
| App | pro expense |
| Complexity | 1.5 |
| Eval | state-check |
| GUI-exclusive | D — App has no "delete all below threshold" filter; requires DB query + batch delete |
| Template | Delete all expenses in Pro Expense that are less than $1.00 (less than 100 cents). |

**Eval logic**: Seeds 3 tiny (<100 cents) + 3 normal (>=100). Reads back all expenses from DB. Returns 0.0 if any tiny name remains or any normal name is missing.

---

## 6. Cross-App (6 tasks) — `cross_app.py`

Each task requires data from 2+ apps. Cleanup prefix `tier4xa_`.

### 6.1 Tier4ExtraCrossAppContactsToMarkor

| Field | Value |
|-------|-------|
| Apps | contacts, markor |
| Complexity | 2.0 |
| Eval | state-check |
| GUI-exclusive | B — Cross-app: read contacts → write Markor file |
| Template | Export all contacts (name and phone number) to a Markor note named 'contacts_export.md'. Write one contact per line. |

**Eval logic**: Seeds 3 contacts. Reads `contacts_export.md` via `cat`. Returns 1.0 if all 3 names appear in file content.

### 6.2 Tier4ExtraCrossAppCalendarSmsConflicts

| Field | Value |
|-------|-------|
| Apps | simple calendar pro, simple sms messenger |
| Complexity | 2.5 |
| Eval | output-check |
| GUI-exclusive | B — Time-range join: SMS.date ∈ [event.dtstart, event.dtend] |
| Template | List all SMS messages that were received during an active calendar event. Output the sender phone numbers. |

**Eval logic**: Creates 1 event (2h ago → 1h ago) + 2 SMS during window + 1 outside. Checks during-event sender numbers in cache.

### 6.3 Tier4ExtraCrossAppExpenseVsCalendar

| Field | Value |
|-------|-------|
| Apps | pro expense, simple calendar pro |
| Complexity | 2.5 |
| Eval | output-check |
| GUI-exclusive | B — Date join: expense.created_date same day as event.dtstart |
| Template | For each calendar event this week, check if any expenses were recorded on the same day. List the event titles that have associated expenses. |

**Eval logic**: Creates 3 events (today, yesterday, 2 days ago). Inserts expenses on today + yesterday only. Checks 2 matching event titles in cache.

### 6.4 Tier4ExtraCrossAppSmsKeywordToTasks

| Field | Value |
|-------|-------|
| Apps | simple sms messenger, tasks |
| Complexity | 2.0 |
| Eval | state-check |
| GUI-exclusive | B — Cross-app: filter SMS → create Tasks entries |
| Template | Find all SMS messages containing the word 'urgent' and create a task in the Tasks app for each one, using the SMS body as the task title. |

**Eval logic**: Seeds 2 "urgent" SMS + 1 normal. Reads Tasks DB (`org.tasks`). Returns 1.0 if both urgent bodies found in task titles.

### 6.5 Tier4ExtraCrossAppOpenTracksToMarkor

| Field | Value |
|-------|-------|
| Apps | activity tracker (OpenTracks), markor |
| Complexity | 2.5 |
| Eval | state-check |
| GUI-exclusive | B — Cross-app: aggregate OpenTracks DB → write Markor file |
| Template | Summarize this week's activities from OpenTracks (total distance in km and number of activities) and write the summary to a Markor note named 'weekly_stats.md'. |

**Eval logic**: Seeds 3 activities with known distances (5+3.2+12 = 20.2 km). Reads `weekly_stats.md`. Checks count "3" and distance within ±0.5 km.

### 6.6 Tier4ExtraCrossAppJoplinToCalendar

| Field | Value |
|-------|-------|
| Apps | joplin, simple calendar pro |
| Complexity | 2.5 |
| Eval | state-check |
| GUI-exclusive | B — Cross-app: filter Joplin DB → create Calendar events |
| Template | Find all Joplin notes whose body contains 'TODO'. For each such note, create a calendar event with the note title as the event title, scheduled for tomorrow at 9 AM. |

**Eval logic**: Seeds 2 notes with "TODO" + 2 without. Queries calendar events. Returns 1.0 if both TODO note titles appear as event titles.

---

## Summary

| Category | Count | Eval Pattern | GUI-Exclusive Reason |
|----------|-------|-------------|---------------------|
| System | 5 | all output-check | A — Hidden state (dumpsys/proc/pm) |
| SMS | 4 | 3 output-check, 1 output-check (variant) | C — Aggregation / D — Completeness |
| Files | 3 | 2 output-check, 1 state-check | C — Aggregation / D — Completeness |
| Calendar | 4 | 3 output-check, 1 state-check | C — Aggregation / D — Completeness |
| Expense | 5 | 3 output-check, 2 state-check | C — Aggregation / D — Completeness |
| Cross-app | 6 | 2 output-check, 4 state-check | B — Cross-app join |
| **Total** | **27** | **18 output-check, 9 state-check** | |

All 27 tasks have unit tests in `tier4_extra_test.py` (27 test classes, 37 test methods).
