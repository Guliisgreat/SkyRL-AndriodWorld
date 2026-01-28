#!/bin/bash
# run_profiling.sh - Run container pool profiling
#
# Usage:
#   ./tests/profiling/run_profiling.sh                    # Default: pool sizes 1, 2, 4 (sequential)
#   ./tests/profiling/run_profiling.sh --quick            # Quick: pool size 1 only, skip concurrent
#   ./tests/profiling/run_profiling.sh --full             # Full: pool sizes 1, 2, 4, 8, 16
#   ./tests/profiling/run_profiling.sh --parallel         # Parallel: pool sizes 4, 8 with parallel creation
#   ./tests/profiling/run_profiling.sh --parallel-full    # Parallel full: pool sizes 4, 8, 16 with parallel
#   ./tests/profiling/run_profiling.sh --pool-sizes 2 4   # Custom pool sizes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

# Enable Docker tests
export RUN_DOCKER_TESTS=true

# Set temp directory (use /shared for more disk space)
export PROFILE_TEMP_DIR="${PROFILE_TEMP_DIR:-/tmp/profile_containers}"
mkdir -p "$PROFILE_TEMP_DIR"

# Parse arguments
MODE="default"
EXTRA_ARGS=""

if [[ "$1" == "--quick" ]]; then
    MODE="quick"
    shift
elif [[ "$1" == "--full" ]]; then
    MODE="full"
    shift
elif [[ "$1" == "--parallel" ]]; then
    MODE="parallel"
    shift
elif [[ "$1" == "--parallel-full" ]]; then
    MODE="parallel-full"
    shift
fi

case $MODE in
    quick)
        echo "Running quick profiling (pool size 1, skip concurrent)..."
        uv run --frozen python tests/profiling/profile_container_pool.py \
            --pool-sizes 1 \
            --skip-concurrent \
            "$@"
        ;;
    full)
        echo "Running full profiling (pool sizes 1, 2, 4, 8, 16, sequential)..."
        uv run --frozen python tests/profiling/profile_container_pool.py \
            --pool-sizes 1 2 4 8 16 \
            --concurrent-duration 60 \
            "$@"
        ;;
    parallel)
        echo "Running parallel profiling (pool sizes 4, 8 with parallel creation)..."
        uv run --frozen python tests/profiling/profile_container_pool.py \
            --pool-sizes 4 8 \
            --parallel-creation \
            --max-concurrent 4 \
            --initial-wait 30 \
            "$@"
        ;;
    parallel-full)
        echo "Running parallel full profiling (pool sizes 4, 8, 16 with parallel creation)..."
        uv run --frozen python tests/profiling/profile_container_pool.py \
            --pool-sizes 4 8 16 \
            --parallel-creation \
            --max-concurrent 8 \
            --initial-wait 30 \
            --concurrent-duration 60 \
            "$@"
        ;;
    default)
        echo "Running default profiling (pool sizes 1, 2, 4, sequential)..."
        uv run --frozen python tests/profiling/profile_container_pool.py \
            --pool-sizes 1 2 4 \
            "$@"
        ;;
esac

echo ""
echo "Profiling complete!"
echo "Results saved to: $PROFILE_TEMP_DIR"
