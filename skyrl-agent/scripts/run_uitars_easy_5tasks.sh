#!/bin/bash
# Run 5 easy UI-TARS tasks (Open X app) with cli_agent.py
# Requires: emulator already running (or remove --skip-emulator), OPENAI_API_KEY set.
set -e
cd "$(dirname "$0")/.."
LOG="/tmp/uitars_easy_5tasks.log"
echo "Logging to $LOG"
for i in 0 1 2 3 4; do
  echo ""
  echo "========== TASK $i / 5 ==========" | tee -a "$LOG"
  uv run --with "protobuf>=5.0" --with "grpcio>=1.78.0" python scripts/cli_agent.py \
    --task-file data/uitars_easy_5tasks.jsonl \
    --task-index "$i" \
    --model gpt-4o \
    --api-url https://api.openai.com \
    --max-steps 15 \
    --skip-emulator \
    2>&1 | tee -a "$LOG"
  echo "Task $i exit: $?"
done
echo ""
echo "========== ALL 5 TASKS COMPLETE ==========" | tee -a "$LOG"
