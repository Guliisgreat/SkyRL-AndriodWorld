#!/bin/bash
# T3A-ADB agent: 78 unseen tasks, gpt-5-mini, 16 envs.
# Uses AndroidT3AADBAgent (text-only UI elements + ADB commands).
#
# Usage:
#   OPENAI_API_KEY=sk-... ./openai_android_t3a_adb_inference.sh
#
# Overrides:
#   ENV_POOL_SIZE=4 ./openai_android_t3a_adb_inference.sh
#   MAX_INSTANCES=10 ./openai_android_t3a_adb_inference.sh  # debug
#   MODEL=gpt-4o ./openai_android_t3a_adb_inference.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

MODEL=${MODEL:-gpt-5-mini}
ENV_POOL_SIZE=${ENV_POOL_SIZE:-16}
DATA_FILE="${1:-./data/androidworld_generalization/unseen_task_instance/test_seed7.jsonl}"

if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$DATA_FILE")
echo "T3A-ADB inference: $NUM_INSTANCES tasks, $ENV_POOL_SIZE envs, $MODEL"

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "ERROR: OPENAI_API_KEY is not set"
    exit 1
fi

uv run --frozen --extra verl --env-file .env \
    python "${SCRIPT_DIR}/run_openai_android_inference.py" \
    --data "$DATA_FILE" \
    --yaml "${SCRIPT_DIR}/openai_android_t3a_adb_gpt5mini.yaml" \
    --model "$MODEL" \
    --pool-size "$ENV_POOL_SIZE" \
    ${MAX_INSTANCES:+--max-instances "$MAX_INSTANCES"}
