# Tier 4 Final Specification: 56 ADB-Exclusive Tasks

## Overview

This document specifies the final Tier 4 benchmark consisting of 56 tasks designed to evaluate CLI/ADB-based Android agents. Every task in this tier is specifically chosen because ADB shell access provides a decisive structural advantage over GUI-only agents.

## Category Summary

| Category | Name | Count | Core Principle |
|----------|------|-------|----------------|
| A | Aggregation / TopK | 13 | Read all items, compute derived answers |
| B | Bulk / Dedup | 11 | Mutate multiple items in one operation |
| C | Filter / Coverage | 12 | Multi-condition queries across datasets |
| D | CrossApp | 10 | Read from one app, write/compare to another |
| E | HiddenState | 10 | Query device state not exposed in any GUI |

**Total: 56 tasks**

## Evaluation Patterns

Three eval patterns are used across the benchmark:

1. **State-check eval**: `is_successful` queries device state after the agent acts (e.g., verifying deleted files are gone). Used for Bulk/Dedup tasks.
2. **Cache-match eval**: `is_successful` checks `env.interaction_cache` (the agent's text output) against computed ground truth. Used for Aggregation/TopK/Filter/HiddenState tasks.
3. **Hybrid eval**: Checks both device state mutations AND agent text output. Used for CrossApp tasks that write data and report results.

---

## Category A — Aggregation / TopK (13 tasks)

### Category Rationale

These tasks require reading ALL items in a dataset, then computing an aggregate value (sum, count, max, top-K, duplicate detection). A GUI agent can only view items one screen at a time, scrolling repeatedly and manually tracking state. A CLI agent can query the entire dataset in a single command and pipe it through standard tools (sort, awk, wc) to derive the answer instantly.

### CLI Advantage (General)

- File-based aggregation: `find` + `stat` + `sort` processes all files in one pass
- Database aggregation: `sqlite3` with `GROUP BY`, `ORDER BY`, `COUNT`, `SUM`
- Content provider queries: `content query` retrieves all rows at once
- No scrolling, no pagination, no missed items

---

### Task 6: Tier4AggregationLongestMarkorNote

**Description:** Which note in the Markor folder (/storage/emulated/0/Documents/Markor/) has the most content by character count? Output the filename.

**Why it fits:** Requires reading character counts across all files and selecting the maximum — a classic aggregation.

**CLI Advantage:** `wc -c` on all files in one pass vs. opening each note individually in the GUI.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Documents/Markor/ -type f -exec wc -c {} \; | sort -rn | head -1'
```

**Evaluation:** Cache-match eval. Ground truth is computed during `initialize_task` by measuring all files; `is_successful` checks that the correct filename appears in the agent's output.

---

### Task 27: Tier4AggregationDownloadSizeTop3

**Description:** What is the total size (in bytes) of all files in the Downloads folder, and what are the 3 largest files? Output the total size and the 3 largest filenames.

**Why it fits:** Requires summing all file sizes (aggregation) and identifying top-3 (TopK) simultaneously.

**CLI Advantage:** `du` or `stat` + `sort` handles both total and ranking in one pipeline.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Download/ -type f -exec stat -c "%s %n" {} \; | sort -rn' 
# Parse output: sum all sizes for total, take top 3 filenames
```

**Evaluation:** Cache-match eval. Ground truth includes the total byte count and the 3 largest filenames. Both must appear in the agent's output.

---

### Task 15: Tier4AggregationExpenseCategoryTop3

**Description:** What are the top 3 expense categories by total amount this month in Pro Expense? Output the category names.

**Why it fits:** Requires grouping expenses by category, summing amounts per group, and ranking — a GROUP BY + ORDER BY aggregation.

**CLI Advantage:** A single SQL query with GROUP BY and ORDER BY vs. manually tallying per-category totals in the GUI.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT category_name, SUM(amount) as total FROM expense WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now') GROUP BY category_name ORDER BY total DESC LIMIT 3;"
```

**Evaluation:** Cache-match eval. Ground truth is the 3 category names with highest totals; all must appear in agent output.

---

### Task 16: Tier4AggregationExpenseSuspectedDuplicates

**Description:** How many suspected duplicate expenses are there in Pro Expense (same date, same amount, same category)? Output the number of duplicates (i.e., extras beyond the first of each group).

**Why it fits:** Duplicate detection across an entire dataset requires comparing every row against every other — pure aggregation logic.

**CLI Advantage:** SQL `GROUP BY ... HAVING COUNT(*) > 1` finds all duplicates instantly. GUI would require manually comparing each expense.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT SUM(cnt - 1) FROM (SELECT COUNT(*) as cnt FROM expense GROUP BY date, amount, category HAVING cnt > 1);"
```

**Evaluation:** Cache-match eval. Ground truth is the integer count of extra duplicates.

---

### Task 48: Tier4AggregationExpenseAllCategorized

**Description:** Verify that all expenses in Pro Expense have a valid category assigned. If any are uncategorized (category 0 or missing), output their names. If all are categorized, output 'all categorized'.

**Why it fits:** Coverage verification across all records — checking a property holds universally.

**CLI Advantage:** A single SQL WHERE clause finds violations; GUI would require opening every expense entry.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT name FROM expense WHERE category IS NULL OR category = 0;"
```

**Evaluation:** Cache-match eval. If uncategorized expenses exist, their names must appear. If none exist, 'all categorized' must appear.

---

### Task 11: Tier4AggregationContactsDuplicatePhones

**Description:** List all groups of contacts that share the same phone number. Output each group with the shared phone number and the contact names.

**Why it fits:** Requires grouping contacts by phone number and finding groups with more than one member — set-based aggregation.

**CLI Advantage:** Content provider query retrieves all phone-contact pairs; grouping logic in a script. GUI would require checking each contact individually.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.contacts/data \
  --projection display_name:data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"
# Group results by phone number, output groups with count > 1
```

**Evaluation:** Cache-match eval. Ground truth lists each shared phone number with its associated contact names.

---

### Task 21: Tier4AggregationOpenTracksWeeklyStats

**Description:** What is the total distance of all activities this week in OpenTracks, and which activity covered the longest distance?

**Why it fits:** Requires summing distances (aggregation) and finding the maximum (argmax) across all activities.

**CLI Advantage:** SQL SUM and MAX in one query vs. scrolling through activity list in the app.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \
  "SELECT SUM(totaldistance), name FROM tracks WHERE starttime >= datetime('now', '-7 days') GROUP BY NULL UNION ALL SELECT totaldistance, name FROM tracks WHERE starttime >= datetime('now', '-7 days') ORDER BY totaldistance DESC LIMIT 1;"
```

**Evaluation:** Cache-match eval. Ground truth includes total distance and the longest activity's name.

---

### Task 7: Tier4TopKMarkorMostModifiedNotes

**Description:** Which 5 notes in Markor (/storage/emulated/0/Documents/Markor/) were modified most recently in the last 7 days? List the filenames.

**Why it fits:** TopK by modification time — sort all files by mtime and take top 5.

**CLI Advantage:** `find -mtime` + `stat` + `sort` handles this in one pipeline. GUI file managers may not show modification times clearly.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Documents/Markor/ -type f -mtime -7 -exec stat -c "%Y %n" {} \; | sort -rn | head -5'
```

**Evaluation:** Cache-match eval. Ground truth is the 5 most recently modified filenames.

---

### Task 28: Tier4TopKLargestDownloadFiles

**Description:** What are the 5 largest files in the Downloads folder? List their filenames and sizes.

**Why it fits:** TopK by file size — straightforward ranking.

**CLI Advantage:** `ls -lS` or `find + stat + sort` returns ranked results immediately.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Download/ -type f -exec stat -c "%s %n" {} \; | sort -rn | head -5'
```

**Evaluation:** Cache-match eval. Ground truth is the 5 largest filenames with their sizes.

---

### Task 8: Tier4TopKSmsThreadsByCount

**Description:** Which 3 phone numbers have the most SMS messages in your inbox? List their phone numbers.

**Why it fits:** TopK by message count — requires counting messages grouped by sender.

**CLI Advantage:** Content provider query returns all SMS; grouping by address is trivial in CLI. GUI requires scrolling through all threads.

**CLI Approach:**
```bash
adb shell content query --uri content://sms/inbox --projection address
# Count occurrences per address, sort descending, take top 3
```

**Evaluation:** Cache-match eval. Ground truth is the 3 phone numbers with highest message counts.

---

### Task 17: Tier4TopKExpenseHighestAmount

**Description:** What are the 5 highest-amount expenses in Pro Expense? List the expense names and amounts.

**Why it fits:** TopK by amount — simple ORDER BY DESC LIMIT 5.

**CLI Advantage:** One SQL query vs. scrolling and mentally ranking expenses in the GUI.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT name, amount FROM expense ORDER BY amount DESC LIMIT 5;"
```

**Evaluation:** Cache-match eval. Ground truth is the 5 expense names and their amounts.

---

### Task 22: Tier4TopKOpenTracksFastestActivity

**Description:** Which activity in OpenTracks had the highest average speed? Output the activity name and its average speed.

**Why it fits:** TopK (K=1) by computed metric (distance/time = speed).

**CLI Advantage:** SQL can compute speed = distance/duration and find the max in one query. GUI shows stats per activity but doesn't rank them.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \
  "SELECT name, (totaldistance / (totaltime / 1000.0)) as avg_speed FROM tracks ORDER BY avg_speed DESC LIMIT 1;"
```

**Evaluation:** Cache-match eval. Ground truth is the activity name and its average speed value.

---

### Task 24: Tier4TopKRetroMusicLongestSongs

**Description:** What are the 5 longest songs in Retro Music by duration? List their titles.

**Why it fits:** TopK by duration across all songs in the library.

**CLI Advantage:** Query the media database for all tracks sorted by duration. GUI would require scrolling through the entire library.

**CLI Approach:**
```bash
adb shell content query --uri content://media/external/audio/media \
  --projection title:duration --sort "duration DESC" | head -5
```
Or via sqlite3 on the media database.

**Evaluation:** Cache-match eval. Ground truth is the 5 song titles with longest duration.

---

## Category B — Bulk / Dedup (11 tasks)

### Category Rationale

These tasks require mutating multiple items at once: deleting by pattern, renaming batches, moving files conditionally, or merging duplicates. A GUI agent must perform each action individually (tap, confirm, repeat). A CLI agent can use wildcards, loops, and SQL UPDATE/DELETE statements to process all items in a single operation.

### CLI Advantage (General)

- Wildcard deletion: `rm *.tmp` or `find -delete`
- Batch rename: `for f in ...; do mv "$f" ...; done`
- Conditional moves: `find -size +50M -exec mv {} dest/ \;`
- SQL batch updates: `UPDATE expense SET category = X WHERE category = Y`
- No confirmation dialogs, no per-item tapping

---

### Task 0: Tier4BulkDeleteTmpInDownloads

**Description:** Delete all .tmp files in the Downloads folder.

**Why it fits:** Bulk deletion by file extension — the canonical wildcard operation.

**CLI Advantage:** `find -name "*.tmp" -delete` vs. selecting and deleting each file individually in a file manager GUI.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Download/ -name "*.tmp" -delete'
```

**Evaluation:** State-check eval. `is_successful` runs `find *.tmp` and verifies zero results.

---

### Task 46: Tier4BulkDeleteApkFiles

**Description:** Delete all .apk files in my Downloads folder — those are leftover app installers I no longer need.

**Why it fits:** Bulk deletion by extension, same pattern as Task 0 but for .apk files.

**CLI Advantage:** Single wildcard command vs. per-file GUI deletion.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Download/ -name "*.apk" -delete'
```

**Evaluation:** State-check eval. Verifies no .apk files remain in Downloads.

---

### Task 49: Tier4BulkDeleteSmallExpenses

**Description:** Delete all expenses in Pro Expense that are less than $1.00 (less than 100 cents).

**Why it fits:** Bulk deletion from a database by value condition.

**CLI Advantage:** One SQL DELETE vs. finding and deleting each small expense individually through the app UI.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "DELETE FROM expense WHERE amount < 100;"
```

**Evaluation:** State-check eval. Verifies no expenses with amount < 100 remain in the database.

---

### Task 32: Tier4BulkDeleteCalendarTestEvents

**Description:** Delete all events in Simple Calendar Pro whose title contains the word 'test' (case-insensitive).

**Why it fits:** Bulk deletion by string pattern match in a content provider.

**CLI Advantage:** SQL or content provider DELETE with LIKE condition vs. scrolling through calendar finding and deleting each test event.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.calendar/events \
  --projection _id:title --where "title LIKE '%test%'"
# For each matching _id:
adb shell content delete --uri content://com.android.calendar/events --where "_id=<id>"
```

**Evaluation:** State-check eval. Verifies no calendar events with 'test' in the title remain.

---

### Task 3: Tier4BulkRenameScreenshots

**Description:** Rename all files starting with 'Screenshot_' in the Pictures folder (/storage/emulated/0/Pictures/) to the format YYYYMMDD_HHMMSS.png based on each file's modification time.

**Why it fits:** Batch rename requiring per-file metadata extraction and string formatting.

**CLI Advantage:** A shell loop with `stat` for mtime and `mv` for rename. GUI has no batch-rename-by-metadata feature.

**CLI Approach:**
```bash
adb shell 'for f in /storage/emulated/0/Pictures/Screenshot_*; do
  ts=$(stat -c %Y "$f")
  newname=$(date -d @$ts +%Y%m%d_%H%M%S).png
  mv "$f" "/storage/emulated/0/Pictures/$newname"
done'
```

**Evaluation:** State-check eval. Verifies no files starting with 'Screenshot_' remain and that correctly-named files exist with proper timestamps.

---

### Task 4: Tier4BulkMoveLargeFiles

**Description:** Move all files larger than 50MB in the Download folder to the Archive folder (/storage/emulated/0/Archive/). Create the Archive folder if it doesn't exist.

**Why it fits:** Conditional bulk move by file size.

**CLI Advantage:** `find -size +50M -exec mv` does this in one command. GUI requires sorting by size, selecting large files, and moving them.

**CLI Approach:**
```bash
adb shell 'mkdir -p /storage/emulated/0/Archive/ && find /storage/emulated/0/Download/ -type f -size +50M -exec mv {} /storage/emulated/0/Archive/ \;'
```

**Evaluation:** State-check eval. Verifies no files >50MB remain in Downloads and that they exist in Archive.

---

### Task 5: Tier4BulkAppendFooterToMarkdown

**Description:** Append the following text to every .md file in the 'Notes' folder in Markor (/storage/emulated/0/Documents/Markor/Notes/):\n---\nGenerated by AutoBot

**Why it fits:** Bulk file content modification — appending text to multiple files.

**CLI Advantage:** A shell loop with `echo >>` appends to all files. GUI would require opening each note and manually typing the footer.

**CLI Approach:**
```bash
adb shell 'for f in /storage/emulated/0/Documents/Markor/Notes/*.md; do
  printf "\n---\nGenerated by AutoBot" >> "$f"
done'
```

**Evaluation:** State-check eval. Verifies each .md file in the folder ends with the expected footer text.

---

### Task 13: Tier4BulkRecategorizeExpense

**Description:** I miscategorized some expenses — change all 'Food' entries in Pro Expense to 'Entertainment'.

**Why it fits:** Bulk UPDATE on a database — changing a field value for all matching rows.

**CLI Advantage:** One SQL UPDATE statement vs. editing each expense individually in the app.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "UPDATE expense SET category = (SELECT id FROM category WHERE name='Entertainment') WHERE category = (SELECT id FROM category WHERE name='Food');"
```

**Evaluation:** State-check eval. Verifies no expenses with category 'Food' remain and that the count of 'Entertainment' entries increased appropriately.

---

### Task 19: Tier4BulkChangePriorityTasks

**Description:** Change all overdue tasks in the Tasks app to High priority.

**Why it fits:** Conditional bulk update — find tasks past due date, update their priority field.

**CLI Advantage:** SQL UPDATE with date condition vs. opening each overdue task and changing its priority in the GUI.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/org.tasks/databases/tasks.db \
  "UPDATE tasks SET priority = 1 WHERE dueDate < strftime('%s', 'now') * 1000 AND completed = 0;"
```

**Evaluation:** State-check eval. Verifies all overdue incomplete tasks now have High priority.

---

### Task 12: Tier4DedupMergeContactsSamePhone

**Description:** Some contacts share the same phone number. Merge them by keeping only the contact whose name comes first alphabetically and deleting the others. Output the names you kept.

**Why it fits:** Deduplication with a merge strategy — requires grouping, choosing a winner, and deleting losers.

**CLI Advantage:** Query all contacts, group by phone, sort names alphabetically, delete non-first entries. GUI has no merge-by-rule feature.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.contacts/data \
  --projection raw_contact_id:display_name:data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"
# Group by phone number, keep alphabetically first, delete others:
adb shell content delete --uri content://com.android.contacts/raw_contacts --where "id=<id_to_delete>"
```

**Evaluation:** Hybrid eval. State-check verifies duplicates are gone; cache-match checks that kept names appear in agent output.

---

### Task 34: Tier4DedupCalendarDeleteDuplicateEvents

**Description:** Delete duplicate calendar events in Simple Calendar Pro (events with the same title AND the same start time), keeping only one copy of each.

**Why it fits:** Deduplication in a content provider — identify groups with same (title, start), keep one, delete the rest.

**CLI Advantage:** Query all events, group by (title, dtstart), delete extras by ID. GUI would require manually comparing events.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.calendar/events \
  --projection "_id:title:dtstart"
# Identify duplicates (same title + dtstart), keep lowest _id, delete others:
adb shell content delete --uri content://com.android.calendar/events --where "_id=<dup_id>"
```

**Evaluation:** State-check eval. Verifies no duplicate (title, dtstart) pairs remain in the calendar.

---

## Category C — Filter / Coverage (12 tasks)

### Category Rationale

These tasks require filtering items by multiple simultaneous conditions (AND/OR logic) or verifying that a property holds across an entire dataset. GUI agents must inspect each item individually and mentally combine conditions. CLI agents can compose WHERE clauses, pipe through grep, or use find with multiple predicates to get exact results in one pass.

### CLI Advantage (General)

- Multi-predicate queries: SQL WHERE with AND/OR
- Content provider WHERE clauses combine conditions
- `find` with `-size`, `-mtime`, `-name` simultaneously
- `grep` pipelines for text-based filtering
- Coverage checks: `SELECT ... WHERE NOT ...` finds violations instantly

---

### Task 9: Tier4FilterContactsBirthdayNoPhone

**Description:** List all contacts that have a birthday set but no phone number. Output the contact names.

**Why it fits:** Multi-condition filter: has birthday AND lacks phone number — requires checking two different data types per contact.

**CLI Advantage:** Join/query contact data for birthday presence and phone absence in one pass. GUI requires checking each contact individually.

**CLI Approach:**
```bash
# Find contacts with birthday
adb shell content query --uri content://com.android.contacts/data \
  --projection raw_contact_id --where "mimetype='vnd.android.cursor.item/contact_event' AND data2=3"
# Find contacts with phone
adb shell content query --uri content://com.android.contacts/data \
  --projection raw_contact_id --where "mimetype='vnd.android.cursor.item/phone_v2'"
# Compute set difference: has_birthday - has_phone
```

**Evaluation:** Cache-match eval. Ground truth is the list of contact names matching both conditions.

---

### Task 10: Tier4FilterContactsNoFamilyName

**Description:** List all contacts that have a phone number but no family name (first name only).

**Why it fits:** Multi-condition filter: has phone AND family_name is null/empty.

**CLI Advantage:** Query structured name data directly. GUI shows display names but doesn't visually distinguish missing family names.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.contacts/data \
  --projection raw_contact_id:data2:data3 --where "mimetype='vnd.android.cursor.item/name'"
# Filter where data3 (family name) is NULL or empty, cross-reference with phone existence
```

**Evaluation:** Cache-match eval. Ground truth is the list of contact names with phone but no family name.

---

### Task 14: Tier4FilterExpenseHighTravelLastMonth

**Description:** List all Pro Expense records with amount greater than $50, category 'Transportation', from last month. Output the expense names.

**Why it fits:** Three simultaneous conditions: amount > 5000 (cents), category = Transportation, date in last month.

**CLI Advantage:** One SQL WHERE with three AND conditions. GUI requires filtering by category, then scanning for amount and date.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT name FROM expense WHERE amount > 5000 AND category = (SELECT id FROM category WHERE name='Transportation') AND strftime('%Y-%m', date) = strftime('%Y-%m', 'now', '-1 month');"
```

**Evaluation:** Cache-match eval. Ground truth is the list of matching expense names.

---

### Task 47: Tier4FilterExpenseAboveAverage

**Description:** Which of my expenses are above my average spending? List them.

**Why it fits:** Filter requiring a computed threshold (the average) — must first aggregate, then filter.

**CLI Advantage:** Subquery computes average, outer query filters. GUI cannot dynamically compute and apply an average threshold.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT name, amount FROM expense WHERE amount > (SELECT AVG(amount) FROM expense);"
```

**Evaluation:** Cache-match eval. Ground truth is the list of expense names above the average.

---

### Task 20: Tier4FilterJoplinContainsNotContains

**Description:** List all Joplin notes that contain '{keyword_a}' but do NOT contain '{keyword_b}'. Output the note titles.

**Why it fits:** Text content filter with inclusion AND exclusion — requires reading body text of every note.

**CLI Advantage:** SQL LIKE or grep across all note bodies in one pass. GUI requires opening each note and searching.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/net.cozic.joplin/databases/joplin.db \
  "SELECT title FROM notes WHERE body LIKE '%keyword_a%' AND body NOT LIKE '%keyword_b%';"
```

**Evaluation:** Cache-match eval. Ground truth is the list of note titles matching the content conditions.

---

### Task 23: Tier4FilterRetroMusicMultiCondition

**Description:** List all songs in Retro Music by artist '{artist}' that are longer than 4 minutes. Output the song titles.

**Why it fits:** Two conditions: artist match AND duration > 240000ms.

**CLI Advantage:** Media content provider query with compound WHERE clause. GUI requires filtering by artist then checking each song's duration.

**CLI Approach:**
```bash
adb shell content query --uri content://media/external/audio/media \
  --projection title --where "artist='{artist}' AND duration > 240000"
```

**Evaluation:** Cache-match eval. Ground truth is the list of matching song titles.

---

### Task 42: Tier4FilterSmsContainingUrl

**Description:** List all SMS messages in the inbox that contain a URL (http:// or https://). Output the sender phone numbers.

**Why it fits:** Text pattern filter across all SMS — requires regex/pattern matching on message bodies.

**CLI Advantage:** Content provider query + grep for URL pattern across all messages. GUI requires reading each message.

**CLI Approach:**
```bash
adb shell content query --uri content://sms/inbox --projection "address:body"
# Filter lines where body contains 'http://' or 'https://'
```

**Evaluation:** Cache-match eval. Ground truth is the list of sender phone numbers from messages containing URLs.

---

### Task 44: Tier4FilterLargeOldFiles

**Description:** Are there any large files (over 10 MB) in my Downloads folder that haven't been modified in over 30 days? List them.

**Why it fits:** Two conditions on file metadata: size > 10MB AND mtime > 30 days ago.

**CLI Advantage:** `find -size +10M -mtime +30` combines both conditions natively. GUI file manager may not filter on both simultaneously.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Download/ -type f -size +10M -mtime +30 -exec basename {} \;'
```

**Evaluation:** Cache-match eval. Ground truth is the list of qualifying filenames (or indication that none exist).

---

### Task 45: Tier4FilterEmptyFilesInDownloads

**Description:** List all zero-byte (empty) files in the Downloads folder. Output the filenames.

**Why it fits:** Single-condition filter but requires checking every file's size — not visible at a glance in GUI.

**CLI Advantage:** `find -empty` or `find -size 0` instantly identifies all empty files.

**CLI Approach:**
```bash
adb shell 'find /storage/emulated/0/Download/ -type f -empty -exec basename {} \;'
```

**Evaluation:** Cache-match eval. Ground truth is the list of zero-byte filenames.

---

### Task 50: Tier4FilterCalendarWeekendEvents

**Description:** What do I have planned on weekends this month? List all calendar events that fall on a Saturday or Sunday.

**Why it fits:** Date-based filter requiring day-of-week computation for each event.

**CLI Advantage:** SQL date functions can compute day-of-week and filter. GUI calendar view requires manually checking each Saturday and Sunday.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.calendar/events \
  --projection "title:dtstart"
# Convert dtstart timestamps to day-of-week, filter for Saturday (6) or Sunday (0)
```

**Evaluation:** Cache-match eval. Ground truth is the list of event titles falling on weekends this month.

---

### Task 43: Tier4CoverageSmsAllFromKnownContacts

**Description:** Are there any SMS messages in my inbox from numbers not in my contacts? If so, how many?

**Why it fits:** Coverage verification — checking whether all SMS senders exist in the contacts database.

**CLI Advantage:** Query SMS addresses, query all contact phone numbers, compute set difference. GUI would require checking each sender manually.

**CLI Approach:**
```bash
# Get all unique SMS sender numbers
adb shell content query --uri content://sms/inbox --projection address
# Get all contact phone numbers
adb shell content query --uri content://com.android.contacts/data \
  --where "mimetype='vnd.android.cursor.item/phone_v2'" --projection data1
# Compute difference
```

**Evaluation:** Cache-match eval. Ground truth is the count of SMS from unknown numbers (or 'all known').

---

### Task 35: Tier4CoverageCalendarEventsHaveReminders

**Description:** Do all my calendar events this month have reminders set? If any are missing reminders, tell me which ones.

**Why it fits:** Coverage check — verify a property (has reminder) across all events this month.

**CLI Advantage:** Query events, left-join with reminders table, find events with no matching reminder. GUI requires opening each event to check.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.calendar/events \
  --projection "_id:title:dtstart"
# For this month's events, check reminders table:
adb shell content query --uri content://com.android.calendar/reminders \
  --projection event_id
# Find event IDs without reminders
```

**Evaluation:** Cache-match eval. Ground truth is either 'all have reminders' or the list of event titles missing reminders.

---

## Category D — CrossApp (10 tasks)

### Category Rationale

These tasks require reading data from one application and writing or comparing it to another. A GUI agent must switch between apps repeatedly, remembering data across context switches. A CLI agent can query both apps' data stores in a single shell session and pipe results directly between them.

### CLI Advantage (General)

- Query App A's database, store result in variable, write to App B's storage — all in one shell session
- No app-switching latency or context loss
- Can compose multi-app pipelines: `sqlite3 appA.db "..." | while read line; do content insert appB ...; done`
- Atomic operations across apps without risk of forgetting intermediate data

---

### Task 2: Tier4CrossAppSmsNumbersNotInContacts

**Description:** List all phone numbers you have received SMS from in the last 7 days that are NOT in your contacts. Output the numbers.

**Why it fits:** Cross-app: reads SMS database (messaging) and contacts database, computes set difference.

**CLI Advantage:** Query both databases in one session, compute difference programmatically. GUI requires switching between SMS app and Contacts.

**CLI Approach:**
```bash
# Get recent SMS senders
adb shell content query --uri content://sms/inbox --projection address --where "date > $(date -d '7 days ago' +%s)000"
# Get all contact numbers
adb shell content query --uri content://com.android.contacts/data \
  --where "mimetype='vnd.android.cursor.item/phone_v2'" --projection data1
# Compute set difference
```

**Evaluation:** Cache-match eval. Ground truth is the list of phone numbers present in SMS but not in contacts.

---

### Task 18: Tier4CrossAppExpenseToMarkorCalendar

**Description:** Calculate the total expenses for this month in Pro Expense, write the total (in dollars) to a Markor note named 'monthly_summary.md', and create a Simple Calendar Pro event titled 'Monthly Expense: $<total>' on the last day of this month.

**Why it fits:** Three-app coordination: read from Pro Expense, write to Markor file, insert into Calendar.

**CLI Advantage:** Pipeline: SQL query -> write file -> content insert. All in one shell script with no app switching.

**CLI Approach:**
```bash
# Calculate total
TOTAL=$(adb shell sqlite3 /data/data/com.arduia.expense/databases/pro_expense.db \
  "SELECT SUM(amount)/100.0 FROM expense WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now');")
# Write to Markor
adb shell "echo '$TOTAL' > /storage/emulated/0/Documents/Markor/monthly_summary.md"
# Create calendar event on last day of month
adb shell content insert --uri content://com.android.calendar/events \
  --bind title:s:"Monthly Expense: \$$TOTAL" --bind dtstart:l:<last_day_ms> ...
```

**Evaluation:** Hybrid eval. Checks that monthly_summary.md contains the correct total AND that the calendar event exists with correct title.

---

### Task 25: Tier4CrossAppBroccoliToMarkorIndex

**Description:** Which of my contacts texted me but I haven't replied to?

**Why it fits:** Cross-app: reads SMS inbox (received messages) and SMS sent/outbox, compares sender sets vs. recipient sets.

**CLI Advantage:** Query inbox senders and outbox recipients in one session, compute difference. GUI requires comparing message threads manually.

**CLI Approach:**
```bash
# Get unique inbox senders
adb shell content query --uri content://sms/inbox --projection address
# Get unique sent recipients
adb shell content query --uri content://sms/sent --projection address
# Find senders not in sent recipients, cross-reference with contacts
```

**Evaluation:** Cache-match eval. Ground truth is the list of contacts who sent messages but received no reply.

---

### Task 26: Tier4CrossAppMarkorPhonesVsContacts

**Description:** Extract all phone numbers mentioned in Markor notes, then list the ones that are NOT in your contacts. Output the numbers.

**Why it fits:** Cross-app: reads Markor files (text extraction with regex), compares against contacts database.

**CLI Advantage:** grep for phone patterns in files, query contacts, compute difference — all in one shell.

**CLI Approach:**
```bash
# Extract phone numbers from Markor notes
adb shell 'grep -rohP "\+?[\d\-()]{7,}" /storage/emulated/0/Documents/Markor/*.md' | sort -u
# Get all contact numbers
adb shell content query --uri content://com.android.contacts/data \
  --where "mimetype='vnd.android.cursor.item/phone_v2'" --projection data1
# Compute difference
```

**Evaluation:** Cache-match eval. Ground truth is the list of phone numbers found in notes but not in contacts.

---

### Task 33: Tier4CrossAppCalendarToMarkor

**Description:** Find all events in Simple Calendar Pro whose title contains '{keyword}'. Create a Markor note named '{keyword}_events.md' listing the event titles and dates (one per line).

**Why it fits:** Cross-app: reads calendar events, writes structured output to a Markor file.

**CLI Advantage:** Query calendar, format output, write file — one pipeline. GUI requires switching between calendar and text editor.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.calendar/events \
  --projection "title:dtstart" --where "title LIKE '%keyword%'"
# Format and write to file
adb shell "echo '<formatted_output>' > /storage/emulated/0/Documents/Markor/keyword_events.md"
```

**Evaluation:** Hybrid eval. Checks that the Markor note exists and contains all matching event titles and dates.

---

### Task 51: Tier4CrossAppContactsToMarkor

**Description:** Export all contacts (name and phone number) to a Markor note named 'contacts_export.md'. Write one contact per line in the format: 'Name: phone_number'.

**Why it fits:** Cross-app: reads all contacts, writes formatted output to a file.

**CLI Advantage:** Query all contact data, format as text, write to file — one pipeline. GUI has no export-to-note feature.

**CLI Approach:**
```bash
adb shell content query --uri content://com.android.contacts/data \
  --projection "display_name:data1" --where "mimetype='vnd.android.cursor.item/phone_v2'"
# Format each line as "Name: phone" and write to file
adb shell "echo '<formatted>' > /storage/emulated/0/Documents/Markor/contacts_export.md"
```

**Evaluation:** Hybrid eval. Verifies the file exists and contains all contacts in the specified format.

---

### Task 52: Tier4CrossAppCalendarSmsConflicts

**Description:** Did anyone text me during my meetings yesterday? List the senders of all SMS received while a calendar event was active yesterday.

**Why it fits:** Cross-app temporal correlation: joins calendar event time ranges with SMS timestamps.

**CLI Advantage:** Query both databases, compare time ranges programmatically. GUI would require checking each meeting's time against each SMS timestamp.

**CLI Approach:**
```bash
# Get yesterday's calendar events with start/end times
adb shell content query --uri content://com.android.calendar/events \
  --projection "dtstart:dtend" --where "dtstart >= <yesterday_start> AND dtstart < <today_start>"
# Get SMS received yesterday
adb shell content query --uri content://sms/inbox --projection "address:date" \
  --where "date >= <yesterday_start_ms> AND date < <today_start_ms>"
# For each SMS, check if its timestamp falls within any event's [dtstart, dtend]
```

**Evaluation:** Cache-match eval. Ground truth is the list of SMS sender numbers that overlapped with calendar events.

---

### Task 53: Tier4CrossAppSmsKeywordToTasks

**Description:** Find all SMS messages in the inbox that contain the word 'urgent' and create a task in the Tasks app for each one, using the SMS body as the task title.

**Why it fits:** Cross-app: reads SMS (filter by keyword), writes to Tasks database.

**CLI Advantage:** Query SMS, filter for keyword, insert into Tasks — one script. GUI requires reading each SMS and manually creating tasks.

**CLI Approach:**
```bash
adb shell content query --uri content://sms/inbox --projection "body" --where "body LIKE '%urgent%'"
# For each matching body:
adb shell sqlite3 /data/data/org.tasks/databases/tasks.db \
  "INSERT INTO tasks (title) VALUES ('<sms_body>');"
```

**Evaluation:** Hybrid eval. Verifies tasks were created in the Tasks database with titles matching the SMS bodies.

---

### Task 54: Tier4CrossAppOpenTracksToMarkor

**Description:** Summarize this week's OpenTracks activities (total distance in km and number of activities) and save it as a note called 'weekly_stats' in Markor.

**Why it fits:** Cross-app: reads activity data from OpenTracks, writes summary to Markor.

**CLI Advantage:** SQL aggregation on OpenTracks database, write result to file — one pipeline.

**CLI Approach:**
```bash
STATS=$(adb shell sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \
  "SELECT COUNT(*), SUM(totaldistance)/1000.0 FROM tracks WHERE starttime >= datetime('now', '-7 days');")
adb shell "echo 'Activities: X, Total distance: Y km' > /storage/emulated/0/Documents/Markor/weekly_stats.md"
```

**Evaluation:** Hybrid eval. Verifies the Markor note exists and contains correct aggregated values.

---

### Task 55: Tier4CrossAppJoplinToCalendar

**Description:** Export all Joplin notes whose title contains 'meeting' to Markor as separate notes.

**Why it fits:** Cross-app: reads from Joplin database, writes multiple files to Markor directory.

**CLI Advantage:** Query Joplin database for matching notes, write each body to a separate file. GUI would require opening each note and copy-pasting.

**CLI Approach:**
```bash
adb shell sqlite3 /data/data/net.cozic.joplin/databases/joplin.db \
  "SELECT title, body FROM notes WHERE title LIKE '%meeting%';"
# For each result, write to /storage/emulated/0/Documents/Markor/<title>.md
```

**Evaluation:** Hybrid eval. Verifies that Markor files exist for each matching Joplin note with correct content.

---

## Category E — HiddenState (10 tasks)

### Category Rationale

These tasks query device-level state that is completely invisible in any application's GUI. The information is only accessible via ADB shell commands: `dumpsys`, `getprop`, `/proc`, `/sys` filesystem, and package manager queries. No amount of GUI navigation can reveal this data.

### CLI Advantage (General)

- `dumpsys` exposes internal service state (audio, package, telephony)
- `/proc` and `/sys` filesystems expose kernel-level hardware state
- `pm` and `dumpsys package` reveal app metadata not shown in settings
- `getprop` reveals system properties
- These data sources have NO GUI equivalent whatsoever

---

### Task 1: Tier4HiddenStateListAppVersions

**Description:** List the version of each of the following apps: Markor, Pro Expense, Simple Calendar Pro. Output each app name and its version.

**Why it fits:** App version info is stored in package metadata, not displayed in the app itself (only in Settings > Apps, which may truncate).

**CLI Advantage:** `dumpsys package` returns exact version strings. Deterministic and complete.

**CLI Approach:**
```bash
adb shell dumpsys package net.gsantner.markor | grep versionName
adb shell dumpsys package com.arduia.expense | grep versionName
adb shell dumpsys package com.simplemobiletools.calendar.pro | grep versionName
```

**Evaluation:** Cache-match eval. Ground truth is the exact version string for each app; all must appear in output.

---

### Task 29: Tier4HiddenStateLocationPermissions

**Description:** List all apps (by package name or app name) that have been granted location permission on this device. If none, output 'None'.

**Why it fits:** Permission grants are stored in the package manager, not visible from within any app.

**CLI Advantage:** `dumpsys package` or `pm list permissions` reveals all grants. Settings GUI requires checking each app individually.

**CLI Approach:**
```bash
adb shell dumpsys package | grep -B1 "android.permission.ACCESS_FINE_LOCATION: granted=true"
# Or:
adb shell 'for pkg in $(pm list packages -3 | cut -d: -f2); do
  if dumpsys package $pkg | grep -q "ACCESS_FINE_LOCATION: granted=true"; then echo $pkg; fi
done'
```

**Evaluation:** Cache-match eval. Ground truth is the list of packages with location permission granted.

---

### Task 30: Tier4HiddenStateAudioRouting

**Description:** What is the current audio output routing device and the current media volume level? Output the routing device name and the volume number.

**Why it fits:** Audio routing internals (which hardware device is active) are not shown in any user-facing app.

**CLI Advantage:** `dumpsys audio` exposes the active output device and volume levels.

**CLI Approach:**
```bash
adb shell dumpsys audio | grep -A5 "Output devices"
adb shell dumpsys audio | grep "STREAM_MUSIC"
```

**Evaluation:** Cache-match eval. Ground truth includes the routing device name and volume level number.

---

### Task 31: Tier4HiddenStateAppsCameraPermission

**Description:** List all apps (by package name or app name) that have been granted Camera permission on this device. If none, output 'None'.

**Why it fits:** Same pattern as Task 29 but for camera permission — hidden in package manager state.

**CLI Advantage:** `dumpsys package` grep for CAMERA permission grants.

**CLI Approach:**
```bash
adb shell dumpsys package | grep -B1 "android.permission.CAMERA: granted=true"
```

**Evaluation:** Cache-match eval. Ground truth is the list of packages with camera permission granted.

---

### Task 36: Tier4HiddenStatePhoneTemperature

**Description:** What is my phone's current temperature? Is it overheating?

**Why it fits:** Hardware thermal sensors are only accessible via `/sys/class/thermal/` — no app exposes this.

**CLI Advantage:** Direct filesystem read of thermal zone data.

**CLI Approach:**
```bash
adb shell 'for z in /sys/class/thermal/thermal_zone*; do
  echo "$(cat $z/type): $(cat $z/temp)"
done'
# Temperature is typically in millidegrees; divide by 1000 for Celsius
# Overheating threshold is typically 45-50C
```

**Evaluation:** Cache-match eval. Ground truth includes the temperature reading and whether it exceeds the overheating threshold.

---

### Task 37: Tier4HiddenStateRecentInstalls

**Description:** What are the 3 most recently installed apps on the device? Output their package names.

**Why it fits:** Installation timestamps are stored in package manager metadata, not visible in any app list GUI.

**CLI Advantage:** `dumpsys package` includes firstInstallTime; sort to find most recent.

**CLI Approach:**
```bash
adb shell 'for pkg in $(pm list packages -3 | cut -d: -f2); do
  echo "$(dumpsys package $pkg | grep firstInstallTime | head -1) $pkg"
done | sort -r | head -3'
```

**Evaluation:** Cache-match eval. Ground truth is the 3 most recently installed package names.

---

### Task 38: Tier4HiddenStateUptime

**Description:** How long has the device been running since last reboot? Output the uptime in hours and minutes.

**Why it fits:** System uptime is kernel state, accessible only via /proc/uptime.

**CLI Advantage:** Direct read of `/proc/uptime` and arithmetic conversion to hours/minutes.

**CLI Approach:**
```bash
adb shell cat /proc/uptime
# First field is seconds since boot; convert to hours and minutes
```

**Evaluation:** Cache-match eval. Ground truth is the uptime in hours and minutes (with reasonable tolerance for elapsed time during evaluation).

---

### Task 39: Tier4HiddenStateBackgroundLocationApps

**Description:** Which apps have recently accessed my location in the background?

**Why it fits:** Background location access history is stored in system services, not exposed to the user via any standard app.

**CLI Advantage:** `dumpsys location` or `appops` reveals recent background location access.

**CLI Approach:**
```bash
adb shell dumpsys appops | grep -A2 "ACCESS_FINE_LOCATION.*background"
# Or:
adb shell appops query-op --op ACCESS_BACKGROUND_LOCATION allow
```

**Evaluation:** Cache-match eval. Ground truth is the list of apps with recent background location access.

---

### Task 40: Tier4HiddenStateSignalStrength

**Description:** What is my current network signal strength in dBm?

**Why it fits:** Signal strength in raw dBm is only available via telephony service internals.

**CLI Advantage:** `dumpsys telephony.registry` exposes exact signal strength values.

**CLI Approach:**
```bash
adb shell dumpsys telephony.registry | grep -i "signalstrength"
# Or:
adb shell dumpsys connectivity | grep -i "signal"
```

**Evaluation:** Cache-match eval. Ground truth is the signal strength value in dBm.

---

### Task 41: Tier4HiddenStateSmsDbSize

**Description:** How much storage space is my SMS database using?

**Why it fits:** Database file size on disk is a filesystem-level metric not exposed by the SMS app.

**CLI Advantage:** Direct `stat` or `ls -l` on the SMS database file.

**CLI Approach:**
```bash
adb shell ls -l /data/data/com.android.providers.telephony/databases/mmssms.db
# Or:
adb shell stat -c %s /data/data/com.android.providers.telephony/databases/mmssms.db
```

**Evaluation:** Cache-match eval. Ground truth is the file size (with reasonable tolerance for minor size changes).

---

## Appendix: Task Index

| ID | Class | Category |
|----|-------|----------|
| 0 | Tier4BulkDeleteTmpInDownloads | B |
| 1 | Tier4HiddenStateListAppVersions | E |
| 2 | Tier4CrossAppSmsNumbersNotInContacts | D |
| 3 | Tier4BulkRenameScreenshots | B |
| 4 | Tier4BulkMoveLargeFiles | B |
| 5 | Tier4BulkAppendFooterToMarkdown | B |
| 6 | Tier4AggregationLongestMarkorNote | A |
| 7 | Tier4TopKMarkorMostModifiedNotes | A |
| 8 | Tier4TopKSmsThreadsByCount | A |
| 9 | Tier4FilterContactsBirthdayNoPhone | C |
| 10 | Tier4FilterContactsNoFamilyName | C |
| 11 | Tier4AggregationContactsDuplicatePhones | A |
| 12 | Tier4DedupMergeContactsSamePhone | B |
| 13 | Tier4BulkRecategorizeExpense | B |
| 14 | Tier4FilterExpenseHighTravelLastMonth | C |
| 15 | Tier4AggregationExpenseCategoryTop3 | A |
| 16 | Tier4AggregationExpenseSuspectedDuplicates | A |
| 17 | Tier4TopKExpenseHighestAmount | A |
| 18 | Tier4CrossAppExpenseToMarkorCalendar | D |
| 19 | Tier4BulkChangePriorityTasks | B |
| 20 | Tier4FilterJoplinContainsNotContains | C |
| 21 | Tier4AggregationOpenTracksWeeklyStats | A |
| 22 | Tier4TopKOpenTracksFastestActivity | A |
| 23 | Tier4FilterRetroMusicMultiCondition | C |
| 24 | Tier4TopKRetroMusicLongestSongs | A |
| 25 | Tier4CrossAppBroccoliToMarkorIndex | D |
| 26 | Tier4CrossAppMarkorPhonesVsContacts | D |
| 27 | Tier4AggregationDownloadSizeTop3 | A |
| 28 | Tier4TopKLargestDownloadFiles | A |
| 29 | Tier4HiddenStateLocationPermissions | E |
| 30 | Tier4HiddenStateAudioRouting | E |
| 31 | Tier4HiddenStateAppsCameraPermission | E |
| 32 | Tier4BulkDeleteCalendarTestEvents | B |
| 33 | Tier4CrossAppCalendarToMarkor | D |
| 34 | Tier4DedupCalendarDeleteDuplicateEvents | B |
| 35 | Tier4CoverageCalendarEventsHaveReminders | C |
| 36 | Tier4HiddenStatePhoneTemperature | E |
| 37 | Tier4HiddenStateRecentInstalls | E |
| 38 | Tier4HiddenStateUptime | E |
| 39 | Tier4HiddenStateBackgroundLocationApps | E |
| 40 | Tier4HiddenStateSignalStrength | E |
| 41 | Tier4HiddenStateSmsDbSize | E |
| 42 | Tier4FilterSmsContainingUrl | C |
| 43 | Tier4CoverageSmsAllFromKnownContacts | C |
| 44 | Tier4FilterLargeOldFiles | C |
| 45 | Tier4FilterEmptyFilesInDownloads | C |
| 46 | Tier4BulkDeleteApkFiles | B |
| 47 | Tier4FilterExpenseAboveAverage | C |
| 48 | Tier4AggregationExpenseAllCategorized | A |
| 49 | Tier4BulkDeleteSmallExpenses | B |
| 50 | Tier4FilterCalendarWeekendEvents | C |
| 51 | Tier4CrossAppContactsToMarkor | D |
| 52 | Tier4CrossAppCalendarSmsConflicts | D |
| 53 | Tier4CrossAppSmsKeywordToTasks | D |
| 54 | Tier4CrossAppOpenTracksToMarkor | D |
| 55 | Tier4CrossAppJoplinToCalendar | D |
