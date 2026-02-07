# Debug Test Files

Debug subset files for investigating "list index out of range" errors during inference.

## Files

### `debug_failing_tasks.jsonl` (8 instances)
All tasks that failed with "list index out of range" error during inference run on 2026-01-30.

| Task ID | Seed | Difficulty | Task Description |
|---------|------|------------|------------------|
| 65 | 7, 30, 1234 | android_medium | Reply to SMS using Simple SMS Messenger |
| 68 | 30 | android_medium | Text address of event |
| 69 | 30 | android_medium | Update Markor note |
| 72 | 30 | android_medium | Create playlist "Mystery and Thrills Series" |
| 73 | 1234 | android_medium | Create playlist "Travel Guide Essentials" |
| 74 | 30 | android_medium | Add favorite location in OsmAnd |

### `debug_sms_task65.jsonl` (3 instances)
Only task_id 65 instances (SMS Messenger tasks) - the most frequently failing task.

## Error Details

The "list index out of range" error occurs during trajectory execution. Based on log analysis:
- Error happens consistently across different containers
- Not a container health issue (containers are replaced but error persists)
- Likely an issue with task setup, observation parsing, or environment state

## How to Run Debug

```bash
# Run inference on just the failing tasks
cd /shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent
./examples/run_verl/verl_android_inference.sh ./data/debug/debug_failing_tasks.jsonl
```

## Potential Causes

1. **Task initialization** - Some tasks may not properly initialize required app state
2. **Observation parsing** - Empty or malformed observation data from Android
3. **SMS/Messaging tasks** - May require specific app state (existing messages, contacts)
4. **Playlist creation** - May need specific app configuration

## Next Steps

1. Run debug subset with increased logging
2. Check Android container logs for detailed error traceback
3. Verify task prerequisites are met in emulator snapshot
