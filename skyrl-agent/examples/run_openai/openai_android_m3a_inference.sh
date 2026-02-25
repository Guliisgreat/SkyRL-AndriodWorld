#!/bin/bash
# openai_android_m3a_inference.sh - M3A agent AndroidWorld evaluation via OpenAI-compatible API
#
# The M3A (Multimodal Autonomous Agent for Android) agent uses SOM-annotated
# screenshots with index-based JSON actions. It sends two images per step
# (raw + marked) and a UI element list to the LLM.
#
# Usage:
#   # With OpenAI API (GPT-5-mini):
#   OPENAI_API_KEY=sk-... ./openai_android_m3a_inference.sh
#
#   # With local vLLM server:
#   OPENAI_API_KEY=dummy API_URL=http://localhost:8000 MODEL=Qwen/Qwen2-VL-7B-Instruct \
#     API_TYPE=completions ./openai_android_m3a_inference.sh
#
#   # Debug mode (1 container, saves trajectories):
#   OPENAI_API_KEY=sk-... DEBUG=1 ./openai_android_m3a_inference.sh
#
#   # Override data file:
#   ./openai_android_m3a_inference.sh path/to/test.jsonl
#
# Environment variables:
#   OPENAI_API_KEY  - Required. API key for the endpoint.
#   MODEL           - Model name (default: gpt-5-mini)
#   API_URL         - API endpoint URL (default: https://api.openai.com)
#   API_TYPE        - "chat" or "completions" (default: chat)
#   TOKENIZER       - HuggingFace tokenizer name (default: same as MODEL)
#   ENV_POOL_SIZE   - Number of Android containers (default: 16)
#   MAX_INSTANCES   - Limit instances for debugging (default: all)
#   DEBUG           - Set to 1 to use debug config (1 container, save trajectories)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

# === Defaults ===
MODEL=${MODEL:-gpt-5-mini}
API_URL=${API_URL:-https://api.openai.com}
API_TYPE=${API_TYPE:-chat}
TOKENIZER=${TOKENIZER:-$MODEL}
ENV_POOL_SIZE=${ENV_POOL_SIZE:-16}
DEBUG=${DEBUG:-0}

# === Config ===
if [ "$DEBUG" = "1" ]; then
    YAML_FILE="${SCRIPT_DIR}/openai_android_m3a_debug.yaml"
    echo "Running in DEBUG mode (1 container, trajectories saved)"
else
    YAML_FILE="${SCRIPT_DIR}/openai_android_m3a.yaml"
fi

# === Data ===
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"
DATA_FILE="${1:-${DATA_DIR}/test_seed7.jsonl}"

if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$DATA_FILE")
echo "Data: $DATA_FILE ($NUM_INSTANCES instances)"

# === Validate API key ===
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "ERROR: OPENAI_API_KEY is not set"
    exit 1
fi

# === Output ===
OUTPUT_DIR=${OUTPUT_DIR:-./results}
mkdir -p "$OUTPUT_DIR"

echo ""
echo "=============================================="
echo "AndroidWorld M3A Inference (OpenAI API)"
echo "=============================================="
echo "  Agent:       AndroidM3AAgent"
echo "  Model:       $MODEL"
echo "  API URL:     $API_URL"
echo "  API type:    $API_TYPE"
echo "  Tokenizer:   $TOKENIZER"
echo "  Containers:  $ENV_POOL_SIZE"
echo "  Instances:   $NUM_INSTANCES"
echo "  Config:      $YAML_FILE"
echo "  Output:      $OUTPUT_DIR"
echo "=============================================="
echo ""

# Build extra args
EXTRA_ARGS=()
EXTRA_ARGS+=(--model "$MODEL")
EXTRA_ARGS+=(--api-url "$API_URL")
EXTRA_ARGS+=(--api-type "$API_TYPE")
EXTRA_ARGS+=(--tokenizer "$TOKENIZER")
EXTRA_ARGS+=(--output-dir "$OUTPUT_DIR")

if [ -n "${MAX_INSTANCES:-}" ]; then
    EXTRA_ARGS+=(--max-instances "$MAX_INSTANCES")
fi

uv run --frozen --extra verl --env-file .env \
    python "${SCRIPT_DIR}/run_openai_android_inference.py" \
    --data "$DATA_FILE" \
    --yaml "$YAML_FILE" \
    "${EXTRA_ARGS[@]}"

EXIT_CODE=$?

echo ""
echo "=============================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "M3A Inference completed!"
    if [ -f "${OUTPUT_DIR}/final_metrics.json" ]; then
        echo ""
        echo "Final Metrics:"
        cat "${OUTPUT_DIR}/final_metrics.json"
    fi
else
    echo "M3A Inference failed (exit $EXIT_CODE)"
fi
echo "=============================================="

exit $EXIT_CODE
