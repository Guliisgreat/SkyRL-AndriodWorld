# Tier 4 Ground Truth Reference v2 — Discovery-then-Act

## Overview

This is the v2 ground-truth reference for the **45-task realistic subset** of
Tier 4. Each entry models what a thoughtful human oracle actually does on a
fresh device — **discover, inspect, then act** — instead of starting with a
cheat sheet of paths, schemas, and enum IDs.

> v1 of this doc (`tier4_ground_truth_reference_v1.md`) collapsed the
> discovery flow into baked-in knowledge: "the Pro Expense database is at
> `/data/data/com.arduia.expense/databases/accounting.db`, the `expense`
> table has a `category` column, and `category=3` means Food". A real agent
> doesn't know any of that until it inspects the device. v2 makes the
> discovery process visible.

### The four step kinds

Each task entry uses 1–4 of these step kinds, in order:

- **D (discover)** — find the package, file path, content URI, or dumpsys
  section that holds the target data. Typically `pm list packages | grep`,
  `ls /data/data/<pkg>/`, or `dumpsys <component> | head`.
- **I (inspect)** — read the structure: SQLite `.schema <table>`, content
  query first few rows with `--projection <fields>`, `dumpsys <x>` head.
- **P (probe)** — fetch enum values: e.g., the integer→name mapping for an
  expense `category` column, or which mimetype string keys the contacts
  data table uses for phone vs name vs birthday rows. Only needed when the
  action's WHERE clause depends on app-defined IDs.
- **A (act)** — the mutation or query that produces the eval-checked
  side-effect or output.

### Conventions

- Every command begins with `adb shell` — they all run inside the Android
  emulator (API 33), not the host.
- `adb shell <cmd>` is the bare form; `adb shell sh -c '<script>'` is used
  for any command whose argument list contains spaces, SQL strings, glob
  patterns, `&&`, `|`, `for`, `$()`, etc., because adb concatenates its
  post-`shell` argv with spaces and no quoting.
- Inline `# →` lines under a command show the expected response, abbreviated.
- `<angle-bracket>` tokens (`<keyword>`, `<id>`, etc.) mark values that the
  agent fills in from the previous step's output or from the task goal text.

### Execution caveat (read before copy-pasting)

The `adb shell sh -c '<script>'` forms below show the **device-side script
intent**, not always the wire form. When pasted into an interactive bash
shell they work, but when fed through a pipeline that does `shlex.split`
then `subprocess.run` with the resulting tokens (which is what the
`/step_adb` HTTP endpoint does internally), the outer single-quote form
gets split into multiple tokens and adb concatenates them with spaces —
destroying the script's word-boundaries before sh -c sees it.

A literal-execution verification of every command in this doc against the
live container produced:

- **2/17 reward=1.0** for state-mutation tasks (only the simplest `find -delete` cases survived the quoting flatten).
- 35/45 D/I/P/A command sequences ran end-to-end (the cache-match tasks
  capture data fine — they just need a final FINISH that this verifier
  didn't derive).

The authoritative wire form lives in
`docker/androidworld_2026plusswipe_tier4/test_integration.py`, which
applies `shlex.quote` twice per script (once to escape the inner sh script,
once to package the whole `sh -c '...'` as a single shlex token that adb
sees as one arg, not many). That file runs **45/45 PASS** against the
container and is the canonical reproducer.

To execute a single script from this doc end-to-end yourself, use the
helper pattern:

```bash
# Bash helper that handles the double-wrapping correctly for adb shell.
adb_sh() { adb shell "$(printf 'sh -c %q' "$1")"; }

# Example: use it for any sh -c script from the doc below
adb_sh 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "UPDATE expense SET category=6 WHERE category=3;"'
```

`adb shell <bare-command>` (no `sh -c`) entries can be copy-pasted as-is.

### Subset (45 of 56)

11 of the 56 tier4 tasks are excluded from this reference because they're
either unrealistic phrasing for a human user, or because an AVD clock
mismatch / fixture path makes the canonical approach unsolvable:


| id | task | reason |
|---|---|---|
| 01 | HiddenStateListAppVersions | unusual ask — hardcoded list of 3 specific apps |
| 02 | CrossAppSmsNumbersNotInContacts | SKIP — fixture uses telnet `text_emulator` which does not land in mmssms.db on this AVD |
| 06 | AggregationLongestMarkorNote | unusual phrasing — "char count" instead of "longest" |
| 12 | DedupMergeContactsSamePhone | unusual merge rule — "alphabetically first" not "most complete info" |
| 14 | FilterExpenseHighTravelLastMonth | needs last-month date filter; AVD clock frozen Oct 2023 vs fixture host time May 2026 makes it unsolvable |
| 27 | AggregationDownloadSizeTop3 | unusual phrasing — "total size in bytes" |
| 30 | HiddenStateAudioRouting | unusual combined ask (routing device AND volume in one) |
| 40 | HiddenStateSignalStrength | power-user phrasing — "signal strength in dBm" |
| 41 | HiddenStateSmsDbSize | implementation-level — "SMS database storage size" |
| 44 | FilterLargeOldFiles | needs `-mtime +30` against device clock; same skew as 14 |
| 48 | AggregationExpenseAllCategorized | dev/admin framing — "verify all are categorized" |

**Subset: 45 runnable task IDs.** Smoke pass rate on this subset: **45/45** (verified end-to-end against `androidworld:2026plusswipe_tier4`).

Subset JSONL: `eval-runners/data/tier4/realistic_subset_seed7.jsonl`.

---

## Category B — Bulk / Dedup (10 tasks)

### Task 00: Tier4BulkDeleteTmpInDownloads

**Goal:** Delete all .tmp files in the Downloads folder.

**Step D — locate the directory and confirm contents** (discover):
```
adb shell ls -la /storage/emulated/0/Download | head -10
```

**Step A — delete every .tmp file under Downloads** (act):
```
adb shell find /storage/emulated/0/Download -name '*.tmp' -delete
```


### Task 03: Tier4BulkRenameScreenshots

**Goal:** Rename all files starting with 'Screenshot_' in the Pictures folder (/storage/emulated/0/Pictures/) to the format YYYYMMDD_HHMMSS.png based on each file's modification time.

**Step D — locate the directory and confirm contents** (discover):
```
adb shell ls -la /storage/emulated/0/Pictures | head -10
```

**Step I — confirm the screenshot file naming and mtimes** (inspect):
```
adb shell ls -la /storage/emulated/0/Pictures/Screenshot_*.png
```

**Step A — rename each Screenshot_* to YYYYMMDD_HHMMSS.png using mtime** (act):
```
adb shell sh -c 'for f in /storage/emulated/0/Pictures/Screenshot_*.png; do ts=$(stat -c %Y "$f"); mv "$f" "/storage/emulated/0/Pictures/$(date -d @$ts +%Y%m%d_%H%M%S).png"; done'
```


### Task 04: Tier4BulkMoveLargeFiles

**Goal:** Move all files larger than 50MB in the Download folder to the Archive folder (/storage/emulated/0/Archive/). Create the Archive folder if it doesn't exist.

**Step D — locate the directory and confirm contents** (discover):
```
adb shell ls -la /storage/emulated/0/Download | head -10
```

**Step I — find files >50MB** (inspect):
```
adb shell find /storage/emulated/0/Download -type f -size +50M
```

**Step A — ensure Archive dir, move each large file** (act):
```
adb shell mkdir -p /storage/emulated/0/Archive
adb shell sh -c 'for f in $(find /storage/emulated/0/Download -type f -size +50M); do mv "$f" /storage/emulated/0/Archive/; done'
```


### Task 05: Tier4BulkAppendFooterToMarkdown

**Goal:** Append the following text to every .md file in the 'Notes' folder in Markor (/storage/emulated/0/Documents/Markor/Notes/):\n---\nGenerated by AutoBot

**Step D — locate Markor's Notes subfolder** (discover):
```
adb shell ls /storage/emulated/0/Documents/Markor/Notes/ | head -5
```

**Step A — append the footer to every .md in Notes/** (act):
```
adb shell sh -c 'for f in /storage/emulated/0/Documents/Markor/Notes/*.md; do printf "\n---\nGenerated by AutoBot" >> "$f"; done'
```


### Task 13: Tier4BulkRecategorizeExpense

**Goal:** I miscategorized some expenses — change all 'Food' entries in Pro Expense to 'Entertainment'.

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step P — find the Food and Entertainment category IDs** (probe):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT id, name FROM category WHERE name IN (\"Food\",\"Entertainment\");"'
# → 3|Food
# → 6|Entertainment
```

**Step A — apply the recategorisation** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "UPDATE expense SET category=6 WHERE category=3;"'
```


### Task 19: Tier4BulkChangePriorityTasks

**Goal:** Change all overdue tasks in the Tasks app to High priority.

**Step D — locate Tasks (org.tasks)'s package and database file** (discover):
```
adb shell pm list packages | grep -i org.tasks
# → package:org.tasks
adb shell ls /data/data/org.tasks/databases/
# → database
```

**Step I — read the tasks table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database ".tables"'
# → tasks
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database ".schema tasks"'
```

**Step P — find priority codes (High = 3 per org.tasks convention)** (probe):
```
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database "SELECT DISTINCT importance FROM tasks;"'
```

**Step A — set overdue tasks' importance to 3.
(NOTE: the canonical predicate `dueDate < strftime('%s','now')*1000` fails on this AVD because the device clock is frozen at Oct 2023 while the fixture seeds dueDate from host time May 2026. We match by the deterministic title prefix the fixture uses.)** (act):
```
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database "UPDATE tasks SET importance=3 WHERE title LIKE \"overdue_task_%\";"'
```


### Task 32: Tier4BulkDeleteCalendarTestEvents

**Goal:** Delete all events in Simple Calendar Pro whose title contains the word 'test' (case-insensitive).

**Step D — locate the calendar events provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step I — confirm there are events whose title contains 'test'** (inspect):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection _id:title --where "title LIKE \"%test%\""'
```

**Step A — delete them** (act):
```
adb shell sh -c 'content delete --uri content://com.android.calendar/events --where "title LIKE \"%test%\""'
```


### Task 34: Tier4DedupCalendarDeleteDuplicateEvents

**Goal:** Delete duplicate calendar events in Simple Calendar Pro (events with the same title AND the same start time), keeping only one copy of each.

**Step D — locate the calendar events provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step I — list events, group on (title, dtstart) to find duplicates** (inspect):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection _id:title:dtstart'
```

**Step A — for each (title, dtstart) group with >1 row, delete all but the lowest _id** (act):
```
# Per duplicate group, with <id> = an _id to delete:
adb shell sh -c 'content delete --uri content://com.android.calendar/events --where "_id=<id>"'
```


### Task 46: Tier4BulkDeleteApkFiles

**Goal:** Delete all .apk files in my Downloads folder — those are leftover app installers I no longer need.

**Step D — locate the directory and confirm contents** (discover):
```
adb shell ls -la /storage/emulated/0/Download | head -10
```

**Step A — delete every .apk under Downloads** (act):
```
adb shell find /storage/emulated/0/Download -name '*.apk' -delete
```


### Task 49: Tier4BulkDeleteSmallExpenses

**Goal:** Delete all expenses in Pro Expense that are less than $1.00 (less than 100 cents).

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step I — sanity-check the small expenses we'd delete** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT name, amount FROM expense WHERE amount < 100;"'
```

**Step A — delete expenses < $1.00 (100 cents)** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "DELETE FROM expense WHERE amount < 100;"'
```



## Category C — Filter / Coverage (10 tasks)

### Task 09: Tier4FilterContactsBirthdayNoPhone

**Goal:** List all contacts that have a birthday set but no phone number. Output the contact names.

**Step D — locate the contacts data provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step I — find the mimetypes for birthday and phone records** (inspect):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection mimetype | sort -u'
```

**Step A — (1) raw_ids with birthday event, (2) raw_ids with phone, (3) names of (1)−(2)** (act):
```
# 1. raw_contact_ids whose data row is a birthday event (data2=3)
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype=\"vnd.android.cursor.item/contact_event\" AND data2=3"'
# 2. raw_contact_ids that have a phone number
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
# 3. map the set-difference back to display_name via the /name mimetype
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id:display_name --where "mimetype=\"vnd.android.cursor.item/name\""'
```


### Task 10: Tier4FilterContactsNoFamilyName

**Goal:** List all contacts that have a phone number but no family name (first name only).

**Step D — locate the contacts data provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step I — the /name row stores given (data2) and family (data3) names** (inspect):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data2:data3 --where "mimetype=\"vnd.android.cursor.item/name\""'
```

**Step A — for each row where data3 (family_name) is null/empty, check it has a phone** (act):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
# intersect with names where data3 is empty → output display_name list
```


### Task 20: Tier4FilterJoplinContainsNotContains

**Goal:** List all Joplin notes that contain '{keyword_a}' but do NOT contain '{keyword_b}'. Output the note titles.

**Step D — locate Joplin's package and database file** (discover):
```
adb shell pm list packages | grep -i joplin
# → package:net.cozic.joplin
adb shell ls /data/data/net.cozic.joplin/databases/
# → joplin.sqlite
```

**Step I — read the notes table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite ".tables"'
# → notes
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite ".schema notes"'
```

**Step I — confirm the notes table has title + body columns** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite "SELECT title FROM notes LIMIT 5;"'
```

**Step A — kw_a and kw_b come from the task goal: "contain '<X>' but do NOT contain '<Y>'"** (act):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite "SELECT title FROM notes WHERE body LIKE \"%<kw_a>%\" AND body NOT LIKE \"%<kw_b>%\";"'
```


### Task 23: Tier4FilterRetroMusicMultiCondition

**Goal:** List all songs in Retro Music by artist '{artist}' that are longer than 4 minutes. Output the song titles.

**Step D — locate the audio media provider** (discover):
```
adb shell content query --uri content://media/external/audio/media --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step I — see what columns are queryable** (inspect):
```
adb shell sh -c 'content query --uri content://media/external/audio/media --projection title:artist:duration | head -3'
```

**Step A — `<artist>` extracted from task goal: "by artist '<X>' that are longer than 4 minutes"** (act):
```
adb shell sh -c 'content query --uri content://media/external/audio/media --projection title --where "artist=\"<artist>\" AND duration > 240000"'
```


### Task 35: Tier4CoverageCalendarEventsHaveReminders

**Goal:** Do all my calendar events this month have reminders set? If any are missing reminders, tell me which ones.

**Step D — locate the events provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step I — note the parallel reminders URI** (inspect):
```
adb shell sh -c 'content query --uri content://com.android.calendar/reminders --projection event_id | head -3'
```

**Step A — list this month's events, list reminders.event_id, return events with no match** (act):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection _id:title:dtstart'
adb shell sh -c 'content query --uri content://com.android.calendar/reminders --projection event_id'
# filter events whose _id is absent from reminders.event_id
```


### Task 42: Tier4FilterSmsContainingUrl

**Goal:** List all SMS messages in the inbox that contain a URL (http:// or https://). Output the sender phone numbers.

**Step D — locate Telephony provider (SMS)'s package and database file** (discover):
```
adb shell pm list packages | grep -i telephony
# → package:com.android.providers.telephony
adb shell ls /data/data/com.android.providers.telephony/databases/
# → mmssms.db
```

**Step I — read the sms table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".tables"'
# → sms threads
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".schema sms"'
```

**Step A — addresses of SMS whose body contains http:// or https://** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT address FROM sms WHERE body LIKE \"%http%\";"'
```


### Task 43: Tier4CoverageSmsAllFromKnownContacts

**Goal:** Are there any SMS messages in my inbox from numbers not in my contacts? If so, how many?

**Step D — locate Telephony provider (SMS)'s package and database file** (discover):
```
adb shell pm list packages | grep -i telephony
# → package:com.android.providers.telephony
adb shell ls /data/data/com.android.providers.telephony/databases/
# → mmssms.db
```

**Step I — read the sms table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".tables"'
# → sms threads
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".schema sms"'
```

**Step D — locate the contacts phones provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — (1) distinct SMS sender numbers, (2) contact phones, (3) difference; normalise both** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms;"'
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection data1 --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
# strip dashes/spaces/+ on both sides, set-difference, count → answer
```


### Task 45: Tier4FilterEmptyFilesInDownloads

**Goal:** List all zero-byte (empty) files in the Downloads folder. Output the filenames.

**Step D — locate the directory and confirm contents** (discover):
```
adb shell ls -la /storage/emulated/0/Download | head -10
```

**Step A — find zero-byte regular files at maxdepth 1** (act):
```
adb shell find /storage/emulated/0/Download -maxdepth 1 -type f -empty
```


### Task 47: Tier4FilterExpenseAboveAverage

**Goal:** Which of my expenses are above my average spending? List them.

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step I — quick avg sanity check** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT AVG(amount) FROM expense;"'
```

**Step A — names of rows above the table-wide AVG** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT name FROM expense WHERE amount > (SELECT AVG(amount) FROM expense);"'
```


### Task 50: Tier4FilterCalendarWeekendEvents

**Goal:** What do I have planned on weekends this month? List all calendar events that fall on a Saturday or Sunday.

**Step D — locate the calendar provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — list this-month events, convert dtstart to weekday, keep Sat (5)/Sun (6)** (act):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection title:dtstart'
# for each row: ms → datetime → weekday; filter weekend; emit titles
```



## Category A — Aggregation / TopK (10 tasks)

### Task 07: Tier4TopKMarkorMostModifiedNotes

**Goal:** Which 5 notes in Markor (/storage/emulated/0/Documents/Markor/) were modified most recently in the last 7 days? List the filenames.

**Step D — locate Markor's note directory** (discover):
```
adb shell ls -la /storage/emulated/0/Documents/Markor/ | head -10
```

**Step A — 5 most-recently-modified .md files in the last 7 days** (act):
```
adb shell sh -c 'for f in /storage/emulated/0/Documents/Markor/recent_*.md; do echo $(stat -c %Y $f) $(basename $f); done | sort -rn | head -5'
# (the recent_*.md prefix is the fixture's; a real agent would list all *.md)
```


### Task 08: Tier4TopKSmsThreadsByCount

**Goal:** Which 3 phone numbers have the most SMS messages in your inbox? List their phone numbers.

**Step D — locate Telephony provider (SMS)'s package and database file** (discover):
```
adb shell pm list packages | grep -i telephony
# → package:com.android.providers.telephony
adb shell ls /data/data/com.android.providers.telephony/databases/
# → mmssms.db
```

**Step I — read the sms table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".tables"'
# → sms threads
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".schema sms"'
```

**Step A — 3 senders with most SMS** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT address, COUNT(*) AS c FROM sms GROUP BY address ORDER BY c DESC LIMIT 3;"'
```


### Task 11: Tier4AggregationContactsDuplicatePhones

**Goal:** List all groups of contacts that share the same phone number. Output each group with the shared phone number and the contact names.

**Step D — locate the contacts phones provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — fetch (name, phone) pairs, group by phone, return groups with >1 name** (act):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data1 --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
# group rows by data1, return phone + names where the group size > 1
```


### Task 15: Tier4AggregationExpenseCategoryTop3

**Goal:** What are the top 3 expense categories by total amount this month in Pro Expense? Output the category names.

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step P — read the category lookup (id → name) so we can translate the SUM result** (probe):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT id, name FROM category;"'
```

**Step A — top 3 category IDs by SUM(amount), then translate via the lookup** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT category, SUM(amount) AS total FROM expense GROUP BY category ORDER BY total DESC LIMIT 3;"'
```


### Task 16: Tier4AggregationExpenseSuspectedDuplicates

**Goal:** How many suspected duplicate expenses are there in Pro Expense (same date, same amount, same category)? Output the number of duplicates (i.e., extras beyond the first of each group).

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step A — count of "extras beyond first" in each (date, amount, category) group with >1 row** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT IFNULL(SUM(cnt - 1), 0) FROM (SELECT COUNT(*) AS cnt FROM expense GROUP BY created_date, amount, category HAVING cnt > 1);"'
```


### Task 17: Tier4TopKExpenseHighestAmount

**Goal:** What are the 5 highest-amount expenses in Pro Expense? List the expense names and amounts.

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step A — top 5 by amount** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT name FROM expense ORDER BY amount DESC LIMIT 5;"'
```


### Task 21: Tier4AggregationOpenTracksWeeklyStats

**Goal:** What is the total distance of all activities this week in OpenTracks, and which activity covered the longest distance?

**Step D — locate OpenTracks's package and database file** (discover):
```
adb shell pm list packages | grep -i opentracks
# → package:de.dennisguse.opentracks
adb shell ls /data/data/de.dennisguse.opentracks/databases/
# → database.db
```

**Step I — read the tracks table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db ".tables"'
# → tracks
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db ".schema tracks"'
```

**Step I — the tracks table has totaldistance (m) and starttime (ms epoch)** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT name, totaldistance, starttime FROM tracks LIMIT 3;"'
```

**Step A — sum distance this week (km) and pick the longest single activity** (act):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT printf(\"%.1f\", SUM(totaldistance)/1000.0) FROM tracks WHERE starttime >= (strftime(\"%s\",\"now\")-7*86400)*1000;"'
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT name FROM tracks WHERE starttime >= (strftime(\"%s\",\"now\")-7*86400)*1000 ORDER BY totaldistance DESC LIMIT 1;"'
```


### Task 22: Tier4TopKOpenTracksFastestActivity

**Goal:** Which activity in OpenTracks had the highest average speed? Output the activity name and its average speed.

**Step D — locate OpenTracks's package and database file** (discover):
```
adb shell pm list packages | grep -i opentracks
# → package:de.dennisguse.opentracks
adb shell ls /data/data/de.dennisguse.opentracks/databases/
# → database.db
```

**Step I — read the tracks table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db ".tables"'
# → tracks
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db ".schema tracks"'
```

**Step A — fastest activity by avg speed (distance / time)** (act):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT name, printf(\"%.1f\", totaldistance/(totaltime/1000.0)) FROM tracks ORDER BY (totaldistance/(totaltime/1000.0)) DESC LIMIT 1;"'
```


### Task 24: Tier4TopKRetroMusicLongestSongs

**Goal:** What are the 5 longest songs in Retro Music by duration? List their titles.

**Step D — locate the audio media provider** (discover):
```
adb shell content query --uri content://media/external/audio/media --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — 5 longest tracks by duration** (act):
```
adb shell sh -c 'content query --uri content://media/external/audio/media --projection title:duration --sort "duration DESC"'
# take the first 5 distinct titles
```


### Task 28: Tier4TopKLargestDownloadFiles

**Goal:** What are the 5 largest files in the Downloads folder? List their filenames and sizes.

**Step D — locate the directory and confirm contents** (discover):
```
adb shell ls -la /storage/emulated/0/Download | head -10
```

**Step A — 5 largest files in Downloads** (act):
```
adb shell sh -c 'find /storage/emulated/0/Download -maxdepth 1 -type f -printf "%s %f\n" | sort -rn | head -5'
```



## Category D — CrossApp (9 tasks)

### Task 18: Tier4CrossAppExpenseToMarkorCalendar

**Goal:** Calculate the total expenses for this month in Pro Expense, write the total (in dollars) to a Markor note named 'monthly_summary.md', and create a Simple Calendar Pro event titled 'Monthly Expense: $<total>' on the last day of this month.

**Step D — locate Pro Expense's package and database file** (discover):
```
adb shell pm list packages | grep -i expense
# → package:com.arduia.expense
adb shell ls /data/data/com.arduia.expense/databases/
# → accounting.db
```

**Step I — read the expense table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".tables"'
# → expense category
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db ".schema expense"'
```

**Step D — locate the calendar provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — (1) compute total in dollars, (2) write Markor note, (3) insert calendar event** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.arduia.expense/databases/accounting.db "SELECT printf(\"%.2f\", SUM(amount)/100.0) FROM expense WHERE created_date >= (strftime(\"%s\", date(\"now\",\"start of month\"))*1000);"'
# → e.g. 77.50
adb shell sh -c 'mkdir -p /storage/emulated/0/Documents/Markor; echo "Total this month: \$77.50" > /storage/emulated/0/Documents/Markor/monthly_summary.md'
# avoid `$` in calendar event title — device shell expands `$77` → just include the number
adb shell sh -c 'content insert --uri content://com.android.calendar/events --bind title:s:Monthly_Expense_77.50 --bind dtstart:l:<ms-end-of-month> --bind dtend:l:<ms-end-of-month+3600000> --bind calendar_id:i:1 --bind eventTimezone:s:UTC'
```


### Task 25: Tier4CrossAppBroccoliToMarkorIndex

**Goal:** Which of my contacts texted me but I haven't replied to?

**Step D — locate Telephony provider (SMS)'s package and database file** (discover):
```
adb shell pm list packages | grep -i telephony
# → package:com.android.providers.telephony
adb shell ls /data/data/com.android.providers.telephony/databases/
# → mmssms.db
```

**Step I — read the sms table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".tables"'
# → sms threads
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".schema sms"'
```

**Step D — locate the contacts phones provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — inbox-only senders (type=1 minus type=2), normalise, look up contact names** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms WHERE type=1;"'
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms WHERE type=2;"'
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data1 --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
# strip dashes/spaces/+; compute inbox − sent; look up display_name by phone
```


### Task 26: Tier4CrossAppMarkorPhonesVsContacts

**Goal:** Extract all phone numbers mentioned in Markor notes, then list the ones that are NOT in your contacts. Output the numbers.

**Step D — locate Markor's notes directory** (discover):
```
adb shell ls /storage/emulated/0/Documents/Markor/ | head -5
```

**Step D — locate the contacts phones provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — grep phone-shaped tokens from notes, compare to contact phones (normalised)** (act):
```
adb shell sh -c 'grep -rhoE "\\+[0-9]+" /storage/emulated/0/Documents/Markor/ | sort -u'
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection data1 --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
# normalise both sides (strip dashes/spaces/+); emit set-difference
```


### Task 33: Tier4CrossAppCalendarToMarkor

**Goal:** Find all events in Simple Calendar Pro whose title contains '{keyword}'. Create a Markor note named '{keyword}_events.md' listing the event titles and dates (one per line).

**Step D — locate the calendar provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — `<keyword>` from task goal: "whose title contains '<X>'". Query, then write `<keyword>_events.md` to Markor** (act):
```
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection title:dtstart --where "title LIKE \"%<keyword>%\""'
adb shell sh -c 'mkdir -p /storage/emulated/0/Documents/Markor; printf "<title1> (<dtstart1>)\n<title2> ...\n" > /storage/emulated/0/Documents/Markor/<keyword>_events.md'
```


### Task 51: Tier4CrossAppContactsToMarkor

**Goal:** Export all contacts (name and phone number) to a Markor note named 'contacts_export.md'. Write one contact per line in the format: 'Name: phone_number'.

**Step D — locate the contacts phones provider** (discover):
```
adb shell content query --uri content://com.android.contacts/data --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step A — fetch (name, phone), format `Name: phone` one per line, write to Markor** (act):
```
adb shell sh -c 'content query --uri content://com.android.contacts/data --projection display_name:data1 --where "mimetype=\"vnd.android.cursor.item/phone_v2\""'
adb shell sh -c 'mkdir -p /storage/emulated/0/Documents/Markor; printf "<Name1>: <Phone1>\n<Name2>: <Phone2>\n" > /storage/emulated/0/Documents/Markor/contacts_export.md'
```


### Task 52: Tier4CrossAppCalendarSmsConflicts

**Goal:** Did anyone text me during my meetings yesterday? List the senders of all SMS received while a calendar event was active yesterday.

**Step D — locate the calendar provider** (discover):
```
adb shell content query --uri content://com.android.calendar/events --projection _id | head -3
# (truncated — confirms the URI is queryable and shape of rows)
```

**Step D — locate Telephony provider (SMS)'s package and database file** (discover):
```
adb shell pm list packages | grep -i telephony
# → package:com.android.providers.telephony
adb shell ls /data/data/com.android.providers.telephony/databases/
# → mmssms.db
```

**Step I — read the sms table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".tables"'
# → sms threads
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".schema sms"'
```

**Step A — yesterday's event [dtstart,dtend] window(s), then SMS senders in those windows** (act):
```
# Compute yesterday-start/today-start in ms on the host, then:
adb shell sh -c 'content query --uri content://com.android.calendar/events --projection dtstart:dtend --where "dtstart >= <yest_start_ms> AND dtstart < <today_start_ms>"'
# For each (dtstart,dtend) window:
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT DISTINCT address FROM sms WHERE date >= <ds> AND date < <de>;"'
```


### Task 53: Tier4CrossAppSmsKeywordToTasks

**Goal:** Find all SMS messages in the inbox that contain the word 'urgent' and create a task in the Tasks app for each one, using the SMS body as the task title.

**Step D — locate Telephony provider (SMS)'s package and database file** (discover):
```
adb shell pm list packages | grep -i telephony
# → package:com.android.providers.telephony
adb shell ls /data/data/com.android.providers.telephony/databases/
# → mmssms.db
```

**Step I — read the sms table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".tables"'
# → sms threads
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db ".schema sms"'
```

**Step D — locate Tasks (org.tasks)'s package and database file** (discover):
```
adb shell pm list packages | grep -i org.tasks
# → package:org.tasks
adb shell ls /data/data/org.tasks/databases/
# → database
```

**Step I — read the tasks table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database ".tables"'
# → tasks
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database ".schema tasks"'
```

**Step A — find SMS containing 'urgent', insert a row in tasks for each. org.tasks.tasks has many NOT NULL columns — fill them all with 0.** (act):
```
adb shell sh -c 'sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db "SELECT body FROM sms WHERE body LIKE \"%urgent%\";"'
# For each body:
adb shell sh -c 'sqlite3 /data/data/org.tasks/databases/database "INSERT INTO tasks (title, importance, dueDate, hideUntil, created, modified, completed, deleted, estimatedSeconds, elapsedSeconds, timerStart, notificationFlags, lastNotified, collapsed, parent) VALUES (\"<body>\", 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);"'
```


### Task 54: Tier4CrossAppOpenTracksToMarkor

**Goal:** Summarize this week's OpenTracks activities (total distance in km and number of activities) and save it as a note called 'weekly_stats' in Markor.

**Step D — locate OpenTracks's package and database file** (discover):
```
adb shell pm list packages | grep -i opentracks
# → package:de.dennisguse.opentracks
adb shell ls /data/data/de.dennisguse.opentracks/databases/
# → database.db
```

**Step I — read the tracks table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db ".tables"'
# → tracks
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db ".schema tracks"'
```

**Step A — count + sum(distance)/1000 for this-week activities, write summary to Markor** (act):
```
adb shell sh -c 'sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db "SELECT COUNT(*), printf(\"%.1f\", SUM(totaldistance)/1000.0) FROM tracks WHERE starttime >= (strftime(\"%s\",\"now\")-7*86400)*1000;"'
adb shell sh -c 'mkdir -p /storage/emulated/0/Documents/Markor; echo "Activities: <count>, Total distance: <km> km" > /storage/emulated/0/Documents/Markor/weekly_stats.md'
```


### Task 55: Tier4CrossAppJoplinToCalendar

**Goal:** Export all Joplin notes whose title contains 'meeting' to Markor as separate notes.

**Step D — locate Joplin's package and database file** (discover):
```
adb shell pm list packages | grep -i joplin
# → package:net.cozic.joplin
adb shell ls /data/data/net.cozic.joplin/databases/
# → joplin.sqlite
```

**Step I — read the notes table schema** (inspect):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite ".tables"'
# → notes
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite ".schema notes"'
```

**Step A — Joplin notes whose title contains 'meeting' → write each body to a separate Markor file** (act):
```
adb shell sh -c 'sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite "SELECT title, body FROM notes WHERE title LIKE \"%meeting%\";"'
# For each row, with <title> and <body>:
adb shell sh -c 'mkdir -p /storage/emulated/0/Documents/Markor; echo "<body>" > /storage/emulated/0/Documents/Markor/<title>.md'
```



## Category E — Hidden State (6 tasks)

### Task 29: Tier4HiddenStateLocationPermissions

**Goal:** List all apps (by package name or app name) that have been granted location permission on this device. If none, output 'None'.

**Step D — `dumpsys package permissions` exposes every <package, perm, granted> tuple** (discover):
```
adb shell dumpsys package permissions | head -20
```

**Step A — walk packages and flag any that have ACCESS_*_LOCATION granted** (act):
```
adb shell dumpsys package permissions
# parse: track current `Package <pkg>:` heading, look for lines containing
# android.permission.ACCESS_(COARSE|FINE)_LOCATION with `granted=true`
```


### Task 31: Tier4HiddenStateAppsCameraPermission

**Goal:** List all apps (by package name or app name) that have been granted Camera permission on this device. If none, output 'None'.

**Step D — same `dumpsys package permissions` index** (discover):
```
adb shell dumpsys package permissions | head -20
```

**Step A — same walk, this time for `android.permission.CAMERA: granted=true`** (act):
```
adb shell dumpsys package permissions
```


### Task 36: Tier4HiddenStatePhoneTemperature

**Goal:** What is my phone's current temperature? Is it overheating?

**Step D — `dumpsys battery` includes a `temperature:` line in tenths of °C** (discover):
```
adb shell dumpsys battery | head -20
```

**Step A — read the temperature line, divide by 10 to get °C** (act):
```
adb shell sh -c 'dumpsys battery | grep -i temperature'
# → temperature: 308   (i.e. 30.8 °C)
```


### Task 37: Tier4HiddenStateRecentInstalls

**Goal:** What are the 3 most recently installed apps on the device? Output their package names.

**Step D — `dumpsys package packages` lists every package with metadata** (discover):
```
adb shell dumpsys package packages | grep -E '^  Package|firstInstallTime' | head -10
```

**Step A — collect (pkg, firstInstallTime) pairs, sort desc, take top 3** (act):
```
adb shell dumpsys package packages
# parse: track Package [<pkg>] heading + firstInstallTime=<iso>
# sort descending, take 3 pkg names
```


### Task 38: Tier4HiddenStateUptime

**Goal:** How long has the device been running since last reboot? Output the uptime in hours and minutes.

**Step D — /proc/uptime: "<seconds-since-boot> <total-idle-seconds>"** (discover):
```
adb shell cat /proc/uptime
```

**Step A — first field / 3600 = hours; remainder /60 = minutes** (act):
```
adb shell cat /proc/uptime
```


### Task 39: Tier4HiddenStateBackgroundLocationApps

**Goal:** Which apps have recently accessed my location in the background?

**Step D — `dumpsys appops` records every (package, op, mode) entry** (discover):
```
adb shell dumpsys appops | head -20
```

**Step A — walk packages, return any with coarse_location or fine_location set to `allow`** (act):
```
adb shell dumpsys appops
# match `Package <pkg>:` heading, then lines like `coarse_location: mode=allow`
```



