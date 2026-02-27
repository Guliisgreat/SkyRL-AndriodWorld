# TODO: AndroidWorld Task Prerequisite Data Issues

**Created:** 2026-01-30  
**Priority:** Medium  
**Status:** Documented, workaround in place

## Summary

Several AndroidWorld tasks fail during initialization with `IndexError: list index out of range` because they assume prerequisite data exists that is not present in the `clean` snapshot.

## Root Cause

The error occurs in the AndroidWorld task initialization code. For example, in the SMS reply task:

```python
# File: /data/RL4AndroidWorld/android_world/android_world/task_evals/single/sms.py:103
self._get_received_messages(env.controller)[0]
```

The `_get_received_messages()` function returns an empty list when no SMS messages exist in the device, and accessing `[0]` fails.

## Affected Tasks

| Task ID | Seed(s) | Task Type | Issue |
|---------|---------|-----------|-------|
| 65 | 7, 30, 1234 | SMS Reply | No received messages to reply to |
| 68 | 30 | SMS (Text event address) | No received messages with event data |
| 69 | 30 | Markor Update | Note file doesn't exist |
| 72 | 30 | VLC Playlist | Media files don't exist |
| 73 | 1234 | VLC Playlist | Media files don't exist |
| 74 | 30 | OsmAnd Favorite | Unknown prerequisite issue |

**Total affected:** 8 out of 234 test instances (3.4%)

## Current Workaround

A filtered test set has been created that excludes these failing instances:
- **Original:** `data/androidworld_generalization/unseen_task_instance/test.jsonl` (234 instances)
- **Filtered:** `data/androidworld_generalization/unseen_task_instance/test_filtered.jsonl` (226 instances)

## Potential Fixes

### Option 1: Patch Task Initialization (Recommended)

Modify the AndroidWorld task files to create prerequisite data during `initialize_task()` before accessing it.

Example fix for SMS tasks:
```python
def initialize_task(self, env):
    # Ensure at least one message exists before accessing
    messages = self._get_received_messages(env.controller)
    if not messages:
        # Create a prerequisite message
        self._create_dummy_message(env.controller)
        messages = self._get_received_messages(env.controller)
    
    target_message = messages[0]
    # ... rest of initialization
```

**Implementation:**
1. Extract affected task files from Docker image
2. Apply patches
3. Either rebuild Docker image OR use volume mounts

Files to patch:
- `/data/RL4AndroidWorld/android_world/android_world/task_evals/single/sms.py`
- `/data/RL4AndroidWorld/android_world/android_world/task_evals/single/markor.py`
- `/data/RL4AndroidWorld/android_world/android_world/task_evals/single/vlc.py`
- `/data/RL4AndroidWorld/android_world/android_world/task_evals/single/osmand.py`

### Option 2: Use Pre-populated Snapshots

Create Android emulator snapshots that include:
- Pre-existing SMS conversations
- Pre-created Markor notes
- Pre-downloaded media files for VLC
- OsmAnd configuration

### Option 3: Volume Mount Patches

Mount patched Python files into containers at runtime without rebuilding:

```python
# In container_manager.py, add to docker run command:
volumes = {
    '/path/to/patches/sms.py': {
        'bind': '/data/RL4AndroidWorld/android_world/android_world/task_evals/single/sms.py',
        'mode': 'ro'
    }
}
```

## Impact on Evaluation

- **Without fix:** 8/234 instances (3.4%) will always fail with infrastructure error
- **With filtered set:** Full evaluation possible on 226 instances
- **With fix:** All 234 instances will be evaluable

## Related Files

- Docker image: `androidworld:full_adb_agent`
- Container manager: `skyrl_agent/runtime/android/container_manager.py`
- Test data: `data/androidworld_generalization/unseen_task_instance/`
- Debug data: `data/debug/debug_failing_tasks.jsonl`

## Notes

The failure is deterministic based on task_id + seed combination. The same task_id with different seeds may or may not fail depending on whether the seed-specific prerequisite data setup works correctly.

This appears to be a bug in the original AndroidWorld benchmark where certain task variants don't properly set up their prerequisites during initialization.
