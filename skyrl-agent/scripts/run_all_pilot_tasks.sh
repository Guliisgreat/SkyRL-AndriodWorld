#!/bin/bash
# Run all 5 tasks from adb_agent_pilot_5tasks.jsonl sequentially.
# Requires: emulator already running (or remove --skip-emulator), OPENAI_API_KEY set.
set -e
cd "$(dirname "$0")/.."
for i in 0 1 2 3 4; do
  echo ""
  echo "========== TASK $i / 5 =========="
  uv run --with "protobuf>=5.0" --with "grpcio>=1.78.0" python scripts/cli_adb_agent.py \
    --task-file data/adb_agent_pilot_5tasks.jsonl \
    --task-index "$i" \
    --skip-emulator
  echo "Task $i done. Exit: $?"
done
echo ""
echo "========== ALL 5 TASKS COMPLETE =========="
