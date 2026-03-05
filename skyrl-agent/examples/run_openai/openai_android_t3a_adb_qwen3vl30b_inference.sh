#!/bin/bash
# T3A-ADB agent: 78 unseen tasks, Qwen3-VL-30B-A3B-Thinking (text-only), 16 envs.
# Uses local vLLM server on port 8234 + broker-managed container pool.
#
# Step 1: Start vLLM server (separate terminal):
#   CUDA_VISIBLE_DEVICES=4 uv run --frozen --extra verl python -m vllm.entrypoints.openai.api_server \
#     --model Qwen/Qwen3-VL-30B-A3B-Thinking --port 8234 \
#     --gpu-memory-utilization 0.85 --max-model-len 32768 --trust-remote-code
#
# Step 2: Run this script:
#   ./openai_android_t3a_adb_qwen3vl30b_inference.sh
#
# Overrides:
#   ENV_POOL_SIZE=8 ./openai_android_t3a_adb_qwen3vl30b_inference.sh
#   MAX_INSTANCES=5 ./openai_android_t3a_adb_qwen3vl30b_inference.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

ENV_POOL_SIZE=${ENV_POOL_SIZE:-16}
DATA_FILE="${1:-./data/androidworld_generalization/unseen_task_instance/test_seed7.jsonl}"

if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$DATA_FILE")
echo "T3A-ADB inference: $NUM_INSTANCES tasks, $ENV_POOL_SIZE envs, Qwen3-VL-30B-A3B-Thinking (text-only)"

# Check vLLM server is running
if ! curl -s http://localhost:8234/health > /dev/null 2>&1; then
    echo "ERROR: vLLM server not running on port 8234"
    echo "Start it with:"
    echo "  CUDA_VISIBLE_DEVICES=4 uv run --frozen --extra verl python -m vllm.entrypoints.openai.api_server \\"
    echo "    --model Qwen/Qwen3-VL-30B-A3B-Thinking --port 8234 \\"
    echo "    --gpu-memory-utilization 0.85 --max-model-len 32768 --trust-remote-code"
    exit 1
fi

uv run --frozen --extra verl --env-file .env \
    python "${SCRIPT_DIR}/run_openai_android_inference.py" \
    --data "$DATA_FILE" \
    --yaml "${SCRIPT_DIR}/openai_android_t3a_adb_qwen3vl30b.yaml" \
    --pool-size "$ENV_POOL_SIZE" \
    ${MAX_INSTANCES:+--max-instances "$MAX_INSTANCES"}
