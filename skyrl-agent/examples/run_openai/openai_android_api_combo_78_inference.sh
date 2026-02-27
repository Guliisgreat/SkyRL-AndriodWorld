#!/bin/bash
# API Combo agent: 78 tasks, gpt-5-mini, 8 envs.
# Uses AndroidAPIComboAgent (screenshot + a11y tree).
#
# Usage:
#   OPENAI_API_KEY=sk-... ./openai_android_api_combo_78_inference.sh
#
# Overrides:
#   ENV_POOL_SIZE=4 ./openai_android_api_combo_78_inference.sh
#   MAX_INSTANCES=10 ./openai_android_api_combo_78_inference.sh  # debug

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

MODEL=${MODEL:-gpt-5-mini}
ENV_POOL_SIZE=${ENV_POOL_SIZE:-8}
DATA_FILE="${1:-./data/androidworld_generalization/unseen_task_instance/test_seed7.jsonl}"

if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$DATA_FILE")
echo "API Combo inference: $NUM_INSTANCES tasks, $ENV_POOL_SIZE envs, $MODEL"

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "ERROR: OPENAI_API_KEY is not set"
    exit 1
fi

uv run --frozen --extra verl --env-file .env \
    python "${SCRIPT_DIR}/run_openai_android_inference.py" \
    --data "$DATA_FILE" \
    --yaml "${SCRIPT_DIR}/openai_android_api_combo.yaml" \
    --model "$MODEL" \
    --pool-size "$ENV_POOL_SIZE" \
    ${MAX_INSTANCES:+--max-instances "$MAX_INSTANCES"}
