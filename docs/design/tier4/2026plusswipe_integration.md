# Tier4 ADB-Exclusive Tasks: 2026plusswipe Integration

## Overview

The `androidworld:2026plusswipe_tier4` Docker image packages 50 ADB-exclusive
("Tier 4") tasks on top of the `androidworld:2026plusswipe` base image.  These
tasks are designed so that CLI/ADB agents can solve them efficiently while GUI
agents would need prohibitively many error-prone steps.

## Image Hierarchy

```
androidworld:v8
  └── androidworld:2026          (upstream pip packages + skyrl_server)
        └── androidworld:2026plusswipe   (pixel swipe patches)
              └── androidworld:2026plusswipe_tier4   ← NEW
                    (+ tier4 tasks, registry_ext, merged env.py)
```

## Task Inventory (50 tasks)

| # | Module        | Tasks | Names |
|---|---------------|-------|-------|
| 0-1 | files.py    | 2 | BulkDeleteTmpInDownloads, CoverageNoTmpInDownloads |
| 2   | system.py   | 1 | HiddenStateListAppVersions |
| 3-4 | sms.py      | 2 | AggregationCountUnreadSMS, CrossAppSmsNumbersNotInContacts |
| 5-7 | files.py    | 3 | BulkRenameScreenshots, BulkMoveLargeFiles, FilterRecentLogFiles |
| 8-10 | markor.py  | 3 | BulkAppendFooterToMarkdown, AggregationLongestMarkorNote, TopKMarkorMostModifiedNotes |
| 11-12 | sms.py    | 2 | FilterDeleteOldNonContactKeywordSms, TopKSmsThreadsByCount |
| 13-17 | contacts.py | 5 | CrossAppContactsNoRecentSms, FilterContactsBirthdayNoPhone, AggregationLongestContactName, DedupContactsDuplicatePhones, DedupMergeContactsSamePhone |
| 18-23 | expense.py | 6 | BulkRecategorizeExpense, FilterExpenseHighTravelLastMonth, AggregationExpenseCategoryTop3, DedupExpenseSuspectedDuplicates, TopKExpenseHighestAmount, CrossAppExpenseToMarkorCalendar |
| 24-25 | tasks_app.py | 2 | BulkChangePriorityTasks, CoverageOverdueTasksCompleted |
| 26-27 | joplin.py  | 2 | FilterJoplinContainsNotContains, DedupJoplinSameTitleNotes |
| 28-30 | opentracks.py | 3 | AggregationOpenTracksWeeklyStats, TopKOpenTracksFastestActivity, CrossAppOpenTracksToTasks |
| 31-32 | retro_music.py | 2 | FilterRetroMusicMultiCondition, TopKRetroMusicLongestSongs |
| 33 | broccoli.py | 1 | CrossAppBroccoliToMarkorIndex |
| 34-35 | cross_app.py | 2 | CrossAppFilesCreatedDuringEvents, CrossAppMarkorPhonesVsContacts |
| 36-37 | files.py   | 2 | AggregationDownloadSizeTop3, TopKLargestDownloadFiles |
| 38 | sms.py      | 1 | CoverageAllSmsRead |
| 39-42 | system.py  | 4 | HiddenStateLocationPermissions, HiddenStateAudioRouting, CoverageAppsCameraPermission, CoverageWifiConnected |
| 43-49 | calendar.py | 7 | BulkDeleteCalendarTestEvents, CrossAppCalendarToMarkor, FilterCalendarLongNoReminder, AggregationCalendarTotalDuration, DedupCalendarDeleteDuplicateEvents, TopKCalendarEarliestEvent, CoverageCalendarEventsHaveReminders |

## Build Instructions

```bash
cd /shared/ligu/projects/SkyRL-AndriodWorld/docker

# Prerequisite: androidworld:2026plusswipe must exist
docker images | grep 2026plusswipe

# Build the tier4 image
docker build -f androidworld_2026plusswipe_tier4/Dockerfile \
  -t androidworld:2026plusswipe_tier4 .
```

Build time: ~1 second (thin layer on top of base image).

## env.py Merge Decisions

The merged `env.py` starts from the `2026plusswipe` version (optimized for
headless ADB workflows) with one addition from the tier4 version:

| Feature | Choice | Reason |
|---------|--------|--------|
| GPU mode | `-gpu off` (2026plusswipe) | Headless containers, no GPU passthrough |
| White-screen loop | Removed (2026plusswipe) | ADB tasks don't need screenshot stability |
| Step budget | 50x complexity (2026plusswipe) | Generous for multi-round ADB workflows |
| Terminal-only eval | Yes (2026plusswipe) | Skips wasted evaluation on non-FINISH steps |
| save_images guard | `and self.image_folder` (2026plusswipe) | Prevents NoneType crash |
| **TASK_FAMILY env var** | **Added (tier4)** | Enables runtime task family selection via `ENV TASK_FAMILY=tier4` |
| **interaction_cache** | **Added (new)** | Stores FINISH(content='...') text so tier4 tasks can verify agent answers |

## Running Unit Tests

Unit tests run inside the container without a real emulator.  They exercise all
50 task classes' `is_successful()` logic with mocked ADB responses.

```bash
docker run --rm --entrypoint bash androidworld:2026plusswipe_tier4 -c \
  "cd /data && python -m pytest skyrl_server/tier4/tier4_test.py -v --tb=short"
```

Expected: **102 tests passed** (50 tasks, ~2 tests each).  Runtime: ~1 second.

## Running Integration Tests

Integration tests validate the full server stack with a real emulator.

### Step 1: Start the container

```bash
docker run -d --name tier4_test --device /dev/kvm \
  -e ENV_SKIP_SCREENSHOT=true -e LAZY_EVAL=true \
  -p 5000:5000 androidworld:2026plusswipe_tier4
```

The container needs `/dev/kvm` for the Android emulator.  Boot takes ~45-60s.

### Step 2: Run the test script

```bash
python docker/androidworld_2026plusswipe_tier4/test_integration.py \
  --base-url http://localhost:5000 \
  --timeout 600 \
  --verbose
```

The script:
1. Waits for `/health` to report healthy
2. Verifies `/get_n_tasks` returns 50
3. Cycles through all 50 tasks via `/reset` with `task_id=0..49`
4. Tests `/step_adb` with ADB echo and FINISH commands
5. Solves `Tier4BulkDeleteTmpInDownloads` end-to-end (reward=1.0)
6. Solves `Tier4HiddenStateListAppVersions` end-to-end (reward=1.0)

### Step 3: Cleanup

```bash
docker rm -f tier4_test
```

## Using with pool_broker for Eval Runs

```bash
# Start broker with tier4 containers
python eval-runners/common/runtime/pool_broker.py \
  --pool-size 16 \
  --docker-image androidworld:2026plusswipe_tier4 \
  --port 9400 \
  --base-env-id 700 \
  --parallel 4

# Run evaluation
python eval-runners/benchmarks/androidworld/run_claude_cli.py \
  --data eval-runners/data/tier4/val_data.jsonl \
  --broker-url http://localhost:9400 \
  --pool-size 16 \
  --model claude-opus-4-6 \
  --max-turns 30
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TASK_FAMILY` | `tier4` | Task set to serve (set by Dockerfile) |
| `ENV_TASK_FAMILY` | `tier4` | Same, read by server.py (belt-and-suspenders) |
| `ENV_SAMPLE_MODE` | `sequential` | Task cycling mode (`sequential` or `random`) |
| `ENV_SKIP_SCREENSHOT` | `false` | Skip image capture (set `true` for ADB-only agents) |
| `LAZY_EVAL` | `true` | Only evaluate on FINISH, skip mid-step eval |
| `ENV_ID` | `0` | Container identifier for logging |

### Sequential Task Selection

In sequential mode, the task is selected by `options.task_id` (not by seed).
The `/reset` call must include:

```json
{"seed": 42, "options": {"task_id": 3}}
```

This selects task index 3 (`Tier4AggregationCountUnreadSMS`).  Without
`options.task_id`, the server always returns task 0.

## Troubleshooting

### Container never becomes healthy

- Check `/dev/kvm` exists: `ls -la /dev/kvm`
- Check container logs: `docker logs tier4_test`
- The emulator needs KVM for acceptable boot times

### Port 5000 already in use

```bash
docker run -d --name tier4_test --device /dev/kvm \
  -e ENV_SKIP_SCREENSHOT=true -e LAZY_EVAL=true \
  -p 5001:5000 androidworld:2026plusswipe_tier4
```

Then use `--base-url http://localhost:5001`.

### /get_n_tasks returns wrong count

The tier4 registry should return exactly 50.  If it returns a different number:
1. Check `TASK_FAMILY` env var: `docker exec tier4_test env | grep TASK`
2. Verify `registry_ext.py` was copied: `docker exec tier4_test ls /data/skyrl_server/registry_ext.py`
3. Verify tier4 modules: `docker exec tier4_test ls /data/skyrl_server/tier4/`

### Golden path test fails with reward=0

Tasks that check `interaction_cache` (agent's answer) need the `FINISH(content='...')`
text to be stored.  The merged env.py includes this fix.  If using a different
base env.py, ensure it has:

```python
# In the "Handle complete status" block:
if action.get("text"):
    self.env.interaction_cache = action["text"]
```

## Code Structure: Current State and Redesign Proposal

### Current Pain Points

1. **Triple task list**: Adding one task requires edits in 3 files:
   - Module file (class definition)
   - `tier4/__init__.py` (re-export + `__all__`)
   - `registry_ext.py` (`_TIER4_TASKS` tuple)

2. **env.py divergence**: 5 Docker variants each maintain their own env.py copy

3. **Import shadowing**: Module names (`calendar.py`, `sms.py`) shadow stdlib names,
   requiring aliased imports (`from .tier4 import calendar as tier4_calendar`)

### Proposed Improvements (priority order)

**A. Auto-discovery registry** — Replace `_TIER4_TASKS` tuple with
`pkgutil.walk_packages` to auto-discover `Tier4*` subclasses.  Adding a task
becomes: write the class, done.

**B. env.py configuration extraction** — Extract variant behavior (gpu, budget,
white-screen loop) into an `EnvConfig` dataclass.  Single env.py reads
`ENV_CONFIG` to select preset.  Eliminates all env.py copies.

**C. Rename modules** — `calendar.py` -> `tier4_calendar.py` etc.  One-time
cost, eliminates import aliasing.

**D. Parameterized Dockerfile** — Single template with ARGs for base image and
features.  Nice-to-have, low priority.

## Files Created/Modified

| File | Description |
|------|-------------|
| `docker/androidworld_2026plusswipe_tier4/Dockerfile` | Image definition |
| `docker/androidworld_2026plusswipe_tier4/env.py` | Merged env (2026plusswipe + TASK_FAMILY + interaction_cache) |
| `docker/androidworld_2026plusswipe_tier4/test_integration.py` | Integration test script |
| `docs/design/tier4_2026plusswipe_integration.md` | This document |
