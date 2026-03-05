#!/bin/bash
# run_claude_sdk.sh - AndroidWorld evaluation using the Claude Agent SDK
#
# The SDK's query() function replaces the entire agent loop.
# MCP tools bridge to the container infrastructure for ADB commands.
#
# Usage:
#   ANTHROPIC_API_KEY=sk-ant-... ./run_claude_sdk.sh
#   ANTHROPIC_API_KEY=sk-ant-... ./run_claude_sdk.sh path/to/test.jsonl
#
# Environment variables:
#   ANTHROPIC_API_KEY  - Required. Anthropic API key.
#   MODEL              - Claude model (default: claude-sonnet-4-20250514)
#   ENV_POOL_SIZE      - Number of Android containers (default: 16)
#   MAX_INSTANCES      - Limit instances for debugging (default: all)
#   MAX_TURNS          - Max turns per instance (default: 30)
#   OUTPUT_DIR         - Output directory (default: ./results)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}"

# === Defaults ===
MODEL=${MODEL:-claude-sonnet-4-20250514}
ENV_POOL_SIZE=${ENV_POOL_SIZE:-16}
MAX_TURNS=${MAX_TURNS:-30}
OUTPUT_DIR=${OUTPUT_DIR:-./results}

# === Config ===
YAML_FILE="${SCRIPT_DIR}/claude_sdk_android.yaml"

# === Data ===
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"
DATA_FILE="${1:-${DATA_DIR}/test.jsonl}"

if [ ! -f "$DATA_FILE" ]; then
    echo "ERROR: Data file not found: $DATA_FILE"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$DATA_FILE")
echo "Data: $DATA_FILE ($NUM_INSTANCES instances)"

# === Validate API key ===
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo ""
echo "=============================================="
echo "AndroidWorld Claude Agent SDK Evaluation"
echo "=============================================="
echo "  Model:       $MODEL"
echo "  Max turns:   $MAX_TURNS"
echo "  Containers:  $ENV_POOL_SIZE"
echo "  Instances:   $NUM_INSTANCES"
echo "  Config:      $YAML_FILE"
echo "  Output:      $OUTPUT_DIR"
echo "=============================================="
echo ""

# Build extra args
EXTRA_ARGS=()
EXTRA_ARGS+=(--model "$MODEL")
EXTRA_ARGS+=(--pool-size "$ENV_POOL_SIZE")
EXTRA_ARGS+=(--max-turns "$MAX_TURNS")
EXTRA_ARGS+=(--output-dir "$OUTPUT_DIR")

if [ -n "${MAX_INSTANCES:-}" ]; then
    EXTRA_ARGS+=(--max-instances "$MAX_INSTANCES")
fi

python "${SCRIPT_DIR}/run_claude_sdk_android.py" \
    --data "$DATA_FILE" \
    --yaml "$YAML_FILE" \
    "${EXTRA_ARGS[@]}"

EXIT_CODE=$?

echo ""
echo "=============================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "Claude SDK Evaluation completed!"
    if [ -f "${OUTPUT_DIR}/final_metrics.json" ]; then
        echo ""
        echo "Final Metrics:"
        cat "${OUTPUT_DIR}/final_metrics.json"
    fi
else
    echo "Claude SDK Evaluation failed (exit $EXIT_CODE)"
fi
echo "=============================================="

exit $EXIT_CODE
