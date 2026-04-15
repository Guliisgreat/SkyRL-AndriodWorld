#!/bin/bash
# Start Android-Lab containers and broker.
#
# Usage:
#   ./start_broker.sh [NUM_CONTAINERS] [BASE_ENV_ID] [BROKER_PORT]
#
# Defaults: 8 containers, base_env_id=100, broker port 9200

set -e

NUM=${1:-8}
BASE_ENV=${2:-100}
BROKER_PORT=${3:-9200}
IMAGE="androidlab:v1"

echo "=== Starting $NUM Android-Lab containers (base_env=$BASE_ENV) ==="

for i in $(seq 0 $((NUM-1))); do
    ENV_ID=$((BASE_ENV + i))
    SERVER_PORT=$((6000 + ENV_ID))
    ADB_PORT=$((15037 + i))
    EMULATOR_PORT=$((5570 + i * 2))
    NAME="env${ENV_ID}"

    # Skip if already running
    if docker ps --format '{{.Names}}' | grep -q "^${NAME}$"; then
        echo "  $NAME already running, skipping"
        continue
    fi

    # Remove if stopped
    docker rm "$NAME" 2>/dev/null || true

    echo "  Starting $NAME (server=$SERVER_PORT, adb=$ADB_PORT, emu=$EMULATOR_PORT)..."
    docker run -d --privileged \
        --device /dev/kvm \
        --name "$NAME" \
        --network host \
        -e SERVER_PORT=$SERVER_PORT \
        -e ADB_PORT=$ADB_PORT \
        -e EMULATOR_PORT=$EMULATOR_PORT \
        "$IMAGE" > /dev/null

done

echo ""
echo "=== Waiting for containers to boot (up to 120s) ==="

ALL_READY=false
for attempt in $(seq 1 24); do
    sleep 5
    READY=0
    for i in $(seq 0 $((NUM-1))); do
        ENV_ID=$((BASE_ENV + i))
        PORT=$((6000 + ENV_ID))
        STATUS=$(curl -s "http://localhost:$PORT/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready',False))" 2>/dev/null || echo "False")
        if [ "$STATUS" = "True" ]; then
            READY=$((READY + 1))
        fi
    done
    echo "  ${attempt}: $READY/$NUM ready"
    if [ "$READY" -eq "$NUM" ]; then
        ALL_READY=true
        break
    fi
done

if [ "$ALL_READY" = "true" ]; then
    echo "All $NUM containers ready!"
else
    echo "WARNING: Not all containers ready. Proceeding anyway."
fi

echo ""
echo "=== Container ports ==="
for i in $(seq 0 $((NUM-1))); do
    ENV_ID=$((BASE_ENV + i))
    PORT=$((6000 + ENV_ID))
    echo "  env${ENV_ID}: http://localhost:$PORT"
done

echo ""
echo "Containers ready. You can now run:"
echo "  python run_gui_agent_androidlab.py --broker-url http://localhost:$BROKER_PORT --pool-size $NUM"
echo ""
echo "Or start the broker with adopt mode:"
echo "  cd skyrl-agent && python -m skyrl_agent.runtime.android.androidlab_broker \\"
echo "      --pool-size $NUM --docker-image $IMAGE --port $BROKER_PORT \\"
echo "      --base-env-id $BASE_ENV --adopt"
