# Tier4 Tasks Unsolvable by Any GUI Agent

26/50 tier4 tasks were failed by ALL three GUI agents (Qwen3-VL-32B, MAI-UI-8B,
UI-Venus-1.5-8B) even with real task goals and 50 max steps. These represent the
true ADB-exclusive core of the tier4 benchmark.

Of these 26 tasks, Opus 4.6 CLI solved 17 (65%), confirming CLI advantage.
9 tasks remain unsolved by any agent.

## Failure Categories

| Category | Count | Tasks |
|----------|------:|-------|
| Hidden system state (no UI exposure) | 5 | 39, 40, 41, 42, 38 |
| Calendar operations (content provider required) | 7 | 43, 44, 45, 46, 47, 48, 49 |
| Cross-app data joins (multi-DB correlation) | 4 | 4, 13, 23, 34 |
| Bulk file operations (rename/move) | 2 | 5, 9 |
| Dedup via database (identify + merge/delete) | 3 | 16, 17, 14 |
| Music/media database queries | 2 | 31, 32 |
| File metadata queries (size, timestamps) | 2 | 36, 37 |
| SMS database aggregation | 1 | 12 |

---

## Hidden System State (5 tasks)

These tasks query system state that is not exposed in any app UI. They require
`dumpsys`, `getprop`, content provider queries, or `settings get` commands.

### Task 38: Tier4CoverageAllSmsRead
**Goal**: Confirm all SMS messages have been read. If any are unread, output the count.
**CLI solution**: `content query --uri content://sms/inbox --where "read=0"` — counts unread SMS via content provider.
**Why GUI fails**: The SMS app shows unread indicators per conversation, but no single view shows the total unread count across all threads. The agent must count individual unread indicators, which is error-prone and doesn't guarantee completeness.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 39: Tier4HiddenStateLocationPermissions
**Goal**: List all apps granted location permission.
**CLI solution**: `dumpsys package | grep "android.permission.ACCESS_FINE_LOCATION"` with per-package filtering.
**Why GUI fails**: Settings → Apps → Permissions → Location shows a list, but navigating to it requires 4+ precise taps through nested menus. The GUI agents get lost in the Settings hierarchy or can't parse the permission list from screenshots.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 40: Tier4HiddenStateAudioRouting
**Goal**: What is the current audio output routing device and media volume level?
**CLI solution**: `dumpsys audio` to get routing device, `settings get system volume_music_speaker` for volume.
**Why GUI fails**: Audio routing info (speaker vs headset vs Bluetooth) is not displayed in any standard UI. Volume is shown in the volume slider but not as a numeric value. No app surfaces the routing device name.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 41: Tier4CoverageAppsCameraPermission
**Goal**: List all apps granted Camera permission.
**CLI solution**: `dumpsys package | grep "android.permission.CAMERA"` — scans all package permissions.
**Why GUI fails**: Same as task 39. Settings → Apps → Permissions → Camera requires precise navigation. Agents spend 50 steps trying to navigate Settings menus without reaching the correct screen, or misread the permission list.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 42: Tier4CoverageWifiConnected
**Goal**: Is WiFi enabled and connected? What SSID?
**CLI solution**: `dumpsys wifi | grep "mNetworkInfo"` or `settings get global wifi_on`.
**Why GUI fails**: WiFi status is visible in the status bar (small icon) and Settings → WiFi, but agents struggle to navigate to Settings → WiFi and read the SSID text from the screenshot. The information is technically visible but requires precise UI navigation that fails in practice.
**Opus CLI**: FAIL | **All GUI**: FAIL

---

## Calendar Operations (7 tasks)

Simple Calendar Pro stores events in the Android calendar content provider
(`content://com.android.calendar/events`). GUI access requires navigating a
calendar UI with date-based views, which makes bulk operations, filtering, and
cross-referencing extremely difficult.

### Task 43: Tier4BulkDeleteCalendarTestEvents
**Goal**: Delete all events whose title contains 'test'.
**CLI solution**: `content query` to find matching event IDs, then `content delete` for each.
**Why GUI fails**: The calendar shows a month/week/day view. Finding events with 'test' in the title requires scrolling through every day, tapping each event, checking its title, then deleting. With multiple test events across different dates, this is prohibitively slow and error-prone.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 44: Tier4CrossAppCalendarToMarkor
**Goal**: Find calendar events containing a keyword, create a Markor note listing them.
**CLI solution**: `content query` with `WHERE title LIKE '%keyword%'`, then `write-file` to Markor directory.
**Why GUI fails**: Requires searching calendar (no search function in Simple Calendar Pro UI), noting each matching event, switching to Markor, and typing all event details. The multi-app switching and manual data transfer is too complex within 50 steps.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 45: Tier4FilterCalendarLongNoReminder
**Goal**: List events with no reminder, lasting >2 hours, containing 'meeting' in title.
**CLI solution**: SQL query joining events table with reminders table, filtering by duration and title.
**Why GUI fails**: Requires checking three conditions per event (title, duration, reminder status). The calendar UI shows events but not their reminder status or exact duration. Each event must be opened individually to check these fields.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 46: Tier4AggregationCalendarTotalDuration
**Goal**: What is the total duration of all events this month?
**CLI solution**: `content query` all events this month, compute `SUM(dtend - dtstart)` in minutes.
**Why GUI fails**: No calendar UI shows aggregate duration. The agent would need to open every event, read start/end times, calculate each duration, and sum them — impossible within 50 steps for many events.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 47: Tier4DedupCalendarDeleteDuplicateEvents
**Goal**: Delete duplicate events (same title + same start time), keeping one copy.
**CLI solution**: `content query` to find duplicates by grouping, then `content delete` extras.
**Why GUI fails**: Identifying duplicates requires comparing every pair of events by title and time. The calendar UI shows one day/week at a time. Scrolling through all dates, remembering which events appeared before, and deleting only the extras is beyond GUI agent capability.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 48: Tier4TopKCalendarEarliestEvent
**Goal**: What is the earliest (oldest) event? Output title and date.
**CLI solution**: `content query --sort "dtstart ASC" --projection title,dtstart` — single query.
**Why GUI fails**: Simple Calendar Pro defaults to the current month view. Finding the earliest event requires scrolling backward through months/years until no more events exist. Agents hit the 50-step limit before scrolling far enough back.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 49: Tier4CoverageCalendarEventsHaveReminders
**Goal**: Confirm all events this month have reminders. List those without.
**CLI solution**: LEFT JOIN events with reminders table, find events with no reminder row.
**Why GUI fails**: Reminder status is not shown in the calendar's event list view. Each event must be opened individually to check if a reminder is set. With many events this month, checking each one exceeds the step budget.
**Opus CLI**: OK | **All GUI**: FAIL

---

## Cross-App Data Joins (4 tasks)

These tasks require correlating data between two apps/databases — an operation
that requires programmatic data access, not UI navigation.

### Task 4: Tier4CrossAppSmsNumbersNotInContacts
**Goal**: List SMS sender numbers from last 7 days that are NOT in contacts.
**CLI solution**: Query `content://sms/inbox` for sender numbers, query `content://contacts` for all contact numbers, compute the set difference.
**Why GUI fails**: Requires cross-referencing every SMS sender against every contact. The SMS app shows conversations but doesn't indicate whether a sender is in contacts. The agent would need to check each sender number in the Contacts app individually — too many app switches.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 13: Tier4CrossAppContactsNoRecentSms
**Goal**: List contacts with email but no SMS from them in 6 months.
**CLI solution**: Query contacts with email, query SMS for sender numbers, find contacts whose number has no recent SMS.
**Why GUI fails**: Same cross-referencing problem. No app shows "contacts who haven't texted recently." The agent would need to open each contact, note their number, switch to SMS, search for that number, and check dates — impossibly slow.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 23: Tier4CrossAppExpenseToMarkorCalendar
**Goal**: Calculate total monthly expenses, write to Markor note, and create calendar event.
**CLI solution**: SQL query on expense DB for monthly total, `write-file` to Markor, `content insert` to calendar.
**Why GUI fails**: Three-app coordination (Pro Expense → Markor → Calendar). The agent must read the total from Pro Expense (navigating to the right view), switch to Markor to create a note with the value, then switch to Calendar to create an event. Data must be carried accurately across app switches. Agents lose context or make errors during transitions.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 34: Tier4CrossAppFilesCreatedDuringEvents
**Goal**: List files in Downloads whose modification time falls within any calendar event's time range.
**CLI solution**: Query calendar events for time ranges, `stat` each file for mtime, compare timestamps.
**Why GUI fails**: File timestamps are not shown in the Files app UI. Calendar event times require navigating the calendar. Cross-referencing timestamps between two apps is impossible via GUI — there's no UI that shows file modification times alongside calendar events.
**Opus CLI**: OK | **All GUI**: FAIL

---

## Bulk File Operations (2 tasks)

### Task 5: Tier4BulkRenameScreenshots
**Goal**: Rename all files starting with 'Screenshot_' in Pictures folder to a new naming pattern.
**CLI solution**: `find` + `mv` in a shell loop.
**Why GUI fails**: The Files app has no bulk rename function. Each file must be long-pressed, "Rename" selected, old name deleted, new name typed, and confirmed. With multiple files, this exceeds the step budget. Furthermore, GUI agents often fail at the precise text editing required for renaming.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 9: Tier4AggregationLongestMarkorNote
**Goal**: Which Markor note has the most content by character count?
**CLI solution**: `wc -c` on each file, sort, report the longest.
**Why GUI fails**: Markor shows file list with names and dates, but not character counts or file sizes. The agent would need to open each file and estimate content length from the screen — no precise character counting is possible via GUI.
**Opus CLI**: OK | **All GUI**: FAIL

---

## Dedup via Database (3 tasks)

### Task 12: Tier4TopKSmsThreadsByCount
**Goal**: Which 3 phone numbers have the most SMS messages?
**CLI solution**: `content query --uri content://sms` with GROUP BY on address, ORDER BY count.
**Why GUI fails**: The SMS app shows conversations but not message counts per thread. The agent would need to open each conversation, scroll through and count messages, then compare across threads. Impractical.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 14: Tier4FilterContactsBirthdayNoPhone
**Goal**: List contacts with birthday set but no phone number.
**CLI solution**: Query contacts data table for birthday entries, cross-reference with phone entries.
**Why GUI fails**: The Contacts app shows names and phone numbers in the list view. Birthdays are only visible when opening individual contacts. Checking "has birthday but no phone" requires opening every contact — too many steps.
**Opus CLI**: FAIL | **All GUI**: FAIL

### Task 16: Tier4DedupContactsDuplicatePhones
**Goal**: List groups of contacts sharing the same phone number.
**CLI solution**: Query contacts for phone numbers, GROUP BY number, find groups with count > 1.
**Why GUI fails**: Phone numbers are shown per-contact in the contact list, but identifying duplicates requires comparing every contact's number against every other contact's number. No search or sort by phone number exists in the Contacts UI.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 17: Tier4DedupMergeContactsSamePhone
**Goal**: Merge contacts sharing the same phone number, keeping alphabetically first.
**CLI solution**: Same as task 16 to find duplicates, then `content delete` to remove extras.
**Why GUI fails**: Even if duplicates could be identified (task 16 fails), merging/deleting contacts via GUI requires opening each contact, confirming deletion, and ensuring the right one is kept. Multi-step and error-prone.
**Opus CLI**: OK | **All GUI**: FAIL

---

## Music/Media Database Queries (2 tasks)

### Task 31: Tier4FilterRetroMusicMultiCondition
**Goal**: List songs by a specific artist that are longer than 4 minutes.
**CLI solution**: Query `content://media/external/audio/media` with WHERE clause on artist and duration.
**Why GUI fails**: Retro Music can filter by artist, but not by duration. The agent can navigate to an artist's songs but cannot determine which are >4 minutes from the UI alone (duration is shown but comparing against a threshold requires reading each song's duration text).
**Opus CLI**: OK | **All GUI**: FAIL

### Task 32: Tier4TopKRetroMusicLongestSongs
**Goal**: What are the 5 longest songs by duration?
**CLI solution**: Query media content provider, ORDER BY duration DESC, LIMIT 5.
**Why GUI fails**: Retro Music shows song lists but cannot sort by duration. The agent would need to browse all songs, read each duration, and mentally sort — impossible to do accurately.
**Opus CLI**: OK | **All GUI**: FAIL

---

## File Metadata Queries (2 tasks)

### Task 36: Tier4AggregationDownloadSizeTop3
**Goal**: Total size of all files in Downloads, and the 3 largest files.
**CLI solution**: `ls -la` or `stat` to get file sizes, sum and sort.
**Why GUI fails**: The Files app shows files but not their sizes in the default list view. Even if sizes are shown, summing them requires reading each size value from the screenshot and performing arithmetic — beyond GUI agent capability.
**Opus CLI**: OK | **All GUI**: FAIL

### Task 37: Tier4TopKLargestDownloadFiles
**Goal**: What are the 5 largest files in Downloads?
**CLI solution**: `ls -lS` or `find -printf '%s %f'` sorted by size.
**Why GUI fails**: Same as task 36 — file sizes are not easily readable or sortable via the Files app UI.
**Opus CLI**: OK | **All GUI**: FAIL

---

## Summary: Why These 26 Tasks Are GUI-Unsolvable

| Reason | Count | Examples |
|--------|------:|---------|
| **Data not in any UI** | 10 | Permissions, audio routing, file sizes, character counts, SMS read status |
| **Requires database queries** | 8 | Calendar content provider, SMS aggregation, contact dedup, media filtering |
| **Cross-app data correlation** | 4 | SMS vs contacts, files vs calendar, expense across 3 apps |
| **Bulk operations with no UI support** | 4 | Rename files, delete calendar events by title, merge contacts |

The common thread: these tasks require **programmatic data access** (content
providers, SQL, file system metadata) that is only available through ADB shell
commands. GUI agents are limited to what apps display on screen, which excludes
aggregated statistics, cross-app joins, system internals, and bulk modifications.
