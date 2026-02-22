#!/bin/bash
# Run ADB agent with gpt-5.2 on tasks 1, 3, 4 (dialer, clock, camera)
# Requires: OPENAI_API_KEY set, emulator (or remove --skip-emulator)
set -e
cd "$(dirname "$0")/.."
LOG="/tmp/adb_agent_easy_tasks_134.log"
echo "Logging to $LOG"
for i in 1 3 4; do
  echo ""
  echo "========== TASK $i (index) ==========" | tee -a "$LOG"
  uv run --with "protobuf>=5.0" --with "grpcio>=1.78.0" python scripts/cli_adb_agent.py \
    --task-file data/uitars_easy_5tasks.jsonl \
    --task-index "$i" \
    --model gpt-5.2 \
    --api-url https://api.openai.com \
    --max-steps 15 \
    --skip-emulator \
    2>&1 | tee -a "$LOG"
  echo "Task $i exit: $?"
done
echo ""
echo "========== ALL TASKS COMPLETE ==========" | tee -a "$LOG"
