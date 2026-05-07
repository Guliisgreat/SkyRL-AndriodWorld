> **STATUS: SUPERSEDED.** Realism review of the original 20-task proposal.
> The current realism filter is embedded in
> [`../tier4/cli_dataset_45_balanced.md`](../tier4/cli_dataset_45_balanced.md).

# Tier4 Task Realism Review

Honest assessment: which of the 20 proposed tasks would a real user actually
ask for, and which feel artificially designed to exploit GUI weaknesses?

## Scoring

- **Realistic**: A real user would plausibly ask this
- **Borderline**: Plausible but the specific formulation feels engineered
- **Artificial**: No real user would ask this; designed to test a capability

---

## Confirmed CLI-Only (15 tasks)

| # | Task | Realism | Assessment |
|---|------|---------|------------|
| 4 | CrossAppSmsNumbersNotInContacts | **Realistic** | "Who's texting me that's not in my contacts?" — common spam/unknown number concern |
| 5 | BulkRenameScreenshots | **Borderline** | Users organize photos, but the specific rename pattern (date-based) is engineered. Real ask: "organize my screenshots by date" |
| 9 | AggregationLongestMarkorNote | **Artificial** | No user cares about character count. Real ask might be: "which note is the largest file?" but even that is rare |
| 16 | DedupContactsDuplicatePhones | **Realistic** | "Do I have duplicate contacts?" — very common after phone migration or sync issues |
| 17 | DedupMergeContactsSamePhone | **Realistic** | "Clean up my duplicate contacts" — phones literally have built-in merge features for this |
| 31 | FilterRetroMusicMultiCondition | **Borderline** | "Find long songs by this artist" — plausible for playlist curation, but the specific threshold (4 min) feels like a test |
| 32 | TopKRetroMusicLongestSongs | **Borderline** | "What are my longest songs?" — plausible for storage management or DJ prep, but uncommon |
| 34 | CrossAppFilesCreatedDuringEvents | **Artificial** | No real user correlates file timestamps with calendar events. This is purely designed to test cross-app joins |
| 36 | AggregationDownloadSizeTop3 | **Realistic** | "How much space do my downloads take? What's the biggest?" — common storage cleanup |
| 37 | TopKLargestDownloadFiles | **Realistic** | "What are the biggest files in my Downloads?" — very common storage management |
| 40 | HiddenStateAudioRouting | **Borderline** | "Where is my audio playing?" — plausible when debugging Bluetooth/speaker issues, but niche |
| 44 | CrossAppCalendarToMarkor | **Borderline** | "Make me a note of all meetings about X" — plausible for meeting prep, but the specific cross-app formulation is engineered |
| 45 | FilterCalendarLongNoReminder | **Artificial** | Three conditions (no reminder + >2 hours + 'meeting' in title) is obviously engineered. Real ask: "which meetings don't have reminders?" |
| 48 | TopKCalendarEarliestEvent | **Borderline** | "What's my oldest calendar event?" — plausible for cleanup, but rare |
| 49 | CoverageCalendarEventsHaveReminders | **Borderline** | "Do all my events have reminders?" — plausible for organized users |

### Promoted from Neither (5 tasks)

| # | Task | Realism | Assessment |
|---|------|---------|------------|
| 12 | TopKSmsThreadsByCount | **Realistic** | "Who do I text the most?" — common curiosity, screen time awareness |
| 14 | FilterContactsBirthdayNoPhone | **Artificial** | "Contacts with birthday but no phone" — extremely specific, no real user asks this |
| 43 | BulkDeleteCalendarTestEvents | **Artificial** | The word 'test' in the criteria makes this obviously a developer task, not a user task |
| 46 | AggregationCalendarTotalDuration | **Realistic** | "How many hours of meetings do I have this month?" — very common for time management |
| 47 | DedupCalendarDeleteDuplicateEvents | **Realistic** | "Delete my duplicate calendar events" — common sync issue |

---

## Summary

| Rating | Count | Tasks |
|--------|------:|-------|
| **Realistic** | 8 | 4, 12, 16, 17, 36, 37, 46, 47 |
| **Borderline** | 7 | 5, 31, 32, 40, 44, 48, 49 |
| **Artificial** | 5 | 9, 14, 34, 43, 45 |

**Problem**: 5 of 20 tasks are clearly artificial. This weakens the benchmark's
claim of testing real-world CLI advantage.

---

## Recommended Replacements

Replace the 5 artificial tasks with more realistic alternatives that still
require CLI/ADB access and remain GUI-unsolvable.

### Replace Task 9 (longest note by chars)
**Better**: "How many notes do I have in Markor, and what is the total word
count across all notes?"
— Real need: understanding note-taking volume. Requires `wc -w` on each file.
Still GUI-unsolvable (no word count in Markor UI).

### Replace Task 14 (birthday + no phone)
**Better**: "List all contacts that have no phone number"
— Real need: cleaning up incomplete contacts after import. Simpler, more natural.
Still requires content provider query (`data` table with phone MIME type).

### Replace Task 34 (files during calendar events)
**Better**: "List all files in Downloads that were modified more than 30 days
ago" (old files cleanup)
— Real need: storage management. Requires `stat` or `find -mtime`. Files app
doesn't show modification dates prominently.

### Replace Task 43 (delete 'test' events)
**Better**: "Delete all calendar events that have already passed and are older
than 3 months" (calendar cleanup)
— Real need: cleaning up old events. Requires timestamp comparison via content
provider. Calendar UI has no bulk delete for old events.

### Replace Task 45 (3-condition calendar filter)
**Better**: "Which of my calendar events this month don't have a reminder set?"
— Real need: reminder hygiene. Same CLI method (LEFT JOIN events with reminders)
but simpler, single-condition query that feels natural.

---

## Revised 20-Task Subset

If we apply the 5 replacements, the revised subset would be:

**8 Realistic (unchanged)**:
4, 12, 16, 17, 36, 37, 46, 47

**7 Borderline (unchanged)**:
5, 31, 32, 40, 44, 48, 49

**5 Realistic (new replacements)**:
- Total word count across Markor notes
- Contacts with no phone number
- Files older than 30 days in Downloads
- Delete calendar events older than 3 months
- Calendar events this month without reminders

This gives **13 Realistic + 7 Borderline + 0 Artificial** = a much more
convincing benchmark that tests real user needs.

---

## Borderline Tasks: How to Strengthen

The 7 borderline tasks can be reframed with more natural language:

| Current | More Natural |
|---------|-------------|
| "Rename all files starting with Screenshot_..." | "Organize my screenshots by date" |
| "List songs by artist X longer than 4 minutes" | "Find all the long tracks by [artist]" |
| "What are my 5 longest songs?" | "Which songs take up the most time in my library?" |
| "What is the audio output device?" | "Why can't I hear sound? Where is audio playing?" |
| "Find calendar events with keyword, create note" | "Make me a summary of all meetings about [topic]" |
| "What's my oldest calendar event?" | "Clean up my calendar — what's the oldest event still there?" |
| "Do all events have reminders?" | "Did I forget to set reminders on any events this month?" |

The underlying task mechanism stays the same; only the prompt wording changes
to sound like something a real person would say.
