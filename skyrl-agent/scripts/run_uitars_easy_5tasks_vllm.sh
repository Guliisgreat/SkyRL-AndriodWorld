#!/bin/bash
# Run 5 easy UI-TARS tasks with UI-TARS base model (ByteDance-Seed/UI-TARS-7B-SFT)
# Requires: vLLM server running with UI-TARS model, emulator (or remove --skip-emulator)
#   Start vLLM first: vllm serve ByteDance-Seed/UI-TARS-7B-SFT --port 8000
set -e
cd "$(dirname "$0")/.."
LOG="/tmp/uitars_easy_5tasks_vllm.log"
echo "Logging to $LOG"
for i in 0 1 2 3 4; do
  echo ""
  echo "========== TASK $i / 5 ==========" | tee -a "$LOG"
  uv run --with "protobuf>=5.0" --with "grpcio>=1.78.0" python scripts/cli_agent.py \
    --task-file data/uitars_easy_5tasks.jsonl \
    --task-index "$i" \
    --model ByteDance-Seed/UI-TARS-7B-SFT \
    --api-url http://localhost:8000 \
    --max-steps 15 \
    --skip-emulator \
    2>&1 | tee -a "$LOG"
  echo "Task $i exit: $?"
done
echo ""
echo "========== ALL 5 TASKS COMPLETE ==========" | tee -a "$LOG"
