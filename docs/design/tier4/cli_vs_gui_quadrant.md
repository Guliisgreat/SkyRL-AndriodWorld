# Tier4 CLI vs GUI: Quadrant Analysis

Goal: identify a task subset where **CLI agents solve but GUI agents cannot**.

Using best results per modality:
- **Best CLI**: Opus 4.6 + `clean_optimized_tools` (37/50, 74%)
- **Best GUI**: Union of Qwen3-VL-32B (16/50), MAI-UI-8B (15/50), Venus-1.5-8B (8/50)
  — a task counts as "GUI-solvable" if ANY GUI agent solves it (24/50 union)

## Quadrant Summary

| Quadrant | Count | Description |
|----------|------:|-------------|
| **CLI-only** | **15** | CLI solves, no GUI agent solves — **the target set** |
| Both solve | 22 | Both CLI and at least one GUI agent solve |
| GUI-only | 2 | At least one GUI agent solves, best CLI fails |
| Neither | 11 | No agent solves |

## Quadrant A: CLI-Only (15 tasks)

These 15 tasks are solved by CLI agents but failed by ALL three GUI agents.
This is the **validated CLI-exclusive task set**.

| # | Task | Opus-T | Opus | Son-T | Son | Failure Category |
|---|------|:------:|:----:|:-----:|:---:|------------------|
| 4 | CrossAppSmsNumbersNotInContacts | OK | OK | OK | OK | Cross-app data join |
| 5 | BulkRenameScreenshots | OK | OK | OK | OK | Bulk file operation |
| 9 | AggregationLongestMarkorNote | OK | OK | OK | OK | File metadata (char count) |
| 16 | DedupContactsDuplicatePhones | OK | OK | OK | OK | Database dedup |
| 17 | DedupMergeContactsSamePhone | OK | OK | OK | OK | Database dedup + delete |
| 31 | FilterRetroMusicMultiCondition | OK | OK | . | . | Media DB multi-condition filter |
| 32 | TopKRetroMusicLongestSongs | OK | OK | OK | OK | Media DB sort by duration |
| 34 | CrossAppFilesCreatedDuringEvents | OK | OK | OK | OK | Cross-app timestamp join |
| 36 | AggregationDownloadSizeTop3 | OK | OK | OK | OK | File metadata (sizes) |
| 37 | TopKLargestDownloadFiles | OK | OK | OK | OK | File metadata (sizes) |
| 40 | HiddenStateAudioRouting | OK | OK | OK | OK | Hidden system state |
| 44 | CrossAppCalendarToMarkor | OK | OK | . | . | Cross-app calendar→file |
| 45 | FilterCalendarLongNoReminder | OK | OK | OK | OK | Calendar DB multi-condition |
| 48 | TopKCalendarEarliestEvent | OK | OK | OK | . | Calendar DB sort query |
| 49 | CoverageCalendarEventsHaveReminders | OK | . | . | . | Calendar DB join (events+reminders) |

**CLI success rate on these 15 tasks:**
- Opus 4.6 (tools): **15/15 (100%)**
- Opus 4.6: 14/15 (93%)
- Sonnet 4 (tools): 12/15 (80%)
- Sonnet 4: 11/15 (73%)

**Why these fail for GUI:**
- 4 require **cross-app data joins** (SMS↔contacts, files↔calendar)
- 3 require **file metadata** not shown in UI (sizes, character counts)
- 3 require **calendar content provider queries** (sort, filter, join reminders)
- 2 require **database dedup** (group by phone number, compare)
- 2 require **media DB queries** (filter by duration, sort)
- 1 requires **hidden system state** (audio routing via `dumpsys`)

## Quadrant B: Both Solve (22 tasks)

These tasks are solvable via both GUI and CLI. They should be **excluded** from
a CLI-exclusive benchmark.

| # | Task | GUI Agents That Solve |
|---|------|-----------------------|
| 0 | BulkDeleteTmpInDownloads | Qwen, MAI |
| 1 | CoverageNoTmpInDownloads | Qwen, MAI, Venus |
| 2 | HiddenStateListAppVersions | MAI |
| 3 | AggregationCountUnreadSMS | Qwen, MAI, Venus |
| 6 | BulkMoveLargeFiles | MAI |
| 7 | FilterRecentLogFiles | Venus |
| 8 | BulkAppendFooterToMarkdown | Qwen, MAI |
| 10 | TopKMarkorMostModifiedNotes | Qwen, Venus |
| 11 | FilterDeleteOldNonContactKeywordSms | Qwen, MAI, Venus |
| 15 | AggregationLongestContactName | Qwen, MAI, Venus |
| 19 | FilterExpenseHighTravelLastMonth | Qwen |
| 20 | AggregationExpenseCategoryTop3 | Qwen, Venus |
| 21 | DedupExpenseSuspectedDuplicates | Qwen, Venus |
| 22 | TopKExpenseHighestAmount | Qwen |
| 24 | BulkChangePriorityTasks | MAI |
| 25 | CoverageOverdueTasksCompleted | Qwen |
| 26 | FilterJoplinContainsNotContains | Qwen |
| 27 | DedupJoplinSameTitleNotes | Qwen, MAI |
| 28 | AggregationOpenTracksWeeklyStats | MAI |
| 29 | TopKOpenTracksFastestActivity | Qwen |
| 33 | CrossAppBroccoliToMarkorIndex | MAI |
| 35 | CrossAppMarkorPhonesVsContacts | MAI |

**Why these are GUI-solvable:**
- Information is visually displayed in app UIs (counts, names, lists)
- Standard UI operations (browse, read, select, delete, type) are sufficient
- Apps have built-in search/filter features (Joplin, Pro Expense)
- No bulk/batch processing required (or small enough to do manually)

**Note:** 10 of these 22 tasks are solved by only 1 GUI agent. They are
borderline — a different seed or slightly different task setup might push them
into the CLI-only quadrant.

## Quadrant C: GUI-Only (2 tasks)

These tasks are solved by at least one GUI agent but NOT by the best CLI agent.

| # | Task | GUI Agents | Why CLI Fails |
|---|------|------------|---------------|
| 18 | BulkRecategorizeExpense | MAI | Pro Expense's SQLite schema uses integer category IDs that differ across DB versions. CLI agent misidentifies the ID mapping. MAI-UI navigates the app's category picker UI which abstracts away the IDs. |
| 30 | CrossAppOpenTracksToTasks | Qwen, MAI | CLI agent reads activity distance from OpenTracks DB but the distance format/units don't match what the verifier expects in the Tasks.org entry. GUI agent reads the formatted distance from the UI and types it directly. |

**Implication:** These 2 tasks have verifiers that are easier to satisfy via GUI
interaction than via database manipulation. The CLI agent does the right thing
conceptually but fails on format/ID mismatches.

## Quadrant D: Neither Solves (11 tasks)

No agent (CLI or GUI) solves these tasks. They represent the hardest tier4 tasks.

| # | Task | Failure Reason |
|---|------|----------------|
| 12 | TopKSmsThreadsByCount | SMS content provider doesn't support GROUP BY; requires client-side aggregation |
| 13 | CrossAppContactsNoRecentSms | Complex 3-way join (contacts + email + SMS) with temporal filtering |
| 14 | FilterContactsBirthdayNoPhone | Birthday data stored in a non-obvious contacts data table format |
| 23 | CrossAppExpenseToMarkorCalendar | 3-app coordination (expense→markor→calendar) with precise data transfer |
| 38 | CoverageAllSmsRead | SMS "read" status not reliably queryable; depends on app-specific behavior |
| 39 | HiddenStateLocationPermissions | Permission grant state requires parsing complex `dumpsys` output |
| 41 | CoverageAppsCameraPermission | Same as 39 — `dumpsys` output parsing too complex |
| 42 | CoverageWifiConnected | WiFi SSID extraction from `dumpsys wifi` output is fragile |
| 43 | BulkDeleteCalendarTestEvents | Calendar content provider delete requires exact ID matching; CLI agents delete from wrong DB |
| 46 | AggregationCalendarTotalDuration | Timestamp math (UTC→local, milliseconds→minutes) with off-by-one errors |
| 47 | DedupCalendarDeleteDuplicateEvents | Complex: identify duplicates, keep one copy, delete rest — all via content provider |

**Implication:** These 11 tasks may need prompt improvements, better tool support,
or task/verifier refinements to become solvable.

## Recommendation: CLI-Exclusive Benchmark Subset

For a benchmark that measures **CLI advantage over GUI**, use the 15 CLI-only
tasks (Quadrant A) plus the 11 neither-solves tasks (Quadrant D) = **26 tasks**
where no GUI agent succeeds.

Alternatively, for a **strict CLI-exclusive set** with confirmed CLI solvability,
use just the **15 CLI-only tasks** where CLI achieves 73-100% and GUI achieves 0%.

| Metric | 15 CLI-only | 26 no-GUI | Full 50 |
|--------|------------:|----------:|--------:|
| Opus CLI (tools) | **100%** | 58% | 74% |
| Sonnet CLI (tools) | 80% | 46% | 64% |
| Best GUI (union) | **0%** | **0%** | 48% |
| CLI/GUI gap | **∞** | **∞** | 2.3x |
