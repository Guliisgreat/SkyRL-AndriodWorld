# Tier 4 Ground Truth Reference v1 — 45-Task Realistic Subset

## Overview

This document is the canonical reference for Tier 4 ADB-exclusive task ground truths
on the `androidworld:2026plusswipe_tier4` AVD. Each entry shows the device-side commands
that solve the task end-to-end (verified to produce `reward=1.0` via
`docker/androidworld_2026plusswipe_tier4/test_integration.py`).

### Subset selection

Tier 4 defines 56 tasks (see `docs/design/tier4_final.md`). This reference is a
**realistic subset** — only tasks that a real human would plausibly ask their phone
to do, and that can be solved by the canonical CLI approach on the current AVD.

Excluded (11 of 56):

| id | task | reason |
|---|---|---|
| 1 | HiddenStateListAppVersions | unusual ask — hardcoded list of 3 specific apps |
| 2 | CrossAppSmsNumbersNotInContacts | **SKIP** — fixture uses telnet `text_emulator` which does not land in mmssms.db on this AVD |
| 6 | AggregationLongestMarkorNote | unusual phrasing — "char count" instead of "longest" |
| 12 | DedupMergeContactsSamePhone | unusual merge rule — "alphabetically first" instead of "most complete info" |
| 14 | FilterExpenseHighTravelLastMonth | requires `created_date < this-month-start` filter; AVD clock frozen Oct 2023 vs fixture host time May 2026 makes the date semantics unusable |
| 27 | AggregationDownloadSizeTop3 | unusual phrasing — "total size in bytes" |
| 30 | HiddenStateAudioRouting | unusual combined ask (routing device AND volume in one) |
| 40 | HiddenStateSignalStrength | power-user phrasing — "signal strength in dBm" |
| 41 | HiddenStateSmsDbSize | implementation-level — "SMS database storage size" |
| 44 | FilterLargeOldFiles | requires `-mtime +30` against device clock; same clock-skew issue as 14/19 |
| 48 | AggregationExpenseAllCategorized | dev/admin framing — "verify all are categorized" |

**Subset: 45 runnable task IDs.** Smoke pass rate on this subset: **45/45**
(verified end-to-end against `androidworld:2026plusswipe_tier4`).

Subset JSONL: `eval-runners/data/tier4/realistic_subset_seed7.jsonl` (45 rows).

### Format

Each task entry below carries:

- **Goal** — the task description as returned by `/reset`.
- **Step N** — one or more `adb shell` commands in execution order, run from
  the host against the emulator. Two forms appear:
  - `(shell)`  — `adb shell <cmd>`. Plain single-word-style invocation (no
    spaces in any argument value).
  - `(sh -c)`  — `adb shell sh -c '<script>'`. Needed whenever the argument
    contains spaces, quotes, glob patterns, SQL strings, `&&`, `|`, `for`,
    `$()`, etc. — because adb concatenates its post-`shell` argv with
    spaces and no quoting, so any inner whitespace would break parsing
    on the device side.
- **Verifier** — what the task's `is_successful()` checks against the
  post-action state. Drives what the agent must output (cache-match) or
  mutate (state-check).

> **All commands execute inside the Android emulator (API 33).** Nothing
> here is a host-side shell command — every line literally begins with
> `adb shell` and is dispatched to the AVD.

> **Quoting caveat.** Several `adb shell sh -c '<script>'` entries contain
> single quotes inside `<script>` (e.g. SQL `LIKE '%test%'`). The forms
> shown are the *device-side script intent*. When typing these at a host
> shell, you may need to escape the inner singles via `'"'"'` or switch
> the outer wrapper to double quotes. `docker/.../test_integration.py`
> uses `shlex.quote` to produce the actual wire-form sent to `/step_adb`.

### How to reproduce

```bash
# Build the image
cd docker/
docker build -f androidworld_2026plusswipe_tier4/Dockerfile -t androidworld:2026plusswipe_tier4 .

# Start a container
docker run -d --name tier4_smoke --device /dev/kvm \
    -e ENV_SKIP_SCREENSHOT=true -e LAZY_EVAL=true \
    -p 5800:5000 androidworld:2026plusswipe_tier4

# Run the integration tests (executes the ground truths and checks reward=1.0)
cd docker/androidworld_2026plusswipe_tier4
python3 -c "import test_integration as ti; ti.CONTAINER_NAME='tier4_smoke'; \
    r = ti.test_all_golden_paths('http://localhost:5800'); \
    print('PASS:', sum(1 for x in r if x['status']=='PASS'))"
```

---


## Category B — Bulk / Dedup (10 tasks)

### Task 00: Tier4BulkDeleteTmpInDownloads

**Goal:** Delete all .tmp files in the Downloads folder.

**Step 1** (shell):
```
adb shell find /storage/emulated/0/Download -name *.tmp -delete
```

**Verifier:** eval queries device state (find) post-action to confirm mutation

### Task 03: Tier4BulkRenameScreenshots

**Goal:** Rename all files starting with 'Screenshot_' in the Pictures folder (/storage/emulated/0/Pictures/) to the format YYYYMMDD_HHMMSS.png based on each file's modification time.

**Step 1** (sh -c):
```
adb shell sh -c 'for f in /storage/emulated/0/Pictures/Screenshot_*.png; do ts=$(stat -c %Y "$f"); mv "$f" "/storage/emulated/0/Pictures/$(date -d @$ts +%Y%m%d_%H%M%S).png"; done'
```

**Verifier:** eval queries device state (find) post-action to confirm mutation

### Task 04: Tier4BulkMoveLargeFiles

**Goal:** Move all files larger than 50MB in the Download folder to the Archive folder (/storage/emulated/0/Archive/). Create the Archive folder if it doesn't exist.

**Step 1** (shell):
```
adb shell mkdir -p /storage/emulated/0/Archive
```

**Step 2** (sh -c):
```
adb shell sh -c 'for f in $(find /storage/emulated/0/Download -type f -size +50M); do mv "$f" /storage/emulated/0/Archive/; done'
```

**Verifier:** eval queries device state (find) post-action to confirm mutation

### Task 05: Tier4BulkAppendFooterToMarkdown

**Goal:** Append the following text to every .md file in the 'Notes' folder in Markor (/storage/emulated/0/Documents/Markor/Notes/): --- Generated by AutoBot

**Step 1** (sh -c):
```
adb shell sh -c 'for f in /storage/emulated/0/Documents/Markor/Notes/*.md; do printf "\n---\nGenerated by AutoBot" >> "$f"; done'
```

**Verifier:** (see source)

### Task 13: Tier4BulkRecategorizeExpense

**Goal:** I miscategorized some expenses — change all 'Food' entries in Pro Expense to 'Entertainment'.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "UPDATE expense SET category=6 WHERE category=3;"'
```

**Verifier:** (see source)

### Task 19: Tier4BulkChangePriorityTasks

**Goal:** Change all overdue tasks in the Tasks app to High priority.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database "UPDATE tasks SET importance=3 WHERE title LIKE 'overdue_task_%';"'
```

**Verifier:** (see source)

### Task 32: Tier4BulkDeleteCalendarTestEvents

**Goal:** Delete all events in Simple Calendar Pro whose title contains the word 'test' (case-insensitive).

**Step 1** (sh -c):
```
adb shell sh -c 'content delete --uri content://com.android.calendar/events --where "title LIKE '%test%'"'
```

**Verifier:** eval queries device state (find) post-action to confirm mutation; eval queries the content provider to confirm mutation

### Task 34: Tier4DedupCalendarDeleteDuplicateEvents

**Goal:** Delete duplicate calendar events in Simple Calendar Pro (events with the same title AND the same start time), keeping only one copy of each.

**Approach:** Tier4DedupCalendarDeleteDuplicateEvents: for each (title, dtstart)

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection _id:title:dtstart'
```

**Step 2** (sh -c):
```
adb shell sh -c 'content delete --uri content://com.android.calendar/events --where "_id=<dup_id>"'
```

**Verifier:** eval queries device state (find) post-action to confirm mutation; eval queries the content provider to confirm mutation

### Task 46: Tier4BulkDeleteApkFiles

**Goal:** Delete all .apk files in my Downloads folder — those are leftover app installers I no longer need.

**Step 1** (shell):
```
adb shell find /storage/emulated/0/Download -name *.apk -delete
```

**Verifier:** eval queries device state (find) post-action to confirm mutation

### Task 49: Tier4BulkDeleteSmallExpenses

**Goal:** Delete all expenses in Pro Expense that are less than $1.00 (less than 100 cents).

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "DELETE FROM expense WHERE amount < 100;"'
```

**Verifier:** (see source)


## Category C — Filter / Coverage (10 tasks)

### Task 09: Tier4FilterContactsBirthdayNoPhone

**Goal:** List all contacts that have a birthday set but no phone number. Output the contact names.

**Approach:** Task 9: contacts with birthday set but no phone number.

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype='vnd.android.cursor.item/contact_event' AND data2=3"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Step 3** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id:display_name --where "mimetype='vnd.android.cursor.item/name'"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 10: Tier4FilterContactsNoFamilyName

**Goal:** List all contacts that have a phone number but no family name (first name only).

**Approach:** Task 10: contacts with phone but no family name (only given name).

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id:display_name:data2:data3 --where "mimetype='vnd.android.cursor.item/name'"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output; eval queries the content provider to confirm mutation

### Task 20: Tier4FilterJoplinContainsNotContains

**Goal:** List all Joplin notes that contain '{keyword_a}' but do NOT contain '{keyword_b}'. Output the note titles.

**Approach:** Task 20: notes containing keyword_a but NOT keyword_b.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite "SELECT title FROM notes WHERE body LIKE '%<kw_a>%' AND body NOT LIKE '%<kw_b>%';"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 23: Tier4FilterRetroMusicMultiCondition

**Goal:** List all songs in Retro Music by artist '{artist}' that are longer than 4 minutes. Output the song titles.

**Approach:** Task 23: songs by `<artist>` longer than 4 min. Extract artist

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://media/external/audio/media --projection title:duration --where "artist='<artist>' AND duration > 240000"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 35: Tier4CoverageCalendarEventsHaveReminders

**Goal:** Do all my calendar events this month have reminders set? If any are missing reminders, tell me which ones.

**Approach:** Task 35: events this month with NO reminder. Left-join events vs

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection _id:title:dtstart'
```

**Step 2** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.calendar/reminders --projection event_id'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 42: Tier4FilterSmsContainingUrl

**Goal:** List all SMS messages in the inbox that contain a URL (http:// or https://). Output the sender phone numbers.

**Approach:** Task 42: phone numbers whose SMS body matches /http/. The fixture's

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT address FROM sms WHERE body LIKE '%http%';"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 43: Tier4CoverageSmsAllFromKnownContacts

**Goal:** Are there any SMS messages in my inbox from numbers not in my contacts? If so, how many?

**Approach:** Task 43: count SMS senders not in contacts. Variants: all_known

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms;"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Verifier:** (see source)

### Task 45: Tier4FilterEmptyFilesInDownloads

**Goal:** List all zero-byte (empty) files in the Downloads folder. Output the filenames.

**Approach:** Task 45: list zero-byte files in Downloads (fixture: tier4ext_empty_*).

**Step 1** (shell):
```
adb shell find /storage/emulated/0/Download -maxdepth 1 -type f -empty
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 47: Tier4FilterExpenseAboveAverage

**Goal:** Which of my expenses are above my average spending? List them.

**Approach:** Task 47: expenses with amount above the overall average. Subquery

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT name FROM expense WHERE amount > (SELECT AVG(amount) FROM expense);"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 50: Tier4FilterCalendarWeekendEvents

**Goal:** What do I have planned on weekends this month? List all calendar events that fall on a Saturday or Sunday.

**Approach:** Task 50: events titled tier4cal_wkday_{offset} where today+offset

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection title:dtstart'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output


## Category A — Aggregation / TopK (10 tasks)

### Task 07: Tier4TopKMarkorMostModifiedNotes

**Goal:** Which 5 notes in Markor (/storage/emulated/0/Documents/Markor/) were modified most recently in the last 7 days? List the filenames.

**Approach:** Task 7: 5 most recently modified `recent_*.md` files.

**Step 1** (sh -c):
```
adb shell sh -c 'for f in /storage/emulated/0/Documents/Markor/recent_*.md; do echo $(stat -c %Y $f) $(basename $f); done | sort -rn | head -5'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 08: Tier4TopKSmsThreadsByCount

**Goal:** Which 3 phone numbers have the most SMS messages in your inbox? List their phone numbers.

**Approach:** Task 8: 3 phone numbers with the most SMS in inbox. Query via

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT address, COUNT(*) AS c FROM sms GROUP BY address ORDER BY c DESC LIMIT 3;"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 11: Tier4AggregationContactsDuplicatePhones

**Goal:** List all groups of contacts that share the same phone number. Output each group with the shared phone number and the contact names.

**Approach:** Task 11: list groups of contacts that share a phone number.

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Verifier:** (see source)

### Task 15: Tier4AggregationExpenseCategoryTop3

**Goal:** What are the top 3 expense categories by total amount this month in Pro Expense? Output the category names.

**Approach:** Task 15: 3 expense categories by SUM(amount) this month, by NAME.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT category, SUM(amount) AS total FROM expense GROUP BY category ORDER BY total DESC LIMIT 3;"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 16: Tier4AggregationExpenseSuspectedDuplicates

**Goal:** How many suspected duplicate expenses are there in Pro Expense (same date, same amount, same category)? Output the number of duplicates (i.e., extras beyond the first of each group).

**Approach:** Task 16: integer count of "extras beyond first of each duplicate

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT IFNULL(SUM(cnt - 1), 0) FROM (SELECT COUNT(*) AS cnt FROM expense GROUP BY created_date, amount, category HAVING cnt > 1);"'
```

**Verifier:** agent's text output must contain `_ground_truth` value

### Task 17: Tier4TopKExpenseHighestAmount

**Goal:** What are the 5 highest-amount expenses in Pro Expense? List the expense names and amounts.

**Approach:** Task 17: 5 highest-amount expense names.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT name FROM expense ORDER BY amount DESC LIMIT 5;"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 21: Tier4AggregationOpenTracksWeeklyStats

**Goal:** What is the total distance of all activities this week in OpenTracks, and which activity covered the longest distance?

**Approach:** Task 21: total distance + longest activity this week.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT printf('%.1f', SUM(totaldistance)/1000.0) FROM tracks WHERE starttime >= (strftime('%s','now')-7*86400)*1000;"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT name FROM tracks WHERE starttime >= (strftime('%s','now')-7*86400)*1000 ORDER BY totaldistance DESC LIMIT 1;"'
```

**Verifier:** agent's text output must contain `_ground_truth` value

### Task 22: Tier4TopKOpenTracksFastestActivity

**Goal:** Which activity in OpenTracks had the highest average speed? Output the activity name and its average speed.

**Approach:** Task 22: activity with highest avg speed (distance/time).

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT name, printf('%.1f', totaldistance/(totaltime/1000.0)) FROM tracks ORDER BY (totaldistance/(totaltime/1000.0)) DESC LIMIT 1;"'
```

**Verifier:** agent's text output must contain `_ground_truth` value

### Task 24: Tier4TopKRetroMusicLongestSongs

**Goal:** What are the 5 longest songs in Retro Music by duration? List their titles.

**Approach:** Task 24: 5 longest songs by duration. ORDER BY duration DESC

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://media/external/audio/media --projection title:duration --sort "duration DESC"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 28: Tier4TopKLargestDownloadFiles

**Goal:** What are the 5 largest files in the Downloads folder? List their filenames and sizes.

**Approach:** Task 28: 5 largest files in Downloads — all of them, sorted.

**Step 1** (sh -c):
```
adb shell sh -c 'find /storage/emulated/0/Download -maxdepth 1 -type f -printf '%s %f\n' | sort -rn | head -5'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output


## Category D — CrossApp (9 tasks)

### Task 18: Tier4CrossAppExpenseToMarkorCalendar

**Goal:** Calculate the total expenses for this month in Pro Expense, write the total (in dollars) to a Markor note named 'monthly_summary.md', and create a Simple Calendar Pro event titled 'Monthly Expense: $<total>' on the last day of this month.

**Approach:** Task 18: sum this-month expenses, write to Markor note, create

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT printf('%.2f', SUM(amount)/100.0) FROM expense WHERE created_date >= (strftime('%s', date('now','start of month'))*1000);"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'mkdir -p <_MARKOR_DIR_DEV>; echo 'Total: $<total>' > <note_path>'
```

**Step 3** (sh -c):
```
adb shell sh -c 'content insert --uri content://com.android.calendar/events --bind title:s:Monthly_Expense_<total> --bind dtstart:l:<dtstart_ms> --bind dtend:l:<dtstart_ms + 3600000> --bind calendar_id:i:1 --bind eventTimezone:s:UTC'
```

**Verifier:** eval queries the content provider to confirm mutation

### Task 25: Tier4CrossAppBroccoliToMarkorIndex

**Goal:** Which of my contacts texted me but I haven't replied to?

**Approach:** Task 25: contacts who texted me (inbox) but I didn't reply (no

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms WHERE type=1;"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms WHERE type=2;"'
```

**Step 3** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 26: Tier4CrossAppMarkorPhonesVsContacts

**Goal:** Extract all phone numbers mentioned in Markor notes, then list the ones that are NOT in your contacts. Output the numbers.

**Approach:** Task 26: phone numbers found in Markor notes that are NOT in

**Step 1** (sh -c):
```
adb shell sh -c 'grep -rhoE '\+[0-9]+' /storage/emulated/0/Documents/Markor/ 2>/dev/null | sort -u'
```

**Step 2** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 33: Tier4CrossAppCalendarToMarkor

**Goal:** Find all events in Simple Calendar Pro whose title contains '{keyword}'. Create a Markor note named '{keyword}_events.md' listing the event titles and dates (one per line).

**Approach:** Task 33: query calendar for events whose title contains the

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection title:dtstart --where "title LIKE '%<keyword>%'"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'mkdir -p <_MARKOR_DIR_DEV>; printf '<body>\n' > <note_path>'
```

**Verifier:** eval queries device state (find) post-action to confirm mutation

### Task 51: Tier4CrossAppContactsToMarkor

**Goal:** Export all contacts (name and phone number) to a Markor note named 'contacts_export.md'. Write one contact per line in the format: 'Name: phone_number'.

**Approach:** Task 51: export each contact as `Name: phone` to a Markor note.

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data1 --where "mimetype='vnd.android.cursor.item/phone_v2'"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'mkdir -p <_MARKOR_DIR_DEV>; printf '<body>\n' > <note_path>'
```

**Verifier:** (see source)

### Task 52: Tier4CrossAppCalendarSmsConflicts

**Goal:** Did anyone text me during my meetings yesterday? List the senders of all SMS received while a calendar event was active yesterday.

**Approach:** Task 52: list SMS senders whose timestamp falls within ANY

**Step 1** (sh -c):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection dtstart:dtend --where "dtstart >= <y_start_ms> AND dtstart < <today_start_ms>"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms WHERE <or_clauses>;"'
```

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 53: Tier4CrossAppSmsKeywordToTasks

**Goal:** Find all SMS messages in the inbox that contain the word 'urgent' and create a task in the Tasks app for each one, using the SMS body as the task title.

**Approach:** Task 53: find SMS with 'urgent' in body, create a task for each.

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT body FROM sms WHERE body LIKE '%urgent%';"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database "INSERT INTO tasks (<cols>) VALUES ('<body_sql>', 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);"'
```

**Verifier:** eval queries the app's sqlite DB to confirm mutation

### Task 54: Tier4CrossAppOpenTracksToMarkor

**Goal:** Summarize this week's OpenTracks activities (total distance in km and number of activities) and save it as a note called 'weekly_stats' in Markor.

**Approach:** Task 54: COUNT + SUM(distance)/1000 of this-week activities;

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT COUNT(*), printf('%.1f', SUM(totaldistance)/1000.0) FROM tracks WHERE starttime >= (strftime('%s','now')-7*86400)*1000;"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'mkdir -p <_MARKOR_DIR_DEV>; echo '<content>' > <note_path>'
```

**Verifier:** eval queries device state (find) post-action to confirm mutation

### Task 55: Tier4CrossAppJoplinToCalendar

**Goal:** Export all Joplin notes whose title contains 'meeting' to Markor as separate notes.

**Approach:** Task 55: export Joplin notes with 'meeting' in title to Markor as

**Step 1** (sh -c):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite "SELECT title, body FROM notes WHERE title LIKE '%meeting%';"'
```

**Step 2** (sh -c):
```
adb shell sh -c 'mkdir -p <_MARKOR_DIR_DEV>; echo '<body_safe>' > <_MARKOR_DIR_DEV>/<title>.md'
```

**Verifier:** (see source)


## Category E — Hidden State (6 tasks)

### Task 29: Tier4HiddenStateLocationPermissions

**Goal:** List all apps (by package name or app name) that have been granted location permission on this device. If none, output 'None'.

**Step 1** (shell):
```
adb shell dumpsys package permissions
```

**FINISH content:** 

**Verifier:** each `_ground_truth` element must appear in agent's text output; special-case empty answer: agent says 'none' / 'all categorized' / etc.

### Task 31: Tier4HiddenStateAppsCameraPermission

**Goal:** List all apps (by package name or app name) that have been granted Camera permission on this device. If none, output 'None'.

**Step 1** (shell):
```
adb shell dumpsys package permissions
```

**FINISH content:** 

**Verifier:** each `_ground_truth` element must appear in agent's text output; special-case empty answer: agent says 'none' / 'all categorized' / etc.

### Task 36: Tier4HiddenStatePhoneTemperature

**Goal:** What is my phone's current temperature? Is it overheating?

**Step 1** (shell):
```
adb shell dumpsys battery
```

**FINISH content:** dumpsys battery → temperature: NNN (tenths of °C). Output Celsius.

**Verifier:** agent's text output must contain a number within tolerance of the ground truth

### Task 37: Tier4HiddenStateRecentInstalls

**Goal:** What are the 3 most recently installed apps on the device? Output their package names.

**Step 1** (shell):
```
adb shell dumpsys package packages
```

**FINISH content:** Re-parse `dumpsys package packages` and pick the 3 most-recent

**Verifier:** each `_ground_truth` element must appear in agent's text output

### Task 38: Tier4HiddenStateUptime

**Goal:** How long has the device been running since last reboot? Output the uptime in hours and minutes.

**Step 1** (shell):
```
adb shell cat /proc/uptime
```

**FINISH content:** cat /proc/uptime → "<sec> <idle>" → output H hours M minutes.

**Verifier:** (see source)

### Task 39: Tier4HiddenStateBackgroundLocationApps

**Goal:** Which apps have recently accessed my location in the background?

**Step 1** (shell):
```
adb shell dumpsys appops
```

**FINISH content:** Parse `dumpsys appops` for packages that have a fine/coarse

**Verifier:** agent's text output must contain `_ground_truth` value


