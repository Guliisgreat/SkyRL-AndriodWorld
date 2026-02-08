#!/bin/bash
#
# Pressure Test Runner for Dispatcher Error Detection and Recovery
#
# Usage:
#   ./run_pressure_test.sh [scenario]
#
# Scenarios:
#   quick     - Quick test (8 trajectories, low failure rate)
#   medium    - Medium test (20 trajectories, moderate failure rate)
#   stress    - Stress test (50 trajectories, high failure rate)
#   unit      - Run only unit tests for error classification
#   custom    - Custom parameters (pass additional args after 'custom')
#
# Examples:
#   ./run_pressure_test.sh quick
#   ./run_pressure_test.sh stress
#   ./run_pressure_test.sh custom --num-trajectories 10 --failure-rate 0.4

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

SCENARIO="${1:-quick}"
shift 2>/dev/null || true

echo "=============================================="
echo "Pressure Test Runner"
echo "=============================================="
echo "Scenario: $SCENARIO"
echo ""

case "$SCENARIO" in
    quick)
        echo "Running quick test (8 trajectories, low failure rate)..."
        uv run python tests/profiling/pressure_test_dispatcher.py \
            --num-trajectories 2 \
            --num-instances 4 \
            --num-containers 4 \
            --failure-rate 0.15 \
            --dead-container-rate 0.05 \
            --context-error-rate 0.02 \
            --seed 42
        ;;
    
    medium)
        echo "Running medium test (24 trajectories, moderate failure rate)..."
        uv run python tests/profiling/pressure_test_dispatcher.py \
            --num-trajectories 4 \
            --num-instances 6 \
            --num-containers 4 \
            --failure-rate 0.25 \
            --dead-container-rate 0.1 \
            --context-error-rate 0.03 \
            --seed 123
        ;;
    
    stress)
        echo "Running stress test (50 trajectories, high failure rate)..."
        uv run python tests/profiling/pressure_test_dispatcher.py \
            --num-trajectories 5 \
            --num-instances 10 \
            --num-containers 6 \
            --failure-rate 0.4 \
            --dead-container-rate 0.15 \
            --context-error-rate 0.05 \
            --stress-mode \
            --seed 456
        ;;
    
    unit)
        echo "Running unit tests for error classification..."
        uv run python tests/profiling/pressure_test_dispatcher.py --run-unit-tests
        ;;
    
    large)
        echo "Running large scale test (100 trajectories)..."
        uv run python tests/profiling/pressure_test_dispatcher.py \
            --num-trajectories 10 \
            --num-instances 10 \
            --num-containers 8 \
            --failure-rate 0.2 \
            --dead-container-rate 0.08 \
            --context-error-rate 0.02 \
            --seed 789 \
            --output results_large_$(date +%Y%m%d_%H%M%S).json
        ;;
    
    custom)
        echo "Running custom test with args: $@"
        uv run python tests/profiling/pressure_test_dispatcher.py "$@"
        ;;
    
    *)
        echo "Unknown scenario: $SCENARIO"
        echo ""
        echo "Available scenarios:"
        echo "  quick   - Quick test (8 trajectories, low failure rate)"
        echo "  medium  - Medium test (24 trajectories, moderate failure rate)"
        echo "  stress  - Stress test (50 trajectories, high failure rate)"
        echo "  large   - Large scale test (100 trajectories, saves JSON output)"
        echo "  unit    - Run only unit tests for error classification"
        echo "  custom  - Custom parameters (pass additional args after 'custom')"
        exit 1
        ;;
esac

echo ""
echo "=============================================="
echo "Test completed!"
echo "=============================================="
