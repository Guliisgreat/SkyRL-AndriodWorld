#!/usr/bin/env bash
# Verify that parallel creation of multiple containers with host network works.
# Exit 0 if all containers are created and pass /health; exit 1 otherwise.
# Use this before integrating host-network pools with the vLLM/agent pipeline.
#
# Usage:
#   cd skyrl-agent && RUN_DOCKER_TESTS=true ./scripts/verify_host_network_parallel.sh
#   RUN_DOCKER_TESTS=true ./scripts/verify_host_network_parallel.sh
#
# Options (pass-through to verify_container_pool.py):
#   VERIFY_POOL_SIZE=4 VERIFY_MAX_CONCURRENT=2 ./scripts/verify_host_network_parallel.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

export RUN_DOCKER_TESTS="${RUN_DOCKER_TESTS:-true}"
POOL_SIZE="${VERIFY_POOL_SIZE:-4}"
BUFFER_SIZE="${VERIFY_BUFFER_SIZE:-0}"
MAX_CONCURRENT="${VERIFY_MAX_CONCURRENT:-2}"

if [[ "$RUN_DOCKER_TESTS" != "true" ]]; then
  echo "FAIL: Set RUN_DOCKER_TESTS=true to run host-network parallel verification"
  exit 1
fi

echo "Verifying parallel host-network container creation (pool=$POOL_SIZE, max_concurrent=$MAX_CONCURRENT)..."
if python scripts/verify_container_pool.py \
  --host-network \
  --pool-size "$POOL_SIZE" \
  --buffer-size "$BUFFER_SIZE" \
  --max-concurrent "$MAX_CONCURRENT" \
  --skip-allocate \
  --image "${ANDROID_DOCKER_IMAGE:-androidworld:v9}"; then
  echo "PASS: Parallel host-network container creation is working. Safe to integrate with vLLM/agent."
  exit 0
else
  echo "FAIL: Parallel host-network container verification failed. Fix before integrating with vLLM/agent."
  exit 1
fi
