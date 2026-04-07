#!/bin/bash
# ---------------------------------------------------------------
# Ground Truth CLI Finder for MobileWorld
#
# Finds which GUI-only tasks can be solved purely via CLI commands
# (ADB, SQLite, REST APIs, file writes) without any UI interaction.
#
# Usage:
#   # Single container
#   ./run_gt_cli_finder.sh
#
#   # Multiple containers in parallel
#   CONTAINERS="http://localhost:6800=localhost:5556,http://localhost:6801=localhost:5557" \
#       ./run_gt_cli_finder.sh
#
#   # With broker
#   BROKER_URL=http://localhost:9200 POOL_SIZE=8 ./run_gt_cli_finder.sh
#
#   # Specific tasks
#   TASKS="AdjustBrightnessMaximumTask,MastodonNewPostTask" ./run_gt_cli_finder.sh
# ---------------------------------------------------------------
set -euo pipefail

# Configurable via environment
CONTAINER_URL="${CONTAINER_URL:-http://localhost:6800}"
ADB_SERIAL="${ADB_SERIAL:-localhost:5556}"
DEVICE_ID="${DEVICE_ID:-emulator-5554}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-2}"
CONTAINERS="${CONTAINERS:-}"
BROKER_URL="${BROKER_URL:-}"
POOL_SIZE="${POOL_SIZE:-4}"
TASKS="${TASKS:-}"

cd "$(dirname "$0")"

echo "=========================================="
echo "MobileWorld Ground Truth CLI Finder"
echo "=========================================="
echo "Max attempts: ${MAX_ATTEMPTS}"

CMD=(python ground_truth_cli_finder.py --max-attempts "${MAX_ATTEMPTS}")

if [ -n "${BROKER_URL}" ]; then
    echo "Mode:         broker"
    echo "Broker:       ${BROKER_URL}"
    echo "Pool size:    ${POOL_SIZE}"
    CMD+=(--broker-url "${BROKER_URL}" --pool-size "${POOL_SIZE}")
elif [ -n "${CONTAINERS}" ]; then
    echo "Mode:         parallel"
    echo "Containers:   ${CONTAINERS}"
    CMD+=(--containers "${CONTAINERS}")
else
    echo "Mode:         sequential"
    echo "Container:    ${CONTAINER_URL}"
    echo "ADB serial:   ${ADB_SERIAL}"

    # Check ADB
    if adb -s "${ADB_SERIAL}" get-state 2>/dev/null | grep -q "device"; then
        echo "ADB:          connected"
    else
        echo "ADB:          connecting..."
        adb connect "${ADB_SERIAL}" 2>/dev/null || true
        sleep 2
    fi

    CMD+=(--container-url "${CONTAINER_URL}" --adb-serial "${ADB_SERIAL}"
          --device-id "${DEVICE_ID}")
fi

if [ -n "${TASKS}" ]; then
    echo "Tasks:        ${TASKS}"
    CMD+=(--tasks "${TASKS}")
fi

echo ""
echo "Running: ${CMD[*]}"
echo ""

exec "${CMD[@]}"
