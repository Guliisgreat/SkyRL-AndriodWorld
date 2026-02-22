#!/bin/bash
# Run tasks 1-4 from adb_agent_pilot_5tasks.jsonl with original GUI agent (cli_agent.py)
# Uses same model (gpt-4o) and same task instances as ADB agent run.
# Requires: emulator already running (or remove --skip-emulator), OPENAI_API_KEY set.
set -e
cd "$(dirname "$0")/.."
LOG="/tmp/gui_agent_tasks_1_4.log"
echo "Logging to $LOG"
for i in 1 2 3 4; do
  echo ""
  echo "========== TASK $i / 4 ==========" | tee -a "$LOG"
  uv run --with "protobuf>=5.0" --with "grpcio>=1.78.0" python scripts/cli_agent.py \
    --task-file data/adb_agent_pilot_5tasks.jsonl \
    --task-index "$i" \
    --model gpt-4o \
    --api-url https://api.openai.com \
    --max-steps 15 \
    --skip-emulator \
    2>&1 | tee -a "$LOG"
  echo "Task $i exit: $?"
done
echo ""
echo "========== ALL TASKS COMPLETE ==========" | tee -a "$LOG"
