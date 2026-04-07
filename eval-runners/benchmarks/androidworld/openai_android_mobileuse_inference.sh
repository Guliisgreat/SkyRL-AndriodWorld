#!/bin/bash
# openai_android_mobileuse_inference.sh - MobileUse agent AndroidWorld evaluation
#
# MobileUse hierarchical multi-agent (Planner + Operator + Reflector + ...) using
# Qwen2.5-VL-72B-Instruct as backbone. Based on https://github.com/MadeAgents/mobile-use
#
# Usage:
#   # With local vLLM server (default):
#   OPENAI_API_KEY=dummy ./openai_android_mobileuse_inference.sh
#
#   # Override data file:
#   ./openai_android_mobileuse_inference.sh path/to/test.jsonl
#
# Environment variables:
#   OPENAI_API_KEY   - Required. API key for the endpoint.
#   MODEL            - Model name (default: Qwen/Qwen2.5-VL-72B-Instruct)
#   API_URL          - API endpoint URL (default: http://localhost:8000)
#   API_TYPE         - "chat" or "completions" (default: chat)
#   TOKENIZER        - HuggingFace tokenizer name (default: same as MODEL)
#   ENV_POOL_SIZE    - Number of Android containers (default: 24)
#   MAX_INSTANCES    - Limit instances for debugging (default: all)
#   BASE_ENV_ID      - Starting env ID for port allocation (default: 100)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

# === Defaults ===
MODEL=${MODEL:-Qwen/Qwen2.5-VL-72B-Instruct}
API_URL=${API_URL:-http://localhost:8000}
API_TYPE=${API_TYPE:-chat}
TOKENIZER=${TOKENIZER:-$MODEL}
ENV_POOL_SIZE=${ENV_POOL_SIZE:-24}
BASE_ENV_ID=${BASE_ENV_ID:-100}

# === Config ===
YAML_FILE="${SCRIPT_DIR}/openai_android_mobileuse_qwen72b.yaml"

# === Data ===
DATA_DIR="./data/androidworld_original"
DATA_FILE="${1:-${DATA_DIR}/val_data_seed7.jsonl}"

if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$DATA_FILE")
echo "Data: $DATA_FILE ($NUM_INSTANCES instances)"

# === Validate API key ===
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "WARNING: OPENAI_API_KEY not set, using 'dummy' (OK for local vLLM)"
    export OPENAI_API_KEY=dummy
fi

# === Output ===
# When OUTPUT_DIR is set, results go directly there.
# When unset, the Python script auto-creates results/{AgentClass}_{TaskClass}_{mmdd_HHMM}/.
OUTPUT_DIR=${OUTPUT_DIR:-}

echo ""
echo "=============================================="
echo "AndroidWorld MobileUse Inference"
echo "=============================================="
echo "  Agent:       AndroidMobileUseAgent"
echo "  Model:       $MODEL"
echo "  API URL:     $API_URL"
echo "  API type:    $API_TYPE"
echo "  Tokenizer:   $TOKENIZER"
echo "  Containers:  $ENV_POOL_SIZE"
echo "  Base env ID: $BASE_ENV_ID"
echo "  Instances:   $NUM_INSTANCES"
echo "  Config:      $YAML_FILE"
echo "  Output:      ${OUTPUT_DIR:-./results/<auto>}"
echo "=============================================="
echo ""

# Build extra args
EXTRA_ARGS=()
EXTRA_ARGS+=(--model "$MODEL")
EXTRA_ARGS+=(--api-url "$API_URL")
EXTRA_ARGS+=(--api-type "$API_TYPE")
EXTRA_ARGS+=(--tokenizer "$TOKENIZER")
EXTRA_ARGS+=(--pool-size "$ENV_POOL_SIZE")
if [ -n "$OUTPUT_DIR" ]; then
    EXTRA_ARGS+=(--output-dir "$OUTPUT_DIR")
fi

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
    echo "MobileUse Inference completed! (check ./results/ for output)"
else
    echo "MobileUse Inference failed (exit $EXIT_CODE)"
fi
echo "=============================================="

exit $EXIT_CODE
