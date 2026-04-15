# Tier 4: Filling the Benchmark Gap with 50 ADB-Exclusive Tasks

**Date:** 2026-03-25

---

## 1. The Gap

AndroidWorld's original benchmark contains 91 action tasks and 25 information-retrieval tasks, all designed for GUI agents that interact with the device through screen taps and swipes. This design choice reflects the dominant agent paradigm at the time: a model observes a screenshot, produces a tap/swipe action, and the cycle repeats.

The benchmark works well for what it measures. The problem is what it cannot measure.

A growing class of agents operates via ADB shell — querying content providers directly, running SQL against app databases, using `dumpsys` for system introspection, and issuing batch file operations. These agents bypass the screen entirely. On the original 91+25 tasks, a competent ADB agent and a competent GUI agent are evaluated on tasks where the screen is the intended interface. The ADB agent may solve them faster, but the benchmark offers no way to measure the *kind* of capability that makes terminal agents distinctively useful: the ability to access information and perform operations that the GUI never exposes.

Tier 4 fills this gap. The 50 tasks described here share a single defining property: **the information required to solve them is either never displayed on screen, or the screen provides access only through a sequence of navigations that scales with the number of items rather than the complexity of the query.**

This is not a claim about agent quality. It is a claim about the Android interface. The tasks are chosen so that the GUI agent's failure is architectural, not behavioral.

---

## 2. Why "Never Appears on Screen" Is the Right Standard

Before describing the task categories, it is worth being precise about what makes a task ADB-exclusive.

A task is ADB-exclusive if at least one of the following is true:

**Condition A — The answer is not rendered.** The required value exists in system state (a database, a kernel counter, a permission table) but is not surfaced in any UI. No amount of scrolling, tapping, or menu traversal causes the value to appear.

**Condition B — The answer requires a cross-app join that no UI presents.** The required answer is a function of data from two or more apps. No single screen or combination of screens shows the joined result. A GUI agent can visit both apps, but combining the results requires persistent state and set operations that exceed what a screenshot-action loop can practically do.

**Condition C — Coverage proof is impossible via GUI.** The task asks the agent to *confirm* that a property holds over all members of a set (e.g., "confirm every calendar event this month has a reminder"). A GUI agent can scroll a list and check items one by one, but cannot prove that the list is complete or that no items were missed off-screen. The ADB query returns the full set in one result.

Tasks that fail these conditions were excluded from Tier 4, even if they are tedious for a GUI agent. Tedious is not the same as impossible. The audit removed 11 candidate tasks on exactly this basis.

---

## 3. Task Categories

### 3.1 Hidden State / System Introspection (3 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4HiddenStateListAppVersions` | List the version of each of the following apps: Markor, Pro Expense, Simple Calendar Pro. Output each app name and its version. | `settings` |
| `Tier4HiddenStateLocationPermissions` | List all apps that have been granted location permission. | `settings` |
| `Tier4HiddenStateAudioRouting` | What is the current audio output routing and media volume level? | `settings` |

**Why GUI agents fail (Condition A).**

App version numbers are stored in the package manager and shown in Settings → Apps → [App] → App Info, but only one app at a time. The GUI agent can navigate to an individual app's info screen and read a version string. But the version string displayed in Settings is the marketing version name (`versionName`); the full package metadata — including `versionCode`, the value used programmatically — is only accessible via `dumpsys package <pkg>`. More importantly, when the task asks for versions of *N* apps, the GUI must navigate N separate screens. The ADB command `dumpsys package` returns all package metadata in one call.

Permission tables are similarly structured. Settings → Privacy → Permission Manager → Location shows a list of apps with location access, but the list is split across "Allowed all the time," "Allowed only while in use," and "Denied" sections, each potentially requiring scroll. There is no single view that says "here is the complete set of packages with `ACCESS_FINE_LOCATION`." The `appops` command returns the complete set in one query. A GUI agent cannot prove it has seen all entries (Condition C).

Audio routing is the clearest case of Condition A. The Android Settings UI shows a volume slider for media audio and may show a connected Bluetooth device name. It does not show which output sink the AudioManager has selected, the active strategy, or the port in use. This information exists only in `dumpsys audio`, a multi-hundred-line diagnostic dump that is never presented in any UI.

**Expected outcome:** A GUI agent scrolling Settings reaches the correct screen for one app at a time but cannot query `dumpsys` output. Score ≈ 0%. An ADB agent issues one shell command and parses the output. Score ≈ 85–95%.

---

### 3.2 Off-Screen Aggregation (7 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4AggregationCountUnreadSMS` | How many unread SMS messages do you have in total? | `simple sms messenger` |
| `Tier4AggregationCalendarTotalDuration` | What is the total duration (in minutes) of all calendar events this month? | `simple calendar pro` |
| `Tier4AggregationLongestContactName` | What is the longest contact name in your contacts? | `contacts` |
| `Tier4AggregationLongestMarkorNote` | Which Markor note has the most content (by character count)? Output the note filename. | `markor` |
| `Tier4AggregationDownloadSizeTop3` | What is the total size of all files in Downloads, and what are the 3 largest files? | `files` |
| `Tier4AggregationExpenseCategoryTop3` | What are the top 3 expense categories by total amount this month? Output category name and percentage. | `pro expense` |
| `Tier4AggregationOpenTracksWeeklyStats` | What is the total distance (in km) of all activities this week, and which activity covered the longest distance? | `open tracks sports tracker` |

**Why GUI agents fail (Condition A + Condition B).**

The SMS Messenger app displays unread message threads. It does not display a count of unread messages. There is no badge showing "7 unread messages total" that a GUI agent can read. The count must be computed by querying `content://sms/inbox` with `WHERE read=0` and counting rows. The answer is a number that never appears on any screen.

Calendar apps show individual events. They do not show aggregate statistics. The total duration of all events in a month is a SUM query over the events table. No calendar view renders this number. Similarly, Markor is a file-based note editor; it shows file names and previews but does not sort by character count or display character counts in the file list. The Downloads folder size is not shown in the Files app (file sizes are shown per-file, but not summed). In each case, the required answer is a derived statistic over a dataset, and no UI computes or displays it.

Contact name length is computed from the contacts database, which stores display names as strings. The Contacts app sorts alphabetically by first name or last name. There is no "sort by name length" view and no way to identify the maximum without visiting all contacts.

**Expected outcome:** GUI agent cannot produce a number that is never displayed. Score ≈ 0%. ADB agent queries the content provider or database directly. Score ≈ 80–90%.

---

### 3.3 Bulk Edit / Delete / Rename (7 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4BulkDeleteTmpInDownloads` | Delete all `.tmp` files in the Downloads folder. | `files` |
| `Tier4BulkRenameScreenshots` | Rename all `Screenshot_*` files in Pictures to `YYYYMMDD_HHMMSS.png` format based on file modification time. | `files` |
| `Tier4BulkMoveLargeFiles` | Move all files larger than 50 MB in the Download folder to the Archive folder. | `files` |
| `Tier4BulkRecategorizeExpense` | In Pro Expense, change all expenses with category "Food" to category "Dining". | `pro expense` |
| `Tier4BulkDeleteCalendarTestEvents` | Delete all events in Simple Calendar Pro whose title contains the word "test". | `simple calendar pro` |
| `Tier4BulkChangePriorityTasks` | In Tasks app, change all tasks with priority "Low" to priority "Medium". | `tasks` |
| `Tier4BulkAppendFooterToMarkdown` | Append the text "---\nGenerated by AutoBot" to every `.md` file in the "Notes" folder in Markor. | `markor` |

**Why GUI agents fail (Condition A for the selection criterion).**

The Files app can display file names and sizes. It cannot filter by extension. To delete all `.tmp` files, a GUI agent must: scroll the entire Downloads directory, visually identify each `.tmp` file, long-press to enter selection mode, tap each `.tmp` file, and delete. The extension is visible in the filename, but the *selection criterion* — "select everything matching `*.tmp`" — is not a UI operation. The app has no "select by type" function. The number of taps scales with the number of files.

For rename-by-mtime, the situation is worse: the Files app displays modification time in human-readable form ("Yesterday, 3:42 PM") but not as a parseable timestamp. The new filename (`20210315_143022.png`) must be derived from the UNIX mtime. The mtime in machine-readable form (`stat` output) never appears on screen. The GUI agent cannot compute the new filename from what it sees.

For expense recategorization, Pro Expense allows editing one record at a time. There is no "select all records in category X and change category" operation. The GUI agent must open each record, tap the category field, select the new category, and save — once per record. The ADB agent updates all matching rows in one SQL statement.

In all bulk cases, the atomic operation (delete one file, rename one file, recategorize one record) is accessible to the GUI. What is inaccessible is the *selection* — identifying all members of the target set without scrolling an unbounded list — and the *batch application* of the operation.

**Expected outcome:** GUI agent can perform the operation on visible items but misses items off-screen, cannot identify items by computed attributes (mtime-derived filename), and requires O(n) interactions. Score ≈ 0–10%. ADB agent uses `find`, `mv`, a SQL `UPDATE WHERE`, or `shell` to operate on the full set. Score ≈ 75–90%.

---

### 3.4 Complex Predicate Filtering (7 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4FilterDeleteOldNonContactKeywordSms` | Delete all SMS messages that are: older than 30 days, from numbers NOT in your contacts, AND contain the keyword "{keyword}". | `simple sms messenger`, `contacts` |
| `Tier4FilterCalendarLongNoReminder` | List all calendar events that have no reminder, last more than 2 hours, and contain "meeting" in the title. | `simple calendar pro` |
| `Tier4FilterContactsBirthdayNoPhone` | List all contacts that have a birthday set but no phone number. | `contacts` |
| `Tier4FilterExpenseHighTravelLastMonth` | List all Pro Expense records with amount > $100, category "Travel", from last month. | `pro expense` |
| `Tier4FilterRecentLogFiles` | List all `.log` and `.txt` files in Downloads that were modified within the last 60 minutes. | `files` |
| `Tier4FilterJoplinContainsNotContains` | List all Joplin notes that contain "{keyword_A}" but do NOT contain "{keyword_B}". | `joplin` |
| `Tier4FilterRetroMusicMultiCondition` | List all songs in Retro Music by artist "{artist}" that are longer than 4 minutes and haven't been played in the last 30 days. | `retro music` |

**Why GUI agents fail (Condition A for multi-field predicates).**

Each individual predicate may be partially visible in the UI. A contact's birthday is shown on the contact detail screen. A contact's phone number is shown on the same screen. But whether a contact has a birthday *and* no phone number is a conjunction over two fields that requires visiting the contact detail screen for every contact and mentally tracking which match both conditions. No Contacts app view filters by "has birthday, missing phone." The combined predicate is never presented as a filterable attribute.

Calendar apps have reminder indicators on event detail views, but no list view that filters "no reminder AND duration > 2h AND title contains 'meeting'." Each condition is individually visible (you can open an event and see whether it has a reminder), but the three-way AND is computed by the viewer, not rendered by the app.

Joplin has a search function, but it performs inclusion search only. "Contains A but not B" requires a search for A followed by manual exclusion of results that also contain B. The Joplin search results screen does not display note content, only titles — so the agent must open each result to check for B. This is Condition A: the negative condition (absence of B) is not surfaced by any UI query.

The Retro Music "last played" timestamp is stored in the database and may be visible on individual song detail screens, but there is no filter view for "not played in N days." The condition is never rendered as a selectable filter.

**Expected outcome:** GUI agent can apply single-field filters if they exist in the UI but fails on multi-field conjunctions where the combined predicate is not rendered. Score ≈ 0%. ADB agent composes a SQL WHERE clause or shell pipeline. Score ≈ 80–90%.

---

### 3.5 Cross-App Data Joins (8 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4CrossAppSmsNumbersNotInContacts` | List all phone numbers you have received SMS from in the last 7 days that are NOT in your contacts. | `simple sms messenger`, `contacts` |
| `Tier4CrossAppContactsNoRecentSms` | List all contacts that have an email address but have NOT received any SMS in the last 6 months. | `contacts`, `simple sms messenger` |
| `Tier4CrossAppCalendarToMarkor` | Find all events in Simple Calendar Pro with "{keyword}" in the title, and create a Markor note listing the event titles and dates. | `simple calendar pro`, `markor` |
| `Tier4CrossAppFilesCreatedDuringEvents` | List all files in Downloads that were created during a calendar event time window. | `files`, `simple calendar pro` |
| `Tier4CrossAppMarkorPhonesVsContacts` | Extract all phone numbers mentioned in Markor notes, and list those that are NOT in your contacts. | `markor`, `contacts` |
| `Tier4CrossAppOpenTracksToTasks` | Find the longest activity in OpenTracks and create a task in Tasks app with the activity name and distance as the task title. | `open tracks sports tracker`, `tasks` |
| `Tier4CrossAppExpenseToMarkorCalendar` | Calculate total expenses for this month in Pro Expense, write the total to a Markor note named "monthly_summary.md", and create a Simple Calendar Pro event titled "Monthly Expense: $X" on the last day of the month. | `pro expense`, `markor`, `simple calendar pro` |
| `Tier4CrossAppBroccoliToMarkorIndex` | List all recipe names from the Broccoli app and write them as a bulleted list in a Markor note named "recipes_index.md". | `broccoli`, `markor` |

**Why GUI agents fail (Condition B).**

No Android UI presents joined views across app boundaries. To find phone numbers that sent SMS but are not in Contacts, a GUI agent must: open the SMS app, record every sender number from every thread in the last 7 days (scrolling to find all threads), then open the Contacts app and check whether each number appears. The result set — the complement of the SMS sender set relative to the Contacts set — is computed by the agent from two separate screens, requiring the agent to maintain a set in working memory across app switches.

This is not merely inconvenient; it exceeds the practical capability of a screenshot-action loop. Each app switch clears the previous screen. The agent must either remember every number from the SMS thread list (which may span dozens of threads) or cycle back and forth. The cross-product of checking every SMS number against every contact is O(n × m) GUI interactions. The ADB query is a single `content query` with a NOT IN subquery.

For files-during-events: the Files app shows file modification times, and the Calendar app shows event times. But no UI presents the join: "which files in Downloads have mtime between dtstart and dtend of any calendar event?" The agent must query both datasets, compare timestamps, and produce the intersection. This computation is not rendered on any screen.

The output tasks (write to Markor, create Calendar event) are individually achievable by a GUI agent. The failure is in computing the *source* value — the monthly total, the longest activity, the keyword-matching events — which requires the aggregation or filtering operations described in sections 3.2 and 3.4.

**Expected outcome:** GUI agent can read individual items from each app but cannot produce the join result. Score ≈ 0%. ADB agent queries both content providers in sequence and computes the set operation. Score ≈ 70–85%.

---

### 3.6 Deduplication and Consistency Repair (5 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4DedupContactsDuplicatePhones` | List all groups of contacts that share the same phone number. | `contacts` |
| `Tier4DedupMergeContactsSamePhone` | Merge contacts that have the same phone number, keeping the first name alphabetically. | `contacts` |
| `Tier4DedupCalendarDeleteDuplicateEvents` | Delete duplicate calendar events (same title and same start time), keeping only one copy of each. | `simple calendar pro` |
| `Tier4DedupJoplinSameTitleNotes` | List all Joplin notes that have the same title as another note. | `joplin` |
| `Tier4DedupExpenseSuspectedDuplicates` | How many suspected duplicate expenses are there in Pro Expense (same date, same amount, same category)? | `pro expense` |

**Why GUI agents fail (Condition A + Condition C).**

The Contacts app has a "Merge duplicates" function on some Android versions, but it merges contacts that the system considers duplicates (typically matched by name or linked account). It does not find contacts that share a phone number and have different names. This specific duplicate criterion — identical phone number across differently-named contacts — is not exposed as a filter. The GUI agent must visit every contact, note its phone numbers, and cross-reference across all contacts. The duplicate set is never rendered.

Calendar does not detect or display duplicate events. The agent must compare event records by (title, dtstart) to find duplicates. Two events with identical title and start time are displayed as two separate entries in the calendar view; there is no "this is a duplicate" indicator.

Joplin shows note titles in the note list. Two notes with the same title are displayed as two separate list items with no visual indicator of duplication. Finding all duplicate-titled notes requires comparing every title against every other title — an O(n²) comparison that is not performed by any UI.

For Pro Expense, the suspected-duplicate query (same date + amount + category) is a GROUP BY query on three columns. The UI shows expenses in a chronological list. Identifying tuples where multiple rows share all three attributes requires a computation the UI never performs.

**Expected outcome:** GUI agent can identify one duplicate if it is visually adjacent, but cannot find all duplicates across a full dataset without O(n²) interactions. Score ≈ 0–5%. ADB agent uses GROUP BY or set comparison queries. Score ≈ 80–90%.

---

### 3.7 Ranking / Top-K (7 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4TopKSmsThreadsByCount` | Which 3 contacts have the most SMS threads? List their phone numbers. | `simple sms messenger` |
| `Tier4TopKCalendarEarliestEvent` | What is the earliest (oldest) event in Simple Calendar Pro? Output the title and date. | `simple calendar pro` |
| `Tier4TopKLargestDownloadFiles` | What are the 5 largest files in the Downloads folder? List filenames and sizes. | `files` |
| `Tier4TopKExpenseHighestAmount` | What are the 10 highest-amount expenses in Pro Expense? List description and amount. | `pro expense` |
| `Tier4TopKOpenTracksFastestActivity` | Which activity in OpenTracks had the highest average speed? Output the activity name and speed. | `open tracks sports tracker` |
| `Tier4TopKRetroMusicLongestSongs` | What are the 10 longest songs in Retro Music by duration? List title and duration. | `retro music` |
| `Tier4TopKMarkorMostModifiedNotes` | Which 5 Markor notes were modified most recently in the last 7 days? List filenames. | `markor` |

**Why GUI agents fail (Condition A — sort key not rendered, or Condition C — list may be truncated).**

The SMS Messenger app shows threads grouped by contact in the order they were most recently active. It does not sort by thread count, and it does not display thread counts per contact. The "number of messages in a thread" is a count that is shown when you open a thread (as a count of visible messages), but the per-contact count is never shown in the thread list view. Identifying the top-3 by count requires opening every thread and counting messages — or querying `SELECT address, COUNT(*) FROM sms GROUP BY thread_id ORDER BY COUNT(*) DESC LIMIT 3`.

The Files app on Android does not support "sort by size" in most versions. Files are displayed alphabetically or by date. The top-5 by size is a sort operation on a dimension the UI does not present.

Calendar apps show events in chronological order. To find the "earliest event ever," the GUI agent must scroll back to the beginning of the calendar — potentially years — to find the first entry. The ADB query is `SELECT title, MIN(dtstart) FROM events`.

OpenTracks shows activity speed per activity in the activity detail view. It does not provide a sorted ranking of activities by speed. The fastest activity is identifiable only by comparing a field (average speed) across all activities, which requires visiting each activity's detail page.

**Expected outcome:** GUI agent cannot produce a sorted ranking on a dimension not shown in the list view, and cannot scroll to verify completeness (Condition C). Score ≈ 0–5%. ADB agent issues ORDER BY queries. Score ≈ 80–90%.

---

### 3.8 Coverage-Certified Queries (6 tasks)

| Class | Template | App(s) |
|---|---|---|
| `Tier4CoverageNoTmpInDownloads` | Confirm that there are no `.tmp` files in the Downloads folder. If any exist, list their names. If none, output "None" or "0". | `files` |
| `Tier4CoverageAppsCameraPermission` | List all apps that have been granted Camera permission. If none, output "None". | `settings` |
| `Tier4CoverageWifiConnected` | Is WiFi currently enabled and connected? If so, what SSID is it connected to? | `settings` |
| `Tier4CoverageCalendarEventsHaveReminders` | Confirm that all calendar events this month have a reminder set. If any don't, list the event titles. | `simple calendar pro` |
| `Tier4CoverageAllSmsRead` | Confirm that all SMS messages have been read (no unread). If any are unread, list how many. | `simple sms messenger` |
| `Tier4CoverageOverdueTasksCompleted` | Confirm all overdue tasks in Tasks app are marked completed. If any are not, list their titles. | `tasks` |

**Why GUI agents fail (Condition C — completeness cannot be proven via GUI).**

Coverage tasks ask the agent not just to find items matching a criterion, but to certify the *absence* of non-matching items. This is the verification problem: proving a negative.

The Downloads folder may show zero `.tmp` files after a bulk delete. A GUI agent can scroll the folder and see no `.tmp` files. But if the folder contains many files, the agent cannot prove the scroll was exhaustive — pagination, lazy loading, or off-screen items may exist. The ADB query `find /storage/emulated/0/Download -name '*.tmp'` returns an empty string if and only if no such files exist. The empty result is a proof; the GUI observation is an observation.

Calendar reminders: the calendar month view shows events. Individual events may show reminder icons. But "all events this month have reminders" requires visiting every event's detail screen. If any event lacks a reminder, it is not visually distinct in the month or week view — there is no "missing reminder" indicator. The ADB query filters all events in the month where no reminder row exists in the reminders table.

WiFi state: `settings get global wifi_on` and `dumpsys wifi` return the network connection state unambiguously. The Settings UI shows a WiFi toggle and a connected network name — but only if the user navigates to the WiFi settings screen. The ADB query works without navigating to any screen.

**Expected outcome:** GUI agent cannot certify completeness of a scan or prove absence. Score ≈ 0–15% (partial credit where the answer happens to be "None" and the agent guesses). ADB agent issues a single query and produces a provably complete answer. Score ≈ 85–95%.

---

## 4. Summary: Why the Score Gap Is Structural

The table below maps each category to the impossibility condition that drives the GUI agent's failure.


| Category                             | Condition                   | GUI Agent Score (expected) | ADB Agent Score (expected) |
| ------------------------------------ | --------------------------- | -------------------------- | -------------------------- |
| Hidden State / System Introspection  | A                           | ~0%                        | 85–95%                     |
| Off-Screen Aggregation               | A                           | ~0%                        | 80–90%                     |
| Bulk Edit / Delete / Rename (7)      | A (selection criterion)     | 0–10%                      | 75–90%                     |
| Complex Predicate Filtering (7)      | A (multi-field conjunction) | ~0%                        | 80–90%                     |
| Cross-App Data Joins (8)             | B                           | ~0%                        | 70–85%                     |
| Deduplication and Consistency Repair | A + C                       | 0–5%                       | 80–90%                     |
| Ranking / Top-K                      | A (sort key not rendered)   | 0–5%                       | 80–90%                     |
| Coverage-Certified Queries           | C                           | 0–15%                      | 85–95%                     |


The failure modes are not that GUI agents are slow or inaccurate readers of screens. The failure modes are:

1. The value they need to read is not on any screen.
2. The computation they need to perform (join, aggregate, rank) is not done by any app UI.
3. The completeness guarantee they need to provide cannot be obtained by observation.

These are properties of the Android interface, not of any particular GUI agent implementation. A perfect GUI agent — one that reads every pixel accurately and navigates without error — would still score near zero on most Tier 4 tasks, because the limiting factor is not perception or navigation but the fundamental mismatch between what the task requires and what the screen renders.

ADB agents have direct access to the data layer. Content providers, SQLite databases, `dumpsys` output, and `find`/`stat` filesystem queries provide the raw values from which the answer is computed in one or two commands. The expected high scores for ADB agents reflect this architectural advantage, not a difference in reasoning ability.

This is the gap Tier 4 fills: a set of tasks where the benchmark result reflects the *interface* the agent uses, not just its reasoning quality.